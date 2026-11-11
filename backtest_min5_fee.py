"""
专门针对【东方财富 万1.5 佣金 + 单笔最低收费 5 元（不免5）+ 100股整手】的回测与资金规模敏感性对比
"""
import sys
import pandas as pd

from backtest_engine import (
    COMBO_S1_WEIGHT,
    calc_performance_metrics,
    load_aligned_data,
    run_strict_account_backtest,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    data = load_aligned_data("2020-09-01")
    close_df, raw_close_df = data["close"], data["raw_close"]

    print("=========================================================================================")
    print("🔬 一、6万元本金下：不同佣金制度与防微调锁对严格整手净收益的影响 (2021.01 ~ 2026.11)")
    print("=========================================================================================")
    scenarios = [
        ("对照A：已免5特惠账户 (万0.6按实收，最低0.1元/笔)", 0.1, 0.00006, 0.04, 1),
        ("对照B：万1.5+不免5(最低5元) —— 无防微调锁 + 无Top3缓冲", 5.0, 0.00015, 0.00, 0),
        ("当前实盘：万1.5+不免5(最低5元) —— 开启4%防微调锁 + Top3排名缓冲", 5.0, 0.00015, 0.04, 1),
    ]
    for label, mf, rt, rebal_lock, r_buf in scenarios:
        res = run_strict_account_backtest(
            close_df,
            raw_close_df,
            s1_weight=COMBO_S1_WEIGHT,
            initial_capital=60000.0,
            min_fee=mf,
            comm_rate=rt,
            min_rebal_ratio=rebal_lock,
            rank_buffer=r_buf,
        )
        m = calc_performance_metrics(res["nav"], label, base_capital=60000.0)
        print(f"=== {label} ===")
        print(
            f"  期末总资产: ¥{m['final_capital']:,.0f} | 净赚利润: +¥{m['net_profit']:,.0f} | "
            f"年化(CAGR): {m['cagr_pct']:.2f}% | 最大回撤: {m['max_drawdown_pct']:.2f}% | 夏普: {m['sharpe_ratio']:.2f}"
        )
        print(
            f"  6年累计券商佣金: ¥{res['total_commission_rmb']:,.0f} 元 "
            f"(含滑点总摩擦: ¥{res['total_cost_with_slip_rmb']:,.0f} 元 | 累计成交 {res['order_count']} 笔)"
        )
        print(f"  分年度收益率: {m['yearly_returns_pct']}\n")

    print("=========================================================================================")
    print("💰 二、不同初始本金规模 (5万 ~ 20万) 在【万1.5 + 不免5 + 100股整手】下的表现对比")
    print("=========================================================================================")
    rows = []
    for cap in [50000.0, 60000.0, 100000.0, 150000.0, 200000.0]:
        res = run_strict_account_backtest(
            close_df,
            raw_close_df,
            s1_weight=COMBO_S1_WEIGHT,
            initial_capital=cap,
            min_fee=5.0,
            comm_rate=0.00015,
        )
        m = calc_performance_metrics(res["nav"], f"{int(cap//10000)}万元本金", base_capital=cap)
        comm_drag = res["total_commission_rmb"] / cap * 100.0
        rows.append({
            "初始本金": f"¥{cap:,.0f}",
            "期末总资产": f"¥{m['final_capital']:,.0f}",
            "净赚利润": f"+¥{m['net_profit']:,.0f}",
            "累计收益率": f"+{m['total_return_pct']:.2f}%",
            "年化(CAGR)": f"{m['cagr_pct']:.2f}%",
            "最大回撤": f"{m['max_drawdown_pct']:.2f}%",
            "夏普": f"{m['sharpe_ratio']:.2f}",
            "6年总佣金(占本金)": f"¥{res['total_commission_rmb']:,.0f} ({comm_drag:.2f}%)",
        })
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
