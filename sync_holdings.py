"""
当用户在东方财富 APP 按【二合一策略】完成每周五买卖后，
运行此脚本即可将最新目标持仓与剩余可用现金写入 my_holdings.json，
并记录本周实盘净值快照，供下周五自动计算累计收益、折合年化与买卖差额。
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
LIVE_JSON = BASE_DIR / "output" / "live_signal_eastmoney.json"
HOLDINGS_JSON = BASE_DIR / "my_holdings.json"


def sync():
    if not LIVE_JSON.exists():
        print("未找到今日信号文件，请先运行【一键更新行情并生成今日东财信号.bat】！")
        return

    with open(LIVE_JSON, "r", encoding="utf-8") as f:
        live = json.load(f)

    old_data = {}
    if HOLDINGS_JSON.exists():
        try:
            with open(HOLDINGS_JSON, "r", encoding="utf-8") as hf:
                old_data = json.load(hf)
        except Exception:
            old_data = {}

    as_of_date = live.get("as_of_date", "")
    invest_start_date = old_data.get("invest_start_date") or old_data.get("last_sync_date") or as_of_date
    initial_principal = float(
        old_data.get("initial_principal", live.get("initial_principal", old_data.get("total_budget", 60000.0)))
    )
    nav_history = list(old_data.get("nav_history", []))

    new_pos = {
        "511260": 0,
        "511360": 0,
        "513030": 0,
        "512890": 0,
        "511380": 0,
        "518880": 0,
        "159915": 0,
        "159980": 0,
        "510500": 0,
    }
    post_pos = live.get("post_rebalance_positions")
    if post_pos:
        for code in set(new_pos.keys()) | set(post_pos.keys()):
            new_pos[code] = int(post_pos.get(code, 0))
    else:
        for step in live.get("combo_action_steps", []):
            new_pos[step["code"]] = int(step.get("target_shares", 0))

    auto_cash = float(live.get("est_post_trade_cash", live.get("reserve_cash", 0.0)))
    post_mkt_val = float(live.get("used_combo_cash", 0.0))

    print("=========================================================================")
    print(f"📌 系统自动推算调仓后剩余【可用现金】约为: ¥{auto_cash:,.2f} 元（已扣除预估5元/笔佣金）")
    final_cash = auto_cash
    if sys.stdin and sys.stdin.isatty():
        try:
            raw_in = input("👉 直接按【回车键】采用该金额；或输入东财APP显示的精确【可用资金】数字后回车: ").strip()
            if raw_in:
                final_cash = round(float(raw_in.replace(",", "").replace("¥", "")), 2)
        except Exception:
            final_cash = auto_cash

    total_eq = round(post_mkt_val + final_cash, 2)
    cum_prof = round(total_eq - initial_principal, 2)
    cum_ret_pct = round((total_eq / initial_principal - 1.0) * 100.0, 2) if initial_principal > 0 else 0.0

    snap = {
        "date": as_of_date,
        "market_value": round(post_mkt_val, 2),
        "cash_balance": round(final_cash, 2),
        "total_equity": total_eq,
        "cum_profit_rmb": cum_prof,
        "cum_return_pct": cum_ret_pct,
    }
    nav_history = [x for x in nav_history if x.get("date") != as_of_date]
    nav_history.append(snap)

    payload = {
        "note": "实盘账本：positions 填东财APP当前实际持股数，cash_balance 填东财APP当前【可用资金】(若有周中手动/网格成交可随时修改这两项校准)。",
        "invest_start_date": invest_start_date,
        "last_sync_date": as_of_date,
        "initial_principal": round(initial_principal, 2),
        "cash_balance": round(final_cash, 2),
        "total_budget": total_eq,
        "positions": new_pos,
        "nav_history": nav_history[-104:],
    }
    with open(HOLDINGS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("=========================================================================")
    print("✅ 东方财富实盘持仓与现金账本 (my_holdings.json) 已成功同步！")
    print(f"   当前实盘总资产: ¥{total_eq:,.2f} (持仓市值 ¥{post_mkt_val:,.2f} + 可用现金 ¥{final_cash:,.2f})")
    print(f"   累计净收益: {cum_prof:+,.2f} 元 ({cum_ret_pct:+.2f}%)")
    print("   记录持仓股数:", {k: v for k, v in new_pos.items() if v > 0})
    print("   下周五运行信号脚本时，将自动按最新总资产为您核算累计收益、折合年化与买卖差额！")
    print("=========================================================================")


if __name__ == "__main__":
    sync()
