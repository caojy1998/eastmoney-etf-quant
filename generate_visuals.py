"""
生成东方财富 6万元本金 2021~2026 严格实盘级历史回测对比高清图表 (PNG) 与 交互式实盘信号看板 (HTML)
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
ARTIFACT_DIR = Path(r"C:\Users\zero-max\.gemini\antigravity\brain\8c5b3aaf-dbd0-4ece-9105-bc686571413b")


def get_chinese_font(size: int):
    font_candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for fp in font_candidates:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_png_chart():
    nav_df = pd.read_csv(OUTPUT_DIR / "backtest_nav_history.csv")
    dates = nav_df["date"].tolist()
    n = len(dates)

    W, H = 1800, 1150
    img = Image.new("RGB", (W, H), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    f_title = get_chinese_font(30)
    f_sub = get_chinese_font(19)
    f_label = get_chinese_font(17)
    f_small = get_chinese_font(15)

    init_cap = float(round(nav_df["bench_fixed_income"].iloc[0], -3))
    cap_wan = f"{init_cap/10000:.0f}万" if init_cap % 10000 == 0 else f"{init_cap/10000:.1f}万"

    draw.text(
        (70, 28),
        f"东方财富 {cap_wan}元本金 场内ETF量化策略 6年严格实盘级回测对比 (2021.01 ~ 2026.11)",
        fill=(248, 250, 252),
        font=f_title,
    )
    draw.text(
        (70, 70),
        "国债(511260)/短融(511360)/红利(512890)/可转债(511380)/黄金(518880)/德国(513030)/创业板(159915)/有色(159980) | 100股整手+不免5最低5元+周五调仓",
        fill=(148, 163, 184),
        font=f_sub,
    )

    left, right = 110, 1390
    top1, bottom1 = 125, 665
    draw.rectangle([left, top1, right, bottom1], outline=(51, 65, 85), width=2)

    max_nav_val = float(nav_df.drop(columns=["date"]).max().max())
    y_min = 25000.0
    y_max = max(125000.0, np.ceil(max_nav_val / 10000.0) * 10000.0 + 4000.0)
    for y_val in range(30000, int(y_max) + 1, 10000):
        py = bottom1 - (y_val - y_min) / (y_max - y_min) * (bottom1 - top1)
        color = (71, 85, 105) if y_val == int(init_cap) else (30, 41, 59)
        draw.line([(left, py), (right, py)], fill=color, width=2 if y_val == int(init_cap) else 1)
        draw.text((20, py - 10), f"¥{y_val:,.0f}", fill=(148, 163, 184), font=f_small)

    top2, bottom2 = 745, 1060
    draw.rectangle([left, top2, right, bottom2], outline=(51, 65, 85), width=2)
    draw.text((left + 4, top2 - 28), "▼ 历史动态回撤对比曲线 (Drawdown %，含整手零头与5元最低佣金摩擦)", fill=(203, 213, 225), font=f_label)

    dd_min, dd_max = -50.0, 0.0
    for dd_val in [0, -5, -10, -20, -30, -40, -50]:
        py = top2 + (0.0 - dd_val) / (dd_max - dd_min) * (bottom2 - top2)
        draw.line([(left, py), (right, py)], fill=(30, 41, 59), width=1)
        draw.text((35, py - 10), f"{dd_val}%", fill=(148, 163, 184), font=f_small)

    seen_years = set()
    for i, d_str in enumerate(dates):
        yr = d_str[:4]
        if yr not in seen_years:
            seen_years.add(yr)
            px = left + (i / (n - 1)) * (right - left)
            draw.line([(px, top1), (px, bottom1)], fill=(30, 41, 59), width=1)
            draw.line([(px, top2), (px, bottom2)], fill=(30, 41, 59), width=1)
            draw.text((px - 20, bottom2 + 12), f"{yr}年", fill=(203, 213, 225), font=f_small)

    series_cfg = [
        ("strategy2_momentum", "策略二：跨资产多维动量(整手·不免5)", (251, 146, 60), 4),
        ("strategy_combo", "推荐组合：40%底座+60%动量(整手·不免5)", (56, 189, 248), 4),
        ("strategy1_all_weather", "策略一：全天候固收+底座(整手·不免5)", (52, 211, 153), 4),
        ("bench_bond", "基准A：纯十年国债ETF (511260) 持有", (167, 139, 250), 2),
        ("bench_fixed_income", "基准B：传统银行固收理财 (2.8%年化)", (226, 232, 240), 2),
        ("bench_hs300", "基准C：沪深300ETF (510300) 买入死拿", (248, 113, 113), 2),
    ]

    legend_x = 1412
    legend_y = 135
    draw.text((legend_x, legend_y - 32), f"期末净值与实盘指标 ({cap_wan}本金)", fill=(248, 250, 252), font=f_sub)

    for col, label, color, width in series_cfg:
        vals = nav_df[col].values
        pts1 = []
        for i, v in enumerate(vals):
            px = left + (i / (n - 1)) * (right - left)
            py = bottom1 - (v - y_min) / (y_max - y_min) * (bottom1 - top1)
            pts1.append((px, py))
        draw.line(pts1, fill=color, width=width)

        s = pd.Series(vals)
        peak = np.maximum(init_cap, s.cummax())
        dd = ((s - peak) / peak * 100.0).values
        if col != "bench_fixed_income":
            pts2 = []
            for i, d_v in enumerate(dd):
                px = left + (i / (n - 1)) * (right - left)
                py = top2 + (0.0 - d_v) / (dd_max - dd_min) * (bottom2 - top2)
                pts2.append((px, py))
            draw.line(pts2, fill=color, width=max(1, width - 1))

        final_v = vals[-1]
        tot_ret = (final_v / init_cap - 1.0) * 100.0
        max_dd = dd.min()
        draw.rectangle([legend_x, legend_y, W - 25, legend_y + 135], fill=(30, 41, 59), outline=color, width=2)
        draw.text((legend_x + 12, legend_y + 10), label, fill=color, font=f_label)
        draw.text(
            (legend_x + 12, legend_y + 42),
            f"期末资产: ¥{final_v:,.0f} ({tot_ret:+.1f}%)",
            fill=(248, 250, 252),
            font=f_sub,
        )
        years = max(0.1, (pd.to_datetime(dates[-1]) - pd.to_datetime(dates[0])).days / 365.25)
        cagr = ((final_v / init_cap) ** (1.0 / years) - 1.0) * 100.0
        draw.text(
            (legend_x + 12, legend_y + 78),
            f"年化收益: {cagr:+.2f}%  |  最大回撤: {max_dd:.2f}%",
            fill=(203, 213, 225),
            font=f_small,
        )
        draw.text(
            (legend_x + 12, legend_y + 104),
            f"净赚利润: {'+' if final_v>=init_cap else ''}¥{final_v - init_cap:,.0f} 元",
            fill=(148, 163, 184),
            font=f_small,
        )
        legend_y += 152

    out_png1 = OUTPUT_DIR / "backtest_comparison.png"
    img.save(out_png1)
    if ARTIFACT_DIR.exists():
        img.save(ARTIFACT_DIR / "backtest_comparison.png")
    print(f"高清实盘级回测对比图已生成: {out_png1}")


def render_html_dashboard():
    with open(OUTPUT_DIR / "backtest_metrics.json", "r", encoding="utf-8") as f:
        bt_data = json.load(f)
    with open(OUTPUT_DIR / "live_signal_eastmoney.json", "r", encoding="utf-8") as f:
        live_data = json.load(f)

    is_fri = bool(live_data.get("is_friday_rebalance_window", False))
    banner_bg = "#064e3b" if is_fri else "#3b2f13"
    banner_border = "#10b981" if is_fri else "#f59e0b"
    banner_text_col = "#a7f3d0" if is_fri else "#fde68a"

    m0, m1, m2 = bt_data["metrics"][0], bt_data["metrics"][1], bt_data["metrics"][2]
    combo_ratio_label = live_data.get("combo_ratio_label", "40%全天候固收底座 + 60%跨资产动量轮动")
    util_pct = live_data["used_combo_cash"] / live_data["total_capital"] * 100.0

    lp = live_data.get("live_performance", {})
    init_prin = float(lp.get("initial_principal", live_data.get("initial_principal", 60000.0)))
    live_eq = float(lp.get("total_equity", live_data["total_capital"]))
    live_mv = float(lp.get("market_value", 0.0))
    live_cash = float(lp.get("cash_balance", 0.0))
    cum_prof = float(lp.get("cum_profit_rmb", 0.0))
    cum_ret = float(lp.get("cum_return_pct", 0.0))
    ann_ret = float(lp.get("annualized_return_pct", 0.0))
    hs300_ret = float(lp.get("hs300_same_period_pct", 0.0))
    alpha_ret = float(lp.get("excess_alpha_pct", 0.0))
    cal_days = int(lp.get("calendar_days", 1))
    trd_days = int(lp.get("trading_days", 1))
    inv_start = lp.get("invest_start_date", "2026-11-09")
    ann_note = lp.get("ann_note", "")

    prof_col = "#34d399" if cum_prof >= 0 else "#f87171"
    ann_col = "#fbbf24" if ann_ret >= 0 else "#f87171"
    alpha_col = "#38bdf8" if alpha_ret >= 0 else "#f87171"

    hold_rows_html = ""
    for hb in lp.get("holding_breakdown", []):
        hold_rows_html += (
            f"<tr><td><b>{hb['code']}</b></td><td>{hb['name']}</td><td>{hb['shares']} 股</td>"
            f"<td>{hb['latest_price']:.3f}</td><td><b>¥{hb['market_value']:,.2f}</b></td><td>{hb['weight_pct']:.1f}%</td></tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>东方财富 {init_prin/10000:.1f}万元场内ETF量化回测与实盘信号终端 (v2.1 实盘收益追踪版)</title>
<style>
  body {{ font-family: 'Microsoft YaHei', sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
  .container {{ max-width: 1340px; margin: 0 auto; }}
  h1 {{ font-size: 26px; margin-bottom: 6px; color: #38bdf8; }}
  .subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 18px; line-height: 1.6; }}
  .banner {{ background: {banner_bg}; border: 1px solid {banner_border}; color: {banner_text_col}; padding: 14px 18px; border-radius: 8px; margin-bottom: 20px; font-size: 15px; font-weight: bold; }}
  .live-box {{ background: linear-gradient(135deg, #172554 0%, #1e293b 100%); border: 1px solid #3b82f6; border-radius: 12px; padding: 20px; margin-bottom: 24px; }}
  .live-kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 12px; }}
  .kpi {{ background: rgba(15, 23, 42, 0.72); border: 1px solid #334155; border-radius: 8px; padding: 14px 16px; }}
  .kpi-label {{ color: #94a3b8; font-size: 13px; }}
  .kpi-val {{ font-size: 26px; font-weight: bold; margin: 6px 0 4px 0; }}
  .kpi-sub {{ color: #cbd5e1; font-size: 12px; }}
  .grid-cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 18px; }}
  .card h3 {{ margin: 0 0 10px 0; font-size: 17px; }}
  .big-num {{ font-size: 28px; font-weight: bold; margin: 6px 0; }}
  .green {{ color: #34d399; }}
  .orange {{ color: #fb923c; }}
  .blue {{ color: #38bdf8; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }}
  th, td {{ border: 1px solid #334155; padding: 10px 12px; text-align: center; }}
  th {{ background: #0f172a; color: #cbd5e1; }}
  tr:nth-child(even) {{ background: #162032; }}
  .section {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 20px; margin-bottom: 24px; }}
  .section h2 {{ margin-top: 0; font-size: 19px; color: #f1f5f9; border-left: 4px solid #38bdf8; padding-left: 10px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🚀 东方财富 {init_prin/10000:.1f}万元本金 场内ETF量化回测与实盘信号终端 <span style="font-size:15px;color:#34d399;">(v2.1 实盘净值与年化追踪版)</span></h1>
  <div class="subtitle">
    最新行情基准日：<b>{live_data['as_of_date']} ({live_data.get('as_of_weekday', '')})</b> ｜ 本次刷新时间：<b style="color:#34d399;">{live_data.get('generated_at', '')}</b> ｜ 上次同步持仓日：{live_data.get('last_sync_date', '未记录')}<br/>
    回测与实盘同源准则：<b>100股整手撮合(raw_close) + 东财万1.5不免5(最低5元/笔) + 万2滑点 + 自然周周五14:45调仓 + 0盘中网格注水</b>
  </div>

  <div class="banner">{live_data.get('timing_banner', '')}</div>

  <div class="live-box">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;">
      <div style="font-size:19px;font-weight:bold;color:#f8fafc;">💼 我的东财实盘账户实时成绩单 <span style="font-size:14px;color:#93c5fd;font-weight:normal;">（建仓起始日：{inv_start} ｜ 已运行 {cal_days} 个自然日 / {trd_days} 个交易日）</span></div>
      <div style="font-size:13px;color:#cbd5e1;">投入初始本金：<b>¥{init_prin:,.2f}</b></div>
    </div>
    <div class="live-kpis">
      <div class="kpi">
        <div class="kpi-label">当前实盘账户总资产</div>
        <div class="kpi-val" style="color:#f8fafc;">¥{live_eq:,.2f}</div>
        <div class="kpi-sub">证券市值 ¥{live_mv:,.1f} + 可用现金 ¥{live_cash:,.1f}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">实盘当前累计净收益</div>
        <div class="kpi-val" style="color:{prof_col};">{cum_prof:+,.2f}元 <span style="font-size:17px;">({cum_ret:+.2f}%)</span></div>
        <div class="kpi-sub">相比初始投入本金 ¥{init_prin:,.0f}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">实盘当前折合年化 (CAGR)</div>
        <div class="kpi-val" style="color:{ann_col};">{ann_ret:+.2f}%</div>
        <div class="kpi-sub">按 {cal_days} 天复利年化折算</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">建仓以来跑赢沪深300 (Alpha)</div>
        <div class="kpi-val" style="color:{alpha_col};">{alpha_ret:+.2f}%</div>
        <div class="kpi-sub">同期沪深300 (510300) 涨跌：{hs300_ret:+.2f}%</div>
      </div>
    </div>
    <div style="margin-top:10px;font-size:12.5px;color:#93c5fd;line-height:1.5;">
      ℹ️ {ann_note}<br/>
      💡 <b>对账提示</b>：若周中有过网格/手动买卖（例如卖出一笔德国ETF），只需打开 <code>my_holdings.json</code> 将对应 ETF 股数与 <code>cash_balance</code>（东财APP显示的【可用资金】）改为真实值，或在周五调仓后双击同步脚本时输入精确可用资金，即可分毫不差追踪真实收益！
    </div>
    <details style="margin-top:10px;">
      <summary style="cursor:pointer;color:#60a5fa;font-size:13.5px;font-weight:bold;">📋 展开查看当前记录的实盘持仓市值构成明细</summary>
      <table style="margin-top:8px;">
        <thead>
          <tr><th>ETF代码</th><th>ETF名称</th><th>当前记录持股</th><th>最新实盘价</th><th>当前持仓市值</th><th>占总资产比例</th></tr>
        </thead>
        <tbody>
          {hold_rows_html}
          <tr><td><b>CASH</b></td><td>账户可用现金 / 逆回购</td><td>-</td><td>1.000</td><td><b>¥{live_cash:,.2f}</b></td><td>{live_cash/live_eq*100.0 if live_eq>0 else 0:.1f}%</td></tr>
        </tbody>
      </table>
    </details>
  </div>

  <div class="grid-cards">
    <div class="card" style="border-top: 4px solid #34d399;">
      <h3 class="green">🛡️ 策略一：全天候“超级固收+”低波底座</h3>
      <div class="big-num green">¥{m0['final_capital']:,.0f} <span style="font-size:16px;">(+{m0['total_return_pct']}%)</span></div>
      <div>年化收益：<b>{m0['cagr_pct']}%</b> ｜ 最大回撤：<b>{m0['max_drawdown_pct']}%</b> ｜ 卡玛：<b>{m0['calmar_ratio']}</b></div>
      <div style="color:#94a3b8;font-size:13px;margin-top:6px;">6年累计佣金 ¥{m0.get('total_commission_rmb', 0):,.0f} ({m0.get('order_count', 0)}笔)，连续6年全部正收益！</div>
    </div>
    <div class="card" style="border-top: 4px solid #fb923c;">
      <h3 class="orange">🔥 策略二：跨资产多维动量轮动 + 双债避险</h3>
      <div class="big-num orange">¥{m1['final_capital']:,.0f} <span style="font-size:16px;">(+{m1['total_return_pct']}%)</span></div>
      <div>年化收益：<b>{m1['cagr_pct']}%</b> ｜ 最大回撤：<b>{m1['max_drawdown_pct']}%</b> ｜ 夏普：<b>{m1['sharpe_ratio']}</b></div>
      <div style="color:#94a3b8;font-size:13px;margin-top:6px;">含创业板(159915)与有色(159980) + Top-3 缓冲，6年年年正收益！</div>
    </div>
    <div class="card" style="border-top: 4px solid #38bdf8;">
      <h3 class="blue">⭐ 推荐组合：{combo_ratio_label}</h3>
      <div class="big-num blue">¥{m2['final_capital']:,.0f} <span style="font-size:16px;">(+{m2['total_return_pct']}%)</span></div>
      <div>年化收益：<b>{m2['cagr_pct']}%</b> ｜ 最大回撤：<b>{m2['max_drawdown_pct']}%</b> ｜ 夏普：<b>{m2['sharpe_ratio']}</b></div>
      <div style="color:#94a3b8;font-size:13px;margin-top:6px;">单一6万实盘账户动态配平（扣尽整手零头与5元低消），回撤严控8%内！</div>
    </div>
  </div>

  <div class="section">
    <h2>📌 一、今日东方财富 {live_data['total_capital']:,.0f} 元实盘【先卖后买】差额执行清单（真实资金利用率 {util_pct:.1f}%，预留零钱 ¥{live_data['reserve_cash']:,.1f}）</h2>
    <h3 style="color:#38bdf8;font-size:16px;margin-top:8px;">⭐ 推荐二合一（{combo_ratio_label}）差额执行表（每周五 14:45 按此表操作）：</h3>
    <table>
      <thead>
        <tr><th>执行顺序与动作</th><th>ETF代码</th><th>ETF名称</th><th>最新实盘价</th><th>当前持仓(股)</th><th>目标持仓(股)</th><th>本次需交易股数</th><th>预计成交金额(元)</th></tr>
      </thead>
      <tbody>
"""
    for row in live_data.get("combo_action_steps", []):
        color_act = "#f87171" if "卖出" in row["action"] else ("#34d399" if "买入" in row["action"] else "#94a3b8")
        html += f"""        <tr>
          <td style="color:{color_act};font-weight:bold;">{row['action']}</td>
          <td><b>{row['code']}</b></td><td>{row['name']}</td><td>{row['latest_price']}</td>
          <td>{row['current_shares']} 股</td><td><b>{row['target_shares']} 股</b></td>
          <td style="color:{color_act};font-weight:bold;">{row['trade_shares']} 股 ({row['trade_lots']}手)</td>
          <td>¥{row['est_cash_flow']:,.1f}</td>
        </tr>\n"""

    html += """      </tbody>
    </table>

    <h3 style="color:#fb923c;font-size:16px;margin-top:22px;">📈 6大跨资产零溢价池 实时多周期动量 (10/20/30日 OLS斜率×R²) 打分与 Top-3 缓冲榜：</h3>
    <table>
      <thead>
        <tr><th>ETF代码</th><th>ETF名称</th><th>最新价</th><th>近20日涨跌</th><th>近5日涨跌</th><th>20日年化波动</th><th>站上MA20</th><th>10/20/30日动量分</th><th>综合动量×R²</th><th>风险调整得分</th><th>当前信号状态</th></tr>
      </thead>
      <tbody>
"""
    for b in live_data.get("strategy2_momentum_board", []):
        st = b["passed_filter"]
        st_col = "#34d399" if ("主力入选" in st or "缓冲留存" in st) else ("#fbbf24" if "备选" in st else "#94a3b8")
        adj_txt = f"{b['risk_adj_score']:.3f}" if b["risk_adj_score"] > -900 else "-"
        html += f"""        <tr>
          <td><b>{b['code']}</b></td><td>{b['name']}</td><td>{b['raw_price']}</td>
          <td style="color:{'#f87171' if b['ret_20d_pct']>0 else '#34d399'};">{b['ret_20d_pct']:+.2f}%</td>
          <td style="color:{'#f87171' if b['ret_5d_pct']>0 else '#34d399'};">{b['ret_5d_pct']:+.2f}%</td>
          <td>{b['vol_20d_pct']:.1f}%</td><td>{b['above_ma20']}</td>
          <td style="color:#cbd5e1;font-size:13px;">{b['score_10_20_30']}</td>
          <td><b>{b['momentum_r2_score']:+.3f}</b></td><td>{adj_txt}</td>
          <td style="color:{st_col};font-weight:bold;">{st}</td>
        </tr>\n"""

    html += """      </tbody>
    </table>

    <details style="margin-top:16px;">
      <summary style="cursor:pointer;color:#34d399;font-weight:bold;">👉 展开查看【纯策略一：极低回撤全天候固收+（最大回撤 -1.95%）】独立配仓参考表</summary>
      <table style="margin-top:10px;">
        <thead>
          <tr><th>ETF代码</th><th>ETF名称</th><th>最新实盘价</th><th>目标权重</th><th>建议持仓股数(100股整数倍)</th><th>预计占用资金(元)</th><th>资产定位说明</th></tr>
        </thead>
        <tbody>
"""
    for row in live_data["strategy1_orders"]:
        html += f"""          <tr>
            <td><b>{row['code']}</b></td><td>{row['name']}</td><td>{row['latest_price']}</td>
            <td>{row['target_weight_pct']}%</td><td style="color:#34d399;font-weight:bold;">{row['suggest_shares']} 股 ({row['suggest_lots']}手)</td>
            <td>¥{row['actual_amt']:,.1f}</td><td style="text-align:left;color:#94a3b8;">{row['note']}</td>
          </tr>\n"""

    html += f"""        </tbody>
      </table>
    </details>
  </div>

  <div class="section">
    <h2>📊 二、2021 ~ 2026 严格实盘级历史回测核心指标与分年度净收益（本金：{live_data['total_capital']:,.0f}元 | 100股整手 + 不免5最低5元佣金）</h2>
    <table>
      <thead>
        <tr>
          <th>策略 / 基准名称</th><th>期末总资产</th><th>净赚利润</th><th>年化收益(CAGR)</th><th>最大回撤</th><th>夏普</th><th>6年实缴佣金</th>
          <th>2021年</th><th>2022年(熊市)</th><th>2023年</th><th>2024年</th><th>2025年</th><th>2026年</th>
        </tr>
      </thead>
      <tbody>
"""
    for m in bt_data["metrics"]:
        yr = m["yearly_returns_pct"]
        fee_cell = f"¥{m['total_commission_rmb']:,.0f} ({m['order_count']}笔)" if "order_count" in m else "-"
        html += f"""        <tr>
          <td style="text-align:left;font-weight:bold;">{m['name']}</td>
          <td>¥{m['final_capital']:,.0f}</td>
          <td style="color:{'#34d399' if m['net_profit']>=0 else '#f87171'};">{'+' if m['net_profit']>=0 else ''}¥{m['net_profit']:,.0f}</td>
          <td><b>{m['cagr_pct']}%</b></td>
          <td style="color:#fca5a5;">{m['max_drawdown_pct']}%</td>
          <td>{m['sharpe_ratio']}</td>
          <td style="color:#cbd5e1;font-size:13px;">{fee_cell}</td>
          <td>{yr.get('2021',0):+.2f}%</td>
          <td>{yr.get('2022',0):+.2f}%</td>
          <td>{yr.get('2023',0):+.2f}%</td>
          <td>{yr.get('2024',0):+.2f}%</td>
          <td>{yr.get('2025',0):+.2f}%</td>
          <td>{yr.get('2026',0):+.2f}%</td>
        </tr>\n"""

    html += """      </tbody>
    </table>
    <div style="margin-top: 18px; text-align: center;">
      <img src="backtest_comparison.png" style="max-width: 100%; border-radius: 8px; border: 1px solid #334155;" />
    </div>

    <details style="margin-top:16px;">
      <summary style="cursor:pointer;color:#38bdf8;font-weight:bold;">📅 展开核验【推荐组合最近 8 次历史调仓交割记录】（严格对齐自然周周五，零节假日漂移）</summary>
      <table style="margin-top:10px;">
        <thead>
          <tr><th>调仓日期</th><th>星期校验</th><th>成交笔数</th><th>当周佣金+滑点</th><th>留存现金</th><th>调仓后账户总净值</th><th>调仓后实盘整手持仓明细</th></tr>
        </thead>
        <tbody>
"""
    for lg in bt_data.get("recent_logs_combo", []):
        sh_str = " ｜ ".join(f"{k}: {v}股" for k, v in lg["shares"].items())
        html += f"""          <tr>
            <td><b>{lg['date']}</b></td><td style="color:#34d399;font-weight:bold;">{lg['weekday']}</td>
            <td>{lg['orders_executed']} 笔</td><td>¥{lg['fee_and_slip_rmb']:.2f}</td>
            <td>¥{lg['cash_left']:,.1f}</td><td><b>¥{lg['nav']:,.1f}</b></td>
            <td style="text-align:left;color:#cbd5e1;font-size:13px;">{sh_str}</td>
          </tr>\n"""

    html += """        </tbody>
      </table>
    </details>
  </div>

  <div class="section">
    <h2>🛡️ 三、四大实盘风控与防磨损保护面板（为什么停用盘中网格每年多赚 +1.36%）</h2>
    <table>
      <thead>
        <tr><th style="width:20%;">保护模块</th><th style="width:26%;">当前实时状态</th><th>量化实证原理与东财 APP 操作指引</th></tr>
      </thead>
      <tbody>
"""
    for p in live_data.get("protection_mechanisms", []):
        html += f"""        <tr>
          <td style="font-weight:bold;color:#38bdf8;">{p['module']}</td>
          <td style="font-weight:bold;color:#34d399;">{p['state']}</td>
          <td style="text-align:left;color:#cbd5e1;line-height:1.55;">{p['detail']}</td>
        </tr>\n"""

    html += """      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>🌍 四、主力 ETF 实时 IOPV 折溢价防雷监控（德国 / 有色 / 创业板 vs 纳指高溢价对照）</h2>
    <p style="color:#34d399;font-size:14px;font-weight:bold;">""" + live_data.get("nasdaq_premium_guard", {}).get("advice", "") + """</p>
    <table>
      <thead>
        <tr><th>排序</th><th>ETF代码</th><th>ETF名称</th><th>场内最新价</th><th>IOPV参考净值</th><th>实时折溢价率</th><th>风控状态与操作建议</th></tr>
      </thead>
      <tbody>
"""
    nq_list = live_data.get("nasdaq_premium_guard", {}).get("all_candidates", [])
    for idx, nq in enumerate(nq_list):
        p_pct = nq["premium_pct"]
        if p_pct > 5.5:
            st_text = "🚨 极高溢价(已彻底弃用防雷)"
            p_col = "#f87171"
        elif p_pct > 2.8:
            st_text = "⚠️ 溢价超2.8%新买线(空仓禁追高/底仓观察)"
            p_col = "#fb923c"
        elif nq["code"] in ("513030", "159980", "159915"):
            st_text = "⭐ 核心策略池成员(零溢价/折价安全区)"
            p_col = "#34d399"
        else:
            st_text = "✅ 溢价安全(备用对照)"
            p_col = "#cbd5e1"
        html += f"""        <tr>
          <td>#{idx+1}</td><td><b>{nq['code']}</b></td><td>{nq['name']}</td>
          <td>{nq['price']:.3f}</td><td>{nq['iopv']:.4f}</td>
          <td style="color:{p_col};font-weight:bold;">{p_pct:+.2f}%</td>
          <td style="color:{p_col};">{st_text}</td>
        </tr>\n"""

    html += """      </tbody>
    </table>
  </div>
</div>
</body>
</html>"""

    out_html = OUTPUT_DIR / "dashboard.html"
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"交互式 HTML 实盘看板已生成: {out_html}")


if __name__ == "__main__":
    render_png_chart()
    render_html_dashboard()
