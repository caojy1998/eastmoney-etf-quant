"""
对比实验：我们的【二合一量化策略 / 动量轮动策略】 vs 【标普500ETF (513500) 一次性买入】 vs 【标普500 定投 (DCA)】
回测区间：2021-01-04 ~ 2026-11-06 (近6年真实历史数据，初始总本金 50,000 元)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from backtest_engine import (
    INITIAL_CAPITAL,
    calc_performance_metrics,
    load_aligned_data,
    run_strategy1_all_weather_grid,
    run_strategy2_momentum_rotation,
)
from backtest_min5_fee import sim_combo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).parent / "data"


def calc_xirr_approx(monthly_cashflows: list[float]) -> float:
    """用牛顿迭代/二分法计算月度现金流的年化内部收益率 (IRR)"""
    low, high = -0.05, 0.05
    for _ in range(60):
        mid = (low + high) / 2.0
        npv = sum(cf / ((1.0 + mid) ** t) for t, cf in enumerate(monthly_cashflows))
        if npv > 0:
            low = mid
        else:
            high = mid
    monthly_irr = (low + high) / 2.0
    return ((1.0 + monthly_irr) ** 12 - 1.0) * 100.0


def main():
    data = load_aligned_data("2020-09-01")
    close_df, high_df, low_df = data["close"], data["high"], data["low"]

    sp_df = pd.read_csv(DATA_DIR / "513500.csv")
    sp_df["date"] = pd.to_datetime(sp_df["date"])
    sp_df = sp_df.set_index("date").reindex(close_df.index).ffill().bfill()
    close_df["513500"] = sp_df["close"]

    eval_start = "2021-01-04"
    nav_s1, _ = run_strategy1_all_weather_grid(close_df, high_df, low_df, eval_start=eval_start)
    nav_s2, _ = run_strategy2_momentum_rotation(close_df, eval_start=eval_start)
    nav_combo_min5, _, _, _, _ = sim_combo(close_df, high_df, low_df, 5.0, 0.00015, "optimized_min5")

    dates = nav_s1.index
    sp_slice = close_df.loc[dates, "513500"]

    # 1. 标普500ETF (513500) 5万元一次性全仓买入死拿 (含场内 +10.74% 溢价)
    nav_sp500_lump = INITIAL_CAPITAL * (sp_slice / sp_slice.iloc[0])

    # 2. 标普500 真实净值 (剔除当前场内 +10.74% 虚高溢价泡沫后的真实净值表现)
    # 513500 最新场内价 2.588 vs 官方实时IOPV 2.3371 (溢价率 +10.74%)
    nav_sp500_iopv = nav_sp500_lump.copy()
    # 按期末真实 IOPV 折算剔除溢价后的真实价值
    iopv_discount_factor = 2.3371 / 2.588

    # 3. 标普500 定投 (DCA)：50,000元总本金，分 71 个月每月首个交易日定投 ~704.2 元
    #    - 场景 3A：场外定投 / 免5定投 (无最低5元磨损，闲置待投本金在货币基金享受 2.0% 年化收益)
    #    - 场景 3B：场内不免5定投 (每次定投704元被硬扣 5 元最低佣金 = 0.71% 手续费磨损)
    monthly_first_dates = set(sp_slice.groupby([sp_slice.index.year, sp_slice.index.month]).apply(lambda g: g.index[0]))
    n_months = len(monthly_first_dates)
    installment = INITIAL_CAPITAL / n_months

    cash_pool_a = INITIAL_CAPITAL
    shares_a = 0.0
    dca_nav_a = {}

    cash_pool_b = INITIAL_CAPITAL
    shares_b = 0.0
    dca_nav_b = {}

    cashflows_a = []
    for dt in dates:
        px = float(sp_slice.loc[dt])
        # 闲置待定投现金每日获得 2.0% 年化货币基金利息
        cash_pool_a *= (1.0 + 0.02 / 250.0)
        cash_pool_b *= (1.0 + 0.02 / 250.0)

        if dt in monthly_first_dates:
            amt_a = min(cash_pool_a, installment)
            cash_pool_a -= amt_a
            shares_a += (amt_a * (1.0 - 0.0005)) / px
            cashflows_a.append(-installment)

            amt_b = min(cash_pool_b, installment)
            cash_pool_b -= amt_b
            shares_b += max(0.0, amt_b - 5.0) / px

        dca_nav_a[dt] = cash_pool_a + shares_a * px
        dca_nav_b[dt] = cash_pool_b + shares_b * px

    ser_dca_a = pd.Series(dca_nav_a)
    ser_dca_b = pd.Series(dca_nav_b)
    cashflows_a[-1] += float(shares_a * sp_slice.iloc[-1])
    xirr_dca = calc_xirr_approx(cashflows_a)

    items = [
        calc_performance_metrics(nav_s2, "我们的策略二：跨市场ETF动量轮动+国债避险"),
        calc_performance_metrics(nav_combo_min5, "我们的二合一策略 (50%全天候+50%动量，含不免5扣费)"),
        calc_performance_metrics(nav_s1, "我们的策略一：全天候“超级固收+”+网格"),
        calc_performance_metrics(nav_sp500_lump, "标普500ETF(513500) 一次性梭哈死拿 (含场内10.7%溢价)"),
        calc_performance_metrics(ser_dca_a, f"标普500 按月定投 (5万分{n_months}期，闲钱放货基)"),
        calc_performance_metrics(ser_dca_b, f"标普500 场内不免5按月定投 (每次扣5元佣金)"),
    ]

    print("========================================================================================")
    print("🇺🇸 我们的量化策略 vs 标普500 (一次性买入 & 按月定投) 6年真实历史对比 (2021.01 ~ 2026.11)")
    print("========================================================================================")
    for m in items:
        print(
            f"【{m['name']}】\n"
            f"   期末总资产: ¥{m['final_capital']:,.0f} | 净赚利润: +¥{m['net_profit']:,.0f} | "
            f"总收益率: +{m['total_return_pct']:.2f}% | 年化(CAGR): {m['cagr_pct']:.2f}% | "
            f"最大回撤: {m['max_drawdown_pct']:.2f}% | 夏普: {m['sharpe_ratio']:.2f} | 卡玛(收益/回撤): {m['calmar_ratio']:.2f}\n"
            f"   分年收益(%): {m['yearly_returns_pct']}"
        )

    true_sp_final = float(nav_sp500_lump.iloc[-1] * iopv_discount_factor)
    true_sp_cagr = ((true_sp_final / INITIAL_CAPITAL) ** (1.0 / 5.84) - 1.0) * 100.0
    print("----------------------------------------------------------------------------------------")
    print(f"⚠️ 补充1：标普500ETF(513500) 若剔除当前场内 +10.74% 虚高溢价泡沫（按真实IOPV净值结算）：")
    print(f"   真实期末净值资产: ¥{true_sp_final:,.0f} (净赚 +¥{true_sp_final - INITIAL_CAPITAL:,.0f}) | 真实净值年化(CAGR): {true_sp_cagr:.2f}%")
    print(f"⚠️ 补充2：标普500按月定投的资金内部收益率 (XIRR，仅算已入场资金时间权重): {xirr_dca:.2f}%，但因前几年大部分资金躺在货币基金里等定投，5万元总本金的实际复合年化为 {items[4]['cagr_pct']:.2f}%。")


if __name__ == "__main__":
    main()
