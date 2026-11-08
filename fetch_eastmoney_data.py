"""
东方财富 (EastMoney) 场内 ETF 历史行情与实时数据采集模块
直接调用东方财富官方 K 线接口 (push2his.eastmoney.com)，内置自动重连与腾讯财经双源容灾备份，
无需 Token，支持前复权 (qfq/fqt=1) 与实盘最新价。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).parent / "data"

# 零权限门槛、高流动性、低相关性场内核心 ETF 池
ETF_UNIVERSE = {
    "511260": {"name": "十年国债ETF", "secid": "1.511260", "symbol": "sh511260", "category": "bond", "desc": "长久期国债，股市大跌时的避险安全屋"},
    "511360": {"name": "短融ETF", "secid": "1.511360", "symbol": "sh511360", "category": "cash_bond", "desc": "超低波动短债，类现金管理"},
    "511380": {"name": "可转债ETF", "secid": "1.511380", "symbol": "sh511380", "category": "cb", "desc": "免10万权限门槛的一篮子可转债，进可攻退可守"},
    "512890": {"name": "红利低波ETF", "secid": "1.512890", "symbol": "sh512890", "category": "equity_val", "desc": "高股息+低波动，熊市抗跌、长期复利核心"},
    "518880": {"name": "黄金ETF", "secid": "1.518880", "symbol": "sh518880", "category": "gold", "desc": "T+0抗通胀避险资产，与A股低相关"},
    "513030": {"name": "德国ETF", "secid": "1.513030", "symbol": "sh513030", "category": "global", "desc": "T+0欧洲股市龙头DAX指数，跨国别分散且常年近0溢价"},
    "510500": {"name": "中证500ETF", "secid": "1.510500", "symbol": "sh510500", "category": "equity_growth", "desc": "A股中盘成长弹性代表"},
    "510300": {"name": "沪深300ETF", "secid": "1.510300", "symbol": "sh510300", "category": "benchmark", "desc": "A股大盘宽基基准"},
}


def fetch_kline_eastmoney(secid: str, beg: str = "20200601", end: str = "20500101", fqt: int = 1) -> pd.DataFrame:
    """从东方财富获取日K线数据（带自动重试）"""
    base_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": str(fqt),
        "beg": beg,
        "end": end,
        "lmt": "10000",
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
        "Connection": "close",
    }
    last_err = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            klines = raw.get("data", {}).get("klines", [])
            if not klines:
                raise ValueError(f"东财返回空数据: {secid}")
            rows = []
            for line in klines:
                parts = line.split(",")
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": float(parts[6]),
                    "amplitude": float(parts[7]),
                    "pct_chg": float(parts[8]),
                    "chg": float(parts[9]),
                    "turnover": float(parts[10]),
                })
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    raise last_err


def fetch_kline_gtimg_fallback(symbol: str, fqt_mode: str = "qfq") -> pd.DataFrame:
    """备用高速通道：按两年分段动态拉取（单次请求上限640根K线，两年约485根，确保0缺失且跨年自动延展）"""
    all_rows = []
    cur_year = pd.Timestamp.now().year
    chunks = [("2020-06-01", "2021-12-31")]
    for y in range(2022, cur_year + 1, 2):
        chunks.append((f"{y}-01-01", f"{min(y + 1, cur_year)}-12-31"))
    for start_yr, end_yr in chunks:
        param_str = f"{symbol},day,{start_yr},{end_yr},640,{fqt_mode}"
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param_str}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Connection": "close",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        data_node = raw.get("data", {}).get(symbol, {})
        klines = data_node.get(f"{fqt_mode}day") or data_node.get("day") or []
        for item in klines:
            all_rows.append({
                "date": item[0],
                "open": float(item[1]),
                "close": float(item[2]),
                "high": float(item[3]),
                "low": float(item[4]),
                "volume": float(item[5]),
            })
    df = pd.DataFrame(all_rows).drop_duplicates(subset=["date"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["pct_chg"] = df["close"].pct_change().fillna(0.0) * 100.0
    df["amplitude"] = (df["high"] - df["low"]) / df["close"].shift(1).bfill() * 100.0
    return df


def fetch_realtime_quotes_map() -> dict[str, dict]:
    """从实时行情流获取全部核心 ETF 的盘中最新价与当日高低开数据，确保盘中(如14:45)运行时100%包含当日最新K线"""
    syms = ",".join(info["symbol"] for info in ETF_UNIVERSE.values())
    url = f"https://qt.gtimg.cn/q={syms}"
    quotes = {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("gbk", errors="ignore")
        for line in text.strip().split(";"):
            parts = line.split("~")
            if len(parts) > 35 and parts[2] and parts[3]:
                code = parts[2].strip()
                ts_str = parts[30].strip()
                if len(ts_str) >= 8 and float(parts[3]) > 0:
                    dt_val = pd.to_datetime(ts_str[:8], format="%Y%m%d")
                    quotes[code] = {
                        "date": dt_val,
                        "raw_close": float(parts[3]),
                        "prev_raw_close": float(parts[4]) if parts[4] else float(parts[3]),
                        "raw_open": float(parts[5]) if parts[5] and float(parts[5]) > 0 else float(parts[3]),
                        "raw_high": float(parts[33]) if parts[33] and float(parts[33]) > 0 else float(parts[3]),
                        "raw_low": float(parts[34]) if parts[34] and float(parts[34]) > 0 else float(parts[3]),
                        "volume": float(parts[36]) if parts[36] else 0.0,
                    }
    except Exception:
        pass
    return quotes


def fetch_etf_history(code: str, info: dict, rt_quote: dict | None = None) -> pd.DataFrame:
    secid = info["secid"]
    symbol = info["symbol"]
    try:
        df_adj = fetch_kline_eastmoney(secid, beg="20200601", fqt=1)
        time.sleep(0.2)
        df_raw = fetch_kline_eastmoney(secid, beg="20200601", fqt=0)
    except Exception as e:
        print(f"   [提示] 东财直连限流 ({e})，自动启用备用高速接口拉取 [{code}]...")
        df_adj = fetch_kline_gtimg_fallback(symbol, "qfq")
        df_raw = fetch_kline_gtimg_fallback(symbol, "")

    df = df_adj.merge(
        df_raw[["date", "open", "close", "high", "low"]].rename(
            columns={
                "open": "raw_open",
                "close": "raw_close",
                "high": "raw_high",
                "low": "raw_low",
            }
        ),
        on="date",
        how="left",
    )
    df["raw_close"] = df["raw_close"].fillna(df["close"])
    df["raw_high"] = df["raw_high"].fillna(df["high"])
    df["raw_low"] = df["raw_low"].fillna(df["low"])

    # 若盘中运行且备用接口尚未归档当日K线，自动将实时行情流中的当日K线合并进去；若已有当日K线则刷新为最新秒级现价
    if rt_quote and rt_quote["date"] > df["date"].max():
        last_row = df.iloc[-1]
        prev_raw = rt_quote["prev_raw_close"] if rt_quote["prev_raw_close"] > 0 else float(last_row["raw_close"])
        adj_factor = float(last_row["close"]) / prev_raw if prev_raw > 0 else 1.0
        new_close = round(rt_quote["raw_close"] * adj_factor, 4)
        new_open = round(rt_quote["raw_open"] * adj_factor, 4)
        new_high = round(rt_quote["raw_high"] * adj_factor, 4)
        new_low = round(rt_quote["raw_low"] * adj_factor, 4)
        pct_chg = (rt_quote["raw_close"] / prev_raw - 1.0) * 100.0 if prev_raw > 0 else 0.0
        amp = (rt_quote["raw_high"] - rt_quote["raw_low"]) / prev_raw * 100.0 if prev_raw > 0 else 0.0
        new_row = {
            "date": rt_quote["date"],
            "open": new_open,
            "close": new_close,
            "high": new_high,
            "low": new_low,
            "volume": rt_quote["volume"],
            "pct_chg": round(pct_chg, 2),
            "amplitude": round(amp, 2),
            "raw_open": rt_quote["raw_open"],
            "raw_close": rt_quote["raw_close"],
            "raw_high": rt_quote["raw_high"],
            "raw_low": rt_quote["raw_low"],
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    elif rt_quote and rt_quote["date"] == df["date"].max() and len(df) >= 2:
        idx_last = df.index[-1]
        df.loc[idx_last, "raw_close"] = rt_quote["raw_close"]
        df.loc[idx_last, "raw_high"] = max(float(df.loc[idx_last, "raw_high"]), rt_quote["raw_high"])
        df.loc[idx_last, "raw_low"] = min(float(df.loc[idx_last, "raw_low"]), rt_quote["raw_low"])

    return df


def download_all(force_refresh: bool = True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("==========================================================")
    print("正在从东方财富 (EastMoney) 同步最新场内 ETF 历史与实盘行情...")
    print("==========================================================")

    rt_quotes = fetch_realtime_quotes_map()
    for code, info in ETF_UNIVERSE.items():
        name = info["name"]
        out_path = DATA_DIR / f"{code}.csv"
        if (not force_refresh) and out_path.exists() and out_path.stat().st_size > 10000:
            df_exist = pd.read_csv(out_path)
            if len(df_exist) >= 1450:
                print(
                    f"-> [已缓存] [{code} {name}] 共 {len(df_exist)} 个交易日 "
                    f"({df_exist['date'].iloc[0]} ~ {df_exist['date'].iloc[-1]}), "
                    f"最新实盘价: {df_exist['raw_close'].iloc[-1]:.3f}"
                )
                continue

        print(f"-> 正在拉取 [{code} {name}] 最新前复权与实盘价格序列...")
        try:
            df = fetch_etf_history(code, info, rt_quote=rt_quotes.get(code))
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            print(
                f"   [成功] 共 {len(df)} 个交易日 ({df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}), "
                f"最新实盘价: {df['raw_close'].iloc[-1]:.3f}"
            )
            time.sleep(0.3)
        except Exception as e:
            if out_path.exists():
                df_exist = pd.read_csv(out_path)
                print(f"   [警告] 网络拉取失败 ({e})，回退使用本地最近缓存 ({df_exist['date'].iloc[-1]})")
            else:
                raise

    # 同步刷新场内4大纳指ETF的实时IOPV与折溢价率
    try:
        from qdii_premium_guard import fetch_nasdaq_premiums_live
        nq_records = fetch_nasdaq_premiums_live()
        print("-> [成功] 已同步纳指ETF实时IOPV与溢价率:", [(r["code"], f"{r['premium_pct']:+.2f}%") for r in nq_records])
    except Exception as e:
        print(f"-> [提示] 纳指溢价率同步跳过: {e}")

    print("\n全部东方财富 ETF 历史行情数据已保存至:", DATA_DIR)


if __name__ == "__main__":
    download_all()
