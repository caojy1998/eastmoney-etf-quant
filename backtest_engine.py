"""
东方财富 6万元本金 场内 ETF 量化策略 6年严格实盘级历史回测引擎 (2021.01 ~ 2026.11)
【100% 零注水实盘口径】：
  1. 严格按场内真实不复权现价 (raw_close) 进行【1手 = 100股整数倍】买卖撮合，精准还原份额折算与现金分红；
  2. 严格计入东方财富【万1.5 佣金 + 单笔最低收费 5 元（不免5）】+ 单边 万2 (2bp) 冲击滑点损耗；
  3. 严格按自然周最后一个交易日（每周五 14:45，遇长假自动对齐节前最后交易日，节后立即恢复周五）调仓，彻底杜绝交易日计数漂移；
  4. 二合一组合按【单一真实账户】每周动态统一配平，彻底摒弃盘中网格注水与子账户漂移假设。

对比测试：
  1. 【策略一】全天候“超级固收+”低波底座（国债/短融利率保护 + 红利/可转债/黄金/德国ETF 风险平价）
  2. 【策略二】跨资产多维动量轮动（10/20/30日 OLS斜率×R² + Top-3 排名缓冲防换手 + 双债避险，含创业板ETF与有色ETF）
  3. 【推荐组合】40% 全天候固收底座 + 60% 跨资产动量轮动（6万元不免5账户最优平衡配比）
  4. 【对比基准】纯十年国债ETF (511260) 持有 / 传统银行固收理财 (2.8%年化) / 沪深300ETF (510300) 买入死拿
"""
import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
HOLDINGS_PATH = BASE_DIR / "my_holdings.json"


def get_default_capital() -> float:
    if HOLDINGS_PATH.exists():
        try:
            with open(HOLDINGS_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                val = float(d.get("initial_principal", d.get("total_budget", 60000.0)))
                if val >= 10000.0:
                    return val
        except Exception:
            pass
    return 60000.0


INITIAL_CAPITAL = get_default_capital()  # 默认同步 my_holdings.json 中的实盘总本金 (60,000元)
COMMISSION_RATE = 0.00015                # 东方财富实盘 ETF 佣金率：万1.5
MIN_COMMISSION_RMB = 5.0                 # 东方财富不免5：单笔委托最低佣金 5.0 元
SLIPPAGE_RATE = 0.0002                   # 周五 14:45 流动性高峰时段单边冲击滑点：万2 (2bp)
CASH_REPO_YIELD = 0.015                  # 账户闲置零钱（国债逆回购/货币增强）保守年化收益：1.5%
RESERVE_CASH_RATIO = 0.015               # 取消盘中网格后仅留 1.5% 现金缓冲（6万元留约900元），资金利用率 ~98.5%
MIN_REBALANCE_RATIO = 0.04               # 防磨损微调锁：单品种调仓金额低于总资产 4.0%（6万对应2400元）免于交易

COMBO_S1_WEIGHT = 0.40                   # 40% 全天候固收+低波底座
COMBO_S2_WEIGHT = 0.60                   # 60% 跨资产多维趋势轮动

# 策略一：全天候固收+战略风险预算
S1_BASE_BUDGET = {
    "511260": 0.44,  # 十年国债ETF（若长债破位下跌自动切换为 511360 短融ETF）
    "511380": 0.16,  # 可转债ETF
    "512890": 0.18,  # 红利低波ETF
    "518880": 0.14,  # 黄金ETF
    "513030": 0.08,  # 德国ETF (欧洲DAX)
}

# 策略二：零溢价低相关 6 大跨资产进攻池（覆盖 A股红利价值、A股科技成长、欧洲股市、可转债、黄金、工业有色商品）
RISK_UNIVERSE = ["512890", "511380", "518880", "513030", "159915", "159980"]
HIGH_DENOM_BONDS = ["511260", "511360"]
ALL_TRADABLE_CODES = ["511260", "511360", "511380", "512890", "518880", "513030", "159915", "159980"]


def load_aligned_data(start_date: str = "2020-09-01") -> dict:
    """加载并对齐所有核心与基准 ETF 的前复权及真实不复权日线数据"""
    codes = ["511260", "511360", "511380", "512890", "518880", "513030", "159915", "159980", "510500", "510300"]
    dfs = {}
    for code in codes:
        csv_path = DATA_DIR / f"{code}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"缺少数据文件 {csv_path}，请先运行 fetch_eastmoney_data.py")
        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["date"] >= pd.to_datetime(start_date)].sort_values("date").reset_index(drop=True)
        dfs[code] = df.set_index("date")

    common_start = max(df.index.min() for df in dfs.values())
    calendar = dfs["510300"].index[dfs["510300"].index >= common_start]
    close_df = pd.DataFrame(index=calendar)
    high_df = pd.DataFrame(index=calendar)
    low_df = pd.DataFrame(index=calendar)
    raw_close_df = pd.DataFrame(index=calendar)

    for code, df in dfs.items():
        reindexed = df.reindex(calendar).ffill().bfill()
        close_df[code] = reindexed["close"]
        high_df[code] = reindexed["high"]
        low_df[code] = reindexed["low"]
        raw_close_df[code] = reindexed["raw_close"]

    return {
        "close": close_df,
        "high": high_df,
        "low": low_df,
        "raw_close": raw_close_df,
    }


def get_week_end_flags(dates: pd.DatetimeIndex) -> np.ndarray:
    """
    定位每个自然周（ISO Week）的最后一个真实交易日：
      - 正常周精准落在【周五】；
      - 国庆/五一/春节等长假前自动落在【节前最后一个交易日】，且节后下一周立即恢复为【周五】，永不漂移！
      - 若最新一天是周中（周一至周四），回测末尾不将其误判为周末调仓日。
    """
    iso = dates.isocalendar()
    wk_id = iso["year"].values * 100 + iso["week"].values
    flags = np.zeros(len(dates), dtype=bool)
    for i in range(len(dates) - 1):
        if wk_id[i] != wk_id[i + 1]:
            flags[i] = True
    if len(dates) > 0 and dates[-1].weekday() == 4:
        flags[-1] = True
    return flags


def calc_ols_momentum_r2(log_prices: np.ndarray) -> float:
    """
    计算过去 N 天对数价格的线性回归年化斜率 × 拟合优度 R²：
    既奖励稳步推升的主升浪（高斜率 + 高R²），又自动过滤暴涨暴跌的妖股噪音（低R²）。
    """
    n = len(log_prices)
    if n < 5:
        return 0.0
    x = np.arange(n, dtype=float)
    dx = x - x.mean()
    dy = log_prices - log_prices.mean()
    denom_x = float(np.sum(dx * dx))
    denom_y = float(np.sum(dy * dy))
    if denom_x == 0.0 or denom_y <= 1e-12:
        return 0.0
    slope = float(np.sum(dx * dy)) / denom_x
    r2 = (float(np.sum(dx * dy)) ** 2) / (denom_x * denom_y)
    annualized_slope = math.exp(min(3.0, max(-3.0, slope * 250.0))) - 1.0
    return annualized_slope * r2


def calc_order_cost(
    trade_amt: float,
    min_fee: float = MIN_COMMISSION_RMB,
    comm_rate: float = COMMISSION_RATE,
    slip_rate: float = SLIPPAGE_RATE,
) -> tuple[float, float]:
    """返回 (券商实收佣金, 含滑点总摩擦成本)"""
    if trade_amt <= 1e-6:
        return 0.0, 0.0
    comm = max(min_fee, trade_amt * comm_rate)
    slip = trade_amt * slip_rate
    return comm, comm + slip


def select_safe_bond(close_df: pd.DataFrame, ma60_df: pd.DataFrame, idx: int) -> tuple[str, dict]:
    """
    双债利率风险保护伞：
    正常时期优先持有高收益长债【511260 十年国债ETF】；
    当 511260 跌破 60 日均线且近 20 日跌幅超 -0.30%（债市急跌/加息周期，如2022年底），
    自动将安全垫切换至零回撤的【511360 短融ETF】避险！
    """
    b_px = float(close_df["511260"].iloc[idx])
    b_m60 = float(ma60_df["511260"].iloc[idx])
    b_r20 = float(close_df["511260"].iloc[idx] / close_df["511260"].iloc[max(0, idx - 20)] - 1.0)
    use_short = (b_px < b_m60) and (b_r20 < -0.003)
    chosen_bond = "511360" if use_short else "511260"
    info = {
        "safe_bond_code": chosen_bond,
        "bond_511260_above_ma60": bool(b_px >= b_m60),
        "bond_511260_ret20_pct": round(b_r20 * 100.0, 2),
        "switched_to_short_bond": bool(use_short),
    }
    return chosen_bond, info


def compute_s1_weights(
    close_df: pd.DataFrame,
    vol20_df: pd.DataFrame,
    ma20_df: pd.DataFrame,
    ma60_df: pd.DataFrame,
    idx: int,
    safe_bond: str,
) -> dict[str, float]:
    """计算【策略一：全天候“超级固收+”低波底座】目标权重"""
    raw_s = {}
    released_to_bond = 0.0
    for c, budget in S1_BASE_BUDGET.items():
        v = float(vol20_df[c].iloc[idx])
        if np.isnan(v) or v <= 0.005:
            v = 0.05
        wt = budget * min(2.2, max(0.4, 0.10 / v))
        if c != "511260":
            px = float(close_df[c].iloc[idx])
            if px < float(ma60_df[c].iloc[idx]) and px < float(ma20_df[c].iloc[idx]):
                released_to_bond += wt * 0.55
                wt *= 0.45
        raw_s[c] = wt

    raw_s["511260"] += released_to_bond
    tot = sum(raw_s.values())
    w1 = {c: raw_s[c] / tot for c in S1_BASE_BUDGET}

    if w1["511260"] < 0.35:
        diff = 0.35 - w1["511260"]
        other_sum = 1.0 - w1["511260"]
        for c in w1:
            if c != "511260":
                w1[c] -= diff * (w1[c] / other_sum)
        w1["511260"] = 0.35

    if safe_bond == "511360":
        w1["511360"] = w1.pop("511260")
    return w1


def compute_s2_weights(
    close_df: pd.DataFrame,
    log_close: pd.DataFrame,
    vol20_df: pd.DataFrame,
    ma20_df: pd.DataFrame,
    idx: int,
    safe_bond: str,
    prev_top: list[str] | None = None,
    rank_buffer: int = 1,
    risk_pool: list[str] = RISK_UNIVERSE,
) -> tuple[dict[str, float], list[str], list[dict]]:
    """
    计算【策略二：跨资产多维动量轮动 + Top-3 缓冲防换手 + 双债避险】目标权重与打分看板：
      - 多周期混合动量：0.30 * 10日 + 0.45 * 20日 + 0.25 * 30日 (OLS斜率 × R²)，平滑单窗口参数敏感性；
      - 绝对趋势与防崩盘门禁：综合动量 > 0.02、站稳 20日均线、近5日跌幅未超 -4.2%、20日年化波动率 < 36%；
      - Top-3 排名迟滞缓冲：已持有的主力品种只要仍居合格池前 3 名且未破均线，继续持有免换仓，大幅削减无效摩擦！
    """
    prev_top = prev_top or []
    qualified_scores = {}
    board = []

    for c in risk_pool:
        s10 = calc_ols_momentum_r2(log_close[c].iloc[max(0, idx - 10) : idx + 1].values)
        s20 = calc_ols_momentum_r2(log_close[c].iloc[max(0, idx - 20) : idx + 1].values)
        s30 = calc_ols_momentum_r2(log_close[c].iloc[max(0, idx - 30) : idx + 1].values)
        combo_sc = 0.30 * s10 + 0.45 * s20 + 0.25 * s30

        px = float(close_df[c].iloc[idx])
        m20_val = float(ma20_df[c].iloc[idx])
        vol_val = float(vol20_df[c].iloc[idx])
        ret_5d = float(close_df[c].iloc[idx] / close_df[c].iloc[max(0, idx - 5)] - 1.0)
        ret_20d = float(close_df[c].iloc[idx] / close_df[c].iloc[max(0, idx - 20)] - 1.0)

        passed = (combo_sc > 0.02) and (px >= m20_val) and (ret_5d > -0.042) and (vol_val < 0.36)
        adj_sc = combo_sc / max(0.08, vol_val) if passed else -999.0
        if passed:
            qualified_scores[c] = adj_sc

        board.append({
            "code": c,
            "ret_20d_pct": round(ret_20d * 100.0, 2),
            "ret_5d_pct": round(ret_5d * 100.0, 2),
            "vol_20d_pct": round(vol_val * 100.0, 2),
            "above_ma20": "是" if px >= m20_val else "否(破位)",
            "score_10d": round(s10, 3),
            "score_20d": round(s20, 3),
            "score_30d": round(s30, 3),
            "momentum_r2_score": round(combo_sc, 3),
            "risk_adj_score": round(adj_sc, 3) if passed else None,
            "passed_filter": passed,
        })

    rk = [k for k, _ in sorted(qualified_scores.items(), key=lambda x: x[1], reverse=True)]
    if rank_buffer > 0 and prev_top:
        keep_pool = set(rk[: 2 + rank_buffer])
        kept = [c for c in prev_top if c in keep_pool]
        for c in rk:
            if len(kept) >= 2:
                break
            if c not in kept:
                kept.append(c)
        chosen = kept[:2]
    else:
        chosen = rk[:2]

    w2 = {}
    if len(chosen) >= 2:
        w2[chosen[0]] = 0.50
        w2[chosen[1]] = 0.50
    elif len(chosen) == 1:
        w2[chosen[0]] = 0.50
        w2[safe_bond] = 0.50
    else:
        w2[safe_bond] = 1.00

    # 为看板标注排名与是否触发 Top-3 缓冲留存
    for item in board:
        c = item["code"]
        if c in chosen:
            if c in prev_top and c not in rk[:2]:
                item["status_label"] = "🟢 持仓缓冲留存(Top3)"
            else:
                item["status_label"] = "✅ 主力入选(Top2)"
        elif item["passed_filter"]:
            item["status_label"] = f"🟡 备选观察(第{rk.index(c)+1}名)"
        else:
            item["status_label"] = "🛡️ 破位/避险剔除"

    board.sort(key=lambda x: (0 if x["passed_filter"] else 1, -(x["risk_adj_score"] or -999.0), -x["momentum_r2_score"]))
    return w2, chosen, board


def allocate_integer_lots(
    weights_map: dict[str, float],
    raw_prices: pd.Series | dict[str, float],
    total_nav: float,
    all_codes: list[str] = ALL_TRADABLE_CODES,
    reserve_ratio: float = RESERVE_CASH_RATIO,
) -> dict[str, int]:
    """
    两阶段智能整手（100股整数倍）分配器（回测与实盘信号 100% 同源）：
      1. 第一阶段：先确定高面值国债/短融 ETF (511260/511360，1手≈1.14~1.36万元) 的整手数；
      2. 第二阶段：将扣除大面值债券后的剩余可投资金，按权重比例精准分配给小面值 ETF (1手仅120~1280元)，
         使 6 万元账户的真实资金利用率稳定达到 ~98.5%！
    """
    investable = total_nav * (1.0 - reserve_ratio)
    tgt_shares = {c: 0 for c in all_codes}
    used_bond = 0.0

    bond_codes = [c for c in HIGH_DENOM_BONDS if c in all_codes]
    for bc in bond_codes:
        wb = weights_map.get(bc, 0.0)
        if wb > 0.005:
            lot_b = float(raw_prices[bc]) * 100.0
            lots_b = int(round((investable * wb) / lot_b))
            while (used_bond + lots_b * lot_b) > investable and lots_b > 0:
                lots_b -= 1
            tgt_shares[bc] = lots_b * 100
            used_bond += lots_b * lot_b

    rem_inv = max(0.0, investable - used_bond)
    other_codes = [c for c in all_codes if c not in bond_codes and weights_map.get(c, 0.0) > 0.005]
    other_w_sum = sum(weights_map[c] for c in other_codes)

    for c in other_codes:
        lot_cost = float(raw_prices[c]) * 100.0
        alloc = rem_inv * (weights_map[c] / other_w_sum) if other_w_sum > 0 else 0.0
        lots = int(round(alloc / lot_cost))
        if lots == 0 and (total_nav * weights_map[c]) >= lot_cost * 0.65 and rem_inv >= lot_cost:
            lots = 1
        tgt_shares[c] = lots * 100

    max_allowed_spend = total_nav * (1.0 - max(0.01, reserve_ratio - 0.005))

    def calc_spend() -> float:
        return sum(tgt_shares[k] * float(raw_prices[k]) for k in all_codes)

    while calc_spend() > max_allowed_spend:
        cands = [k for k in all_codes if k not in bond_codes and tgt_shares[k] >= 100]
        if not cands:
            cands = [k for k in bond_codes if tgt_shares[k] >= 100]
        if not cands:
            break
        top_k = max(cands, key=lambda k: tgt_shares[k] * float(raw_prices[k]))
        tgt_shares[top_k] -= 100

    return tgt_shares


def run_strict_account_backtest(
    close_df: pd.DataFrame,
    raw_close_df: pd.DataFrame,
    s1_weight: float,
    eval_start: str = "2021-01-04",
    initial_capital: float = INITIAL_CAPITAL,
    min_fee: float = MIN_COMMISSION_RMB,
    comm_rate: float = COMMISSION_RATE,
    slip_rate: float = SLIPPAGE_RATE,
    reserve_ratio: float = RESERVE_CASH_RATIO,
    min_rebal_ratio: float = MIN_REBALANCE_RATIO,
    rank_buffer: int = 1,
) -> dict:
    """
    严格实盘账户模拟器：
      - 跟踪每一分真实人民币现金 (cash) 与每只 ETF 的 100股整数倍持仓 (shares)
      - 精准处理 ETF 份额拆分折算 (如 512890 1拆5) 与现金分红 (如 511260 季度分红)
      - 严格按自然周最后一个交易日（周五）执行【先卖后买】撮合，逐笔扣除 max(5元, 万1.5) + 万2滑点
    """
    s2_weight = round(1.0 - s1_weight, 6)
    all_codes = ALL_TRADABLE_CODES

    dates = close_df.index
    start_idx = int(dates.searchsorted(pd.to_datetime(eval_start)))
    wk_end_flags = get_week_end_flags(dates)

    ret_df = close_df.pct_change().fillna(0.0)
    raw_ret_df = raw_close_df.pct_change().fillna(0.0)
    log_close = np.log(close_df)
    vol20_df = ret_df.rolling(20, min_periods=10).std() * np.sqrt(250)
    ma20_df = close_df.rolling(20, min_periods=10).mean()
    ma60_df = close_df.rolling(60, min_periods=20).mean()

    cash = float(initial_capital)
    shares = {c: 0 for c in all_codes}
    nav_series = {}
    trade_logs = []

    total_commission = 0.0
    total_cost_with_slip = 0.0
    order_count = 0

    prev_top: list[str] = []
    wk_counter = 0
    cached_w1: dict[str, float] | None = None

    for i in range(start_idx, len(dates)):
        dt = dates[i]

        # 1. 每日开盘至收盘：闲置现金计息 + 持仓除权分红/拆分折算结算
        if i > start_idx:
            cash *= 1.0 + CASH_REPO_YIELD / 250.0
            for c in all_codes:
                sh = shares[c]
                if sh > 0:
                    prev_raw = float(raw_close_df[c].iloc[i - 1])
                    cur_raw = float(raw_close_df[c].iloc[i])
                    r_tot = float(ret_df[c].iloc[i])
                    r_raw = float(raw_ret_df[c].iloc[i])
                    ratio = (1.0 + r_tot) / (1.0 + r_raw) if (1.0 + r_raw) > 0.1 else 1.0
                    # 份额拆分（如 1拆2、1拆5）
                    if abs(ratio - round(ratio)) < 0.03 and round(ratio) >= 2:
                        mult = int(round(ratio))
                        shares[c] = sh * mult
                        expected_val = sh * prev_raw * (1.0 + r_tot)
                        cash += expected_val - shares[c] * cur_raw
                    # 现金分红除息（前复权收益率 > 不复权收益率）
                    elif abs(r_tot - r_raw) > 1e-5:
                        cash += sh * prev_raw * (r_tot - r_raw)

        # 2. 自然周最后一个交易日（周五 14:45）评估信号并执行整手【先卖后买】
        if i == start_idx or wk_end_flags[i]:
            nav_before = cash + sum(shares[c] * float(raw_close_df[c].iloc[i]) for c in all_codes)
            safe_bond, _ = select_safe_bond(close_df, ma60_df, i)

            if s1_weight > 0.0:
                if cached_w1 is None or (wk_counter % 2 == 0):
                    cached_w1 = compute_s1_weights(close_df, vol20_df, ma20_df, ma60_df, i, safe_bond)
                else:
                    # 若双周中间触发了长债破位切换短融，立即平移债券保护仓位
                    if safe_bond == "511360" and "511260" in cached_w1:
                        cached_w1 = dict(cached_w1)
                        cached_w1["511360"] = cached_w1.pop("511260")
                    elif safe_bond == "511260" and "511360" in cached_w1:
                        cached_w1 = dict(cached_w1)
                        cached_w1["511260"] = cached_w1.pop("511360")
            else:
                cached_w1 = {}

            if s2_weight > 0.0:
                w2, chosen_top, _ = compute_s2_weights(
                    close_df, log_close, vol20_df, ma20_df, i, safe_bond, prev_top=prev_top, rank_buffer=rank_buffer
                )
                prev_top = list(chosen_top)
            else:
                w2 = {}

            wk_counter += 1
            combined_w = {
                c: s1_weight * cached_w1.get(c, 0.0) + s2_weight * w2.get(c, 0.0)
                for c in all_codes
            }

            raw_px_row = raw_close_df.iloc[i]
            tgt_shares = allocate_integer_lots(combined_w, raw_px_row, nav_before, all_codes, reserve_ratio=reserve_ratio)

            is_init = sum(shares.values()) == 0
            min_rebal_amt = nav_before * min_rebal_ratio

            exec_shares = {}
            locked_sells = []
            for c in all_codes:
                cur_sh = shares[c]
                t_sh = tgt_shares[c]
                diff_amt = abs(t_sh - cur_sh) * float(raw_px_row[c])
                if t_sh == cur_sh:
                    exec_shares[c] = cur_sh
                elif (not is_init) and (cur_sh > 0 and t_sh > 0) and (diff_amt < min_rebal_amt):
                    exec_shares[c] = cur_sh
                    if t_sh < cur_sh:
                        locked_sells.append(c)
                else:
                    exec_shares[c] = t_sh

            # 防超支解锁：若因微调免卖出导致总持仓超 99% 资产，自动释放微调卖出以腾出买单现金
            for c in locked_sells:
                if sum(exec_shares[k] * float(raw_px_row[k]) for k in all_codes) > nav_before * 0.99:
                    exec_shares[c] = tgt_shares[c]

            wk_orders = 0
            wk_fee = 0.0

            # 第一步：先执行全部卖出减仓，回笼实盘现金
            for c in all_codes:
                if exec_shares[c] < shares[c]:
                    sell_sh = shares[c] - exec_shares[c]
                    amt = sell_sh * float(raw_px_row[c])
                    comm, cost = calc_order_cost(amt, min_fee=min_fee, comm_rate=comm_rate, slip_rate=slip_rate)
                    cash += amt - cost
                    total_commission += comm
                    total_cost_with_slip += cost
                    wk_fee += cost
                    order_count += 1
                    wk_orders += 1
                    shares[c] = exec_shares[c]

            # 第二步：按买入金额从大到小执行整手买入（若现金差几十元不够手续费，自动减 100 股，绝不透支！）
            buy_list = [c for c in all_codes if exec_shares[c] > shares[c]]
            buy_list.sort(key=lambda k: (exec_shares[k] - shares[k]) * float(raw_px_row[k]), reverse=True)
            for c in buy_list:
                px = float(raw_px_row[c])
                want_sh = exec_shares[c] - shares[c]
                while want_sh >= 100:
                    amt = want_sh * px
                    comm, cost = calc_order_cost(amt, min_fee=min_fee, comm_rate=comm_rate, slip_rate=slip_rate)
                    if cash >= amt + cost:
                        cash -= amt + cost
                        total_commission += comm
                        total_cost_with_slip += cost
                        wk_fee += cost
                        order_count += 1
                        wk_orders += 1
                        shares[c] += want_sh
                        break
                    want_sh -= 100

            if wk_orders > 0:
                nav_after = cash + sum(shares[c] * float(raw_px_row[c]) for c in all_codes)
                trade_logs.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()],
                    "shares": {k: int(v) for k, v in shares.items() if v > 0},
                    "orders_executed": wk_orders,
                    "fee_and_slip_rmb": round(wk_fee, 2),
                    "cash_left": round(cash, 2),
                    "nav": round(nav_after, 2),
                })

        nav_series[dt] = cash + sum(shares[c] * float(raw_close_df[c].iloc[i]) for c in all_codes)

    return {
        "nav": pd.Series(nav_series),
        "trade_logs": trade_logs,
        "total_commission_rmb": round(total_commission, 2),
        "total_cost_with_slip_rmb": round(total_cost_with_slip, 2),
        "order_count": order_count,
        "latest_prev_top": prev_top,
    }


def calc_performance_metrics(
    nav_series: pd.Series,
    name: str,
    extra_stats: dict | None = None,
    base_capital: float | None = None,
) -> dict:
    """计算核心量化评价指标：总收益率、年化收益率(CAGR)、最大回撤、夏普比率、卡玛比率、分年度收益"""
    daily_ret = nav_series.pct_change().dropna()
    total_days = (nav_series.index[-1] - nav_series.index[0]).days
    years = total_days / 365.25

    init_cap = float(base_capital) if base_capital is not None else float(nav_series.iloc[0])
    total_return = (float(nav_series.iloc[-1]) / init_cap) - 1.0
    cagr = (float(nav_series.iloc[-1]) / init_cap) ** (1.0 / years) - 1.0

    # 最大回撤（含首日建仓摩擦相对于初始本金的回撤）
    rolling_max = np.maximum(init_cap, nav_series.cummax())
    drawdown = (nav_series - rolling_max) / rolling_max
    max_dd = float(drawdown.min())

    ann_vol = float(daily_ret.std() * np.sqrt(250))
    rf = 0.02
    sharpe = (cagr - rf) / ann_vol if ann_vol > 0.001 else 0.0
    calmar = cagr / abs(max_dd) if max_dd < -0.001 else 0.0

    monthly_nav = nav_series.resample("ME").last()
    monthly_ret = monthly_nav.pct_change().dropna()
    win_months_rate = float((monthly_ret > 0).mean())

    yearly_returns = {}
    for yr, grp in nav_series.groupby(nav_series.index.year):
        prev_yr_data = nav_series[nav_series.index.year < yr]
        base_val = float(prev_yr_data.iloc[-1]) if len(prev_yr_data) > 0 else init_cap
        yr_ret = (float(grp.iloc[-1]) / base_val) - 1.0
        yearly_returns[str(yr)] = round(float(yr_ret * 100), 2)

    out = {
        "name": name,
        "initial_capital": round(init_cap, 2),
        "final_capital": round(float(nav_series.iloc[-1]), 2),
        "net_profit": round(float(nav_series.iloc[-1] - init_cap), 2),
        "total_return_pct": round(float(total_return * 100), 2),
        "cagr_pct": round(float(cagr * 100), 2),
        "max_drawdown_pct": round(float(max_dd * 100), 2),
        "ann_vol_pct": round(float(ann_vol * 100), 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "calmar_ratio": round(float(calmar), 2),
        "monthly_win_rate_pct": round(float(win_months_rate * 100), 1),
        "yearly_returns_pct": yearly_returns,
    }
    if extra_stats:
        out.update(extra_stats)
    return out


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_aligned_data(start_date="2020-09-01")
    close_df = data["close"]
    raw_close_df = data["raw_close"]

    eval_start = "2021-01-04"
    print("=========================================================================================")
    print(
        f"🚀 东方财富 {INITIAL_CAPITAL/10000:.1f}万元场内 ETF 严格实盘级回测 "
        f"(100股整手 + 万1.5不免5最低5元 + 周五日历调仓 | 2021-01 ~ {close_df.index[-1].strftime('%Y-%m')})"
    )
    print("=========================================================================================")

    res_s1 = run_strict_account_backtest(close_df, raw_close_df, s1_weight=1.0, eval_start=eval_start)
    res_s2 = run_strict_account_backtest(close_df, raw_close_df, s1_weight=0.0, eval_start=eval_start)
    res_combo = run_strict_account_backtest(close_df, raw_close_df, s1_weight=COMBO_S1_WEIGHT, eval_start=eval_start)

    nav_s1 = res_s1["nav"]
    nav_s2 = res_s2["nav"]
    nav_combo = res_combo["nav"]
    dates = nav_combo.index

    # 对比基准 1：传统银行固收理财 (年化 2.8% 按自然日计息)
    cal_years_elapsed = (dates - dates[0]).days.values / 365.25
    nav_fixed_income = pd.Series(
        INITIAL_CAPITAL * ((1.0 + 0.028) ** cal_years_elapsed),
        index=dates,
    )

    # 对比基准 2：纯十年国债ETF (511260) 买入持有
    bond_slice = close_df.loc[dates, "511260"]
    nav_bond_hold = INITIAL_CAPITAL * (bond_slice / bond_slice.iloc[0])

    # 对比基准 3：沪深300ETF (510300) 买入持有
    hs300_slice = close_df.loc[dates, "510300"]
    nav_hs300 = INITIAL_CAPITAL * (hs300_slice / hs300_slice.iloc[0])

    s1_pct = int(round(COMBO_S1_WEIGHT * 100))
    s2_pct = int(round(COMBO_S2_WEIGHT * 100))

    metrics_list = [
        calc_performance_metrics(
            nav_s1,
            "策略一：全天候“超级固收+”底座 (实盘整手·不免5)",
            {
                "order_count": res_s1["order_count"],
                "total_commission_rmb": res_s1["total_commission_rmb"],
                "total_cost_with_slip_rmb": res_s1["total_cost_with_slip_rmb"],
            },
            base_capital=INITIAL_CAPITAL,
        ),
        calc_performance_metrics(
            nav_s2,
            "策略二：跨资产多维动量轮动 (实盘整手·不免5)",
            {
                "order_count": res_s2["order_count"],
                "total_commission_rmb": res_s2["total_commission_rmb"],
                "total_cost_with_slip_rmb": res_s2["total_cost_with_slip_rmb"],
            },
            base_capital=INITIAL_CAPITAL,
        ),
        calc_performance_metrics(
            nav_combo,
            f"推荐组合：{s1_pct}%全天候底座 + {s2_pct}%跨资产动量 (实盘整手·不免5)",
            {
                "order_count": res_combo["order_count"],
                "total_commission_rmb": res_combo["total_commission_rmb"],
                "total_cost_with_slip_rmb": res_combo["total_cost_with_slip_rmb"],
            },
            base_capital=INITIAL_CAPITAL,
        ),
        calc_performance_metrics(nav_bond_hold, "基准A：纯十年国债ETF (511260) 持有", base_capital=INITIAL_CAPITAL),
        calc_performance_metrics(nav_fixed_income, "基准B：传统银行固收理财 (2.8%年化)", base_capital=INITIAL_CAPITAL),
        calc_performance_metrics(nav_hs300, "基准C：沪深300ETF (510300) 买入死拿", base_capital=INITIAL_CAPITAL),
    ]

    print(f"\n【一、核心绩效指标对比（初始本金：{INITIAL_CAPITAL:,.0f} 元，严格扣除 100股整手零头 + 万1.5最低5元佣金 + 万2滑点）】")
    summary_rows = []
    for m in metrics_list:
        fee_str = f"¥{m['total_commission_rmb']:,.0f} ({m['order_count']}笔)" if "order_count" in m else "-"
        summary_rows.append({
            "策略/基准名称": m["name"],
            "期末总资产(元)": f"{m['final_capital']:,.0f}",
            "净赚收益(元)": f"+{m['net_profit']:,.0f}" if m["net_profit"] >= 0 else f"{m['net_profit']:,.0f}",
            "年化(CAGR)": f"{m['cagr_pct']:.2f}%",
            "最大回撤": f"{m['max_drawdown_pct']:.2f}%",
            "夏普": f"{m['sharpe_ratio']:.2f}",
            "卡玛": f"{m['calmar_ratio']:.2f}",
            "6年实缴佣金": fee_str,
        })
    print(pd.DataFrame(summary_rows).to_string(index=False))

    print("\n【二、2021 ~ 2026 分年度真实净收益率对比 (%) —— 零网格注水·纯实盘交割口径】")
    yr_rows = []
    years = sorted(metrics_list[0]["yearly_returns_pct"].keys())
    for m in metrics_list:
        row = {"策略/基准名称": m["name"]}
        for y in years:
            val = m["yearly_returns_pct"].get(y, 0.0)
            row[f"{y}年"] = f"{val:+.2f}%"
        yr_rows.append(row)
    print(pd.DataFrame(yr_rows).to_string(index=False))

    nav_export = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "strategy1_all_weather": nav_s1.round(2).values,
        "strategy2_momentum": nav_s2.round(2).values,
        "strategy_combo": nav_combo.round(2).values,
        "bench_bond": nav_bond_hold.round(2).values,
        "bench_fixed_income": nav_fixed_income.round(2).values,
        "bench_hs300": nav_hs300.round(2).values,
    })
    nav_export.to_csv(OUTPUT_DIR / "backtest_nav_history.csv", index=False, encoding="utf-8-sig")

    with open(OUTPUT_DIR / "backtest_metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "execution_model": {
                    "initial_capital": INITIAL_CAPITAL,
                    "lot_size_shares": 100,
                    "commission_rate": COMMISSION_RATE,
                    "min_commission_rmb": MIN_COMMISSION_RMB,
                    "slippage_rate": SLIPPAGE_RATE,
                    "cash_repo_yield": CASH_REPO_YIELD,
                    "reserve_cash_ratio": RESERVE_CASH_RATIO,
                    "min_rebalance_ratio": MIN_REBALANCE_RATIO,
                    "combo_weights": {"s1": COMBO_S1_WEIGHT, "s2": COMBO_S2_WEIGHT},
                    "rebalance_calendar": "ISO自然周最后一个交易日(周五14:45，遇长假对齐节前最后交易日)",
                    "intraday_grid_enabled": False,
                },
                "metrics": metrics_list,
                "recent_logs_strategy1": res_s1["trade_logs"][-8:],
                "recent_logs_strategy2": res_s2["trade_logs"][-8:],
                "recent_logs_combo": res_combo["trade_logs"][-8:],
                "latest_backtest_prev_top": res_combo["latest_prev_top"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n严格实盘级回测完成！净值序列与统计指标已输出至: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
