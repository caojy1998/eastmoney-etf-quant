"""
东方财富 5万元本金 实盘挂单指令与「网格条件单」参数生成器 (已升级为 513030 德国ETF 版本)
根据最新收盘行情自动输出：
  1. 策略一（全天候固收+ & 东财ATR网格）：各ETF精确买入股数（100股整数倍）+ 东财APP网格条件单参数
  2. 策略二（跨市场ETF动量轮动）：实时动量打分排名与当前调仓信号
  3. 二合一（50%策略一 + 50%策略二）：5万元合并实盘一键下单表与【先卖后买】差额执行表
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from backtest_engine import calc_ols_momentum_r2, load_aligned_data
from fetch_eastmoney_data import ETF_UNIVERSE
from qdii_premium_guard import evaluate_global_allocation

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path(__file__).parent / "output"


def generate_live_signals(total_capital: float = 60000.0) -> dict:
    data = load_aligned_data(start_date="2020-09-01")
    close_df = data["close"]
    high_df = data["high"]
    low_df = data["low"]
    raw_close_df = data["raw_close"]

    latest_dt = close_df.index[-1]
    ret_df = close_df.pct_change().fillna(0.0)
    vol20 = (ret_df.rolling(20).std() * np.sqrt(250)).iloc[-1]
    ma20 = close_df.rolling(20).mean().iloc[-1]
    ma60 = close_df.rolling(60).mean().iloc[-1]

    # 计算实盘日内真实波幅 ATR% (用于东方财富网格条件单)
    intraday_range = (high_df - low_df) / close_df.shift(1).bfill()
    atr20_pct = intraday_range.rolling(20).mean().iloc[-1]

    # ---------------------------------------------------------
    # 1. 计算【策略一：全天候“超级固收+”】最新目标权重
    # ---------------------------------------------------------
    base_risk_budget = {
        "511260": 0.42,
        "511380": 0.16,
        "512890": 0.17,
        "518880": 0.15,
        "513030": 0.10,
    }
    raw_scores = {}
    released_to_bond = 0.0

    for c, budget in base_risk_budget.items():
        v = float(vol20[c]) if not np.isnan(vol20[c]) and vol20[c] > 0.005 else 0.05
        inv_vol_factor = min(2.2, max(0.4, 0.10 / v))
        w_target = budget * inv_vol_factor
        px = float(close_df.loc[latest_dt, c])
        if c != "511260":
            if px < float(ma60[c]) and px < float(ma20[c]):
                released_to_bond += w_target * 0.55
                w_target *= 0.45
        raw_scores[c] = w_target

    raw_scores["511260"] += released_to_bond
    total_s = sum(raw_scores.values())
    weights_s1 = {c: raw_scores[c] / total_s for c in base_risk_budget}
    if weights_s1["511260"] < 0.35:
        diff = 0.35 - weights_s1["511260"]
        other_sum = 1.0 - weights_s1["511260"]
        for c in weights_s1:
            if c != "511260":
                weights_s1[c] -= diff * (weights_s1[c] / other_sum)
        weights_s1["511260"] = 0.35

    # ---------------------------------------------------------
    # 2. 计算【策略二：跨市场 ETF 动量轮动】最新打分与信号
    # ---------------------------------------------------------
    log_close = np.log(close_df)
    risk_universe = ["512890", "511380", "518880", "513030", "510500"]
    safe_haven = "511260"

    momentum_board = []
    qualified_scores = {}

    for c in risk_universe:
        w20 = log_close[c].iloc[-21:].values
        w10 = log_close[c].iloc[-11:].values
        s20 = calc_ols_momentum_r2(w20)
        s10 = calc_ols_momentum_r2(w10)
        combo_score = 0.65 * s20 + 0.35 * s10

        px = float(close_df.loc[latest_dt, c])
        m20_val = float(ma20[c])
        v20_val = float(vol20[c])
        ret_5d = float(close_df[c].iloc[-1] / close_df[c].iloc[-6] - 1.0)
        ret_20d = float(close_df[c].iloc[-1] / close_df[c].iloc[-21] - 1.0)

        passed = (combo_score > 0.02) and (px >= m20_val) and (ret_5d > -0.038) and (v20_val < 0.32)
        risk_adj_score = combo_score / max(0.08, v20_val) if passed else -999.0
        if passed:
            qualified_scores[c] = risk_adj_score

        momentum_board.append({
            "code": c,
            "name": ETF_UNIVERSE[c]["name"],
            "raw_price": round(float(raw_close_df.loc[latest_dt, c]), 3),
            "ret_20d_pct": round(ret_20d * 100, 2),
            "ret_5d_pct": round(ret_5d * 100, 2),
            "vol_20d_pct": round(v20_val * 100, 2),
            "above_ma20": "是" if px >= m20_val else "否(破位)",
            "momentum_r2_score": round(combo_score, 3),
            "passed_filter": "✅ 入选" if passed else "🛡️ 避险剔除",
        })

    momentum_board.sort(key=lambda x: x["momentum_r2_score"], reverse=True)
    ranked_q = sorted(qualified_scores.items(), key=lambda x: x[1], reverse=True)

    weights_s2 = {c: 0.0 for c in close_df.columns}
    if len(ranked_q) >= 2:
        weights_s2[ranked_q[0][0]] = 0.50
        weights_s2[ranked_q[1][0]] = 0.50
    elif len(ranked_q) == 1:
        weights_s2[ranked_q[0][0]] = 0.50
        weights_s2[safe_haven] = 0.50
    else:
        weights_s2[safe_haven] = 1.00

    # ---------------------------------------------------------
    # 3. 合成二合一权重并执行跨境 ETF 实时溢价率风控检验
    # ---------------------------------------------------------
    weights_combo = {}
    for c in close_df.columns:
        weights_combo[c] = 0.5 * weights_s1.get(c, 0.0) + 0.5 * weights_s2.get(c, 0.0)

    nasdaq_guard = evaluate_global_allocation(weights_combo.get("513030", 0.0))
    if not nasdaq_guard["allow_buy"]:
        for w_map in (weights_s1, weights_s2, weights_combo):
            w_rel = w_map.get("513030", 0.0)
            w_map["513030"] = 0.0
            w_map["511260"] = w_map.get("511260", 0.0) + w_rel

    # 先读取用户当前东方财富实盘持仓与预算 (my_holdings.json)，确保后续网格与下单表均使用最新预算
    holdings_path = Path(__file__).parent / "my_holdings.json"
    current_pos = {}
    if holdings_path.exists():
        try:
            with open(holdings_path, "r", encoding="utf-8") as hf:
                h_data = json.load(hf)
                current_pos = {k: int(v) for k, v in h_data.get("positions", {}).items()}
                if "total_budget" in h_data and float(h_data["total_budget"]) >= 10000.0:
                    total_capital = float(h_data["total_budget"])
        except Exception:
            current_pos = {}

    # 生成东方财富 APP 网格条件单参数（专门针对【万1.5 + 不免5(单笔最低5元)】账户定制：大步长 >=2.2% + 单格随本金按比例放大）
    grid_configs = []
    single_grid_target = max(2800.0, total_capital * 0.056)
    for gc in ["512890", "513030", "511380", "518880"]:
        raw_px = float(raw_close_df.loc[latest_dt, gc])
        # 不免5账户专享步长：放大至 >= 2.20%，确保单格毛利 > 60元，扣除买5元+卖5元=10元佣金后仍净赚 50元+
        step_pct = round(max(2.20, min(3.20, float(atr20_pct[gc]) * 100 * 1.45)), 2)
        lower_px = round(raw_px * (1.0 - step_pct * 3.5 / 100.0), 3)
        upper_px = round(raw_px * (1.0 + step_pct * 4.0 / 100.0), 3)
        alloc_amt = total_capital * weights_combo.get(gc, 0.0)
        lot_value = raw_px * 100.0
        # 仅对持仓金额 >= 本金16% (5万对应8,000元) 的主力品种开启大步长网格
        if alloc_amt >= total_capital * 0.16:
            grid_lots = max(1, round(single_grid_target / lot_value))
            shares_g = int(grid_lots * 100)
            amt_g = round(grid_lots * lot_value, 1)
            gross_profit = round(amt_g * (step_pct / 100.0), 1)
            net_profit_min5 = round(gross_profit - 10.0, 1)
            grid_note = f"✅ 不免5定制大网格：单格毛利¥{gross_profit}，扣10元佣金后【净赚¥{net_profit_min5}/次】"
        else:
            grid_lots = 1
            shares_g = 100
            amt_g = round(lot_value, 1)
            gross_profit = round(amt_g * (step_pct / 100.0), 1)
            grid_note = "⏸️ 当前仅底仓观察，不开网格（避免5元最低佣金磨损）"
        grid_configs.append({
            "code": gc,
            "name": ETF_UNIVERSE[gc]["name"],
            "base_price": round(raw_px, 3),
            "step_up_sell_pct": f"+{step_pct:.2f}%",
            "step_down_buy_pct": f"-{step_pct:.2f}%",
            "price_range": f"{lower_px:.3f} ~ {upper_px:.3f}",
            "shares_per_grid": shares_g,
            "est_amount_per_grid": amt_g,
            "est_gross_profit": gross_profit,
            "status_note": grid_note,
        })

    def build_order_sheet(weights_map: dict, capital: float, min_reserve_ratio: float = 0.055) -> list[dict]:
        """
        两阶段智能整手分配算法（目标仓位利用率 ~94.5%，仅留 1 格网格低吸备用金 ~5.5%）：
        1. 第一阶段：先确定高面值国债 ETF (511260，1手≈1.36万元) 的整手数；
        2. 第二阶段：将扣除 511260 后的剩余可投资金 (investable_cap - actual_511260)，
           按权重比例精准分配给其余小面值 ETF (512890/513030/511380/518880，1手仅120~1270元)，
           彻底消除因 511260 整手跨度大而造成的数千元资金闲置！
        """
        investable_cap = capital * (1.0 - min_reserve_ratio)
        w_bond = weights_map.get("511260", 0.0)
        px_bond = float(raw_close_df.loc[latest_dt, "511260"])
        lot_bond = px_bond * 100.0

        lots_map = {}
        if w_bond > 0.005:
            lots_b = int(round((investable_cap * w_bond) / lot_bond))
            while lots_b * lot_bond > investable_cap and lots_b > 0:
                lots_b -= 1
            lots_map["511260"] = lots_b
            amt_bond = lots_b * lot_bond
        else:
            amt_bond = 0.0

        rem_investable = max(0.0, investable_cap - amt_bond)
        other_codes = [c for c, w in weights_map.items() if c != "511260" and w > 0.005]
        other_w_sum = sum(weights_map[c] for c in other_codes)

        for c in other_codes:
            raw_px = float(raw_close_df.loc[latest_dt, c])
            lot_cost = raw_px * 100.0
            alloc_target = rem_investable * (weights_map[c] / other_w_sum) if other_w_sum > 0 else 0.0
            lots = int(round(alloc_target / lot_cost))
            if lots == 0 and (capital * weights_map[c]) >= lot_cost * 0.55 and rem_investable >= lot_cost:
                lots = 1
            lots_map[c] = lots

        orders = []
        for c, w in sorted(weights_map.items(), key=lambda x: x[1], reverse=True):
            if w <= 0.005:
                continue
            raw_px = float(raw_close_df.loc[latest_dt, c])
            lots = lots_map.get(c, 0)
            orders.append({
                "code": c,
                "name": ETF_UNIVERSE[c]["name"],
                "latest_price": round(raw_px, 3),
                "target_weight_pct": round(w * 100, 1),
                "target_amt": round(capital * w, 0),
                "suggest_shares": lots * 100,
                "suggest_lots": lots,
                "actual_amt": round(lots * 100 * raw_px, 2),
                "note": ETF_UNIVERSE[c]["desc"],
            })

        # 防超支微调：若四舍五入后略超 investable_cap，从持仓最大的小面值品种减 1 手
        total_spend = sum(item["actual_amt"] for item in orders)
        while total_spend > capital * (1.0 - 0.04):
            candidates = [x for x in orders if x["code"] != "511260" and x["suggest_lots"] >= 1]
            if not candidates:
                break
            target_item = max(candidates, key=lambda x: x["actual_amt"])
            target_item["suggest_lots"] -= 1
            target_item["suggest_shares"] = target_item["suggest_lots"] * 100
            target_item["actual_amt"] = round(target_item["suggest_shares"] * target_item["latest_price"], 2)
            total_spend = sum(item["actual_amt"] for item in orders)

        return orders

    combo_orders = build_order_sheet(weights_combo, total_capital, min_reserve_ratio=0.055)

    all_codes = ["511260", "513030", "512890", "511380", "518880", "510500"]
    target_map = {item["code"]: item["suggest_shares"] for item in combo_orders}
    is_initial_build = sum(current_pos.values()) == 0
    MIN_REBALANCE_AMT = round(total_capital * 0.036, 0)  # 按总本金的 3.6% 设定防磨损阈值（5万为1800元，6万为2160元，10万为3600元）

    action_steps = []
    post_rebalance_positions = {}
    for c in all_codes:
        cur_sh = current_pos.get(c, 0)
        tgt_sh = target_map.get(c, 0)
        diff_sh = tgt_sh - cur_sh
        raw_px = float(raw_close_df.loc[latest_dt, c])
        diff_amt = round(abs(diff_sh) * raw_px, 1)

        if diff_sh == 0:
            action = "⚪ 保持不动"
            post_sh = cur_sh
        elif (not is_initial_build) and (cur_sh > 0 and tgt_sh > 0) and (diff_amt < MIN_REBALANCE_AMT):
            action = "⚪ 微调免操作(防手续费磨损)"
            diff_sh = 0
            diff_amt = 0.0
            post_sh = cur_sh  # 触发防磨损免操作锁时，实盘不交易，同步后的实际持仓保持原股数不变
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
                "name": ETF_UNIVERSE[c]["name"],
                "latest_price": round(raw_px, 3),
                "current_shares": cur_sh,
                "target_shares": post_sh,
                "theoretical_target_shares": tgt_sh,
                "trade_shares": abs(diff_sh),
                "trade_lots": abs(diff_sh) // 100,
                "est_cash_flow": diff_amt,
            })

    order_priority = {"🔴 第一步：卖出减仓": 0, "🟢 第二步：买入加仓": 1, "⚪ 微调免操作(防手续费磨损)": 2, "⚪ 保持不动": 3}

    # 防呆校验：若因某只ETF“微调免卖出”而另一只ETF“买入加仓”导致调仓后总市值超出 (1 - 0.06) 上限，
    # 自动恢复被免除的卖出项，确保用户永远有充足现金执行买入
    max_post_spend = total_capital * (1.0 - 0.06)
    post_used_cash = round(
        sum(post_rebalance_positions[c] * float(raw_close_df.loc[latest_dt, c]) for c in all_codes), 1
    )
    if post_used_cash > max_post_spend:
        for step in action_steps:
            c = step["code"]
            if step["action"] == "⚪ 微调免操作(防手续费磨损)" and step["theoretical_target_shares"] < step["current_shares"]:
                diff_sh_restore = step["theoretical_target_shares"] - step["current_shares"]
                raw_px = float(raw_close_df.loc[latest_dt, c])
                step["action"] = "🔴 第一步：卖出减仓"
                step["target_shares"] = step["theoretical_target_shares"]
                step["trade_shares"] = abs(diff_sh_restore)
                step["trade_lots"] = abs(diff_sh_restore) // 100
                step["est_cash_flow"] = round(abs(diff_sh_restore) * raw_px, 1)
                post_rebalance_positions[c] = int(step["theoretical_target_shares"])
                post_used_cash = round(
                    sum(post_rebalance_positions[k] * float(raw_close_df.loc[latest_dt, k]) for k in all_codes), 1
                )
                if post_used_cash <= max_post_spend:
                    break

    action_steps.sort(key=lambda x: (order_priority.get(x["action"], 9), -x["est_cash_flow"]))

    used_combo_cash = post_used_cash
    reserve_cash = round(total_capital - used_combo_cash, 1)

    result = {
        "as_of_date": latest_dt.strftime("%Y-%m-%d"),
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_capital": total_capital,
        "used_combo_cash": used_combo_cash,
        "reserve_cash": reserve_cash,
        "strategy1_orders": build_order_sheet(weights_s1, total_capital),
        "strategy1_grid_params": grid_configs,
        "strategy2_momentum_board": momentum_board,
        "strategy2_orders": build_order_sheet(weights_s2, total_capital),
        "combo_orders": combo_orders,
        "combo_action_steps": action_steps,
        "post_rebalance_positions": post_rebalance_positions,
        "nasdaq_premium_guard": nasdaq_guard,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "live_signal_eastmoney.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    util_pct = used_combo_cash / total_capital * 100.0 if total_capital > 0 else 0.0
    print("==========================================================================")
    print(f"📌 东方财富 {total_capital:,.0f} 元实盘调仓指令单 (基准行情日: {result['as_of_date']} | 海外核心: 513030 德国ETF)")
    print("==========================================================================")
    print(f"\n【方案 C（推荐二合一）：50%全天候网格 + 50%动量轮动 {total_capital/10000:.1f}万元一键下单表】")
    print(pd.DataFrame(result["combo_orders"])[["code", "name", "latest_price", "target_weight_pct", "suggest_shares", "actual_amt"]].to_string(index=False))
    print(f"   -> 证券持仓合计: ¥{used_combo_cash:,.1f} 元 (资金利用率 {util_pct:.1f}%) | 预留网格低吸/逆回购备用金: ¥{reserve_cash:,.1f} 元")

    print("\n【东方财富 APP「网格交易条件单」推荐填入参数】")
    print(pd.DataFrame(result["strategy1_grid_params"]).to_string(index=False))

    print("\n【跨市场 ETF 动量轮动最新打分榜】")
    print(pd.DataFrame(result["strategy2_momentum_board"]).to_string(index=False))

    return result


if __name__ == "__main__":
    generate_live_signals(60000.0)
