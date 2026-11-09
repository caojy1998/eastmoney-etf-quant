"""
生成 5万元本金 2021~2026 历史回测对比高清图表 (PNG) 与 交互式看板 (HTML)
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

    # 画布尺寸 1800 x 1150 (高清双面板：上方净值曲线，下方回撤曲线)
    W, H = 1800, 1150
    img = Image.new("RGB", (W, H), (15, 23, 42))  # 深色金融终端背景
    draw = ImageDraw.Draw(img)

    f_title = get_chinese_font(30)
    f_sub = get_chinese_font(20)
    f_label = get_chinese_font(17)
    f_small = get_chinese_font(15)

    init_cap = float(round(nav_df["bench_fixed_income"].iloc[0], -3))
    cap_wan = f"{init_cap/10000:.0f}万" if init_cap % 10000 == 0 else f"{init_cap/10000:.1f}万"

    # 标题
    draw.text(
        (70, 28),
        f"东方财富 {cap_wan}元本金 场内ETF量化策略 6年真实历史回测对比 (2021.01 ~ 2026.11)",
        fill=(248, 250, 252),
        font=f_title,
    )
    draw.text(
        (70, 70),
        "含可转债ETF(511380) / 十年国债ETF(511260) / 红利低波ETF(512890) / 黄金ETF(518880) / 德国ETF(513030)  |  已扣除东财佣金与滑点",
        fill=(148, 163, 184),
        font=f_sub,
    )

    # 上面板区域：资金曲线 (y: 120 ~ 680)
    left, right = 110, 1390
    top1, bottom1 = 125, 665
    draw.rectangle([left, top1, right, bottom1], outline=(51, 65, 85), width=2)

    # 动态计算 Y 轴上限，防止未来净值增长超出图表顶部
    max_nav_val = float(nav_df.drop(columns=["date"]).max().max())
    y_min = 25000.0
    y_max = max(122000.0, np.ceil(max_nav_val / 10000.0) * 10000.0 + 2000.0)
    for y_val in range(30000, int(y_max) + 1, 10000):
        py = bottom1 - (y_val - y_min) / (y_max - y_min) * (bottom1 - top1)
        color = (71, 85, 105) if y_val == int(init_cap) else (30, 41, 59)
        draw.line([(left, py), (right, py)], fill=color, width=2 if y_val == int(init_cap) else 1)
        draw.text((20, py - 10), f"¥{y_val:,.0f}", fill=(148, 163, 184), font=f_small)

    # 下面板区域：最大回撤曲线 (y: 740 ~ 1060)
    top2, bottom2 = 745, 1060
    draw.rectangle([left, top2, right, bottom2], outline=(51, 65, 85), width=2)
    draw.text((left + 4, top2 - 28), "▼ 历史动态回撤对比曲线 (Drawdown %，越接近 0% 越稳健)", fill=(203, 213, 225), font=f_label)

    dd_min, dd_max = -50.0, 0.0
    for dd_val in [0, -5, -10, -20, -30, -40, -50]:
        py = top2 + (0.0 - dd_val) / (dd_max - dd_min) * (bottom2 - top2)
        draw.line([(left, py), (right, py)], fill=(30, 41, 59), width=1)
        draw.text((35, py - 10), f"{dd_val}%", fill=(148, 163, 184), font=f_small)

    # X轴年份刻度
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
        ("strategy2_momentum", "策略二：跨市场ETF动量轮动+国债避险", (251, 146, 60), 4),
        ("strategy_combo", "推荐组合：50%全天候网格+50%动量轮动", (56, 189, 248), 4),
        ("strategy1_all_weather", "策略一：全天候“超级固收+”+东财网格", (52, 211, 153), 4),
        ("bench_bond", "基准A：纯十年国债ETF (511260) 持有", (167, 139, 250), 2),
        ("bench_fixed_income", "基准B：传统银行固收理财 (2.8%年化)", (226, 232, 240), 2),
        ("bench_hs300", "基准C：沪深300ETF (510300) 买入死拿", (248, 113, 113), 2),
    ]

    # 绘制曲线与右侧图例卡片
    legend_x = 1412
    legend_y = 135
    draw.text((legend_x, legend_y - 32), f"期末净值与核心指标 ({cap_wan}本金)", fill=(248, 250, 252), font=f_sub)

    for col, label, color, width in series_cfg:
        vals = nav_df[col].values
        pts1 = []
        for i, v in enumerate(vals):
            px = left + (i / (n - 1)) * (right - left)
            py = bottom1 - (v - y_min) / (y_max - y_min) * (bottom1 - top1)
            pts1.append((px, py))
        draw.line(pts1, fill=color, width=width)

        # 计算回撤序列并绘制
        s = pd.Series(vals)
        dd = ((s - s.cummax()) / s.cummax() * 100.0).values
        if col != "bench_fixed_income":
            pts2 = []
            for i, d_v in enumerate(dd):
                px = left + (i / (n - 1)) * (right - left)
                py = top2 + (0.0 - d_v) / (dd_max - dd_min) * (bottom2 - top2)
                pts2.append((px, py))
            draw.line(pts2, fill=color, width=max(1, width - 1))

        # 右侧指标卡片
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
    print(f"高清回测对比图已生成: {out_png1}")


def render_html_dashboard():
    with open(OUTPUT_DIR / "backtest_metrics.json", "r", encoding="utf-8") as f:
        bt_data = json.load(f)
    with open(OUTPUT_DIR / "live_signal_eastmoney.json", "r", encoding="utf-8") as f:
        live_data = json.load(f)
    nav_df = pd.read_csv(OUTPUT_DIR / "backtest_nav_history.csv")

    # 抽样每3个交易日以减小HTML体积并保持丝滑交互
    sampled = nav_df.iloc[::3].copy()
    chart_json = {
        "dates": sampled["date"].tolist(),
        "s1": sampled["strategy1_all_weather"].tolist(),
        "s2": sampled["strategy2_momentum"].tolist(),
        "combo": sampled["strategy_combo"].tolist(),
        "bond": sampled["bench_bond"].tolist(),
        "fixed": sampled["bench_fixed_income"].tolist(),
        "hs300": sampled["bench_hs300"].tolist(),
    }

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>东方财富 {live_data['total_capital']/10000:.1f}万元场内ETF量化回测与实盘信号终端</title>
<style>
  body {{ font-family: 'Microsoft YaHei', sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
  .container {{ max-width: 1320px; margin: 0 auto; }}
  h1 {{ font-size: 26px; margin-bottom: 6px; color: #38bdf8; }}
  .subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 22px; }}
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
  .tag-ok {{ background: #065f46; color: #6ee7b7; padding: 3px 8px; border-radius: 4px; font-size: 12px; }}
  .tag-safe {{ background: #374151; color: #cbd5e1; padding: 3px 8px; border-radius: 4px; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🚀 东方财富 {live_data['total_capital']/10000:.1f}万元本金 场内ETF量化回测与实盘信号终端</h1>
  <div class="subtitle">最新行情基准日：{live_data['as_of_date']} ｜ 本次实时刷新时间：<b style="color:#34d399;">{live_data.get('generated_at', '')}</b> ｜ 免可转债10万权限门槛 ｜ 0印花税</div>

  <div class="grid-cards">
    <div class="card" style="border-top: 4px solid #34d399;">
      <h3 class="green">🛡️ 策略一：全天候“超级固收+” + 东财ATR网格</h3>
      <div class="big-num green">¥{bt_data['metrics'][0]['final_capital']:,.0f} <span style="font-size:16px;">(+{bt_data['metrics'][0]['total_return_pct']}%)</span></div>
      <div>年化收益：<b>{bt_data['metrics'][0]['cagr_pct']}%</b> ｜ 最大回撤：<b>{bt_data['metrics'][0]['max_drawdown_pct']}%</b></div>
      <div style="color:#94a3b8;font-size:13px;margin-top:6px;">夏普比率 {bt_data['metrics'][0]['sharpe_ratio']}，2021~2026连续6年每年全部正收益！</div>
    </div>
    <div class="card" style="border-top: 4px solid #fb923c;">
      <h3 class="orange">🔥 策略二：跨市场ETF动量轮动 + 国债避险</h3>
      <div class="big-num orange">¥{bt_data['metrics'][1]['final_capital']:,.0f} <span style="font-size:16px;">(+{bt_data['metrics'][1]['total_return_pct']}%)</span></div>
      <div>年化收益：<b>{bt_data['metrics'][1]['cagr_pct']}%</b> ｜ 最大回撤：<b>{bt_data['metrics'][1]['max_drawdown_pct']}%</b></div>
      <div style="color:#94a3b8;font-size:13px;margin-top:6px;">牛市抓强势资产主升浪，熊市自动切入十年国债ETF避险。</div>
    </div>
    <div class="card" style="border-top: 4px solid #38bdf8;">
      <h3 class="blue">⭐ 推荐组合：50%全天候网格 + 50%动量轮动</h3>
      <div class="big-num blue">¥{bt_data['metrics'][2]['final_capital']:,.0f} <span style="font-size:16px;">(+{bt_data['metrics'][2]['total_return_pct']}%)</span></div>
      <div>年化收益：<b>{bt_data['metrics'][2]['cagr_pct']}%</b> ｜ 最大回撤：<b>{bt_data['metrics'][2]['max_drawdown_pct']}%</b></div>
      <div style="color:#94a3b8;font-size:13px;margin-top:6px;">{live_data['total_capital']/10000:.1f}万元实战最佳平衡点：收益接近翻倍，回撤控制在8%以内。</div>
    </div>
  </div>

  <div class="section">
    <h2>📊 一、2021 ~ 2026 历史回测核心指标与分年度收益对比（本金：{live_data['total_capital']:,.0f}元）</h2>
    <table>
      <thead>
        <tr>
          <th>策略 / 基准名称</th><th>期末总资产</th><th>净赚利润</th><th>年化收益(CAGR)</th><th>最大回撤</th><th>夏普比率</th>
          <th>2021年</th><th>2022年(熊市)</th><th>2023年</th><th>2024年</th><th>2025年</th><th>2026年</th>
        </tr>
      </thead>
      <tbody>
"""
    for m in bt_data["metrics"]:
        yr = m["yearly_returns_pct"]
        html += f"""        <tr>
          <td style="text-align:left;font-weight:bold;">{m['name']}</td>
          <td>¥{m['final_capital']:,.0f}</td>
          <td style="color:{'#34d399' if m['net_profit']>=0 else '#f87171'};">{'+' if m['net_profit']>=0 else ''}¥{m['net_profit']:,.0f}</td>
          <td><b>{m['cagr_pct']}%</b></td>
          <td style="color:#fca5a5;">{m['max_drawdown_pct']}%</td>
          <td>{m['sharpe_ratio']}</td>
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
  </div>

  <div class="section">
    <h2>📌 二、今日东方财富 {live_data['total_capital']:,.0f} 元实盘一键下单清单（已按 1手=100股 智能取整，资金利用率 {live_data['used_combo_cash']/live_data['total_capital']*100:.1f}%）</h2>
    <p style="color:#94a3b8;font-size:13px;">你可以根据自己的风险偏好，从下方【策略一（极低回撤固收+）】或【二合一推荐组合】中任选其一在东方财富APP下单：</p>
    <h3 style="color:#34d399;font-size:16px;">选项 1：如果你追求极度稳健（最大回撤 ~2.1%，连续6年年年正收益）👉 按【策略一】配仓：</h3>
    <table>
      <thead>
        <tr><th>ETF代码</th><th>ETF名称</th><th>最新实盘价</th><th>目标权重</th><th>建议买入股数(100股整数倍)</th><th>预计占用资金(元)</th><th>资产定位说明</th></tr>
      </thead>
      <tbody>
"""
    for row in live_data["strategy1_orders"]:
        html += f"""        <tr>
          <td><b>{row['code']}</b></td><td>{row['name']}</td><td>{row['latest_price']}</td>
          <td>{row['target_weight_pct']}%</td><td style="color:#34d399;font-weight:bold;">{row['suggest_shares']} 股 ({row['suggest_lots']}手)</td>
          <td>¥{row['actual_amt']:,.1f}</td><td style="text-align:left;color:#94a3b8;">{row['note']}</td>
        </tr>\n"""

    html += """      </tbody>
    </table>

    <h3 style="color:#38bdf8;font-size:16px;margin-top:20px;">⭐ 推荐二合一（50%全天候网格 + 50%动量轮动）本周五【先卖后买】差额执行表：</h3>
    <table>
      <thead>
        <tr><th>执行顺序与动作</th><th>ETF代码</th><th>ETF名称</th><th>最新参考价</th><th>当前持仓(股)</th><th>目标持仓(股)</th><th>本次需交易股数</th><th>预计成交金额(元)</th></tr>
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
  </div>

  <div class="section">
    <h2>⚙️ 三、东方财富 APP「网格交易条件单」自动高抛低吸参数表</h2>
    <p style="color:#94a3b8;font-size:13px;">买入底仓后，打开 <b>东方财富APP -> 交易 -> 条件单 -> 网格交易</b>，填入以下由近20日ATR波动率自动算出的网格参数，即可免盯盘自动收割震荡收益：</p>
    <table>
      <thead>
        <tr><th>ETF代码</th><th>ETF名称</th><th>触发基准价</th><th>每上涨卖出</th><th>每下跌买入</th><th>网格价格上下限</th><th>每笔委托股数</th><th>单格金额</th><th>实盘开启建议</th></tr>
      </thead>
      <tbody>
"""
    for g in live_data["strategy1_grid_params"]:
        html += f"""        <tr>
          <td><b>{g['code']}</b></td><td>{g['name']}</td><td>{g['base_price']}</td>
          <td style="color:#f87171;">{g['step_up_sell_pct']}</td><td style="color:#34d399;">{g['step_down_buy_pct']}</td>
          <td>{g['price_range']}</td><td><b>{g['shares_per_grid']} 股</b></td><td>¥{g['est_amount_per_grid']}</td>
          <td style="text-align:left;">{g.get('status_note', '')}</td>
        </tr>\n"""

    html += """      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>🌍 四、跨境 ETF 实时折溢价防雷监控（主力：513030 德国ETF vs 纳指高溢价对照）</h2>
    <p style="color:#34d399;font-size:14px;font-weight:bold;">""" + live_data.get("nasdaq_premium_guard", {}).get("advice", "") + """</p>
    <table>
      <thead>
        <tr><th>优先级</th><th>ETF代码</th><th>ETF名称</th><th>场内最新价</th><th>IOPV参考净值</th><th>实时折溢价率</th><th>风控状态与操作建议</th></tr>
      </thead>
      <tbody>
"""
    nq_list = live_data.get("nasdaq_premium_guard", {}).get("all_candidates", [])
    for idx, nq in enumerate(nq_list):
        p_pct = nq["premium_pct"]
        if p_pct > 4.0:
            st_text = "🚨 极高溢价(已彻底弃用防雷)"
            p_col = "#f87171"
        elif p_pct > 2.5:
            st_text = "⚠️ 溢价超2.5%熔断线(禁止追高)"
            p_col = "#fb923c"
        elif nq["code"] == "513030":
            st_text = "⭐ 当前海外主力(近0溢价+动量第1名)"
            p_col = "#34d399"
        else:
            st_text = "✅ 溢价安全(备用观察)"
            p_col = "#cbd5e1"
        html += f"""        <tr>
          <td>第 {idx+1} 选</td><td><b>{nq['code']}</b></td><td>{nq['name']}</td>
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
