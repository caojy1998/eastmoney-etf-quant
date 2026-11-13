"""
东方财富 6万元本金 实盘挂单指令与实时账户收益追踪生成器 (v2.1 含实盘累计收益 & 折合年化面板)
与 backtest_engine.py 100% 共享同一套权重引擎、多周期动量打分、Top-3 排名缓冲、双债利率保护与整手分配器：
  1. 实时核算【我的东财实盘账户成绩单】：当前总资产、持仓市值、可用现金、累计净收益、累计收益率、折合年化收益率及跑赢沪深300超额 Alpha
  2. 策略一（全天候“超级固收+”低波底座）：风险平价 + 双均线减仓 + 511260/511360 双债利率保护伞
  3. 策略二（跨资产多维动量轮动）：6大零溢价资产 (含 159915 创业板ETF & 159980 有色ETF) 10/20/30日 OLS×R² + Top-3 缓冲防换手
  4. 推荐组合（40%全天候底座 + 60%跨资产动量）：按当前账户真实总净值自动复利配平，输出【先卖后买】差额执行表
"""
import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from backtest_engine import (
    ALL_TRADABLE_CODES,
    COMBO_S1_WEIGHT,
    COMBO_S2_WEIGHT,
    COMMISSION_RATE,
    MIN_COMMISSION_RMB,
    MIN_REBALANCE_RATIO,
    RESERVE_CASH_RATIO,
    RISK_UNIVERSE,
    allocate_integer_lots,
    compute_s1_weights,
    compute_s2_weights,
    load_aligned_data,
    select_safe_bond,
)
from fetch_eastmoney_data import ETF_UNIVERSE
from qdii_premium_guard import evaluate_global_allocation

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
HOLDINGS_PATH = BASE_DIR / "my_holdings.json"


def calc_single_order_comm(trade_amt: float) -> float:
    if trade_amt <= 1e-6:
        return 0.0
    return round(max(MIN_COMMISSION_RMB, trade_amt * COMMISSION_RATE), 2)


def build_order_sheet_from_weights(
    weights_map: dict[str, float],
    raw_px_row: pd.Series,
    capital: float,
    reserve_ratio: float = RESERVE_CASH_RATIO,
) -> list[dict]:
    tgt_shares_map = allocate_integer_lots(
        weights_map, raw_px_row, capital, all_codes=ALL_TRADABLE_CODES, reserve_ratio=reserve_ratio
    )
    orders = []
    for c, w in sorted(weights_map.items(), key=lambda x: x[1], reverse=True):
        sh = tgt_shares_map.get(c, 0)
        if w <= 0.005 and sh == 0:
            continue
        raw_px = float(raw_px_row[c])
        lots = sh // 100
        orders.append({
            "code": c,
            "name": ETF_UNIVERSE[c]["name"],
            "latest_price": round(raw_px, 3),
            "target_weight_pct": round(w * 100.0, 1),
            "target_amt": round(capital * w, 0),
            "suggest_shares": sh,
            "suggest_lots": lots,
            "actual_amt": round(sh * raw_px, 2),
            "note": ETF_UNIVERSE[c]["desc"],
        })
    return orders


def generate_live_signals(default_capital: float = 60000.0) -> dict:
    data = load_aligned_data(start_date="2020-09-01")
    close_df = data["close"]
    raw_close_df = data["raw_close"]

    idx_last = len(close_df) - 1
    latest_dt = close_df.index[idx_last]
    latest_raw_px = raw_close_df.iloc[idx_last]

    # 1. 读取用户实盘账本 (my_holdings.json) 并实时核算实盘收益与折合年化
    current_pos: dict[str, int] = {}
    last_sync_date = ""
    invest_start_date = latest_dt.strftime("%Y-%m-%d")
    initial_principal = default_capital
    cash_balance: float | None = None
    nav_history: list[dict] = []

    if HOLDINGS_PATH.exists():
        try:
            with open(HOLDINGS_PATH, "r", encoding="utf-8") as hf:
                h_data = json.load(hf)
                current_pos = {k: int(v) for k, v in h_data.get("positions", {}).items()}
                last_sync_date = str(h_data.get("last_sync_date", ""))
                invest_start_date = str(h_data.get("invest_start_date") or last_sync_date or invest_start_date)
                initial_principal = float(h_data.get("initial_principal", h_data.get("total_budget", default_capital)))
                if "cash_balance" in h_data and h_data["cash_balance"] is not None:
                    cash_balance = float(h_data["cash_balance"])
                nav_history = list(h_data.get("nav_history", []))
        except Exception:
            current_pos = {}

    has_live_positions = sum(current_pos.values()) > 0
    live_mkt_value = round(
        sum(sh * float(latest_raw_px[c]) for c, sh in current_pos.items() if sh > 0 and c in latest_raw_px.index),
        2,
    )
    if cash_balance is None:
        cash_balance = round(max(0.0, initial_principal - live_mkt_value), 2) if has_live_positions else initial_principal

    live_total_equity = round(live_mkt_value + cash_balance, 2) if has_live_positions else round(initial_principal, 2)
    cum_profit_rmb = round(live_total_equity - initial_principal, 2)
    cum_return_pct = round((live_total_equity / initial_principal - 1.0) * 100.0, 2) if initial_principal > 0 else 0.0

    start_dt = pd.to_datetime(invest_start_date)
    cal_days = max(1, int((latest_dt - start_dt).days))
    idx_start_bench = min(idx_last, int(close_df.index.searchsorted(start_dt)))
    trading_days_held = max(1, idx_last - idx_start_bench)

    # 复利折合年化收益率 (与回测引擎口径严格一致；防首几日极端对数溢出)
    ratio_eq = max(0.01, live_total_equity / initial_principal) if initial_principal > 0 else 1.0
    exponent = 365.25 / cal_days
    annualized_return_pct = round(float((math.exp(max(-4.5, min(4.5, math.log(ratio_eq) * exponent))) - 1.0) * 100.0), 2)
    simple_annualized_pct = round(float(cum_return_pct * (365.25 / cal_days)), 2)

    base_hs300 = float(close_df["510300"].iloc[idx_start_bench])
    cur_hs300 = float(close_df["510300"].iloc[idx_last])
    hs300_same_period_pct = round((cur_hs300 / base_hs300 - 1.0) * 100.0, 2) if base_hs300 > 0 else 0.0
    excess_alpha_pct = round(cum_return_pct - hs300_same_period_pct, 2)

    if not has_live_positions:
        ann_note = "当前尚未记录实盘持仓，完成首次建仓并同步后将自动追踪实盘累计收益与年化。"
    elif cal_days < 30:
        ann_note = (
            f"实盘已运行 {cal_days} 个自然日（{trading_days_held} 个交易日）；"
            f"建仓初期天数较短，单周微小涨跌在折算年化时会被显著放大（线性折算约 {simple_annualized_pct:+.2f}%），运行满 1~3 个月后年化指标将趋于稳健。"
        )
    else:
        ann_note = f"实盘已稳健运行 {cal_days} 个自然日（{trading_days_held} 个交易日），按复利公式精确折算年化。"

    # 持仓明细拆解
    holding_breakdown = []
    for c, sh in current_pos.items():
        if sh > 0 and c in latest_raw_px.index:
            px = float(latest_raw_px[c])
            mv = round(sh * px, 2)
            holding_breakdown.append({
                "code": c,
                "name": ETF_UNIVERSE.get(c, {}).get("name", c),
                "shares": sh,
                "latest_price": round(px, 3),
                "market_value": mv,
                "weight_pct": round(mv / live_total_equity * 100.0, 1) if live_total_equity > 0 else 0.0,
            })
    holding_breakdown.sort(key=lambda x: x["market_value"], reverse=True)

    live_performance = {
        "has_live_positions": has_live_positions,
        "invest_start_date": invest_start_date,
        "as_of_date": latest_dt.strftime("%Y-%m-%d"),
        "calendar_days": cal_days,
        "trading_days": trading_days_held,
        "initial_principal": round(initial_principal, 2),
        "market_value": live_mkt_value,
        "cash_balance": round(cash_balance, 2),
        "total_equity": live_total_equity,
        "cum_profit_rmb": cum_profit_rmb,
        "cum_return_pct": cum_return_pct,
        "annualized_return_pct": annualized_return_pct,
        "simple_annualized_pct": simple_annualized_pct,
        "hs300_same_period_pct": hs300_same_period_pct,
        "excess_alpha_pct": excess_alpha_pct,
        "ann_note": ann_note,
        "holding_breakdown": holding_breakdown,
    }

    # 用当前账户真实总净值作为本周五复利调仓总资金盘子（实现盈利自动复利滚动，且买单严格匹配可用现金）
    total_capital = live_total_equity

    ret_df = close_df.pct_change().fillna(0.0)
    log_close = np.log(close_df)
    vol20_df = ret_df.rolling(20, min_periods=10).std() * np.sqrt(250)
    ma20_df = close_df.rolling(20, min_periods=10).mean()
    ma60_df = close_df.rolling(60, min_periods=20).mean()

    # 2. 双债利率风险保护伞检测 (511260 十年国债 vs 511360 短融ETF)
    safe_bond, bond_guard_info = select_safe_bond(close_df, ma60_df, idx_last)

    # 3. 计算【策略一：全天候“超级固收+”低波底座】最新目标权重
    weights_s1 = compute_s1_weights(close_df, vol20_df, ma20_df, ma60_df, idx_last, safe_bond)

    # 4. 识别用户实盘当前持有的动量主力仓位（市值 >= 总资产12% 视为已持有主力腿，即使网格卖出一笔后仍稳健识别）
    live_prev_top = []
    if has_live_positions:
        heavy_candidates = []
        for c in RISK_UNIVERSE:
            mkt_v = current_pos.get(c, 0) * float(latest_raw_px[c])
            if mkt_v >= total_capital * 0.12:
                heavy_candidates.append((c, mkt_v))
        heavy_candidates.sort(key=lambda x: x[1], reverse=True)
        live_prev_top = [c for c, _ in heavy_candidates[:2]]

    # 5. 计算【策略二：跨资产多维动量轮动】最新打分看板与目标权重
    weights_s2, chosen_top2, raw_board = compute_s2_weights(
        close_df,
        log_close,
        vol20_df,
        ma20_df,
        idx_last,
        safe_bond,
        prev_top=live_prev_top,
        rank_buffer=1,
    )

    momentum_board = []
    for row in raw_board:
        c = row["code"]
        momentum_board.append({
            "code": c,
            "name": ETF_UNIVERSE[c]["name"],
            "raw_price": round(float(latest_raw_px[c]), 3),
            "ret_20d_pct": row["ret_20d_pct"],
            "ret_5d_pct": row["ret_5d_pct"],
            "vol_20d_pct": row["vol_20d_pct"],
            "above_ma20": row["above_ma20"],
            "score_10_20_30": f"{row['score_10d']:+.2f} / {row['score_20d']:+.2f} / {row['score_30d']:+.2f}",
            "momentum_r2_score": row["momentum_r2_score"],
            "risk_adj_score": row["risk_adj_score"] if row["risk_adj_score"] is not None else -999.0,
            "passed_filter": row["status_label"],
        })

    # 6. 合成二合一权重 (40% 全天候底座 + 60% 跨资产动量) 并执行实时 IOPV 折溢价防雷检验
    weights_combo = {
        c: COMBO_S1_WEIGHT * weights_s1.get(c, 0.0) + COMBO_S2_WEIGHT * weights_s2.get(c, 0.0)
        for c in ALL_TRADABLE_CODES
    }

    premium_guard = evaluate_global_allocation(
        weights_combo.get("513030", 0.0),
        is_holding=(current_pos.get("513030", 0) > 0),
        holdings_map=current_pos,
    )
    for blocked_code in premium_guard.get("blocked_codes", []):
        for w_map in (weights_s1, weights_s2, weights_combo):
            w_rel = w_map.get(blocked_code, 0.0)
            if w_rel > 0:
                w_map[blocked_code] = 0.0
                w_map[safe_bond] = w_map.get(safe_bond, 0.0) + w_rel

    # 7. 生成整手目标持仓与【先卖后买】差额执行清单
    combo_orders = build_order_sheet_from_weights(weights_combo, latest_raw_px, total_capital, reserve_ratio=RESERVE_CASH_RATIO)
    s1_orders = build_order_sheet_from_weights(weights_s1, latest_raw_px, total_capital, reserve_ratio=RESERVE_CASH_RATIO)
    s2_orders = build_order_sheet_from_weights(weights_s2, latest_raw_px, total_capital, reserve_ratio=RESERVE_CASH_RATIO)

    all_check_codes = list(dict.fromkeys(ALL_TRADABLE_CODES + list(current_pos.keys())))
    target_map = {item["code"]: item["suggest_shares"] for item in combo_orders}
    is_initial_build = not has_live_positions
    MIN_REBALANCE_AMT = round(total_capital * MIN_REBALANCE_RATIO, 0)

    action_steps = []
    post_rebalance_positions = {}
    for c in all_check_codes:
        if c not in raw_close_df.columns:
            continue
        cur_sh = int(current_pos.get(c, 0))
        tgt_sh = int(target_map.get(c, 0))
        diff_sh = tgt_sh - cur_sh
        raw_px = float(latest_raw_px[c])
        diff_amt = round(abs(diff_sh) * raw_px, 1)

        if diff_sh == 0:
            action = "⚪ 保持不动"
            post_sh = cur_sh
        elif (not is_initial_build) and (cur_sh > 0 and tgt_sh > 0) and (diff_amt < MIN_REBALANCE_AMT):
            action = "⚪ 微调免操作(防手续费磨损)"
            diff_sh = 0
            diff_amt = 0.0
            post_sh = cur_sh
        elif diff_sh < 0:
            action = "🔴 第一步：卖出减仓"
            post_sh = tgt_sh
        else:
            action = "🟢 第二步：买入加仓"
            post_sh = tgt_sh

        post_rebalance_positions[c] = int(post_sh)

        if cur_sh > 0 or tgt_sh > 0:
            action_steps.append({
                "action": action,
                "code": c,
                "name": ETF_UNIVERSE.get(c, {}).get("name", c),
                "latest_price": round(raw_px, 3),
                "current_shares": cur_sh,
                "target_shares": post_sh,
                "theoretical_target_shares": tgt_sh,
                "trade_shares": abs(diff_sh),
                "trade_lots": abs(diff_sh) // 100,
                "est_cash_flow": diff_amt,
            })

    # 防超支校验：仅当确实存在【买入加仓】且【现有可用现金 + 卖出净回笼 < 买入总额 + 预估佣金 + 100元滑点缓冲】时，
    # 才按金额从大到小解锁 >= 600元 的微调卖出项（无买单时绝不解锁，百元级碎单绝不解锁白交5元佣金！）
    def calc_post_metrics() -> tuple[float, float, float]:
        used_mv = round(
            sum(post_rebalance_positions[k] * float(latest_raw_px[k]) for k in post_rebalance_positions), 1
        )
        comm_sum = round(
            sum(calc_single_order_comm(s["est_cash_flow"]) for s in action_steps if s["trade_shares"] > 0), 2
        )
        rem_c = round(total_capital - used_mv - comm_sum, 2)
        return used_mv, comm_sum, rem_c

    post_used_cash, est_trade_commissions, est_post_trade_cash = calc_post_metrics()
    has_buy_orders = any(s["action"] == "🟢 第二步：买入加仓" and s["trade_shares"] > 0 for s in action_steps)

    if has_buy_orders and est_post_trade_cash < 100.0:
        locked_sell_steps = [
            s for s in action_steps
            if s["action"] == "⚪ 微调免操作(防手续费磨损)" and s["theoretical_target_shares"] < s["current_shares"]
        ]
        locked_sell_steps.sort(
            key=lambda s: (s["current_shares"] - s["theoretical_target_shares"]) * float(latest_raw_px[s["code"]]),
            reverse=True,
        )
        for step in locked_sell_steps:
            c = step["code"]
            raw_px = float(latest_raw_px[c])
            unlock_amt = (step["current_shares"] - step["theoretical_target_shares"]) * raw_px
            if unlock_amt < 600.0:
                continue
            diff_sh_restore = step["theoretical_target_shares"] - step["current_shares"]
            step["action"] = "🔴 第一步：卖出减仓"
            step["target_shares"] = step["theoretical_target_shares"]
            step["trade_shares"] = abs(diff_sh_restore)
            step["trade_lots"] = abs(diff_sh_restore) // 100
            step["est_cash_flow"] = round(abs(diff_sh_restore) * raw_px, 1)
            post_rebalance_positions[c] = int(step["theoretical_target_shares"])
            post_used_cash, est_trade_commissions, est_post_trade_cash = calc_post_metrics()
            if est_post_trade_cash >= 100.0:
                break

        # 若仍差百元以内现金，直接从最大买单少买 1 手 (100股)，绝不为凑百元零钱额外多交一笔 5 元卖出佣金
        while has_buy_orders and est_post_trade_cash < 60.0:
            buy_cands = [
                s for s in action_steps
                if s["action"] == "🟢 第二步：买入加仓" and s["trade_shares"] >= 100
            ]
            if not buy_cands:
                break
            top_buy = max(buy_cands, key=lambda s: s["est_cash_flow"])
            c = top_buy["code"]
            raw_px = float(latest_raw_px[c])
            top_buy["target_shares"] -= 100
            top_buy["trade_shares"] -= 100
            top_buy["trade_lots"] = top_buy["trade_shares"] // 100
            top_buy["est_cash_flow"] = round(top_buy["trade_shares"] * raw_px, 1)
            if top_buy["trade_shares"] == 0:
                top_buy["action"] = "⚪ 保持不动"
            post_rebalance_positions[c] = int(top_buy["target_shares"])
            post_used_cash, est_trade_commissions, est_post_trade_cash = calc_post_metrics()
            has_buy_orders = any(s["action"] == "🟢 第二步：买入加仓" and s["trade_shares"] > 0 for s in action_steps)

    order_priority = {
        "🔴 第一步：卖出减仓": 0,
        "🟢 第二步：买入加仓": 1,
        "⚪ 微调免操作(防手续费磨损)": 2,
        "⚪ 保持不动": 3,
    }
    action_steps.sort(key=lambda x: (order_priority.get(x["action"], 9), -x["est_cash_flow"]))

    used_combo_cash = post_used_cash
    reserve_cash = est_post_trade_cash

    # 8. 调仓窗口识别与防误操作提示（周五 vs 周中预览）
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wk_cn = weekday_names[latest_dt.weekday()]
    is_friday_window = latest_dt.weekday() == 4
    if is_friday_window:
        timing_banner = (
            f"🟢 当前行情基准日 {latest_dt.strftime('%Y-%m-%d')} 为【周五调仓窗口】！"
            f"建议在周五 14:45~14:55 按下方【先卖后买】顺序执行买卖，成交后双击《确认已完成今日调仓_同步持仓.bat》记录最新持仓与可用现金。"
        )
    else:
        timing_banner = (
            f"🕒 当前行情基准日 {latest_dt.strftime('%Y-%m-%d')} 为【{wk_cn}（非周五调仓日）】—— 下方差额单仅供盘后预览！"
            f"请严格等到【本周五 14:45】重新运行脚本后再执行实盘买卖，周中切勿提前调仓（防假突破打脸与5元最低佣金磨损）。"
        )

    # 9. 四大实盘风控与防磨损保护状态说明
    protection_status = [
        {
            "module": "① 盘中网格条件单管控",
            "state": "🚫 已全面停用（实测提效 +1.36%/年）",
            "detail": (
                "严格状态机回测证实：在动量趋势组合上叠加盘中网格会过早卖飞主升浪牛股（正如本周二德国ETF被网格过早卖出一笔，错失周四涨至1.876的后半段涨幅）。"
                "请确保东财APP【条件单 -> 我的条件单】中的网格单已暂停/删除！"
            ),
        },
        {
            "module": "② 双债利率风险保护伞",
            "state": (
                "🛡️ 已切入 511360 短融避险"
                if bond_guard_info["switched_to_short_bond"]
                else f"✅ 511260 十年国债稳健持有 (20日 {bond_guard_info['bond_511260_ret20_pct']:+.2f}%)"
            ),
            "detail": (
                "实时监控 511260 十年国债：当跌破 60 日均线且 20 日跌幅超 -0.30%（债熊/加息冲击）时，自动将固收底仓平移至 511360 短融ETF。"
            ),
        },
        {
            "module": "③ Top-3 排名迟滞缓冲锁",
            "state": f"🔒 当前识别主力持仓: {', '.join(live_prev_top) if live_prev_top else '空仓/新建仓'}",
            "detail": (
                "已持有的策略二主力 ETF 只要仍居合格池前 3 名且站稳 20 日均线，即使第 2、3 名小幅互换也按兵不动，避免数万元无效换仓。"
            ),
        },
        {
            "module": "④ 不免5防微调锁 & 零钱增值",
            "state": f"💰 免操作阈值 ¥{MIN_REBALANCE_AMT:,.0f} ｜ 调仓后预留现金 ¥{reserve_cash:,.0f}",
            "detail": (
                f"单品种调仓差额低于总资产 {MIN_REBALANCE_RATIO*100:.1f}% (¥{MIN_REBALANCE_AMT:,.0f}) 自动锁定免操作"
                f"（仅当存在实际买单且可用现金不足时才解锁 ≥¥600 的减仓项，绝不空卖碎单）；"
                f"预计本次调仓券商佣金合计约 ¥{est_trade_commissions:.1f} 元。"
            ),
        },
    ]

    s1_pct = int(round(COMBO_S1_WEIGHT * 100))
    s2_pct = int(round(COMBO_S2_WEIGHT * 100))

    result = {
        "as_of_date": latest_dt.strftime("%Y-%m-%d"),
        "as_of_weekday": wk_cn,
        "is_friday_rebalance_window": is_friday_window,
        "timing_banner": timing_banner,
        "last_sync_date": last_sync_date,
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_principal": round(initial_principal, 2),
        "total_capital": total_capital,
        "live_performance": live_performance,
        "nav_history": nav_history,
        "combo_ratio_label": f"{s1_pct}%全天候固收底座 + {s2_pct}%跨资产动量轮动",
        "used_combo_cash": used_combo_cash,
        "est_trade_commissions": est_trade_commissions,
        "est_post_trade_cash": est_post_trade_cash,
        "reserve_cash": reserve_cash,
        "min_rebalance_amt": MIN_REBALANCE_AMT,
        "bond_guard_info": bond_guard_info,
        "live_prev_top": live_prev_top,
        "chosen_top2": chosen_top2,
        "strategy1_orders": s1_orders,
        "strategy2_momentum_board": momentum_board,
        "strategy2_orders": s2_orders,
        "combo_orders": combo_orders,
        "combo_action_steps": action_steps,
        "post_rebalance_positions": post_rebalance_positions,
        "protection_mechanisms": protection_status,
        "nasdaq_premium_guard": premium_guard,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "live_signal_eastmoney.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    util_pct = used_combo_cash / total_capital * 100.0 if total_capital > 0 else 0.0
    print("=========================================================================================")
    print(f"💼 【我的东财实盘账户实时成绩单】（建仓起始日: {invest_start_date} | 已运行 {cal_days} 天 / {trading_days_held} 个交易日）")
    print("=========================================================================================")
    print(
        f"   投入总本金: ¥{initial_principal:,.2f}  |  当前账户总资产: ¥{live_total_equity:,.2f} "
        f"(证券市值 ¥{live_mkt_value:,.2f} + 可用现金 ¥{cash_balance:,.2f})"
    )
    print(
        f"   📈 当前累计净收益: {cum_profit_rmb:+,.2f} 元 ({cum_return_pct:+.2f}%)  |  "
        f"🔥 折合年化收益率: {annualized_return_pct:+.2f}%"
    )
    print(
        f"   📊 同期沪深300涨跌: {hs300_same_period_pct:+.2f}%  |  "
        f"🏆 实盘跑赢大盘超额 (Alpha): {excess_alpha_pct:+.2f}%"
    )
    print(f"   ℹ️  {ann_note}")
    print("-----------------------------------------------------------------------------------------")
    print(f"⚠️  {timing_banner}")
    print(f"\n【推荐二合一：{result['combo_ratio_label']} | 先卖后买差额执行表（按当前实盘总资产 ¥{total_capital:,.1f} 复利配仓）】")
    if action_steps:
        cols = ["action", "code", "name", "latest_price", "current_shares", "target_shares", "trade_shares", "est_cash_flow"]
        print(pd.DataFrame(action_steps)[cols].to_string(index=False))
    print(
        f"   -> 调仓后证券市值: ¥{used_combo_cash:,.1f} 元 (利用率 {util_pct:.1f}%) | "
        f"预估佣金: ¥{est_trade_commissions:.1f} 元 | 预计剩余可用现金: ¥{est_post_trade_cash:,.1f} 元"
    )

    print("\n【6大跨资产零溢价池 实时多周期动量 (10/20/30日 OLS×R²) 打分榜】")
    print(pd.DataFrame(momentum_board).to_string(index=False))

    return result


if __name__ == "__main__":
    generate_live_signals(60000.0)
