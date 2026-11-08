"""
专门针对【东方财富 万1.5 佣金 + 单笔最低收费 5 元（不免5）】的 6年真实历史回测对比 (2021.01 ~ 2026.11)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from backtest_engine import (
    INITIAL_CAPITAL,
    SLIPPAGE_RATE,
    calc_ols_momentum_r2,
    calc_performance_metrics,
    load_aligned_data,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def calc_order_fee(trade_amt: float, min_fee: float = 5.0, rate: float = 0.00015) -> float:
    if trade_amt <= 1.0:
        return 0.0
    return max(min_fee, trade_amt * rate) + trade_amt * SLIPPAGE_RATE


def sim_combo(close_df, high_df, low_df, min_fee: float = 5.0, rate: float = 0.00015, mode: str = "naive"):
    ret_df = close_df.pct_change().fillna(0.0)
    vol20_df = ret_df.rolling(20, min_periods=10).std() * np.sqrt(250)
    ma60_df = close_df.rolling(60, min_periods=20).mean()
    ma20_df = close_df.rolling(20, min_periods=10).mean()
    intraday_range = (high_df - low_df) / close_df.shift(1).bfill()
    atr20_pct = intraday_range.rolling(20).mean()
    log_close = np.log(close_df)

    dates = close_df.index
    start_idx = dates.searchsorted(pd.to_datetime("2021-01-04"))
    nav = INITIAL_CAPITAL
    nav_series = {}
    all_codes = ["511260", "511380", "512890", "518880", "513030", "510500"]
    cur_w = {c: 0.0 for c in all_codes}
    cur_w["511260"] = 1.0
    w_s1 = {c: 0.0 for c in all_codes}
    w_s1["511260"] = 1.0
    w_s2 = {c: 0.0 for c in all_codes}
    w_s2["511260"] = 1.0

    total_fees = 0.0
    rebal_orders = 0
    grid_triggers = 0
    grid_net_gain_sum = 0.0

    base_budget = {"511260": 0.42, "511380": 0.16, "512890": 0.17, "518880": 0.15, "513030": 0.10}
    risk_u = ["512890", "511380", "518880", "513030", "510500"]

    for i in range(start_idx, len(dates)):
        dt = dates[i]
        d_ret = sum(cur_w[c] * ret_df.loc[dt, c] for c in all_codes if cur_w[c] > 0)
        nav *= (1.0 + d_ret)

        # 日内网格模拟（不免5时，一买一卖最少收 5 + 5 = 10 元佣金！）
        if mode != "no_grid":
            for gc in ["512890", "513030", "511380", "518880"]:
                alloc_amt = nav * cur_w.get(gc, 0.0)
                if mode == "naive":
                    # 原小步长网格：单格 ~1000元，步长 ~1.0%~1.4%
                    if alloc_amt >= 2000.0:
                        grid_order_amt = min(1100.0, alloc_amt * 0.25)
                        step = max(0.010, float(atr20_pct.loc[dt, gc]) * 0.85)
                        day_rng = float(intraday_range.loc[dt, gc])
                        if day_rng >= step * 1.35 and abs(float(ret_df.loc[dt, gc])) < day_rng * 0.75:
                            gross_gain = grid_order_amt * (step * 0.90)
                            rt_fee = 2.0 * max(min_fee, grid_order_amt * rate)
                            net_gain = gross_gain - rt_fee
                            nav += net_gain
                            total_fees += rt_fee
                            grid_triggers += 1
                            grid_net_gain_sum += net_gain
                elif mode == "optimized_min5":
                    # 针对“不免5”专门优化的【波段大网格】：单格金额随本金等比放大(5万->2800元, 6万->3360元)，但5元最低佣金不变！
                    scale = INITIAL_CAPITAL / 50000.0
                    if alloc_amt >= 8000.0 * scale:
                        grid_order_amt = 2800.0 * scale
                        step = max(0.022, float(atr20_pct.loc[dt, gc]) * 1.45)
                        day_rng = float(intraday_range.loc[dt, gc])
                        if day_rng >= step * 1.25 and abs(float(ret_df.loc[dt, gc])) < day_rng * 0.78:
                            gross_gain = grid_order_amt * (step * 0.92)
                            rt_fee = 2.0 * max(min_fee, grid_order_amt * rate)
                            net_gain = gross_gain - rt_fee
                            if net_gain > 0:
                                nav += net_gain
                                total_fees += rt_fee
                                grid_triggers += 1
                                grid_net_gain_sum += net_gain

        need_eval = False
        if (i - start_idx) % 10 == 0:
            need_eval = True
            raw_s = {c: 0.0 for c in all_codes}
            rel = 0.0
            for c, b in base_budget.items():
                v = float(vol20_df.loc[dt, c])
                v = 0.05 if (np.isnan(v) or v <= 0.005) else v
                wt = b * min(2.2, max(0.4, 0.10 / v))
                if (
                    c != "511260"
                    and float(close_df.loc[dt, c]) < float(ma60_df.loc[dt, c])
                    and float(close_df.loc[dt, c]) < float(ma20_df.loc[dt, c])
                ):
                    rel += wt * 0.55
                    wt *= 0.45
                raw_s[c] = wt
            raw_s["511260"] += rel
            tot = sum(raw_s.values())
            w_s1 = {c: raw_s[c] / tot for c in all_codes}
            if w_s1["511260"] < 0.35:
                diff = 0.35 - w_s1["511260"]
                osum = 1.0 - w_s1["511260"]
                for c in w_s1:
                    if c != "511260":
                        w_s1[c] -= diff * (w_s1[c] / osum)
                w_s1["511260"] = 0.35

        if (i - start_idx) % 5 == 0:
            need_eval = True
            scores = {}
            for c in risk_u:
                sc = 0.65 * calc_ols_momentum_r2(log_close[c].iloc[i - 20 : i + 1].values) + 0.35 * calc_ols_momentum_r2(
                    log_close[c].iloc[i - 10 : i + 1].values
                )
                px, m20, vol = float(close_df.loc[dt, c]), float(ma20_df.loc[dt, c]), float(vol20_df.loc[dt, c])
                r5 = float(close_df[c].iloc[i] / close_df[c].iloc[i - 5] - 1.0)
                if sc > 0.02 and px >= m20 and r5 > -0.038 and vol < 0.32:
                    scores[c] = sc / max(0.08, vol)
            rk = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            w_s2 = {c: 0.0 for c in all_codes}
            if len(rk) >= 2:
                w_s2[rk[0][0]] = 0.5
                w_s2[rk[1][0]] = 0.5
            elif len(rk) == 1:
                w_s2[rk[0][0]] = 0.5
                w_s2["511260"] = 0.5
            else:
                w_s2["511260"] = 1.0

        if need_eval:
            tgt_w = {c: 0.5 * w_s1[c] + 0.5 * w_s2[c] for c in all_codes}
            scale = INITIAL_CAPITAL / 50000.0
            min_trade_thresh = 300.0 * scale if mode == "naive" else 1800.0 * scale
            new_w = dict(cur_w)
            step_fee = 0.0
            changed = False
            for c in all_codes:
                trade_amt = abs(tgt_w[c] - cur_w[c]) * nav
                if i == start_idx or (tgt_w[c] == 0 and cur_w[c] > 0.02) or trade_amt >= min_trade_thresh:
                    fee = calc_order_fee(trade_amt, min_fee=min_fee, rate=rate)
                    step_fee += fee
                    total_fees += max(min_fee, trade_amt * rate) if trade_amt > 1.0 else 0.0
                    rebal_orders += 1 if trade_amt > 1.0 else 0
                    new_w[c] = tgt_w[c]
                    changed = True
            if changed:
                nav -= step_fee
                tot_nw = sum(new_w.values())
                cur_w = {c: new_w[c] / tot_nw for c in all_codes} if tot_nw > 0 else new_w

        nav_series[dt] = nav

    return pd.Series(nav_series), round(total_fees, 1), rebal_orders, grid_triggers, round(grid_net_gain_sum, 1)


def main():
    data = load_aligned_data("2020-09-01")
    close_df, high_df, low_df = data["close"], data["high"], data["low"]

    for label, mf, rt, md in [
        ("对照基准：已免5账户 (万0.6按实收，约0.2元/笔)", 0.2, 0.00006, "naive"),
        ("情况1：万1.5+不免5(最低5元) —— 照搬原小步长高频网格+无门槛微调", 5.0, 0.00015, "naive"),
        ("情况2：万1.5+不免5(最低5元) —— 关闭小网格，只跑周五低频调仓(含防微调锁)", 5.0, 0.00015, "no_grid"),
        ("情况3：万1.5+不免5(最低5元) —— 开启【不免5专用大步长网格 2.2%+2800元/格】+防微调锁", 5.0, 0.00015, "optimized_min5"),
    ]:
        ser, fees, r_cnt, g_cnt, g_net = sim_combo(close_df, high_df, low_df, mf, rt, md)
        m = calc_performance_metrics(ser, label)
        print(f"=== {label} ===")
        print(
            f"  期末总资产: ¥{m['final_capital']:,.0f} | 净赚利润: +¥{m['net_profit']:,.0f} | "
            f"年化(CAGR): {m['cagr_pct']:.2f}% | 最大回撤: {m['max_drawdown_pct']:.2f}% | 夏普: {m['sharpe_ratio']:.2f}"
        )
        print(f"  6年累计被券商收走佣金: ¥{fees:,.0f} 元 (其中调仓下单 {r_cnt} 笔, 网格来回触发 {g_cnt} 次, 网格净收益贡献: {g_net:+.0f} 元)")
        print(f"  分年度收益率: {m['yearly_returns_pct']}\n")

    print("==========================================================================")
    print("💰 不同初始本金在【万1.5 + 不免5(最低5元)】下的收益率与佣金摊薄对比")
    print("==========================================================================")
    global INITIAL_CAPITAL
    for cap in [50000.0, 60000.0, 80000.0, 100000.0]:
        INITIAL_CAPITAL = cap
        ser, fees, r_cnt, g_cnt, g_net = sim_combo(close_df, high_df, low_df, 5.0, 0.00015, "optimized_min5")
        m = calc_performance_metrics(ser, f"{int(cap//10000)}万元本金")
        fee_drag = fees / cap * 100.0
        print(
            f"本金 ¥{cap:,.0f} -> 期末资产: ¥{m['final_capital']:,.0f} | 净赚: +¥{m['net_profit']:,.0f} | "
            f"总收益率: +{m['total_return_pct']:.2f}% | 年化(CAGR): {m['cagr_pct']:.2f}% | "
            f"6年总佣金: ¥{fees:,.0f} (占初始本金 {fee_drag:.2f}%)"
        )


if __name__ == "__main__":
    main()
