"""
当用户在东方财富 APP 按【二合一策略】完成今日买卖后，
运行此脚本即可将最新目标持仓自动写入 my_holdings.json，供下周五自动计算买卖差额。
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

    new_pos = {"511260": 0, "513030": 0, "512890": 0, "511380": 0, "518880": 0, "510500": 0}
    post_pos = live.get("post_rebalance_positions")
    if post_pos:
        for code in new_pos:
            new_pos[code] = int(post_pos.get(code, 0))
    else:
        for step in live.get("combo_action_steps", []):
            new_pos[step["code"]] = int(step.get("target_shares", 0))

    payload = {
        "note": f"已于 {live.get('as_of_date', '')} 同步最新二合一策略持仓。如有微调也可直接用记事本修改股数。",
        "last_sync_date": live.get("as_of_date", ""),
        "total_budget": live.get("total_capital", 60000.0),
        "positions": new_pos,
    }
    with open(HOLDINGS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("=========================================================")
    print("✅ 东方财富实盘持仓记录 (my_holdings.json) 已成功同步！")
    print("当前记录的持仓股数：", new_pos)
    print("下周五运行信号脚本时，将自动按此持仓为你计算【先卖后买】差额！")
    print("=========================================================")


if __name__ == "__main__":
    sync()
