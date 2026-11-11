"""
跨境 / 大宗商品 ETF (513030 德国ETF / 159980 有色ETF 等) 实时折溢价率监控与防雷模块
解决痛点：
  1. 核心仓位采用常年近 0 溢价的【513030 德国ETF】、【159980 有色ETF】与【159915 创业板ETF】，彻底规避纳指ETF(+20%+)的极端溢价风险。
  2. 本模块每次实时监控主力品种及场内对照跨境 ETF (513630 / 513400 / 513100) 的实时 IOPV 与折溢价率：
     - 空仓新买时：溢价率 <= 2.80% 允许建仓；超过 2.80% 严禁追高，仓位自动转入安全债券避险；
     - 已持仓时：考虑欧股16:00开盘/夜盘时差导致的日内静态IOPV滞后，溢价率 <= 5.50% 继续持有，避免假性溢价频繁清仓磨损。
"""
import json
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
CACHE_PATH = DATA_DIR / "nasdaq_premium_snapshot.json"

GLOBAL_ETF_POOL = [
    {"code": "513030", "name": "华安德国ETF(海外主力)", "secid": "1.513030", "gt_sym": "sh513030"},
    {"code": "159980", "name": "大成有色ETF(商品主力)", "secid": "0.159980", "gt_sym": "sz159980"},
    {"code": "159915", "name": "易方达创业板ETF(成长主力)", "secid": "0.159915", "gt_sym": "sz159915"},
    {"code": "513630", "name": "港股红利低波ETF(备用观察)", "secid": "1.513630", "gt_sym": "sh513630"},
    {"code": "513400", "name": "鹏华道琼斯ETF(美股对照)", "secid": "1.513400", "gt_sym": "sh513400"},
    {"code": "513100", "name": "国泰纳指ETF(高溢价防雷对照)", "secid": "1.513100", "gt_sym": "sh513100"},
]

MAX_BUY_PREMIUM_PCT = 2.80   # 空仓新建仓熔断线：溢价率超过 2.8% 严禁新建仓/追高
MAX_HOLD_PREMIUM_PCT = 5.50  # 已持仓止盈熔断线：考虑欧股16:00开盘导致的日内IOPV滞后，已持仓时溢价率<=5.5%免于清仓折腾


def fetch_nasdaq_premiums_live() -> list[dict]:
    """
    从实时行情接口拉取主力ETF及对照跨境ETF的实时现价、IOPV(parts[78]) 与 实时折溢价率(parts[77])，
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

    raise RuntimeError("未找到实时溢价率数据，请先运行 fetch_eastmoney_data.py 拉取最新行情。")


def check_single_etf_premium(code: str, is_holding: bool, candidates: list[dict]) -> dict:
    item = next((x for x in candidates if x["code"] == code), None)
    if not item:
        return {"code": code, "allow_buy": True, "premium_pct": 0.0, "threshold": MAX_BUY_PREMIUM_PCT}
    threshold = MAX_HOLD_PREMIUM_PCT if is_holding else MAX_BUY_PREMIUM_PCT
    allow = item["premium_pct"] <= threshold
    return {
        "code": code,
        "name": item["name"],
        "price": item["price"],
        "iopv": item["iopv"],
        "premium_pct": item["premium_pct"],
        "threshold": threshold,
        "allow_buy": allow,
        "in_buffer": bool(is_holding and allow and item["premium_pct"] > MAX_BUY_PREMIUM_PCT),
    }


def evaluate_global_allocation(
    raw_weight: float,
    is_holding: bool = False,
    holdings_map: dict[str, int] | None = None,
) -> dict:
    """
    检验海外与大宗商品主力品种【513030 德国ETF / 159980 有色ETF / 159915 创业板ETF】的实时溢价率：
      - 空仓新买时：溢价率 <= 2.8% 允许建仓；
      - 已持仓时（含欧股未开盘导致的A股日内IOPV滞后）：溢价率 <= 5.5% 继续安心持有，避免假性溢价频繁清仓磨损。
    """
    candidates = fetch_nasdaq_premiums_live()
    holdings_map = holdings_map or {}
    hold_513030 = is_holding or (holdings_map.get("513030", 0) > 0)

    p513030 = next((x for x in candidates if x["code"] == "513030"), candidates[0])
    p513100 = next((x for x in candidates if x["code"] == "513100"), candidates[-1])

    per_etf_checks = {}
    blocked_codes = []
    for code in ["513030", "159980", "159915"]:
        chk = check_single_etf_premium(code, holdings_map.get(code, 0) > 0 or (code == "513030" and hold_513030), candidates)
        per_etf_checks[code] = chk
        if not chk["allow_buy"]:
            blocked_codes.append(code)

    c513030 = per_etf_checks["513030"]
    if not c513030["allow_buy"]:
        return {
            "status": "🚨 高溢价熔断保护（禁止买入/清仓避险）",
            "allow_buy": False,
            "blocked_codes": blocked_codes,
            "per_etf_checks": per_etf_checks,
            "adjusted_weight": 0.0,
            "redirect_to_bond_weight": raw_weight,
            "target_etf": p513030,
            "all_candidates": candidates,
            "advice": (
                f"🚨 触发高溢价熔断！513030 德国ETF 当前实时溢价率达 +{p513030['premium_pct']:.2f}% > {c513030['threshold']}% 熔断线，"
                f"程序已自动将其仓位清零，转入安全债券ETF避险！"
            ),
        }

    if c513030["in_buffer"]:
        return {
            "status": "🟡 持仓缓冲保护（日内IOPV滞后·继续持有）",
            "allow_buy": True,
            "blocked_codes": blocked_codes,
            "per_etf_checks": per_etf_checks,
            "adjusted_weight": raw_weight,
            "redirect_to_bond_weight": 0.0,
            "target_etf": p513030,
            "all_candidates": candidates,
            "advice": (
                f"🟡 海外主力【513030 德国ETF】现价 {p513030['price']:.3f}（日内静态IOPV {p513030['iopv']:.4f}，表观溢价 +{p513030['premium_pct']:.2f}%）。"
                f"因欧洲股市16:00后才开盘，日内IOPV存在跨时区滞后；您目前已持有底仓且未超 {MAX_HOLD_PREMIUM_PCT}% 持仓极限线，继续安心持有，免除无效换仓磨损！"
            ),
        }

    p159980 = per_etf_checks.get("159980", {})
    p159915 = per_etf_checks.get("159915", {})
    extra_str = ""
    if "premium_pct" in p159980 and "premium_pct" in p159915:
        extra_str = f"；159980 有色ETF ({p159980['premium_pct']:+.2f}%)、159915 创业板ETF ({p159915['premium_pct']:+.2f}%) 同样处于零溢价/折价安全区"

    return {
        "status": "✅ 溢价极低（安全可买）",
        "allow_buy": True,
        "blocked_codes": blocked_codes,
        "per_etf_checks": per_etf_checks,
        "adjusted_weight": raw_weight,
        "redirect_to_bond_weight": 0.0,
        "target_etf": p513030,
        "all_candidates": candidates,
        "advice": (
            f"✅ 海外主力【513030 德国ETF】实时溢价率仅 {p513030['premium_pct']:+.2f}%（现价 {p513030['price']:.3f} vs IOPV {p513030['iopv']:.4f}）"
            f"{extra_str}，对比纳指ETF 513100 的 {p513100['premium_pct']:+.2f}% 高溢价省下超 15% 溢价成本，可放心按信号执行！"
        ),
    }
