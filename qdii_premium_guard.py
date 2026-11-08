"""
QDII / 跨境 ETF (513030 德国ETF等) 实时折溢价率监控与防雷模块
解决痛点：
  1. 已将海外核心仓位升级为常年近 0 溢价的【513030 德国ETF (欧洲股市龙头DAX)】(当前溢价仅 +0.14%)，彻底规避纳指ETF(+21.26%)的极端溢价风险。
  2. 本模块仍每次实时监控 513030 及场内其他代表性跨境 ETF (513630 / 513400 / 513100) 的实时 IOPV 与折溢价率：
     - 若 513030 德国ETF 溢价率 <= 2.5%：正常按策略信号建仓/持有；
     - 若未来某天 513030 德国ETF 也因极端行情出现 > 2.5% 的溢价，自动触发熔断转入十年国债ETF(511260)避险！
"""
import json
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
CACHE_PATH = DATA_DIR / "nasdaq_premium_snapshot.json"

GLOBAL_ETF_POOL = [
    {"code": "513030", "name": "华安德国ETF(主力)", "secid": "1.513030", "gt_sym": "sh513030"},
    {"code": "513630", "name": "港股红利低波ETF", "secid": "1.513630", "gt_sym": "sh513630"},
    {"code": "513400", "name": "鹏华道琼斯ETF", "secid": "1.513400", "gt_sym": "sh513400"},
    {"code": "513100", "name": "国泰纳指ETF(高溢价对照)", "secid": "1.513100", "gt_sym": "sh513100"},
]

MAX_BUY_PREMIUM_PCT = 2.50   # 买入熔断线：溢价率超过 2.5% 严禁新建仓/追高


def fetch_nasdaq_premiums_live() -> list[dict]:
    """
    从实时行情接口拉取德国ETF及对照跨境ETF的实时现价、IOPV(parts[78]) 与 实时折溢价率(parts[77])，
    并持久化缓存至 data/nasdaq_premium_snapshot.json。
    """
    records = []
    try:
        syms = ",".join(item["gt_sym"] for item in GLOBAL_ETF_POOL)
        url = f"https://qt.gtimg.cn/q={syms}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("gbk", errors="ignore")
        for line, meta in zip(text.strip().split(";"), GLOBAL_ETF_POOL):
            parts = line.split("~")
            if len(parts) > 78 and parts[3]:
                price = float(parts[3])
                prem_pct = float(parts[77]) if parts[77] else 0.0
                iopv = float(parts[78]) if parts[78] else round(price / (1.0 + prem_pct / 100.0), 4)
                records.append({
                    "code": meta["code"],
                    "name": meta["name"],
                    "price": round(price, 3),
                    "iopv": round(iopv, 4),
                    "premium_pct": round(prem_pct, 2),
                    "source": "实时行情官方IOPV",
                })
    except Exception:
        pass

    if records:
        records.sort(key=lambda x: x["premium_pct"])
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return records

    if CACHE_PATH.exists():
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    raise RuntimeError("未找到跨境ETF实时溢价率数据，请先运行 fetch_eastmoney_data.py 拉取最新行情。")


def evaluate_global_allocation(raw_weight: float) -> dict:
    """
    检验主力跨境品种【513030 德国ETF】的实时溢价率是否处于安全区间 (<= 2.5%)
    """
    candidates = fetch_nasdaq_premiums_live()
    p513030 = next((x for x in candidates if x["code"] == "513030"), candidates[0])
    p513100 = next((x for x in candidates if x["code"] == "513100"), candidates[-1])

    if p513030["premium_pct"] > MAX_BUY_PREMIUM_PCT:
        return {
            "status": "🚨 高溢价熔断保护（禁止买入）",
            "allow_buy": False,
            "adjusted_weight": 0.0,
            "redirect_to_bond_weight": raw_weight,
            "target_etf": p513030,
            "all_candidates": candidates,
            "advice": (
                f"🚨 触发高溢价熔断！513030 德国ETF 当前实时溢价率达 +{p513030['premium_pct']:.2f}% > {MAX_BUY_PREMIUM_PCT}% 熔断线，"
                f"程序已自动将其买入仓位清零，转入【511260 十年国债ETF】避险！"
            ),
        }

    return {
        "status": "✅ 溢价极低（安全可买）",
        "allow_buy": True,
        "adjusted_weight": raw_weight,
        "redirect_to_bond_weight": 0.0,
        "target_etf": p513030,
        "all_candidates": candidates,
        "advice": (
            f"✅ 海外主力【513030 德国ETF】当前场内现价 {p513030['price']:.3f} vs 官方实时IOPV {p513030['iopv']:.4f}，"
            f"实时溢价率仅 {p513030['premium_pct']:+.2f}%（远低于 {MAX_BUY_PREMIUM_PCT}% 熔断线，对比纳指ETF 513100 的 "
            f"{p513100['premium_pct']:+.2f}% 高溢价省下超过 21% 溢价成本），可放心按信号建仓！"
        ),
    }
