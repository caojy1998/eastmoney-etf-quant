"""
对比实验：使用【513030 德国ETF (欧洲股市龙头)】与【513400 道琼斯ETF】替代【513100 纳指ETF】
在 2021.01 ~ 2026.11 期间的真实历史回测表现对比
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from backtest_engine import (
    COMMISSION_RATE,
    INITIAL_CAPITAL,
    TOTAL_COST_RATE,
    calc_ols_momentum_r2,
    calc_performance_metrics,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).parent / "data"


def load_extended_data(start_date: str = "2020-09-01") -> dict:
    codes = ["511260", "511360", "511380", "512890", "518880", "513100", "510500", "510300", "513030", "513400"]
    dfs = {}
    for code in codes:
        csv_path = DATA_DIR / f"{code}.csv"
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["date"] >= pd.to_datetime(start_date)].sort_values("date").reset_index(drop=True)
        dfs[code] = df.set_index("date")

    calendar = dfs["510300"].index
    close_df = pd.DataFrame(index=calendar)
    high_df = pd.DataFrame(index=calendar)
    low_df = pd.DataFrame(index=calendar)

    for code, df in dfs.items():
        # 注意：对于 2024 年才上市的 513400 道琼斯ETF，不使用 bfill 填充上市前数据，而是保留 NaN 以便上市前不参与交易
        reindexed = df.reindex(calendar).ffill()
        if code != "513400":
            reindexed = reindexed.bfill()
        close_df[code] = reindexed["close"]
        high_df[code] = reindexed["high"]
        low_df[code] = reindexed["low"]

    return {"close": close_df, "high": high_df, "low": low_df}


def run_s1_custom(close_df, high_df, low_df, mode: str, eval_start: str = "2021-01-04") -> pd.Series:
    ret_df = close_df.pct_change(fill_method=None).fillna(0.0)
    vol20_df = ret_df.rolling(20, min_periods=10).std() * np.sqrt(250)
    ma60_df = close_df.rolling(60, min_periods=20).mean()
    ma20_df = close_df.rolling(20, min_periods=10).mean()
    intraday_range = (high_df - low_df) / close_df.shift(1)
    atr20_pct = intraday_range.rolling(20, min_periods=10).mean()

    dates = close_df.index
    start_idx = dates.searchsorted(pd.to_datetime(eval_start))
    nav = INITIAL_CAPITAL
    nav_series = {}
    all_cols = list(close_df.columns)
    current_weights = {c: 0.0 for c in all_cols}
    current_weights["511260"] = 1.0

    for i in range(start_idx, len(dates)):
        dt = dates[i]
        daily_ret = sum(current_weights[c] * ret_df.loc[dt, c] for c in all_cols if current_weights[c] > 0)
        grid_alpha = 0.0
        for gc in ["511380", "512890", "518880"]:
            w = current_weights.get(gc, 0.0)
            if w > 0.05:
                step = max(0.009, float(atr20_pct.loc[dt, gc]) * 0.85)
                day_rng = float(intraday_range.loc[dt, gc])
                day_ret = abs(float(ret_df.loc[dt, gc]))
                if day_rng >= step * 1.35 and day_ret < day_rng * 0.75:
                    net_grid_gain = (step * 0.45) - (2 * COMMISSION_RATE)
                    if net_grid_gain > 0:
                        grid_alpha += (w * 0.25) * net_grid_gain
        nav *= (1.0 + daily_ret + grid_alpha)

        if (i - start_idx) % 10 == 0:
            if mode == "nasdaq":
                budget_map = {"511260": 0.42, "511380": 0.16, "512890": 0.17, "518880": 0.15, "513100": 0.10}
            elif mode == "germany_only":
                budget_map = {"511260": 0.42, "511380": 0.16, "512890": 0.17, "518880": 0.15, "513030": 0.10}
            elif mode == "germany_dow":
                # 若 513400 道琼斯已上市满 60 天，则德国ETF与道琼斯ETF各分 5% 预算；上市前由德国ETF占 10%
                if not np.isnan(ma60_df.loc[dt, "513400"]):
                    budget_map = {"511260": 0.42, "511380": 0.16, "512890": 0.17, "518880": 0.15, "513030": 0.05, "513400": 0.05}
                else:
                    budget_map = {"511260": 0.42, "511380": 0.16, "512890": 0.17, "518880": 0.15, "513030": 0.10}
            raw_scores = {c: 0.0 for c in all_cols}
            released_to_bond = 0.0
            for c, budget in budget_map.items():
                v = float(vol20_df.loc[dt, c])
                if np.isnan(v) or v <= 0.005:
                    v = 0.05
                w_target = budget * min(2.2, max(0.4, 0.10 / v))
                if c != "511260":
                    px = float(close_df.loc[dt, c])
                    if px < float(ma60_df.loc[dt, c]) and px < float(ma20_df.loc[dt, c]):
                        released_to_bond += w_target * 0.55
                        w_target *= 0.45
                raw_scores[c] = w_target
            raw_scores["511260"] += released_to_bond
            tot = sum(raw_scores.values())
            new_weights = {c: raw_scores[c] / tot for c in all_cols}
            if new_weights["511260"] < 0.35:
                diff = 0.35 - new_weights["511260"]
                other_sum = 1.0 - new_weights["511260"]
                for c in new_weights:
                    if c != "511260":
                        new_weights[c] -= diff * (new_weights[c] / other_sum)
                new_weights["511260"] = 0.35
            turnover = sum(abs(new_weights[c] - current_weights[c]) for c in all_cols)
            if turnover > 0.06 or i == start_idx:
                nav -= nav * turnover * TOTAL_COST_RATE
                current_weights = new_weights
        nav_series[dt] = nav
    return pd.Series(nav_series)


def run_s2_custom(close_df, mode: str, eval_start: str = "2021-01-04") -> pd.Series:
    ret_df = close_df.pct_change(fill_method=None).fillna(0.0)
    log_close = np.log(close_df)
    ma20_df = close_df.rolling(20, min_periods=10).mean()
    vol20_df = ret_df.rolling(20, min_periods=10).std() * np.sqrt(250)

    if mode == "nasdaq":
        risk_universe = ["512890", "511380", "518880", "513100", "510500"]
    elif mode == "germany_only":
        risk_universe = ["512890", "511380", "518880", "513030", "510500"]
    elif mode == "germany_dow":
        risk_universe = ["512890", "511380", "518880", "513030", "513400", "510500"]

    safe_haven = "511260"
    dates = close_df.index
    start_idx = dates.searchsorted(pd.to_datetime(eval_start))
    nav = INITIAL_CAPITAL
    nav_series = {}
    current_weights = {c: 0.0 for c in close_df.columns}
    current_weights[safe_haven] = 1.0

    for i in range(start_idx, len(dates)):
        dt = dates[i]
        daily_ret = sum(current_weights[c] * ret_df.loc[dt, c] for c in current_weights if current_weights[c] > 0)
        nav *= (1.0 + daily_ret)

        if (i - start_idx) % 5 == 0:
            scores = {}
            for c in risk_universe:
                w20 = log_close[c].iloc[i - 20 : i + 1].values
                if np.isnan(w20).any():
                    continue
                w10 = log_close[c].iloc[i - 10 : i + 1].values
                combo_score = 0.65 * calc_ols_momentum_r2(w20) + 0.35 * calc_ols_momentum_r2(w10)
                px = float(close_df.loc[dt, c])
                m20 = float(ma20_df.loc[dt, c])
                vol = float(vol20_df.loc[dt, c])
                r5 = float(close_df[c].iloc[i] / close_df[c].iloc[i - 5] - 1.0)
                if combo_score > 0.02 and px >= m20 and r5 > -0.038 and vol < 0.32:
                    scores[c] = combo_score / max(0.08, vol)
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            new_weights = {c: 0.0 for c in close_df.columns}
            if len(ranked) >= 2:
                new_weights[ranked[0][0]] = 0.50
                new_weights[ranked[1][0]] = 0.50
            elif len(ranked) == 1:
                new_weights[ranked[0][0]] = 0.50
                new_weights[safe_haven] = 0.50
            else:
                new_weights[safe_haven] = 1.00
            turnover = sum(abs(new_weights[c] - current_weights[c]) for c in new_weights)
            if turnover > 0.01:
                nav -= nav * turnover * TOTAL_COST_RATE
                current_weights = new_weights
        nav_series[dt] = nav
    return pd.Series(nav_series)


def main():
    data = load_extended_data()
    close_df, high_df, low_df = data["close"], data["high"], data["low"]

    for mode, title in [
        ("nasdaq", "原版：含 513100 纳指ETF"),
        ("germany_only", "替代方案A：用 513030 德国ETF(欧洲龙头) 替代纳指"),
        ("germany_dow", "替代方案B：用 513030 德国ETF + 513400 道琼斯ETF 替代纳指"),
    ]:
        s1 = run_s1_custom(close_df, high_df, low_df, mode)
        s2 = run_s2_custom(close_df, mode)
        combo = 0.5 * s1 + 0.5 * s2
        print("=================================================================")
        print(f"📊 {title}")
        for ser, label in [(s1, "策略一(全天候网格)"), (s2, "策略二(动量轮动)"), (combo, "二合一组合(50%+50%)")]:
            m = calc_performance_metrics(ser, label)
            print(
                f"  - {label}: 期末 ¥{m['final_capital']:,.0f} | 净利 +¥{m['net_profit']:,.0f} | "
                f"年化 {m['cagr_pct']:.2f}% | 最大回撤 {m['max_drawdown_pct']:.2f}% | 夏普 {m['sharpe_ratio']:.2f} | "
                f"分年: {m['yearly_returns_pct']}"
            )


if __name__ == "__main__":
    main()
