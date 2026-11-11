"""
东方财富 6万元本金 实盘挂单指令生成器 (v2.0 严格零注水实盘同源版)
与 backtest_engine.py 100% 共享同一套权重引擎、多周期动量打分、Top-3 排名缓冲、双债利率保护与整手分配器：
  1. 策略一（全天候“超级固收+”低波底座）：风险平价 + 双均线减仓 + 511260/511360 双债利率保护伞
  2. 策略二（跨资产多维动量轮动）：6大零溢价资产 (含 159915 创业板ETF & 159980 有色ETF) 10/20/30日 OLS×R² + Top-3 缓冲防换手
  3. 推荐组合（40%全天候底座 + 60%跨资产动量）：取消盘中负收益网格，资金利用率提升至 ~98.5%，输出【先卖后买】差额执行表
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from backtest_engine import (
    ALL_TRADABLE_CODES,
    COMBO_S1_WEIGHT,
    COMBO_S2_WEIGHT,
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


def generate_live_signals(total_capital: float = 60000.0) -> dict:
    # 1. 先读取用户当前东方财富实盘持仓与预算 (my_holdings.json)
    current_pos: dict[str, int] = {}
    last_sync_date = ""
    if HOLDINGS_PATH.exists():
        try:
            with open(HOLDINGS_PATH, "r", encoding="utf-8") as hf:
                h_data = json.load(hf)
                current_pos = {k: int(v) for k, v in h_data.get("positions", {}).items()}
                last_sync_date = str(h_data.get("last_sync_date", ""))
                if "total_budget" in h_data and float(h_data["total_budget"]) >= 10000.0:
                    total_capital = float(h_data["total_budget"])
        except Exception:
            current_pos = {}

    data = load_aligned_data(start_date="2020-09-01")
    close_df = data["close"]
    raw_close_df = data["raw_close"]

    idx_last = len(close_df) - 1
    latest_dt = close_df.index[idx_last]
    latest_raw_px = raw_close_df.iloc[idx_last]

    ret_df = close_df.pct_change().fillna(0.0)
    log_close = np.log(close_df)
    vol20_df = ret_df.rolling(20, min_periods=10).std() * np.sqrt(250)
    ma20_df = close_df.rolling(20, min_periods=10).mean()
    ma60_df = close_df.rolling(60, min_periods=20).mean()

    # 2. 双债利率风险保护伞检测 (511260 十年国债 vs 511360 短融ETF)
    safe_bond, bond_guard_info = select_safe_bond(close_df, ma60_df, idx_last)

    # 3. 计算【策略一：全天候“超级固收+”低波底座】最新目标权重
    weights_s1 = compute_s1_weights(close_df, vol20_df, ma20_df, ma60_df, idx_last, safe_bond)

    # 4. 识别用户实盘当前持有的动量主力仓位（市值 >= 总资金14% 视为已持有主力腿，启用 Top-3 排名缓冲防换手）
    live_prev_top = []
    if sum(current_pos.values()) > 0:
        heavy_candidates = []
        for c in RISK_UNIVERSE:
            mkt_v = current_pos.get(c, 0) * float(latest_raw_px[c])
            if mkt_v >= total_capital * 0.14:
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
    is_initial_build = sum(current_pos.values()) == 0
    MIN_REBALANCE_AMT = round(total_capital * MIN_REBALANCE_RATIO, 0)  # 6万元对应 2,400 元防磨损锁

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

    # 防超支校验：若因微调免卖出而另一只品种买入加仓导致总持仓市值超过 99% 总预算，自动恢复卖出项以保证现金充足
    max_post_spend = total_capital * 0.99
    post_used_cash = round(
        sum(post_rebalance_positions[c] * float(latest_raw_px[c]) for c in post_rebalance_positions), 1
    )
    if post_used_cash > max_post_spend:
        for step in action_steps:
            c = step["code"]
            if step["action"] == "⚪ 微调免操作(防手续费磨损)" and step["theoretical_target_shares"] < step["current_shares"]:
                diff_sh_restore = step["theoretical_target_shares"] - step["current_shares"]
                raw_px = float(latest_raw_px[c])
                step["action"] = "🔴 第一步：卖出减仓"
                step["target_shares"] = step["theoretical_target_shares"]
                step["trade_shares"] = abs(diff_sh_restore)
                step["trade_lots"] = abs(diff_sh_restore) // 100
                step["est_cash_flow"] = round(abs(diff_sh_restore) * raw_px, 1)
                post_rebalance_positions[c] = int(step["theoretical_target_shares"])
                post_used_cash = round(
                    sum(post_rebalance_positions[k] * float(latest_raw_px[k]) for k in post_rebalance_positions), 1
                )
                if post_used_cash <= max_post_spend:
                    break

    order_priority = {
        "🔴 第一步：卖出减仓": 0,
        "🟢 第二步：买入加仓": 1,
        "⚪ 微调免操作(防手续费磨损)": 2,
        "⚪ 保持不动": 3,
    }
    action_steps.sort(key=lambda x: (order_priority.get(x["action"], 9), -x["est_cash_flow"]))

    used_combo_cash = post_used_cash
    reserve_cash = round(total_capital - used_combo_cash, 1)

    # 8. 调仓窗口识别与防误操作提示（周五 vs 周中预览）
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wk_cn = weekday_names[latest_dt.weekday()]
    is_friday_window = latest_dt.weekday() == 4
    if is_friday_window:
        timing_banner = (
            f"🟢 当前行情基准日 {latest_dt.strftime('%Y-%m-%d')} 为【周五调仓窗口】！"
            f"建议在周五 14:45~14:55 按下方【先卖后买】顺序执行买卖，成交后双击《确认已完成今日调仓_同步持仓.bat》。"
        )
    else:
        timing_banner = (
            f"🕒 当前行情基准日 {latest_dt.strftime('%Y-%m-%d')} 为【{wk_cn}（非周五调仓日）】—— 下方差额单仅供盘后预览！"
            f"请严格等到【本周五 14:45】重新运行脚本后再执行实盘买卖，周中切勿提前调仓（防假突破打脸与5元最低佣金磨损）。"
        )

    # 9. 四大实盘风控与防磨损保护状态说明（替代原负收益盘中网格表）
    protection_status = [
        {
            "module": "① 盘中网格条件单管控",
            "state": "🚫 已全面停用（实测提效 +1.36%/年）",
            "detail": (
                "严格路径回测证实：在动量趋势组合上叠加盘中网格会过早卖飞主升浪牛股、下跌破位前逆势接刀，且占用 5.5% 闲置现金。"
                "请在东财APP【条件单 -> 我的条件单】中暂停/删除此前设置的网格单，释放资金吃满趋势复利！"
            ),
        },
        {
            "module": "② 双债利率风险保护伞",
            "state": (
                f"🛡️ 已切入 511360 短融避险"
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
            "state": f"💰 免操作阈值 ¥{MIN_REBALANCE_AMT:,.0f} ｜ 预留零钱 ¥{reserve_cash:,.0f}",
            "detail": (
                f"单品种调仓差额低于总本金 {MIN_REBALANCE_RATIO*100:.1f}% (¥{MIN_REBALANCE_AMT:,.0f}) 自动跳过免交 5 元最低佣金；"
                f"账面剩余约 ¥{reserve_cash:,.0f} 零钱可在东财收盘前顺手参与 1 天期国债逆回购 (GC001/R-001)。"
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
        "total_capital": total_capital,
        "combo_ratio_label": f"{s1_pct}%全天候固收底座 + {s2_pct}%跨资产动量轮动",
        "used_combo_cash": used_combo_cash,
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
    print(f"📌 东方财富 {total_capital:,.0f} 元实盘调仓信号单 (基准行情日: {result['as_of_date']} {wk_cn})")
    print("=========================================================================================")
    print(f"⚠️  {timing_banner}")
    print(f"\n【推荐二合一：{result['combo_ratio_label']} | 先卖后买差额执行表】")
    if action_steps:
        cols = ["action", "code", "name", "latest_price", "current_shares", "target_shares", "trade_shares", "est_cash_flow"]
        print(pd.DataFrame(action_steps)[cols].to_string(index=False))
    print(f"   -> 调仓后证券市值: ¥{used_combo_cash:,.1f} 元 (真实资金利用率 {util_pct:.1f}%) | 账户预留零钱: ¥{reserve_cash:,.1f} 元")

    print("\n【6大跨资产零溢价池 实时多周期动量 (10/20/30日 OLS×R²) 打分榜】")
    print(pd.DataFrame(momentum_board).to_string(index=False))

    return result


if __name__ == "__main__":
    generate_live_signals(60000.0)
