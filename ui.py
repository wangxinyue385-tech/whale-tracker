from __future__ import annotations

import json

from flask import jsonify, render_template_string, request

from signal_logger import fill_prices, get_recent, get_stats, get_trade_closes, get_trade_events, log_signal


HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Binance Flow Radar</title>
  <style>
    :root {
      --bg:#eef2f6; --surface:#fff; --surface2:#f8fafc; --line:#d8e0ea;
      --text:#162033; --muted:#68758a; --ink:#0f172a;
      --green:#087f5b; --green-bg:#e9f8f1; --red:#c92a2a; --red-bg:#fff0f0;
      --amber:#a16207; --amber-bg:#fff8df;
    }
    * { box-sizing:border-box; }
    body { margin:0; color:var(--text); background:var(--bg); font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; letter-spacing:0; }
    button,input,select { font:inherit; }
    .topbar { height:58px; padding:0 22px; background:rgba(255,255,255,.96); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:10; }
    .brand { display:flex; align-items:center; gap:10px; font-weight:850; }
    .brand-mark { width:30px; height:30px; border-radius:8px; background:var(--ink); color:#fff; display:grid; place-items:center; font-size:13px; font-weight:900; }
    .statusbar { display:flex; align-items:center; gap:8px; color:var(--muted); font-size:12px; }
    .dot { width:8px; height:8px; border-radius:50%; background:#a8b2c1; }
    .dot.ok { background:var(--green); box-shadow:0 0 0 3px rgba(8,127,91,.12); }
    .dot.bad { background:var(--red); box-shadow:0 0 0 3px rgba(201,42,42,.12); }
    .page { max-width:1840px; margin:0 auto; padding:12px 20px 22px; }
    .controls { display:grid; grid-template-columns:1fr auto auto; gap:10px; align-items:center; margin-bottom:12px; }
    .search { width:100%; border:1px solid var(--line); background:var(--surface); border-radius:8px; padding:10px 12px; color:var(--text); outline:none; }
    .segmented { display:flex; background:var(--surface); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .segmented button { border:0; border-right:1px solid var(--line); background:transparent; color:var(--muted); padding:9px 12px; cursor:pointer; min-width:68px; }
    .segmented button:last-child { border-right:0; }
    .segmented button.active { color:#fff; background:var(--ink); }
    .refresh,.ai-btn { border:1px solid var(--ink); background:var(--ink); color:#fff; border-radius:8px; padding:9px 13px; cursor:pointer; white-space:nowrap; }
    .ai-btn:disabled { opacity:.55; cursor:wait; }
    .stats { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; margin-bottom:10px; }
    .stat { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:9px 11px; min-height:62px; }
    .label { color:var(--muted); font-size:12px; font-weight:750; margin-bottom:8px; }
    .value { color:var(--ink); font-size:19px; font-weight:900; white-space:nowrap; }
    .sub { color:var(--muted); font-size:12px; margin-top:4px; }
    .up { color:var(--green); font-weight:850; }
    .down { color:var(--red); font-weight:850; }
    .layout { display:grid; grid-template-columns:minmax(700px,1fr) 640px; gap:12px; align-items:start; }
    .main-stack { display:grid; gap:10px; min-width:0; }
    .side-stack { display:grid; gap:10px; position:sticky; top:70px; max-height:calc(100vh - 82px); overflow:auto; padding-bottom:2px; }
    .trade-grid { display:grid; gap:10px; align-items:start; }
    .panel,.ai-panel { background:var(--surface); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .ai-panel { margin-top:0; }
    .panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 14px; border-bottom:1px solid var(--line); background:var(--surface2); }
    .panel-title { font-weight:850; }
    .panel-note { color:var(--muted); font-size:12px; }
    .ai-body { padding:12px 14px; font-size:13px; line-height:1.65; white-space:pre-wrap; min-height:92px; }
    .side-stack .ai-body { min-height:64px; max-height:116px; overflow:auto; }
    .table-wrap { overflow-x:auto; }
    .table-wrap.compact { overflow-x:hidden; }
    table { width:100%; border-collapse:collapse; font-size:12.5px; }
    .compact table { table-layout:fixed; font-size:12px; }
    .compact th,.compact td { padding:8px 8px; white-space:normal; }
    .compact th:nth-child(1){width:11%}
    .compact th:nth-child(2){width:10%}
    .compact th:nth-child(3){width:7%}
    .compact th:nth-child(4){width:14%}
    .compact th:nth-child(5){width:8%}
    .compact th:nth-child(6){width:10%}
    .compact th:nth-child(7){width:11%}
    .compact th:nth-child(8){width:10%}
    .compact th:nth-child(9){width:12%}
    .compact th:nth-child(10){width:7%}
    .compact .num { white-space:nowrap; }
    .compact .score { width:48px; height:27px; }
    th { color:var(--muted); text-align:left; font-weight:750; padding:9px 10px; border-bottom:1px solid var(--line); background:#fbfcfe; white-space:nowrap; }
    td { padding:10px; border-bottom:1px solid #edf1f5; vertical-align:middle; white-space:nowrap; }
    tbody tr:hover { background:#f9fbfd; }
    .symbol { font-weight:900; color:var(--ink); font-size:13px; }
    .small { color:var(--muted); font-size:11px; }
    .num { font-variant-numeric:tabular-nums; }
    .badge { display:inline-flex; align-items:center; justify-content:center; min-width:86px; border-radius:6px; padding:4px 8px; font-weight:850; font-size:11px; }
    .badge.long { background:var(--green-bg); color:var(--green); }
    .badge.short { background:var(--red-bg); color:var(--red); }
    .badge.watch { background:var(--amber-bg); color:var(--amber); }
    .score { width:52px; height:28px; border-radius:6px; display:inline-grid; place-items:center; color:#fff; background:var(--ink); font-weight:900; }
    .reason { display:flex; gap:5px; flex-wrap:wrap; min-width:230px; white-space:normal; }
    .chip { border:1px solid var(--line); background:var(--surface2); color:var(--text); border-radius:6px; padding:3px 6px; font-size:11px; }
    .detail-btn { border:1px solid var(--line); background:var(--surface2); color:var(--ink); border-radius:6px; padding:5px 7px; cursor:pointer; font-size:12px; white-space:nowrap; }
    .detail-row td { background:#fbfcfe; white-space:normal; padding:0; }
    .detail-box { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; padding:12px 14px; border-bottom:1px solid #edf1f5; }
    .detail-item { min-width:0; }
    .detail-label { color:var(--muted); font-size:11px; margin-bottom:4px; font-weight:750; }
    .detail-value { color:var(--ink); font-size:12px; line-height:1.45; overflow-wrap:anywhere; }
    .event-list { max-height:300px; overflow:auto; }
    .event { display:grid; grid-template-columns:58px 1fr; gap:8px; padding:10px 12px; border-bottom:1px solid #edf1f5; }
    .event-side { font-size:11px; font-weight:900; }
    .event-side.buy { color:var(--green); }
    .event-side.sell { color:var(--red); }
    .event-title { display:flex; justify-content:space-between; gap:8px; font-size:12px; font-weight:850; }
    .event-meta { color:var(--muted); font-size:11px; margin-top:3px; }
    .warn { margin-top:12px; border:1px solid #efd897; background:var(--amber-bg); color:#744b00; border-radius:8px; padding:10px 12px; font-size:12px; line-height:1.55; }
    .signal-stats { margin-top:10px; background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:12px 14px; font-size:13px; line-height:1.7; color:var(--text); }
    .signal-stats strong { color:var(--ink); }
    .win { color:var(--green); font-weight:850; }
    .lose { color:var(--red); font-weight:850; }
    .trade-form { display:grid; grid-template-columns:1fr 1fr; gap:7px; padding:10px 12px; }
    .trade-form label { color:var(--muted); font-size:11px; font-weight:750; display:grid; gap:5px; }
    .trade-form input,.trade-form select { width:100%; border:1px solid var(--line); background:var(--surface); border-radius:6px; padding:7px 8px; color:var(--text); min-width:0; }
    .trade-form .wide { grid-column:1/-1; }
    .trade-actions { display:flex; align-items:center; gap:8px; padding:0 12px 10px; flex-wrap:wrap; }
    .toggle { display:inline-flex; align-items:center; gap:7px; color:var(--text); font-size:12px; font-weight:800; }
    .toggle input { width:16px; height:16px; }
    .trade-status { padding:0 12px 10px; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; }
    .mini-stat { border:1px solid var(--line); background:var(--surface2); border-radius:6px; padding:7px; min-height:50px; }
    .mini-stat .label { margin-bottom:4px; font-size:11px; }
    .mini-stat .value { font-size:16px; }
    .trade-log { border-top:1px solid var(--line); height:360px; overflow:auto; padding:0; color:var(--muted); font-size:12px; line-height:1.45; background:#fff; }
    .trade-log-row { display:grid; grid-template-columns:68px 54px minmax(0,1fr) 72px; gap:8px; padding:8px 12px; border-bottom:1px solid #edf1f5; align-items:start; }
    .trade-log-row.open { background:#f8fafc; }
    .trade-log-row.close.win { background:#f5fbf7; }
    .trade-log-row.close.loss { background:#fff7f7; }
    .trade-log-time { color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; }
    .trade-log-type { color:var(--ink); font-weight:900; }
    .trade-log-main { color:var(--text); min-width:0; overflow-wrap:anywhere; }
    .trade-log-meta { color:var(--muted); font-size:11px; margin-top:3px; overflow-wrap:anywhere; }
    .trade-log-pnl { text-align:right; font-weight:900; font-variant-numeric:tabular-nums; white-space:nowrap; }
    .chart-wrap { padding:10px 12px 12px; height:220px; }
    #pnlChart,#tradeStatsChart { width:100%; height:160px; display:block; border:1px solid var(--line); border-radius:8px; background:#fff; }
    .chart-meta { display:flex; justify-content:space-between; gap:10px; color:var(--muted); font-size:12px; margin-top:8px; }
    .stats-strip { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:7px; padding:10px 12px 0; }
    .stats-strip .mini-stat { min-height:58px; }
    .trade-strategy-stats { padding:8px 12px 0; color:var(--muted); font-size:12px; line-height:1.6; }
    .trade-strategy-stats strong { color:var(--ink); }
    .full-trade-panel { margin-top:12px; }
    .trade-breakdown { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; padding:10px 12px; border-bottom:1px solid var(--line); background:#fff; }
    .trade-breakdown-card { border:1px solid var(--line); border-radius:6px; background:var(--surface2); padding:8px; min-height:58px; }
    .trade-breakdown-title { color:var(--muted); font-size:11px; font-weight:800; margin-bottom:5px; }
    .trade-breakdown-main { color:var(--ink); font-size:14px; font-weight:900; }
    .trade-breakdown-sub { color:var(--muted); font-size:11px; margin-top:3px; }
    .full-trade-table-wrap { max-height:760px; overflow:auto; background:#fff; }
    .trade-detail-table { table-layout:fixed; min-width:1180px; }
    .trade-detail-table th,.trade-detail-table td { padding:8px 9px; white-space:normal; }
    .trade-detail-table th:nth-child(1){width:56px}
    .trade-detail-table th:nth-child(2){width:92px}
    .trade-detail-table th:nth-child(3){width:100px}
    .trade-detail-table th:nth-child(4){width:116px}
    .trade-detail-table th:nth-child(5){width:72px}
    .trade-detail-table th:nth-child(6){width:96px}
    .trade-detail-table th:nth-child(7){width:86px}
    .trade-detail-table th:nth-child(8){width:86px}
    .trade-detail-table th:nth-child(9){width:340px}
    .trade-detail-row.win { background:#f5fbf7; }
    .trade-detail-row.loss { background:#fff7f7; }
    .api-help { grid-column:1/-1; color:var(--muted); font-size:11px; line-height:1.45; margin-top:-2px; }
    .decision-summary { display:grid; grid-template-columns:1.1fr repeat(3,minmax(0,.7fr)); gap:10px; padding:12px 14px; border-bottom:1px solid var(--line); background:#fbfcfe; }
    .decision-box { border:1px solid var(--line); background:#fff; border-radius:8px; padding:10px; min-height:70px; }
    .decision-box.primary { background:#f8fafc; }
    .decision-label { color:var(--muted); font-size:11px; font-weight:800; margin-bottom:6px; }
    .decision-main { color:var(--ink); font-size:20px; font-weight:900; line-height:1.2; }
    .decision-sub { color:var(--muted); font-size:12px; margin-top:5px; line-height:1.45; }
    .strategy-board { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; padding:12px 14px 14px; }
    .strategy-card { border:1px solid var(--line); background:#fff; border-radius:8px; padding:12px; min-width:0; }
    .strategy-card.follow-long { border-color:#a8dec9; background:#f4fbf7; }
    .strategy-card.follow-short { border-color:#f1b4b4; background:#fff7f7; }
    .strategy-head { display:flex; align-items:start; justify-content:space-between; gap:10px; margin-bottom:10px; }
    .strategy-symbol { font-size:20px; font-weight:950; color:var(--ink); line-height:1; }
    .strategy-action { font-weight:900; font-size:13px; border-radius:6px; padding:5px 8px; white-space:nowrap; }
    .strategy-action.long { color:var(--green); background:var(--green-bg); }
    .strategy-action.short { color:var(--red); background:var(--red-bg); }
    .strategy-action.wait { color:var(--amber); background:var(--amber-bg); }
    .strategy-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:7px; margin-bottom:10px; }
    .metric { background:var(--surface2); border:1px solid var(--line); border-radius:6px; padding:7px; min-width:0; }
    .metric .label { margin-bottom:4px; font-size:10px; }
    .metric .value { font-size:14px; }
    .strategy-note { color:var(--text); font-size:12px; line-height:1.5; display:grid; gap:7px; }
    .strategy-note .reason { min-width:0; }
    .empty-board { padding:26px 14px; color:var(--muted); line-height:1.7; }
    @media (max-width:1200px) { .layout{grid-template-columns:1fr;} .side-stack{position:static; max-height:none; overflow:visible;} .detail-box{grid-template-columns:repeat(2,minmax(0,1fr));} }
    @media (max-width:900px) { .strategy-board,.decision-summary{grid-template-columns:1fr;} }
    @media (max-width:720px) { .stats{grid-template-columns:repeat(2,minmax(0,1fr));} .controls{grid-template-columns:1fr;} .segmented{overflow-x:auto;} .statusbar{display:none;} .trade-form,.trade-status,.detail-box,.strategy-metrics{grid-template-columns:1fr 1fr;} th.optional,td.optional{display:none;} }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand"><div class="brand-mark">FR</div><div>Binance Flow Radar</div></div>
    <div class="statusbar">
      <span class="dot" id="priceDot"></span><span>价格流</span>
      <span class="dot" id="tradeDot"></span><span>大单流</span>
      <span class="dot" id="liqDot"></span><span>爆仓流</span>
      <span id="connText">连接中</span>
    </div>
  </div>
  <main class="page">
    <div class="controls">
      <input class="search" id="search" placeholder="搜索交易对，例如 SOL、1000PEPE、WIF">
      <div class="segmented" id="filters">
        <button class="active" data-filter="all">全部</button>
        <button data-filter="follow">策略信号</button>
        <button data-filter="long">多头资金</button>
        <button data-filter="short">空头资金</button>
        <button data-filter="alts">山寨</button>
      </div>
      <button class="refresh" id="refresh">重连</button>
    </div>
    <section class="stats">
      <div class="stat"><div class="label">扫描交易对</div><div class="value" id="statSymbols">--</div><div class="sub" id="scopeSub">自动扩展范围</div></div>
      <div class="stat"><div class="label">策略多头候选</div><div class="value up" id="statLong">--</div><div class="sub">多因子确认</div></div>
      <div class="stat"><div class="label">策略空头候选</div><div class="value down" id="statShort">--</div><div class="sub">多因子确认</div></div>
      <div class="stat"><div class="label">成本门槛</div><div class="value" id="statCost">--</div><div class="sub">费率+滑点+安全垫</div></div>
      <div class="stat"><div class="label">5 分钟爆仓</div><div class="value" id="statLiq">--</div><div class="sub">强平订单流</div></div>
    </section>
    <section class="layout">
      <div class="main-stack">
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">模拟盘策略测试台</div>
              <div class="panel-note" id="radarNote">后台监控资金流，只展示可测试的买卖策略和等待原因</div>
            </div>
            <div class="panel-note" id="errorNote"></div>
          </div>
          <div class="decision-summary" id="decisionSummary">
            <div class="decision-box primary"><div class="decision-label">当前动作</div><div class="decision-main">等待数据</div><div class="decision-sub">后台正在监控资金流。</div></div>
            <div class="decision-box"><div class="decision-label">候选</div><div class="decision-main">--</div><div class="decision-sub">可测试策略数</div></div>
            <div class="decision-box"><div class="decision-label">市场状态</div><div class="decision-main">--</div><div class="decision-sub">BTC/ETH 方向</div></div>
            <div class="decision-box"><div class="decision-label">模拟盘</div><div class="decision-main">--</div><div class="decision-sub">自动下单状态</div></div>
          </div>
          <div class="strategy-board" id="strategyBoard">
            <div class="empty-board">正在连接行情。策略触发后会在这里显示做多/做空测试方案。</div>
          </div>
        </div>
        <div class="signal-stats" id="statsPanel">信号统计加载中...</div>
        <div class="warn">
          这个工具用于发现大资金流动和缩小观察范围，不构成投资建议。“策略信号”只有在预测空间大于手续费、滑点、资金费风险和安全垫时才会出现；它仍然只是盯盘候选，不代表可以无脑追单。
        </div>
      </div>
      <aside class="side-stack">
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">模拟盘自动下单</div>
              <div class="panel-note" id="tradeConnNote">正在连接模拟盘...</div>
            </div>
            <button class="ai-btn" id="saveTradeCfg">保存连接</button>
          </div>
          <div class="trade-form">
            <label class="wide">执行模式<select id="executionMode"><option value="paper">本地模拟盘（不用 API）</option><option value="binance_testnet">Binance Futures Testnet</option></select></label>
            <label class="wide">模拟盘 API Key<input id="testnetKey" autocomplete="off" type="password" placeholder="第一次必填；保存后不会显示"></label>
            <label class="wide">模拟盘 Secret<input id="testnetSecret" autocomplete="off" type="password" placeholder="第一次必填；以后不改可留空"></label>
            <div class="api-help" id="apiHelp">本地模拟盘不需要 API Key。切到 Binance Futures Testnet 时，第一次连接必须同时填 API Key 和 Secret，不要填实盘 Key。</div>
            <label>每仓保证金 USDT<input id="orderUsdt" type="number" min="1" step="1" value="10"></label>
            <label>杠杆<input id="tradeLeverage" type="number" min="1" max="20" step="1" value="4"></label>
            <label>最多持仓<input id="maxPositions" type="number" min="1" max="20" step="1" value="15"></label>
            <label>平仓分钟<input id="autoCloseMinutes" type="number" min="1" step="1" value="5"></label>
            <label class="wide">当前策略<input id="strategyModeLabel" type="text" value="当前策略：4h突破趋势" readonly><input id="strategyMode" type="hidden" value="current"></label>
          </div>
          <div class="trade-actions">
            <label class="toggle"><input id="autoTradeToggle" type="checkbox">FOLLOW 自动下单</label>
            <span class="panel-note" id="tradeModeNote">本地模拟盘 / Testnet</span>
          </div>
          <div class="trade-status">
            <div class="mini-stat"><div class="label">权益</div><div class="value" id="tradeEquity">--</div></div>
            <div class="mini-stat"><div class="label">盈亏</div><div class="value" id="tradePnl">--</div></div>
            <div class="mini-stat"><div class="label">持仓</div><div class="value" id="tradePositions">--</div></div>
          </div>
          <div class="trade-log" id="tradeLog"><div>正在连接模拟盘...</div></div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">收益曲线</div>
              <div class="panel-note">模拟盘账户权益</div>
            </div>
          </div>
          <div class="chart-wrap">
            <canvas id="pnlChart"></canvas>
            <div class="chart-meta"><span id="chartLeft">等待数据</span><span id="chartRight">--</span></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">后台监控</div>
              <div class="panel-note">连接和最近事件摘要</div>
            </div>
          </div>
          <div class="event-list" id="eventList"></div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">交易统计</div>
              <div class="panel-note">次数、净盈利、盈亏比</div>
            </div>
          </div>
          <div class="stats-strip">
            <div class="mini-stat"><div class="label">交易</div><div class="value" id="statTrades">0</div></div>
            <div class="mini-stat"><div class="label">净利</div><div class="value" id="statNet">--</div></div>
            <div class="mini-stat"><div class="label">胜率</div><div class="value" id="statWinRate">--</div></div>
            <div class="mini-stat"><div class="label">盈亏比</div><div class="value" id="statPF">--</div></div>
          </div>
          <div class="trade-strategy-stats" id="tradeStrategyStats"></div>
          <div class="chart-wrap">
            <canvas id="tradeStatsChart"></canvas>
            <div class="chart-meta"><span id="tradeStatsLeft">等待交易</span><span id="tradeStatsRight">--</span></div>
          </div>
        </div>
      </aside>
    </section>
    <section class="panel full-trade-panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">全部交易明细</div>
          <div class="panel-note" id="fullTradeNote">最近 200 笔平仓，每一笔都显示</div>
        </div>
      </div>
      <div class="trade-breakdown" id="tradeBreakdown"></div>
      <div class="full-trade-table-wrap">
        <table class="trade-detail-table">
          <thead><tr><th>#</th><th>时间</th><th>币种</th><th>信号</th><th>等级</th><th>保证金</th><th>手续费</th><th>净利</th><th>平仓原因</th></tr></thead>
          <tbody id="fullTradeBody"><tr><td colspan="9">等待交易明细。</td></tr></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const runtime.SEED_SYMBOLS = __SEED_SYMBOLS__;
    const runtime.MAX_STREAM_SYMBOLS = __MAX_STREAM_SYMBOLS__;
    const runtime.TRADE_STREAM_CHUNK_SIZE = __TRADE_STREAM_CHUNK_SIZE__;
    const runtime.LARGE_TRADE_USD = __LARGE_TRADE_USD__;
    const runtime.MIN_DYNAMIC_TRADE_USD = __MIN_DYNAMIC_TRADE_USD__;
    const runtime.TAKER_FEE_BPS = __TAKER_FEE_BPS__;
    const runtime.SLIPPAGE_BPS = __SLIPPAGE_BPS__;
    const runtime.SAFETY_EDGE_BPS = __SAFETY_EDGE_BPS__;
    const runtime.HOLD_MINUTES = __HOLD_MINUTES__;
    const runtime.BINANCE_WS_BASES = __BINANCE_WS_BASES__;
    const runtime.BINANCE_REST_BASES = __BINANCE_REST_BASES__;
    const STABLE_SYMBOLS = new Set(["USDCUSDT","BUSDUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT"]);
    const NON_CRYPTO_BASES = new Set(["AVGO","RKLB","SKHYNIX","DRAM","NOK","INTC","MSTR","CRCL","SOXL","SPCX","XAG","LAB","GUA","BEAT"]);
    const MAJORS = new Set(["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]);
    const ALPHA = {
      minScore:50, minProb:52, minEdgePct:0.01,
      minTotal5x:1.5, minDirectionGap:3,
      majorMaxP1:0.45, altMaxP1:0.70, majorMaxP5:1.20, altMaxP5:1.80,
    };
    const MICRO = {
      enableMomentum:true,
      invertFollow:false,
      enableExhaustionReversal:true,
      minLiqX:1.2,
      strongLiqX:3.0,
      washoutP5:0.25,
      reversalP1:0.005,
      minAbsorbX:0.35,
      leadMovePct:0.55,
      lagMaxMovePct:0.85,
    };
    const FUNDING = {
      enabled:true,
      extremePct:0.03, normalPct:0.035,
      minVolume24hUsd:20000000,
      maxAgainstP1:0.32, coolP1:0.08,
      minP5Stretch:0.10,
    };
    const SECTOR_GROUPS = {
      meme:["DOGEUSDT","1000PEPEUSDT","1000SHIBUSDT","1000BONKUSDT","WIFUSDT","FLOKIUSDT","MEMEUSDT","TURBOUSDT","PNUTUSDT"],
      ai:["FETUSDT","AGIXUSDT","OCEANUSDT","WLDUSDT","ARKMUSDT","AIUSDT","TAOUSDT","RENDERUSDT","NFPUSDT","PHBUSDT"],
      l1:["SOLUSDT","SUIUSDT","APTUSDT","SEIUSDT","AVAXUSDT","NEARUSDT","INJUSDT","TONUSDT"],
      l2:["OPUSDT","ARBUSDT","STRKUSDT","MANTAUSDT","METISUSDT","ZKUSDT"],
      defi:["UNIUSDT","AAVEUSDT","SUSHIUSDT","CRVUSDT","COMPUSDT","MKRUSDT","LDOUSDT","PENDLEUSDT"],
      gaming:["GALAUSDT","SANDUSDT","MANAUSDT","AXSUSDT","GMTUSDT","MAGICUSDT","PIXELUSDT"],
      payment:["XRPUSDT","XLMUSDT","HBARUSDT","ADAUSDT","TRXUSDT","ALGOUSDT"],
    };

    const state = {
      activeSymbols:[...SEED_SYMBOLS], marketMeta:new Map(), derivatives:new Map(), candles:new Map(),
      prices:new Map(), priceHistory:new Map(), trades:new Map(), liquidations:new Map(), events:[],
      sockets:[], runId:0, activeFilter:"all",
      expanded:new Set(), testnet:null,
      tradeFormDirty:false, savingTradeConfig:false,
      priceConnected:false, tradeConnected:false, liqConnected:false,
      priceError:"", tradeError:"", liqError:"", restError:"",
      priceMessages:0, tradeMessages:0, liqMessages:0, derivativesUpdatedAt:0,
      marketTimer:null, derivativesTimer:null, klineTimer:null,
    };

    function showClientError(message){
      const note=document.getElementById("errorNote");
      const conn=document.getElementById("connText");
      if(note)note.textContent=message;
      if(conn)conn.textContent="页面脚本错误";
    }
    window.addEventListener("error", event=>showClientError("页面脚本错误："+event.message));
    window.addEventListener("unhandledrejection", event=>showClientError("页面异步错误："+(event.reason&&event.reason.message?event.reason.message:event.reason)));

    function activeSymbols(){ return state.activeSymbols.length ? state.activeSymbols : runtime.SEED_SYMBOLS; }
    function activeSet(){ return new Set(activeSymbols()); }
    function base(symbol){ return symbol.replace("USDT",""); }
    function isCryptoTradableSymbol(symbol){
      const b=base(symbol);
      if(NON_CRYPTO_BASES.has(b))return false;
      if(/^(XAG|XAU|SPX|SPY|QQQ|DOW|NVDA|TSLA|AAPL|MSFT|META|GOOG|AMZN)/.test(b))return false;
      return true;
    }
    function now(){ return Date.now(); }
    function ensureList(map, key){ if(!map.has(key)) map.set(key, []); return map.get(key); }
    function cutoff(rows, ms){ const cut = now() - ms; return rows.filter(row => row.ts >= cut); }
    function money(value){ value=Number(value||0); if(Math.abs(value)>=1e9)return "$"+(value/1e9).toFixed(2)+"B"; if(Math.abs(value)>=1e6)return "$"+(value/1e6).toFixed(2)+"M"; if(Math.abs(value)>=1e3)return "$"+(value/1e3).toFixed(0)+"K"; return "$"+value.toFixed(0); }
    function price(value){ value=Number(value||0); if(!value)return "--"; if(value>=100)return "$"+value.toLocaleString(undefined,{maximumFractionDigits:2}); if(value>=1)return "$"+value.toLocaleString(undefined,{maximumFractionDigits:4}); return "$"+value.toLocaleString(undefined,{maximumFractionDigits:8}); }
    function signedPct(value){ value=Number(value||0); const cls=value>=0?"up":"down"; const sign=value>0?"+":""; return `<span class="${cls}">${sign}${value.toFixed(2)}%</span>`; }
    function isNum(value){ return typeof value==="number" && Number.isFinite(value); }
    function pctOrDash(value){ return isNum(value) ? signedPct(value) : '<span class="small">--</span>'; }
    function ratioOrDash(value){ return isNum(value) ? value.toFixed(2) : '<span class="small">--</span>'; }
    function clamp(value,min,max){ return Math.max(min,Math.min(max,value)); }
    function signedPlain(value,digits=2){ value=Number(value||0); return (value>0?"+":"")+value.toFixed(digits)+"%"; }
    function baseCostPct(){ return (runtime.TAKER_FEE_BPS*2 + runtime.SLIPPAGE_BPS*2 + runtime.SAFETY_EDGE_BPS) / 100; }
    function fundingCostPct(d, side){
      if(!isNum(d.fundingRate)||side==="NEUTRAL")return 0;
      const next=Number(d.nextFundingTime||0);
      const crossesFunding=next>now() && next-now()<=runtime.HOLD_MINUTES*60*1000;
      if(!crossesFunding)return 0;
      if(side==="LONG")return Math.max(0,d.fundingRate);
      if(side==="SHORT")return Math.max(0,-d.fundingRate);
      return 0;
    }
    function costModel(d, side){
      const feePct=runtime.TAKER_FEE_BPS*2/100, slippagePct=runtime.SLIPPAGE_BPS*2/100, safetyPct=runtime.SAFETY_EDGE_BPS/100, fundingPct=fundingCostPct(d,side);
      return {feePct,slippagePct,safetyPct,fundingPct,requiredPct:feePct+slippagePct+safetyPct+fundingPct};
    }
    function tradeThreshold(symbol){ const meta=state.marketMeta.get(symbol)||{}; const vol=Number(meta.quoteVolume||0); if(!vol)return runtime.LARGE_TRADE_USD; return Math.max(runtime.MIN_DYNAMIC_TRADE_USD, Math.min(runtime.LARGE_TRADE_USD, vol * 0.00008)); }
    function rememberPrice(symbol, value, ts){ state.prices.set(symbol, value); const rows=ensureList(state.priceHistory, symbol); rows.push({ts, value}); while(rows.length>600 || (rows.length && rows[0].ts<now()-6*60*1000)) rows.shift(); }
    function price5m(symbol){ const rows=state.priceHistory.get(symbol)||[]; if(rows.length<2)return 0; const recent=rows[rows.length-1].value; const old=(rows.find(row=>row.ts>=now()-5*60*1000)||rows[0]).value; return old ? (recent-old)/old*100 : 0; }
    function priceRet(symbol, ms){ const rows=state.priceHistory.get(symbol)||[]; if(rows.length<2)return 0; const recent=rows[rows.length-1].value; const old=(rows.find(row=>row.ts>=now()-ms)||rows[0]).value; return old ? (recent-old)/old*100 : 0; }
    function candleMetrics(symbol){
      const rows=state.candles.get(symbol)||[];
      if(rows.length<8)return {volSpike:null,rangePct:null,atrPct:null,breakout:0,position:null,ret15:null};
      const last=rows[rows.length-1], prev=rows.slice(Math.max(0,rows.length-21),rows.length-1);
      const avgVol=prev.reduce((sum,row)=>sum+Number(row.quoteVolume||0),0)/Math.max(1,prev.length);
      const high=Math.max(...prev.map(row=>row.high)), low=Math.min(...prev.map(row=>row.low));
      const span=Math.max(high-low, last.close*0.0001);
      const position=(last.close-low)/span;
      const rangePct=prev.reduce((sum,row)=>sum+(row.high-row.low)/Math.max(row.close,1)*100,0)/Math.max(1,prev.length);
      const atrPct=prev.reduce((sum,row,idx)=>{
        const prevClose=idx>0 ? prev[idx-1].close : row.open;
        const tr=Math.max(row.high-row.low,Math.abs(row.high-prevClose),Math.abs(row.low-prevClose));
        return sum + tr/Math.max(row.close,1)*100;
      },0)/Math.max(1,prev.length);
      const first=rows[Math.max(0,rows.length-16)];
      const bbRows=rows.slice(Math.max(0,rows.length-21),rows.length-1).map(row=>row.close);
      const bbMean=bbRows.reduce((sum,value)=>sum+value,0)/Math.max(1,bbRows.length);
      const bbStd=Math.sqrt(bbRows.reduce((sum,value)=>sum+(value-bbMean)*(value-bbMean),0)/Math.max(1,bbRows.length))||last.close*0.001;
      const bbZ=(last.close-bbMean)/bbStd;
      let gains=0, losses=0;
      const rsiRows=rows.slice(Math.max(0,rows.length-15));
      for(let i=1;i<rsiRows.length;i++){
        const diff=rsiRows[i].close-rsiRows[i-1].close;
        if(diff>0)gains+=diff; else losses-=diff;
      }
      const rsi14=losses<=0?100:(100-100/(1+gains/Math.max(losses,1e-12)));
      const lastRange=Math.max(last.high-last.low,last.close*0.0001);
      const closeLocation=(last.close-last.low)/lastRange;
      const bodyPct=last.open?(last.close-last.open)/last.open*100:0;
      const upperWickPct=(last.high-Math.max(last.open,last.close))/Math.max(last.close,1)*100;
	      const lowerWickPct=(Math.min(last.open,last.close)-last.low)/Math.max(last.close,1)*100;
	      const sweepHigh=last.high>high&&last.close<high;
	      const sweepLow=last.low<low&&last.close>low;
      const ema=(values,period)=>{
        if(!values.length)return null;
        const k=2/(period+1);
        let value=values[0];
        for(let i=1;i<values.length;i++) value=values[i]*k+value*(1-k);
        return value;
      };
      const closes=rows.map(row=>row.close).filter(value=>value>0);
      const ema9=ema(closes.slice(-24),9);
      const ema21=ema(closes.slice(-30),21);
      const ema9Prev=ema(closes.slice(-25,-1),9);
      const ema24=ema(closes.slice(-80),24);
      const ema48=ema(closes.slice(-120),48);
      const ema96=ema(closes.slice(-160),96);
      const vwapRows=rows.slice(Math.max(0,rows.length-21));
      const vwapDen=vwapRows.reduce((sum,row)=>sum+Number(row.quoteVolume||0),0);
      const vwap=vwapDen ? vwapRows.reduce((sum,row)=>sum+((row.high+row.low+row.close)/3)*Number(row.quoteVolume||0),0)/vwapDen : null;
      const emaGapPct=ema9&&ema21 ? (ema9-ema21)/last.close*100 : null;
      const emaTrendGapPct=ema48&&ema96 ? (ema48-ema96)/last.close*100 : null;
      const emaSlopePct=ema9&&ema9Prev ? (ema9-ema9Prev)/ema9Prev*100 : null;
      const vwapDistPct=vwap ? (last.close-vwap)/vwap*100 : null;
      const channel55Rows=rows.slice(Math.max(0,rows.length-56),rows.length-1);
      const channel20Rows=rows.slice(Math.max(0,rows.length-21),rows.length-1);
      const high55=channel55Rows.length>=20?Math.max(...channel55Rows.map(row=>row.high)):null;
      const low20=channel20Rows.length>=10?Math.min(...channel20Rows.map(row=>row.low)):null;
      const ret24h=rows.length>=7&&rows[rows.length-7].close ? (last.close-rows[rows.length-7].close)/rows[rows.length-7].close*100 : null;
      const ret72h=rows.length>=19&&rows[rows.length-19].close ? (last.close-rows[rows.length-19].close)/rows[rows.length-19].close*100 : null;
	      return {
	        volSpike: avgVol ? Number(last.quoteVolume||0)/avgVol : null,
	        lastClose: last.close,
	        rangePct,
	        atrPct,
	        breakout: last.close>high ? 1 : (last.close<low ? -1 : 0),
	        prevHigh: high,
	        prevLow: low,
	        sweepHigh,
	        sweepLow,
	        sweepHighPct: high ? (last.high-high)/high*100 : 0,
	        sweepLowPct: low ? (low-last.low)/low*100 : 0,
	        reclaimHighPct: high ? (high-last.close)/high*100 : 0,
	        reclaimLowPct: low ? (last.close-low)/low*100 : 0,
	        position,
        closeLocation,
        bodyPct,
        upperWickPct,
        lowerWickPct,
        bbZ,
        rsi14,
        ema9,
        ema21,
        ema24,
        ema48,
        ema96,
        emaGapPct,
        emaTrendGapPct,
        emaSlopePct,
        vwap,
        vwapDistPct,
        high55,
        low20,
        ret24h,
        ret72h,
        ret15: first&&first.open ? (last.close-first.open)/first.open*100 : null,
      };
    }
    function marketBias(){
      const btc=priceRet("BTCUSDT",5*60*1000), eth=priceRet("ETHUSDT",5*60*1000);
      let bias=0;
      if(btc>0.18)bias++; if(btc<-0.18)bias--;
      if(eth>0.22)bias++; if(eth<-0.22)bias--;
      return {bias, btc, eth};
    }
    function dynamicTargets(cm,cost){
      const atr=isNum(cm.atrPct)?cm.atrPct:(isNum(cm.rangePct)?cm.rangePct:0.35);
      const minTarget=Math.max(cost.requiredPct+0.10,0.35);
      const takeProfit=clamp(atr*1.25,minTarget,1.60);
      const trailArm=clamp(atr*0.80,0.45,1.05);
      return {takeProfit, trailArm};
    }
    function sectorFor(symbol){
      for(const [name,members] of Object.entries(SECTOR_GROUPS)){
        if(members.includes(symbol))return {name,members};
      }
      return null;
    }
    function applyFollowInversion(follow,label,strategyLabel,forecast,strategy){
      if(!MICRO.invertFollow||strategy!=="flow_momentum"||follow!=="FOLLOW_LONG"&&follow!=="FOLLOW_SHORT")return {follow,label,strategyLabel,forecast};
      const nextFollow=follow==="FOLLOW_LONG"?"FOLLOW_SHORT":"FOLLOW_LONG";
      const nextForecast={...forecast};
      nextForecast.side=nextFollow==="FOLLOW_LONG"?"LONG":"SHORT";
      nextForecast.expected5Pct=Math.abs(Number(nextForecast.expected5Pct||0))*(nextFollow==="FOLLOW_LONG"?1:-1);
      return {
        follow:nextFollow,
        label:nextFollow==="FOLLOW_LONG"?"反向做多":"反向做空",
        strategyLabel:(strategyLabel||"策略")+"反向",
        forecast:nextForecast,
      };
    }
    function liquidMarketOk(symbol,d,threshold){
      const m=meta(symbol);
      const quoteVolume=Number(m.quoteVolume||0);
      if(!isCryptoTradableSymbol(symbol))return false;
      if(!MAJORS.has(symbol)&&quoteVolume<35000000)return false;
      if(isNum(d.bookSpreadPct)&&d.bookSpreadPct>(MAJORS.has(symbol)?0.06:0.16))return false;
      const minDepth=Math.max(threshold*3, MAJORS.has(symbol)?45000:18000);
      if(isNum(d.bidDepthUsd)&&d.bidDepthUsd<minDepth)return false;
      if(isNum(d.askDepthUsd)&&d.askDepthUsd<minDepth)return false;
      return true;
    }
    function liquiditySweepReclaimSetup(symbol,p1,p3,p5,f60,f5,l5,cm,d,mb,threshold){
      if(!liquidMarketOk(symbol,d,threshold))return null;
      const closeLocation=isNum(cm.closeLocation)?cm.closeLocation:0.5;
      const hasOiDrop=(isNum(d.oi5Pct)&&d.oi5Pct<=-0.20)||(isNum(d.oi15Pct)&&d.oi15Pct<=-0.70);
      const volumeSpike=isNum(cm.volSpike)?cm.volSpike:1;
      const rsi=isNum(cm.rsi14)?cm.rsi14:50;
      const z=isNum(cm.bbZ)?cm.bbZ:0;
      const coreExtremeLong=(rsi<=32||z<=-1.85||p5<=-0.65);
      const coreExtremeShort=(rsi>=68||z>=1.85||p5>=0.65);
      const probeExtremeLong=(rsi<=38||z<=-1.20||p5<=-0.38);
      const probeExtremeShort=(rsi>=62||z>=1.20||p5>=0.38);
      const coreLongSweep=cm.sweepLow&&cm.sweepLowPct>=0.10&&cm.reclaimLowPct>=0.02&&p1>=-0.08;
      const coreShortSweep=cm.sweepHigh&&cm.sweepHighPct>=0.10&&cm.reclaimHighPct>=0.02&&p1<=0.08;
      const probeLongSweep=cm.sweepLow&&cm.sweepLowPct>=0.055&&cm.reclaimLowPct>=0&&p1>=-0.14;
      const probeShortSweep=cm.sweepHigh&&cm.sweepHighPct>=0.055&&cm.reclaimHighPct>=0&&p1<=0.14;
      const coreLongFlow=f60.net>=threshold*0.85&&f60.buyCount>=2&&f60.lastSide==="BUY"&&f5.total>=threshold*3.2&&f60.imbalance>=0.25;
      const coreShortFlow=f60.net<=-threshold*0.85&&f60.sellCount>=2&&f60.lastSide==="SELL"&&f5.total>=threshold*3.2&&f60.imbalance<=-0.25;
      const probeLongFlow=f60.net>=threshold*0.42&&f60.buyCount>=1&&f60.lastSide==="BUY"&&f5.total>=threshold*1.8&&f60.imbalance>=0.10;
      const probeShortFlow=f60.net<=-threshold*0.42&&f60.sellCount>=1&&f60.lastSide==="SELL"&&f5.total>=threshold*1.8&&f60.imbalance<=-0.10;
      const coreLongTrap=l5.longLiq>=threshold*1.5||cm.lowerWickPct>=0.12||hasOiDrop;
      const coreShortTrap=l5.shortLiq>=threshold*1.5||cm.upperWickPct>=0.12||hasOiDrop;
      const probeLongTrap=l5.longLiq>=threshold*0.65||cm.lowerWickPct>=0.06||hasOiDrop||z<=-1.50;
      const probeShortTrap=l5.shortLiq>=threshold*0.65||cm.upperWickPct>=0.06||hasOiDrop||z>=1.50;
      const volOk=volumeSpike>=0.65||f5.total>=threshold*2.8;
      const longCore=coreLongSweep&&coreExtremeLong&&coreLongFlow&&coreLongTrap&&volOk&&closeLocation>=0.58&&mb.bias>=0;
      const shortCore=coreShortSweep&&coreExtremeShort&&coreShortFlow&&coreShortTrap&&volOk&&closeLocation<=0.42&&mb.bias<=0;
      const longProbe=probeLongSweep&&probeExtremeLong&&probeLongFlow&&probeLongTrap&&volOk&&closeLocation>=0.52&&mb.bias>=-1;
      const shortProbe=probeShortSweep&&probeExtremeShort&&probeShortFlow&&probeShortTrap&&volOk&&closeLocation<=0.48&&mb.bias<=1;
      if(longCore||longProbe){
        const tier=longCore?"core":"probe";
        const strength=Math.min(14,cm.sweepLowPct*12)+Math.min(10,Math.abs(f60.net)/Math.max(threshold,1)*1.4)+Math.min(8,l5.longLiq/Math.max(threshold,1))+Math.max(0,(35-rsi)*0.35);
        return {
          follow:"FOLLOW_LONG", side:"LONG", label:tier==="core"?"极端扫低反转":"测试扫低反转",
          strategy:"liquidity_sweep_reclaim", strategyLabel:"极端扫单反转",
          score:Math.min(98,Math.round((tier==="core"?78:70)+strength)),
          reason:`${tier==="core"?"极端":"测试"}扫破前低 ${cm.sweepLowPct.toFixed(2)}% 后收回，RSI ${rsi.toFixed(0)}，主动买确认`,
          sweepSide:"LOW", reclaimLevel:cm.prevLow, sweepDepthPct:cm.sweepLowPct, testTier:tier,
        };
      }
      if(shortCore||shortProbe){
        const tier=shortCore?"core":"probe";
        const strength=Math.min(14,cm.sweepHighPct*12)+Math.min(10,Math.abs(f60.net)/Math.max(threshold,1)*1.4)+Math.min(8,l5.shortLiq/Math.max(threshold,1))+Math.max(0,(rsi-65)*0.35);
        return {
          follow:"FOLLOW_SHORT", side:"SHORT", label:tier==="core"?"极端扫高反转":"测试扫高反转",
          strategy:"liquidity_sweep_reclaim", strategyLabel:"极端扫单反转",
          score:Math.min(98,Math.round((tier==="core"?78:70)+strength)),
          reason:`${tier==="core"?"极端":"测试"}扫破前高 ${cm.sweepHighPct.toFixed(2)}% 后收回，RSI ${rsi.toFixed(0)}，主动卖确认`,
          sweepSide:"HIGH", reclaimLevel:cm.prevHigh, sweepDepthPct:cm.sweepHighPct, testTier:tier,
        };
      }
      return null;
    }
    function flowExhaustionSetup(symbol,p1,p5,f60,f5,cm,d,mb,threshold){
      if(!MICRO.enableExhaustionReversal)return null;
      const closeLocation=isNum(cm.closeLocation)?cm.closeLocation:0.5;
      const upperWick=isNum(cm.upperWickPct)?cm.upperWickPct:0;
      const lowerWick=isNum(cm.lowerWickPct)?cm.lowerWickPct:0;
      const taker=isNum(d.takerRatio)?d.takerRatio:1;
      const funding=isNum(d.fundingRate)?d.fundingRate:0;
      const oi5=isNum(d.oi5Pct)?d.oi5Pct:null;
      const enoughFlow=f5.total>=threshold*4.5&&f60.largest>=threshold*1.2;
      const longCrowded=taker>=1.10||funding>=0.04||(oi5!==null&&oi5>=0.15);
      const shortCrowded=taker<=0.92||funding<=-0.04||(oi5!==null&&oi5>=0.15);
      const sellTurn=f60.net<=-threshold*0.75||(f60.lastSide==="SELL"&&f60.streak>=3);
      const buyTurn=f60.net>=threshold*0.75||(f60.lastSide==="BUY"&&f60.streak>=3);
      const longExhausted=p5>=0.58&&(p1<=0.03||closeLocation<=0.45||upperWick>=0.12);
      const shortExhausted=p5<=-0.58&&(p1>=-0.03||closeLocation>=0.55||lowerWick>=0.12);
      if(enoughFlow&&longExhausted&&sellTurn&&longCrowded&&mb.bias<=1){
        const score=Math.min(94,Math.round(72+Math.min(14,Math.abs(p5)*8)+Math.min(8,Math.abs(f60.net)/Math.max(threshold,1))));
        return {follow:"FOLLOW_SHORT", side:"SHORT", label:"耗尽空", strategy:"flow_exhaustion_reversal", strategyLabel:"大单耗尽反向", score, reason:`拉升 ${p5.toFixed(2)}% 后主动卖压回`};
      }
      if(enoughFlow&&shortExhausted&&buyTurn&&shortCrowded&&mb.bias>=-1){
        const score=Math.min(94,Math.round(72+Math.min(14,Math.abs(p5)*8)+Math.min(8,Math.abs(f60.net)/Math.max(threshold,1))));
        return {follow:"FOLLOW_LONG", side:"LONG", label:"耗尽多", strategy:"flow_exhaustion_reversal", strategyLabel:"大单耗尽反向", score, reason:`下跌 ${p5.toFixed(2)}% 后主动买收回`};
      }
      return null;
    }
    function liquidationReversalSetup(symbol,p1,p5,f60,l5,cm,d,mb,threshold){
      const closeLocation=isNum(cm.closeLocation)?cm.closeLocation:0.5;
      const oiDrop=(isNum(d.oi5Pct)&&d.oi5Pct<=-0.45)||(isNum(d.oi15Pct)&&d.oi15Pct<=-1.2);
      const longWashout=l5.longLiq>=threshold*MICRO.minLiqX&&p5<=-MICRO.washoutP5;
      const longReclaimed=p1>=MICRO.reversalP1&&closeLocation>=0.58;
      const longAbsorbed=f60.net>=threshold*MICRO.minAbsorbX&&f60.buyCount>=2;
      if(longWashout&&longReclaimed&&longAbsorbed&&(oiDrop||l5.longLiq>=threshold*MICRO.strongLiqX)&&mb.bias>=0){
        const strength=Math.min(18,l5.longLiq/Math.max(threshold,1)*1.8)+Math.max(0,(closeLocation-0.45)*24);
        return {follow:"FOLLOW_LONG", side:"LONG", label:"爆仓反弹", strategy:"liquidation_reversal", strategyLabel:"爆仓反弹", score:Math.min(96,Math.round(76+strength)), reason:`多头爆仓 ${money(l5.longLiq)} 后 1m 收回`};
      }
      const shortWashout=l5.shortLiq>=threshold*MICRO.minLiqX&&p5>=MICRO.washoutP5;
      const shortRejected=p1<=-MICRO.reversalP1&&closeLocation<=0.42;
      const shortAbsorbed=f60.net<=-threshold*MICRO.minAbsorbX&&f60.sellCount>=2;
      if(shortWashout&&shortRejected&&shortAbsorbed&&(oiDrop||l5.shortLiq>=threshold*MICRO.strongLiqX)&&mb.bias<=0){
        const strength=Math.min(18,l5.shortLiq/Math.max(threshold,1)*1.8)+Math.max(0,(0.55-closeLocation)*24);
        return {follow:"FOLLOW_SHORT", side:"SHORT", label:"爆仓回落", strategy:"liquidation_reversal", strategyLabel:"爆仓反弹", score:Math.min(96,Math.round(76+strength)), reason:`空头爆仓 ${money(l5.shortLiq)} 后 1m 压回`};
      }
      return null;
    }
    function sectorLeadLagSetup(symbol,p1,p5,f60,f5,cm,mb,threshold){
      const sector=sectorFor(symbol);
      if(!sector)return null;
      const peers=sector.members.filter(sym=>sym!==symbol&&activeSet().has(sym)&&state.prices.has(sym));
      if(!peers.length)return null;
      let leader=null, leaderP5=0;
      for(const peer of peers){
        const ret=price5m(peer);
        if(Math.abs(ret)>Math.abs(leaderP5)){ leader=peer; leaderP5=ret; }
      }
      if(!leader)return null;
      const closeLocation=isNum(cm.closeLocation)?cm.closeLocation:0.5;
      const leaderUp=leaderP5>=MICRO.leadMovePct;
      const leaderDown=leaderP5<=-MICRO.leadMovePct;
      const notAlreadyMovedWithLeader=Math.abs(p5)<=MICRO.lagMaxMovePct&&Math.abs(p1)<=0.18;
      const contraShortFlow=f60.net<0&&f5.net<0&&f60.sellCount>=2&&f60.largest>=threshold&&f5.total>=threshold*3.5;
      const contraLongFlow=f60.net>0&&f5.net>0&&f60.buyCount>=2&&f60.largest>=threshold&&f5.total>=threshold*3.5;
      if(leaderUp&&notAlreadyMovedWithLeader&&contraShortFlow&&closeLocation<=0.48&&mb.bias<=1){
        return {follow:"FOLLOW_SHORT", side:"SHORT", label:"板块跷跷板空", strategy:"sector_lead_lag", strategyLabel:"板块跷跷板", score:86, reason:`${base(leader)} 5m +${leaderP5.toFixed(2)}%，${sector.name} 跷跷板回落`};
      }
      if(leaderDown&&notAlreadyMovedWithLeader&&contraLongFlow&&closeLocation>=0.52&&mb.bias>=-1){
        return {follow:"FOLLOW_LONG", side:"LONG", label:"板块跷跷板多", strategy:"sector_lead_lag", strategyLabel:"板块跷跷板", score:86, reason:`${base(leader)} 5m ${leaderP5.toFixed(2)}%，${sector.name} 跷跷板反弹`};
      }
      return null;
    }
    function fundingReversionSetup(symbol,p1,p5,f60,cm,d,mb,signal,score,threshold){
      if(!FUNDING.enabled)return null;
      if(!isNum(d.fundingRate)||Math.abs(d.fundingRate)<FUNDING.extremePct)return null;
      const quoteVolume=Number((meta(symbol)||{}).quoteVolume||0);
      if(!MAJORS.has(symbol)&&quoteVolume<FUNDING.minVolume24hUsd)return null;
      const rate=d.fundingRate, absRate=Math.abs(rate);
      const closeLocation=isNum(cm.closeLocation)?cm.closeLocation:0.5;
      const taker=isNum(d.takerRatio)?d.takerRatio:1;
      const oiOk=!isNum(d.oi15Pct)||d.oi15Pct>-4.0;
      if(!oiOk)return null;
      if(rate>0){
        const crowded=p5>=FUNDING.minP5Stretch&&(closeLocation>=0.62||taker>=1.10);
        const cooling=p1<=FUNDING.coolP1&&(f60.net<0||closeLocation<=0.55);
        const fightingPump=p1>FUNDING.maxAgainstP1||(signal==="LONG"&&score>=85&&f60.net>threshold);
        const marketOk=MAJORS.has(symbol)||mb.bias<=1;
        if(crowded&&cooling&&!fightingPump&&marketOk){
          return {follow:"FOLLOW_SHORT", side:"SHORT", label:"费率空", strategy:"funding_reversion", strategyLabel:"费率回归", score:Math.min(96,Math.round(72+absRate*100)), reason:`正资金费 ${rate.toFixed(4)}% 拥挤回归`};
        }
      }else{
        const crowded=p5<=-FUNDING.minP5Stretch&&(closeLocation<=0.38||taker<=0.92);
        const cooling=p1>=-FUNDING.coolP1&&(f60.net>0||closeLocation>=0.45);
        const fightingDump=p1<-FUNDING.maxAgainstP1||(signal==="SHORT"&&score>=85&&f60.net<-threshold);
        const marketOk=MAJORS.has(symbol)||mb.bias>=-1;
        if(crowded&&cooling&&!fightingDump&&marketOk){
          return {follow:"FOLLOW_LONG", side:"LONG", label:"费率多", strategy:"funding_reversion", strategyLabel:"费率回归", score:Math.min(96,Math.round(72+absRate*100)), reason:`负资金费 ${rate.toFixed(4)}% 拥挤回归`};
        }
      }
      return null;
    }
    function forecastModel(symbol,longScore,shortScore,p1,p3,p5,f60,f5,cm,d,mb){
      const edge=longScore-shortScore;
      let probUp=50 + edge*0.30 + p1*4.5 + p3*1.8 + p5*1.0 + f60.imbalance*5 + f5.imbalance*3 + mb.bias*2;
      if(isNum(cm.ret15))probUp += cm.ret15*0.35;
      if(isNum(cm.closeLocation))probUp += (cm.closeLocation-0.5)*4;
      if(isNum(d.oi15Pct)&&d.oi15Pct<-2.5)probUp += p5>=0 ? -3 : 3;
      if(isNum(d.bookImbalance))probUp += d.bookImbalance*3.5;
      if(isNum(d.bookSpreadPct)&&d.bookSpreadPct>(MAJORS.has(symbol)?0.035:0.10))probUp += edge>=0 ? -2.5 : 2.5;
      const tooLateLong=p1>ALPHA.altMaxP1&&p5>ALPHA.altMaxP5;
      const tooLateShort=p1<-ALPHA.altMaxP1&&p5<-ALPHA.altMaxP5;
      if(tooLateLong)probUp-=5;
      if(tooLateShort)probUp+=5;
      probUp=clamp(probUp,10,90);
      const side=probUp>=56?"LONG":probUp<=44?"SHORT":"NEUTRAL";
      const prob5=side==="LONG"?probUp:(side==="SHORT"?100-probUp:Math.max(probUp,100-probUp));
      const volBase=Math.max(0.08,isNum(cm.rangePct)?cm.rangePct:0.12,Math.abs(p5)*0.45,Math.abs(p1)*0.8);
      const strength=clamp(Math.abs(edge)/85 + Math.abs(f60.imbalance)*0.25,0,1);
      const flowBoost=Math.min(0.55,f5.total/Math.max(tradeThreshold(symbol),1)*0.025);
      const expectedAbs=clamp(volBase*(0.72+strength)+flowBoost,0.03,4.5);
      const expected5Pct=side==="LONG"?expectedAbs:(side==="SHORT"?-expectedAbs:0);
      const expected15Pct=expected5Pct*(isNum(cm.ret15)&&Math.sign(cm.ret15)===Math.sign(expected5Pct)?1.45:1.15);
      return {side,probUp,probDown:100-probUp,prob5,expected5Pct,expected15Pct};
    }
    async function fetchJson(path){
      let last;
      for(const host of runtime.BINANCE_REST_BASES){
        const controller=new AbortController();
        const timeout=setTimeout(()=>controller.abort(),6000);
        try{
          const res=await fetch(host+path,{cache:"no-store",signal:controller.signal});
          if(!res.ok)throw new Error(`${res.status} ${res.statusText}`);
          return await res.json();
        }catch(err){
          last=err;
        }finally{
          clearTimeout(timeout);
        }
      }
      throw last || new Error("Binance REST unavailable");
    }

    async function refreshMarketUniverse(){
      try{
        const data=await fetchJson("/fapi/v1/ticker/24hr");
        const rows=data.filter(x=>x.symbol&&x.symbol.endsWith("USDT")&&!STABLE_SYMBOLS.has(x.symbol)&&isCryptoTradableSymbol(x.symbol))
          .map(x=>({symbol:x.symbol, quoteVolume:Number(x.quoteVolume||0), changePct:Number(x.priceChangePercent||0), count:Number(x.count||0), lastPrice:Number(x.lastPrice||0)}))
          .filter(x=>x.quoteVolume>0).sort((a,b)=>b.quoteVolume-a.quoteVolume);
        const selected=[];
        for(const sym of runtime.SEED_SYMBOLS){ if(rows.some(x=>x.symbol===sym) && !selected.includes(sym)) selected.push(sym); }
        for(const item of rows){
          state.marketMeta.set(item.symbol,item);
          if(item.lastPrice>0) rememberPrice(item.symbol,item.lastPrice,Date.now());
          if(!selected.includes(item.symbol)) selected.push(item.symbol);
          if(selected.length>=runtime.MAX_STREAM_SYMBOLS) break;
        }
        const changed=selected.join(",")!==state.activeSymbols.join(",");
        state.activeSymbols=selected;
        document.getElementById("scopeSub").textContent=`Top ${selected.length} USDT 永续`;
        document.getElementById("radarNote").textContent=`自动扫描成交额靠前的 ${selected.length} 个 USDT 永续，按大资金流动排序`;
        state.restError="";
        if(changed && state.tradeConnected) reconnectTradesOnly();
      }catch(err){
        state.restError=`市场列表受限：${err}`;
        document.getElementById("scopeSub").textContent="市场列表受限，使用默认池";
      }
    }

    async function fetchDerivatives(){
      try{
        const premium=await fetchJson("/fapi/v1/premiumIndex");
        if(Array.isArray(premium)){
          const set=activeSet(), ts=Date.now();
          for(const item of premium){
            if(!set.has(item.symbol))continue;
            const prev=state.derivatives.get(item.symbol)||{};
            const mark=Number(item.markPrice||0);
            if(mark>0) rememberPrice(item.symbol,mark,ts);
            state.derivatives.set(item.symbol,{...prev, fundingRate:Number(item.lastFundingRate||0)*100, nextFundingTime:Number(item.nextFundingTime||0), updatedAt:ts});
          }
        }
        const targets=[...new Set([...rows().slice(0,18).map(r=>r.symbol),"BTCUSDT","ETHUSDT","SOLUSDT"].filter(s=>activeSet().has(s)))];
        for(let i=0;i<targets.length;i+=4) await Promise.all(targets.slice(i,i+4).map(fetchDerivativeSymbol));
        state.derivativesUpdatedAt=Date.now();
      }catch(err){ state.restError=`衍生品数据受限：${err}`; }
      render();
    }
    async function fetchDerivativeSymbol(symbol){
      const next={...(state.derivatives.get(symbol)||{}), updatedAt:Date.now()};
      try{
        const oi=await fetchJson(`/futures/data/openInterestHist?symbol=${encodeURIComponent(symbol)}&period=5m&limit=4`);
        if(Array.isArray(oi)&&oi.length){
          const latest=Number(oi[oi.length-1].sumOpenInterestValue||0), prev=Number((oi[oi.length-2]||{}).sumOpenInterestValue||0), first=Number(oi[0].sumOpenInterestValue||0);
          next.oi15Pct=first?(latest-first)/first*100:null; next.oi5Pct=prev?(latest-prev)/prev*100:null;
        }
      }catch(_){}
      try{
        const taker=await fetchJson(`/futures/data/takerlongshortRatio?symbol=${encodeURIComponent(symbol)}&period=5m&limit=1`);
        if(Array.isArray(taker)&&taker.length) next.takerRatio=Number(taker[taker.length-1].buySellRatio||1);
      }catch(_){}
      try{
        const depth=await fetchJson(`/fapi/v1/depth?symbol=${encodeURIComponent(symbol)}&limit=20`);
        const bids=(depth.bids||[]).map(row=>({price:Number(row[0]||0),qty:Number(row[1]||0)})).filter(row=>row.price>0&&row.qty>0);
        const asks=(depth.asks||[]).map(row=>({price:Number(row[0]||0),qty:Number(row[1]||0)})).filter(row=>row.price>0&&row.qty>0);
        if(bids.length&&asks.length){
          const bestBid=bids[0].price, bestAsk=asks[0].price, mid=(bestBid+bestAsk)/2;
          const band=MAJORS.has(symbol)?0.0015:0.0030;
          const bidDepth=bids.filter(row=>row.price>=mid*(1-band)).reduce((sum,row)=>sum+row.price*row.qty,0);
          const askDepth=asks.filter(row=>row.price<=mid*(1+band)).reduce((sum,row)=>sum+row.price*row.qty,0);
          const totalDepth=bidDepth+askDepth;
          next.bookSpreadPct=mid?(bestAsk-bestBid)/mid*100:null;
          next.bookImbalance=totalDepth?(bidDepth-askDepth)/totalDepth:null;
          next.bidDepthUsd=Math.round(bidDepth);
          next.askDepthUsd=Math.round(askDepth);
          next.bookUpdatedAt=Date.now();
        }
      }catch(_){}
      state.derivatives.set(symbol,next);
    }
    async function fetchKlineSymbol(symbol){
      try{
        const data=await fetchJson(`/fapi/v1/klines?symbol=${encodeURIComponent(symbol)}&interval=4h&limit=180`);
        if(!Array.isArray(data))return;
        state.candles.set(symbol,data.map(row=>({
          openTime:Number(row[0]), open:Number(row[1]), high:Number(row[2]), low:Number(row[3]),
          close:Number(row[4]), volume:Number(row[5]), closeTime:Number(row[6]), quoteVolume:Number(row[7]||0),
        })).filter(row=>row.close>0));
      }catch(_){}
    }
    async function fetchKlines(){
      const positionSymbols=new Set(((state.testnet&&state.testnet.positions)||[]).map(pos=>pos.symbol));
      const targets=[...new Set([...activeSymbols().slice(0,80),...positionSymbols,"BTCUSDT","ETHUSDT","SOLUSDT"].filter(symbol=>activeSet().has(symbol)))];
      for(let i=0;i<targets.length;i+=4) await Promise.all(targets.slice(i,i+4).map(fetchKlineSymbol));
      render();
    }

    function flow(symbol, ms){ const rows=cutoff(state.trades.get(symbol)||[],ms); let buy=0,sell=0,largest=0,buyCount=0,sellCount=0,lastSide="",streak=0; for(const row of rows){ if(row.side==="BUY"){buy+=row.notional; buyCount++;} else {sell+=row.notional; sellCount++;} largest=Math.max(largest,row.notional); } for(let i=rows.length-1;i>=0;i--){ if(!lastSide)lastSide=rows[i].side; if(rows[i].side!==lastSide)break; streak++; } return {buy,sell,net:buy-sell,total:buy+sell,largest,buyCount,sellCount,count:rows.length,lastSide,streak,imbalance:buy+sell?(buy-sell)/(buy+sell):0}; }
    function liq(symbol, ms){ const rows=cutoff(state.liquidations.get(symbol)||[],ms); let longLiq=0,shortLiq=0; for(const row of rows){ if(row.side==="SELL")longLiq+=row.notional; else shortLiq+=row.notional; } return {longLiq,shortLiq,total:longLiq+shortLiq}; }
    function derivative(symbol){ return {oi15Pct:null,oi5Pct:null,takerRatio:null,fundingRate:null,nextFundingTime:0,bookSpreadPct:null,bookImbalance:null,bidDepthUsd:null,askDepthUsd:null,bookUpdatedAt:0,...(state.derivatives.get(symbol)||{})}; }
    function meta(symbol){ return state.marketMeta.get(symbol)||{}; }

    function scoreRow(symbol){
      const f60=flow(symbol,60*1000), f5=flow(symbol,5*60*1000), l5=liq(symbol,5*60*1000), p1=priceRet(symbol,60*1000), p3=priceRet(symbol,3*60*1000), p5=price5m(symbol), d=derivative(symbol), threshold=tradeThreshold(symbol), cm=candleMetrics(symbol), mb=marketBias();
      let long=0, short=0;
      const flowPower=Math.min(26,Math.abs(f60.imbalance)*18+f60.total/threshold*5);
      if(f60.net>0)long+=flowPower; if(f60.net<0)short+=flowPower;
      if(f5.net>0)long+=Math.min(18,Math.abs(f5.net)/threshold*3); if(f5.net<0)short+=Math.min(18,Math.abs(f5.net)/threshold*3);
      if(f60.buyCount>=2)long+=Math.min(12,f60.buyCount*2); if(f60.sellCount>=2)short+=Math.min(12,f60.sellCount*2);
      if(f60.lastSide==="BUY")long+=Math.min(8,f60.streak*2); if(f60.lastSide==="SELL")short+=Math.min(8,f60.streak*2);
      if(p1>0)long+=Math.min(6,p1*8); if(p1<0)short+=Math.min(6,Math.abs(p1)*8);
      if(p3>0)long+=Math.min(8,p3*5); if(p3<0)short+=Math.min(8,Math.abs(p3)*5);
      if(p5>0)long+=Math.min(12,p5*3); if(p5<0)short+=Math.min(12,Math.abs(p5)*3);
      if(isNum(cm.volSpike)&&cm.volSpike>=1.25){ if(f5.net>0)long+=Math.min(10,(cm.volSpike-1)*6); if(f5.net<0)short+=Math.min(10,(cm.volSpike-1)*6); }
      if(cm.breakout>0||isNum(cm.position)&&cm.position>=0.78)long+=8;
      if(cm.breakout<0||isNum(cm.position)&&cm.position<=0.22)short+=8;
      if(isNum(d.oi15Pct)&&d.oi15Pct>1.2){ if(p5>=0&&f5.net>=0)long+=Math.min(14,d.oi15Pct*3); if(p5<=0&&f5.net<=0)short+=Math.min(14,d.oi15Pct*3); }
      if(isNum(d.oi15Pct)&&d.oi15Pct<-2.5){ if(p5>=0&&f5.net>=0)long-=8; if(p5<=0&&f5.net<=0)short-=12; }
      if(isNum(d.takerRatio)&&d.takerRatio>1.12)long+=Math.min(10,(d.takerRatio-1)*20); if(isNum(d.takerRatio)&&d.takerRatio<0.9)short+=Math.min(10,(1-d.takerRatio)*20);
      if(isNum(d.fundingRate)&&d.fundingRate>0.04)long-=5; if(isNum(d.fundingRate)&&d.fundingRate<-0.04)short-=5;
      if(!MAJORS.has(symbol)){ if(mb.bias<=-1)long-=8; if(mb.bias<=-2)long-=8; if(mb.bias>=1)short-=8; if(mb.bias>=2)short-=8; }
      long=Math.max(0,Math.min(100,long)); short=Math.max(0,Math.min(100,short));
      let signal=long>=short&&long>=35?"LONG":short>long&&short>=35?"SHORT":"WATCH"; let score=Math.round(Math.max(long,short));
      let forecast=forecastModel(symbol,long,short,p1,p3,p5,f60,f5,cm,d,mb);
      let cost=costModel(d,forecast.side);
      forecast.netEdgePct=Math.abs(forecast.expected5Pct)-cost.requiredPct;
      forecast.cost=cost;
      forecast.targets=dynamicTargets(cm,cost);
      const repeatLong=f60.buyCount>=2||f60.lastSide==="BUY"&&f60.streak>=2, repeatShort=f60.sellCount>=2||f60.lastSide==="SELL"&&f60.streak>=2;
      const volumeOk=isNum(cm.volSpike)?cm.volSpike>=0.5:f5.total>=threshold*ALPHA.minTotal5x;
      const marketOkLong=MAJORS.has(symbol)||mb.bias>=-1, marketOkShort=MAJORS.has(symbol)||mb.bias<=1;
      const oiFallingHard=isNum(d.oi15Pct)&&d.oi15Pct<-2.5;
      const oiExpanding=isNum(d.oi5Pct)?d.oi5Pct>=0.08:(isNum(d.oi15Pct)?d.oi15Pct>=0.35:false);
      const oiNotShrinking=!isNum(d.oi5Pct)||d.oi5Pct>=-0.20;
      const oiLongOk=oiNotShrinking&&(oiExpanding||MAJORS.has(symbol)||Math.abs(f5.imbalance)>=0.35);
      const oiShortOk=oiNotShrinking&&(oiExpanding||MAJORS.has(symbol)||Math.abs(f5.imbalance)>=0.35);
      const flowLong=f60.net>0&&f5.net>0, flowShort=f60.net<0&&f5.net<0;
      const priceLong=p1>=-0.04&&p3>=0.04&&p5>=0.08, priceShort=p1<=0.04&&p3<=-0.04&&p5<=-0.08;
      const profitOk=forecast.side!=="NEUTRAL"&&forecast.netEdgePct>ALPHA.minEdgePct;
      const forecastLong=forecast.side==="LONG"&&forecast.prob5>=ALPHA.minProb&&forecast.expected5Pct>0;
      const forecastShort=forecast.side==="SHORT"&&forecast.prob5>=ALPHA.minProb&&forecast.expected5Pct<0;
      const maxP1=MAJORS.has(symbol)?ALPHA.majorMaxP1:ALPHA.altMaxP1, maxP5=MAJORS.has(symbol)?ALPHA.majorMaxP5:ALPHA.altMaxP5;
      const closeLocation=isNum(cm.closeLocation)?cm.closeLocation:0.5;
      const chaseLong=p1>maxP1||p5>maxP5||(p1>0.25&&closeLocation>=0.92);
      const chaseShort=p1<-maxP1||p5<-maxP5||(p1<-0.25&&closeLocation<=0.08);
      const directionGap=Math.abs(long-short);
      const flowStrong=f5.total>=threshold*ALPHA.minTotal5x&&Math.abs(f5.imbalance)>=0.18;
      const momentumFlowStrong=f5.total>=threshold*2.4&&Math.abs(f5.imbalance)>=0.28&&Math.abs(f60.imbalance)>=0.32;
      const candleOkLong=!isNum(cm.closeLocation)||cm.closeLocation>=0.58;
      const candleOkShort=!isNum(cm.closeLocation)||cm.closeLocation<=0.42;
      const btcOkLong=MAJORS.has(symbol)||mb.btc>=-0.08&&mb.eth>=-0.12;
      const btcOkShort=MAJORS.has(symbol)||mb.btc<=0.08&&mb.eth<=0.12;
      const bookKnown=isNum(d.bookSpreadPct)&&isNum(d.bookImbalance);
      const maxSpreadPct=MAJORS.has(symbol)?0.035:0.10;
      const spreadOk=!bookKnown||d.bookSpreadPct<=maxSpreadPct;
      const bookLongOk=!bookKnown||d.bookImbalance>=-0.18;
      const bookShortOk=!bookKnown||d.bookImbalance<=0.18;
      const depthLongRatio=isNum(d.askDepthUsd)&&d.askDepthUsd>0?Math.abs(f60.net)/d.askDepthUsd:null;
      const depthShortRatio=isNum(d.bidDepthUsd)&&d.bidDepthUsd>0?Math.abs(f60.net)/d.bidDepthUsd:null;
      const depthLongOk=!isNum(depthLongRatio)||depthLongRatio>=0.03;
      const depthShortOk=!isNum(depthShortRatio)||depthShortRatio>=0.03;
      const momentumImpulseLong=p1>=0.02&&p3>=0.06&&p5>=0.10&&closeLocation>=0.58;
      const momentumImpulseShort=p1<=-0.02&&p3<=-0.06&&p5<=-0.10&&closeLocation<=0.42;
      const momentumBookLong=!bookKnown||d.bookImbalance>=0.04;
      const momentumBookShort=!bookKnown||d.bookImbalance<=-0.04;
      const momentumDepthLong=!isNum(depthLongRatio)||depthLongRatio>=0.06;
      const momentumDepthShort=!isNum(depthShortRatio)||depthShortRatio>=0.06;
      const testMomentumLong=p1>=0.01&&p3>=0.04&&p5>=0.08&&closeLocation>=0.56;
      const testMomentumShort=p1<=-0.01&&p3<=-0.04&&p5<=-0.08&&closeLocation<=0.44;
      const alignedLong=MICRO.enableMomentum&&signal==="LONG"&&score>=64&&directionGap>=8&&forecastLong&&forecast.prob5>=62&&forecast.netEdgePct>=0.12&&profitOk&&flowLong&&flowStrong&&momentumFlowStrong&&testMomentumLong&&repeatLong&&volumeOk&&marketOkLong&&btcOkLong&&oiLongOk&&candleOkLong&&spreadOk&&bookLongOk&&depthLongOk&&!oiFallingHard&&f60.largest>=threshold&&!chaseLong;
      const alignedShort=MICRO.enableMomentum&&signal==="SHORT"&&score>=64&&directionGap>=8&&forecastShort&&forecast.prob5>=62&&forecast.netEdgePct>=0.12&&profitOk&&flowShort&&flowStrong&&momentumFlowStrong&&testMomentumShort&&repeatShort&&volumeOk&&marketOkShort&&btcOkShort&&oiShortOk&&candleOkShort&&spreadOk&&bookShortOk&&depthShortOk&&!oiFallingHard&&f60.largest>=threshold&&!chaseShort;
      const sweepSetup=liquiditySweepReclaimSetup(symbol,p1,p3,p5,f60,f5,l5,cm,d,mb,threshold);
      const liquidationSetup=liquidationReversalSetup(symbol,p1,p5,f60,l5,cm,d,mb,threshold);
      const sectorSetup=sectorLeadLagSetup(symbol,p1,p5,f60,f5,cm,mb,threshold);
      const exhaustionSetup=flowExhaustionSetup(symbol,p1,p5,f60,f5,cm,d,mb,threshold);
      const btcCm=candleMetrics("BTCUSDT");
      const currentPrice=Number(state.prices.get(symbol)||cm.lastClose||0);
      const btcRiskOn=MAJORS.has(symbol)||(
        isNum(btcCm.emaTrendGapPct)&&btcCm.emaTrendGapPct>=0&&
        isNum(btcCm.ret24h)&&btcCm.ret24h>=-1.0
      );
      const channelBreakout=isNum(cm.high55)&&currentPrice>cm.high55;
      const trendStack=isNum(cm.emaTrendGapPct)&&cm.emaTrendGapPct>0&&isNum(cm.ret24h)&&cm.ret24h>0;
      const notIlliquid=MAJORS.has(symbol)||Number((meta(symbol)||{}).quoteVolume||0)>=35000000;
      const mainVolumeOk=isNum(cm.volSpike)?cm.volSpike>=0.70:true;
      const mainTrendLong=channelBreakout&&trendStack&&btcRiskOn&&notIlliquid&&mainVolumeOk&&spreadOk&&bookLongOk;
      const mainSetup=mainTrendLong ? {
        follow:"FOLLOW_LONG", side:"LONG", label:"4h突破多",
        strategy:"main_flow_direction", strategyLabel:"4h突破趋势",
        score:Math.max(score,72), reason:"4h价格突破55根高点，EMA48在EMA96上方，BTC风险过滤通过",
      } : null;
      const scalpLong=MICRO.enableMomentum&&signal==="LONG"&&score>=56&&directionGap>=4&&forecastLong&&forecast.prob5>=58&&forecast.netEdgePct>=0.03&&profitOk&&flowLong&&f60.net>threshold*0.28&&f5.total>=threshold*1.15&&testMomentumLong&&repeatLong&&volumeOk&&marketOkLong&&btcOkLong&&spreadOk&&!chaseLong;
      const scalpShort=MICRO.enableMomentum&&signal==="SHORT"&&score>=56&&directionGap>=4&&forecastShort&&forecast.prob5>=58&&forecast.netEdgePct>=0.03&&profitOk&&flowShort&&Math.abs(f60.net)>threshold*0.28&&f5.total>=threshold*1.15&&testMomentumShort&&repeatShort&&volumeOk&&marketOkShort&&btcOkShort&&spreadOk&&!chaseShort;
      const momentumSetup=alignedLong ? {
        follow:"FOLLOW_LONG", side:"LONG", label:"策略多",
        strategy:"flow_momentum", strategyLabel:"大单顺势",
        score:Math.max(score,76), reason:"大单顺势多，强流确认",
      } : (alignedShort ? {
        follow:"FOLLOW_SHORT", side:"SHORT", label:"策略空",
        strategy:"flow_momentum", strategyLabel:"大单顺势",
        score:Math.max(score,76), reason:"大单顺势空，强流确认",
      } : (scalpLong ? {
        follow:"FOLLOW_LONG", side:"LONG", label:"一分钟多",
        strategy:"flow_momentum", strategyLabel:"一分钟顺势",
        score:Math.max(score,64), reason:"1m/3m 价格和 60s 资金同向，短线顺势测试",
      } : (scalpShort ? {
        follow:"FOLLOW_SHORT", side:"SHORT", label:"一分钟空",
        strategy:"flow_momentum", strategyLabel:"一分钟顺势",
        score:Math.max(score,64), reason:"1m/3m 价格和 60s 资金同向，短线顺势测试",
      } : null)));
      const fundingSetup=fundingReversionSetup(symbol,p1,p5,f60,cm,d,mb,signal,score,threshold);
      const microSetup=mainSetup||sweepSetup||liquidationSetup||sectorSetup||exhaustionSetup||momentumSetup;
      let follow=microSetup?microSetup.follow:"";
      let label=microSetup?microSetup.label:"";
      let strategy=microSetup?microSetup.strategy:"none";
      let strategyLabel=microSetup?microSetup.strategyLabel:"";
      if(microSetup){
        signal=microSetup.side;
        score=Math.max(score,microSetup.score);
        forecast.side=microSetup.side;
        const minProb=microSetup.strategy==="liquidity_sweep_reclaim"?(microSetup.testTier==="probe"?67:74):(microSetup.strategy==="flow_momentum"?64:(microSetup.strategy==="main_flow_direction"?72:68));
        forecast.prob5=Math.max(forecast.prob5,minProb);
        const microExpected=Math.max(Math.abs(forecast.expected5Pct),microSetup.strategy==="liquidity_sweep_reclaim"?(microSetup.testTier==="probe"?0.58:0.90):(microSetup.strategy==="flow_momentum"?0.42:(microSetup.strategy==="main_flow_direction"?2.20:0.55)));
        forecast.expected5Pct=microSetup.side==="LONG"?microExpected:-microExpected;
        cost=costModel(d,forecast.side);
        forecast.cost=cost;
        forecast.netEdgePct=Math.abs(forecast.expected5Pct)-cost.requiredPct;
        forecast.targets=microSetup.strategy==="main_flow_direction"?{takeProfit:99,trailArm:99}:({takeProfit:Math.max(microSetup.strategy==="flow_momentum"?1.05:1.20, dynamicTargets(cm,cost).takeProfit), trailArm:Math.max(0.60, dynamicTargets(cm,cost).trailArm)});
      }
      if(!follow&&fundingSetup){
        follow=fundingSetup.follow;
        label=fundingSetup.label;
        strategy=fundingSetup.strategy;
        strategyLabel=fundingSetup.strategyLabel;
        signal=fundingSetup.side;
        score=Math.max(score,fundingSetup.score);
        forecast.side=fundingSetup.side;
        forecast.prob5=Math.max(forecast.prob5,Math.min(76,60+Math.abs(d.fundingRate)*120));
        const fundingExpected=Math.max(Math.abs(forecast.expected5Pct),0.34+Math.min(0.34,Math.abs(d.fundingRate)*3));
        forecast.expected5Pct=fundingSetup.side==="LONG"?fundingExpected:-fundingExpected;
        cost=costModel(d,forecast.side);
        forecast.cost=cost;
        forecast.netEdgePct=Math.abs(forecast.expected5Pct)-cost.requiredPct;
        forecast.targets=dynamicTargets(cm,cost);
      }
      const risks=[];
	      if(strategy==="main_flow_direction"){
	        if(follow==="FOLLOW_LONG"&&isNum(cm.high55)&&currentPrice<=cm.high55)risks.push("未突破4h 55高点");
	        if(follow==="FOLLOW_LONG"&&isNum(cm.emaTrendGapPct)&&cm.emaTrendGapPct<=0)risks.push("4h EMA趋势未转强");
	        if(follow==="FOLLOW_LONG"&&isNum(cm.ret24h)&&cm.ret24h<=0)risks.push("24h动量不足");
	        if(follow==="FOLLOW_LONG"&&!btcRiskOn)risks.push("BTC风险过滤未通过");
	        if(!spreadOk)risks.push("点差过宽");
	        if(cost.fundingPct>0)risks.push("资金费成本");
	      }else if(strategy==="funding_reversion"){
	        if(follow==="FOLLOW_LONG"&&f60.net<0&&Math.abs(f60.net)>=threshold)risks.push("短流反向");
	        if(follow==="FOLLOW_SHORT"&&f60.net>0&&Math.abs(f60.net)>=threshold)risks.push("短流反向");
	        if(cost.fundingPct>0)risks.push("资金费成本");
	      }else if(strategy==="liquidity_sweep_reclaim"){
	        if(!liquidMarketOk(symbol,d,threshold))risks.push("流动性不足");
	        if(follow==="FOLLOW_LONG"&&!cm.sweepLow)risks.push("未扫前低");
	        if(follow==="FOLLOW_SHORT"&&!cm.sweepHigh)risks.push("未扫前高");
	        if(follow==="FOLLOW_LONG"&&f60.net<0)risks.push("收回后卖流反压");
	        if(follow==="FOLLOW_SHORT"&&f60.net>0)risks.push("收回后买流反推");
	        if(follow==="FOLLOW_LONG"&&mb.bias<-1)risks.push("大盘仍弱");
	        if(follow==="FOLLOW_SHORT"&&mb.bias>1)risks.push("大盘仍强");
	        if(cost.fundingPct>0)risks.push("资金费成本");
	      }else if(strategy==="liquidation_reversal"){
        if(follow==="FOLLOW_LONG"&&f60.net<0)risks.push("承接不足");
        if(follow==="FOLLOW_SHORT"&&f60.net>0)risks.push("压回不足");
        if(follow==="FOLLOW_LONG"&&p1<MICRO.reversalP1)risks.push("1m未收回");
        if(follow==="FOLLOW_SHORT"&&p1>-MICRO.reversalP1)risks.push("1m未压回");
        if(follow==="FOLLOW_LONG"&&mb.bias<0)risks.push("大盘仍弱");
        if(follow==="FOLLOW_SHORT"&&mb.bias>0)risks.push("大盘仍强");
        if(!isNum(d.oi5Pct)&&!isNum(d.oi15Pct))risks.push("OI缺失");
        if(cost.fundingPct>0)risks.push("资金费成本");
      }else if(strategy==="flow_exhaustion_reversal"){
        if(follow==="FOLLOW_LONG"&&f60.net<0)risks.push("收回不足");
        if(follow==="FOLLOW_SHORT"&&f60.net>0)risks.push("压回不足");
        if(follow==="FOLLOW_LONG"&&p5>-0.35)risks.push("下跌幅度不足");
        if(follow==="FOLLOW_SHORT"&&p5<0.35)risks.push("拉升幅度不足");
        if(follow==="FOLLOW_LONG"&&mb.bias<-1)risks.push("大盘仍弱");
        if(follow==="FOLLOW_SHORT"&&mb.bias>1)risks.push("大盘仍强");
        if(cost.fundingPct>0)risks.push("资金费成本");
      }else if(strategy==="sector_lead_lag"){
        if(follow==="FOLLOW_LONG"&&!flowLong)risks.push("补涨资金未跟上");
        if(follow==="FOLLOW_SHORT"&&!flowShort)risks.push("补跌资金未跟上");
        if(cost.fundingPct>0)risks.push("资金费成本");
      }else{
        if(signal!=="WATCH"&&!profitOk)risks.push("成本不过");
        if(cost.fundingPct>0)risks.push("资金费成本");
        if(signal==="LONG"&&!priceLong)risks.push("价格未确认"); if(signal==="SHORT"&&!priceShort)risks.push("价格未确认");
        if(signal==="LONG"&&!momentumImpulseLong)risks.push("顺势动量不足");
        if(signal==="SHORT"&&!momentumImpulseShort)risks.push("顺势动量不足");
        if(signal==="LONG"&&!flowLong)risks.push("净流不连续"); if(signal==="SHORT"&&!flowShort)risks.push("净流不连续");
        if(signal!=="WATCH"&&!flowStrong)risks.push("资金流强度不足");
        if(signal==="LONG"&&!repeatLong)risks.push("孤立大单"); if(signal==="SHORT"&&!repeatShort)risks.push("孤立大单");
        if(signal==="LONG"&&chaseLong)risks.push("追涨过热"); if(signal==="SHORT"&&chaseShort)risks.push("追空过热");
        if(signal==="LONG"&&!candleOkLong)risks.push("收盘位置偏弱"); if(signal==="SHORT"&&!candleOkShort)risks.push("收盘位置偏强");
        if(!volumeOk)risks.push("量能不足");
        if(signal==="LONG"&&!marketOkLong)risks.push("大盘反向"); if(signal==="SHORT"&&!marketOkShort)risks.push("大盘反向");
        if(signal==="LONG"&&!btcOkLong)risks.push("BTC/ETH压制"); if(signal==="SHORT"&&!btcOkShort)risks.push("BTC/ETH反抽");
        if(signal==="LONG"&&!oiLongOk)risks.push("OI不支持多"); if(signal==="SHORT"&&!oiShortOk)risks.push("OI不支持空");
        if(!spreadOk)risks.push("点差过宽");
        if(signal==="LONG"&&!bookLongOk)risks.push("盘口不支持多");
        if(signal==="SHORT"&&!bookShortOk)risks.push("盘口不支持空");
        if(signal==="LONG"&&!momentumBookLong)risks.push("盘口顺势不够");
        if(signal==="SHORT"&&!momentumBookShort)risks.push("盘口顺势不够");
        if(signal==="LONG"&&!depthLongOk)risks.push("主动买流弱于盘口");
        if(signal==="SHORT"&&!depthShortOk)risks.push("主动卖流弱于盘口");
        if(oiFallingHard)risks.push("OI下降");
      }
      const reasons=[];
      if(microSetup)reasons.push(microSetup.reason);
      if(strategy==="main_flow_direction")reasons.push("主信号：4h Donchian 突破趋势");
      if(strategy==="flow_momentum")reasons.push("Alpha过滤通过");
      if(strategy==="funding_reversion"&&fundingSetup)reasons.push(fundingSetup.reason);
      if(Math.abs(f60.net)>=threshold)reasons.push((f60.net>0?"主动买净流 ":"主动卖净流 ")+money(Math.abs(f60.net)));
      if(f60.largest>=threshold)reasons.push("最大单 "+money(f60.largest));
      if(isNum(d.fundingRate)&&Math.abs(d.fundingRate)>=FUNDING.extremePct)reasons.push("资金费 "+d.fundingRate.toFixed(4)+"%");
      if(isNum(cm.volSpike))reasons.push("量能 "+cm.volSpike.toFixed(1)+"x");
      if(Math.abs(p5)>=0.25)reasons.push("5m价格 "+(p5>0?"+":"")+p5.toFixed(2)+"%");
      if(isNum(cm.closeLocation))reasons.push("收盘位置 "+Math.round(cm.closeLocation*100)+"%");
      if(isNum(cm.high55))reasons.push("4h通道高点 "+price(cm.high55));
      if(isNum(cm.low20))reasons.push("4h退出低点 "+price(cm.low20));
      if(isNum(cm.emaTrendGapPct))reasons.push("4h EMA差 "+(cm.emaTrendGapPct>0?"+":"")+cm.emaTrendGapPct.toFixed(3)+"%");
      if(isNum(cm.ret24h))reasons.push("24h动量 "+(cm.ret24h>0?"+":"")+cm.ret24h.toFixed(2)+"%");
      if(isNum(d.oi15Pct)&&Math.abs(d.oi15Pct)>=1.2)reasons.push("OI15m "+(d.oi15Pct>0?"+":"")+d.oi15Pct.toFixed(2)+"%");
      if(isNum(d.oi5Pct)&&Math.abs(d.oi5Pct)>=0.08)reasons.push("OI5m "+(d.oi5Pct>0?"+":"")+d.oi5Pct.toFixed(2)+"%");
      if(isNum(d.takerRatio)&&(d.takerRatio>=1.12||d.takerRatio<=0.9))reasons.push("Taker "+d.takerRatio.toFixed(2));
      if(isNum(d.bookImbalance))reasons.push("盘口失衡 "+d.bookImbalance.toFixed(2));
      if(isNum(d.bookSpreadPct))reasons.push("点差 "+d.bookSpreadPct.toFixed(3)+"%");
      if(!reasons.length)reasons.push("等待大额资金流");
      const rawFollow=follow;
      const rawLabel=label;
      const rawStrategy=strategy;
      const rawStrategyLabel=strategyLabel;
      const rawForecast={...forecast};
      const inverted=applyFollowInversion(follow,label,strategyLabel,forecast,strategy);
      follow=inverted.follow;
      label=inverted.label;
      strategyLabel=inverted.strategyLabel;
      forecast=inverted.forecast;
      const signalVariant=rawFollow&&follow!==rawFollow?"inverted":"primary";
      const mainSignal=strategy==="flow_momentum"&&signalVariant==="inverted"?"flow_momentum_inverted":strategy;
      if(!follow){ follow=signal==="LONG"?"WATCH_LONG":signal==="SHORT"?"WATCH_SHORT":"WAIT"; label=follow==="WATCH_LONG"?"多头异动":follow==="WATCH_SHORT"?"空头异动":"观察"; }
      return {symbol,base:base(symbol),price:state.prices.get(symbol)||0,p1,p3,p5,f60,f5,l5,d,m:meta(symbol),cm,btcCm,mb,threshold,signal,score,follow,label,strategy,strategyLabel,mainSignal,signalVariant,rawFollow,rawLabel,rawStrategy,rawStrategyLabel,rawForecast,forecast,cost,risks,reasons,sweepSide:microSetup&&microSetup.sweepSide,reclaimLevel:microSetup&&microSetup.reclaimLevel,sweepDepthPct:microSetup&&microSetup.sweepDepthPct,testTier:microSetup&&microSetup.testTier};
    }
    function rows(){ return activeSymbols().map(scoreRow).sort((a,b)=>b.score-a.score||Math.abs(b.f60.net)-Math.abs(a.f60.net)||Number(b.m.quoteVolume||0)-Number(a.m.quoteVolume||0)); }
    function allowedStrategySet(){
      const items=state.testnet&&Array.isArray(state.testnet.allowed_strategies)?state.testnet.allowed_strategies:["liquidity_sweep_reclaim"];
      return new Set(items);
    }
    function estimatedGrade(row){
      const forecast=row.forecast||{};
      const prob=Number(forecast.prob5||row.forecast_5m_prob||0);
      const edge=Number(forecast.netEdgePct!==undefined?forecast.netEdgePct:(row.net_edge_pct||0));
      let grade="B";
      if(prob>=72)grade="A";
      else if(prob>=68)grade="B+";
      else if(prob<=68)grade="C";
      if(edge>=0.35)grade=grade==="A"||grade==="B+"?"A":grade;
      return grade;
    }
    function strategyBlockReason(row){
      if(!row||!row.strategy||!allowedStrategySet().has(row.strategy))return "当前策略模式不下单";
      const mode=state.testnet&&state.testnet.strategy_mode;
      if(mode!=="one_minute"&&estimatedGrade(row)==="C")return "C级信号不下单";
      return "";
    }
    function strategyAllowed(row){ return !strategyBlockReason(row); }
    function isFollowSignal(row){ return row.follow==="FOLLOW_LONG"||row.follow==="FOLLOW_SHORT"; }
    function isAutoSignal(row){ return isFollowSignal(row)&&strategyAllowed(row); }
    function filteredRows(){ const q=document.getElementById("search").value.trim().toUpperCase(); return rows().filter(r=>{ if(q&&!r.symbol.includes(q)&&!r.base.includes(q))return false; if(state.activeFilter==="follow")return isAutoSignal(r); if(state.activeFilter==="long")return r.signal==="LONG"; if(state.activeFilter==="short")return r.signal==="SHORT"; if(state.activeFilter==="alts")return !MAJORS.has(r.symbol); return true; }); }
    function badge(row){ const block=strategyBlockReason(row); if(isFollowSignal(row)&&block)return `<span class="badge watch">${block.includes("C级")?"C级过滤":"模式过滤"}</span>`; if(row.follow==="FOLLOW_LONG")return `<span class="badge long">${esc(row.label||"策略多")}</span>`; if(row.follow==="FOLLOW_SHORT")return `<span class="badge short">${esc(row.label||"策略空")}</span>`; if(row.follow==="WATCH_LONG")return '<span class="badge long">多头异动</span>'; if(row.follow==="WATCH_SHORT")return '<span class="badge short">空头异动</span>'; return '<span class="badge watch">观察</span>'; }
    function setDot(id,ok,err){ const el=document.getElementById(id); el.classList.toggle("ok",ok); el.classList.toggle("bad",!!err); }
    function addEvent(ev){ state.events.unshift(ev); state.events=state.events.slice(0,220); }

    function renderStats(all){ const active=all.filter(isAutoSignal); document.getElementById("statSymbols").textContent=activeSymbols().length; document.getElementById("statLong").textContent=active.filter(r=>r.follow==="FOLLOW_LONG").length; document.getElementById("statShort").textContent=active.filter(r=>r.follow==="FOLLOW_SHORT").length; document.getElementById("statCost").textContent=baseCostPct().toFixed(2)+"%"; document.getElementById("statLiq").textContent=money(all.reduce((s,r)=>s+r.l5.total,0)); setDot("priceDot",state.priceConnected,state.priceError); setDot("tradeDot",state.tradeConnected,state.tradeError); setDot("liqDot",state.liqConnected,state.liqError); const err=[state.priceError,state.tradeError,state.liqError,state.restError].filter(Boolean); document.getElementById("connText").textContent=err.length?"连接错误":`实时连接中 · 价格${state.priceMessages} 大单${state.tradeMessages} 范围${activeSymbols().length}`; document.getElementById("errorNote").textContent=err[0]||""; }
    function detailItem(label,value){ return `<div class="detail-item"><div class="detail-label">${label}</div><div class="detail-value">${value}</div></div>`; }
    function renderDetail(row){
      const reasons=row.reasons.map(x=>`<span class="chip">${x}</span>`).join("");
      const risks=(row.risks.length?row.risks:["--"]).map(x=>`<span class="chip">${x}</span>`).join("");
      const streak=row.f60.lastSide?(row.f60.lastSide==="BUY"?"买":"卖")+row.f60.streak:"--";
      const closeLoc=isNum(row.cm.closeLocation)?Math.round(row.cm.closeLocation*100)+"%":"--";
      const flowText=`60s ${money(row.f60.net)} / 5m ${money(row.f5.net)} / 最大 ${money(row.f60.largest||row.f5.largest)}`;
      const bookText=`点差 ${isNum(row.d.bookSpreadPct)?row.d.bookSpreadPct.toFixed(3)+"%":"--"} / 失衡 ${isNum(row.d.bookImbalance)?row.d.bookImbalance.toFixed(2):"--"} / 买卖盘 ${money(row.d.bidDepthUsd||0)} / ${money(row.d.askDepthUsd||0)}`;
      const marketText=`BTC ${signedPlain(row.mb.btc,2)} / ETH ${signedPlain(row.mb.eth,2)} / bias ${row.mb.bias}`;
      return `<tr class="detail-row"><td colspan="10"><div class="detail-box">
        ${detailItem("依据",`<div class="reason">${reasons}</div>`)}
        ${detailItem("风险",`<div class="reason">${risks}</div>`)}
        ${detailItem("资金流",flowText)}
        ${detailItem("盘口",bookText)}
        ${detailItem("连续",streak)}
        ${detailItem("OI / Taker",`${pctOrDash(row.d.oi15Pct)} / ${ratioOrDash(row.d.takerRatio)}`)}
        ${detailItem("量能 / 收盘位置",`${isNum(row.cm.volSpike)?row.cm.volSpike.toFixed(1)+"x":"--"} / ${closeLoc}`)}
        ${detailItem("ATR目标",`${row.forecast.targets?row.forecast.targets.takeProfit.toFixed(2)+"% / 移动 "+row.forecast.targets.trailArm.toFixed(2)+"%":"--"}`)}
        ${detailItem("爆仓",`多爆 ${money(row.l5.longLiq)} / 空爆 ${money(row.l5.shortLiq)}`)}
        ${detailItem("大盘",marketText)}
      </div></td></tr>`;
    }
    function renderRow(row){
      const n5=row.f5.net>=0?"up":"down", edgeCls=row.forecast.netEdgePct>=0?"up":"down";
      const riskText=(row.risks.length?row.risks.slice(0,2):["--"]).map(x=>`<span class="chip">${x}</span>`).join("");
      const sideText=row.forecast.side==="LONG"?"多":(row.forecast.side==="SHORT"?"空":"震荡");
      const predText=`${sideText} ${row.forecast.prob5.toFixed(0)}% ${signedPlain(row.forecast.expected5Pct,2)}`;
      const expanded=state.expanded.has(row.symbol);
      const main=`<tr><td><div class="symbol">${row.base}</div><div class="small">${row.symbol}</div></td><td>${badge(row)}</td><td><span class="score">${row.score}</span></td><td class="num">${predText}</td><td class="num ${edgeCls}">${signedPlain(row.forecast.netEdgePct,2)}</td><td class="num">${price(row.price)}</td><td class="num">${signedPct(row.p1)} / ${signedPct(row.p5)}</td><td class="num ${n5}">${row.f5.net>=0?"+":"-"}${money(Math.abs(row.f5.net))}</td><td><div class="reason">${riskText}</div></td><td><button class="detail-btn" data-symbol="${row.symbol}">${expanded?"收起":"详情"}</button></td></tr>`;
      return expanded ? main + renderDetail(row) : main;
    }
    function strategyAction(row){
      if(row.follow==="FOLLOW_LONG"){
        const text=row.strategy==="main_flow_direction"?"自动测主多":(row.strategy==="liquidity_sweep_reclaim"?"自动测扫低收回":(row.strategy==="funding_reversion"?"自动测试费率多":(row.strategy==="liquidation_reversal"?"自动测爆仓反弹":(row.strategy==="sector_lead_lag"?"自动测跷跷板多":"自动测试做多"))));
        return {text, cls:"long", order:"模拟盘将市价 BUY"};
      }
      if(row.follow==="FOLLOW_SHORT"){
        const text=row.strategy==="main_flow_direction"?"自动测主空":(row.strategy==="liquidity_sweep_reclaim"?"自动测扫高收回":(row.strategy==="funding_reversion"?"自动测试费率空":(row.strategy==="liquidation_reversal"?"自动测爆仓回落":(row.strategy==="sector_lead_lag"?"自动测跷跷板空":"自动测试做空"))));
        return {text, cls:"short", order:"模拟盘将市价 SELL"};
      }
      if(row.follow==="WATCH_LONG")return {text:"观察多头", cls:"wait", order:"条件未齐，不下单"};
      if(row.follow==="WATCH_SHORT")return {text:"观察空头", cls:"wait", order:"条件未齐，不下单"};
      return {text:"不交易", cls:"wait", order:"等待下一轮信号"};
    }
    function renderStrategyCard(row){
      const blockReason=strategyBlockReason(row);
      const allowedByMode=!blockReason;
      const action=allowedByMode?strategyAction(row):{text:blockReason.includes("C级")?"C级过滤":"模式过滤", cls:"wait", order:blockReason};
      const cls=allowedByMode&&row.follow==="FOLLOW_LONG"?"follow-long":(allowedByMode&&row.follow==="FOLLOW_SHORT"?"follow-short":"");
      const sideText=row.forecast.side==="LONG"?"多":(row.forecast.side==="SHORT"?"空":"震荡");
      const riskItems=allowedByMode?(row.risks.length?row.risks.slice(0,4):["条件正常"]):[blockReason];
      const risks=riskItems.map(x=>`<span class="chip">${x}</span>`).join("");
      const reasons=row.reasons.slice(0,4).map(x=>`<span class="chip">${x}</span>`).join("");
      const tradeState=allowedByMode?((state.testnet&&state.testnet.auto_trade&&state.testnet.account_ok)?action.order:(row.follow.startsWith("FOLLOW")?"等待模拟盘连接/开启自动下单":"不触发模拟单")):blockReason;
      return `<div class="strategy-card ${cls}">
        <div class="strategy-head">
          <div><div class="strategy-symbol">${row.base}</div><div class="small">${row.symbol} · ${price(row.price)}</div></div>
          <div class="strategy-action ${action.cls}">${action.text}</div>
        </div>
        <div class="strategy-metrics">
          <div class="metric"><div class="label">分数</div><div class="value">${row.score}</div></div>
          <div class="metric"><div class="label">5m预测</div><div class="value">${sideText} ${row.forecast.prob5.toFixed(0)}%</div></div>
          <div class="metric"><div class="label">净边际</div><div class="value ${row.forecast.netEdgePct>=0?"up":"down"}">${signedPlain(row.forecast.netEdgePct,2)}</div></div>
          <div class="metric"><div class="label">5m净流</div><div class="value ${row.f5.net>=0?"up":"down"}">${row.f5.net>=0?"+":"-"}${money(Math.abs(row.f5.net))}</div></div>
        </div>
        <div class="strategy-note">
          <div><strong>模拟盘动作：</strong>${tradeState}</div>
          <div><strong>依据：</strong><div class="reason">${reasons}</div></div>
          <div><strong>阻碍/风险：</strong><div class="reason">${risks}</div></div>
        </div>
      </div>`;
    }
    function renderDecisionSummary(all,cards){
      const box=document.getElementById("decisionSummary");
      const active=all.filter(isAutoSignal);
      const followLong=active.filter(r=>r.follow==="FOLLOW_LONG").length, followShort=active.filter(r=>r.follow==="FOLLOW_SHORT").length;
      const best=cards[0];
      const action=best?strategyAction(best):{text:"等待信号",cls:"wait"};
      const market=`BTC ${signedPlain(marketBias().btc,2)} / ETH ${signedPlain(marketBias().eth,2)}`;
      const auto=state.testnet&&state.testnet.auto_trade?(state.testnet.account_ok?"自动下单开启":"自动下单待连接"):"自动下单关闭";
      box.innerHTML=`<div class="decision-box primary"><div class="decision-label">当前动作</div><div class="decision-main">${best?action.text:"等待信号"}</div><div class="decision-sub">${best?best.base+" · "+(best.risks[0]||"条件通过"):"后台继续监控，不展示实时噪声。"}</div></div>
        <div class="decision-box"><div class="decision-label">可测策略</div><div class="decision-main">${followLong+followShort}</div><div class="decision-sub">多 ${followLong} / 空 ${followShort}</div></div>
        <div class="decision-box"><div class="decision-label">市场状态</div><div class="decision-main">${marketBias().bias}</div><div class="decision-sub">${market}</div></div>
        <div class="decision-box"><div class="decision-label">模拟盘</div><div class="decision-main">${auto}</div><div class="decision-sub">${state.testnet&&state.testnet.message?esc(state.testnet.message):"仅 Testnet"}</div></div>`;
    }
    function render(){
      const all=rows(), visible=filteredRows();
      renderStats(all);
      const board=document.getElementById("strategyBoard");
      const follow=visible.filter(isAutoSignal);
      const watch=visible.filter(r=>strategyAllowed(r)&&(r.follow==="WATCH_LONG"||r.follow==="WATCH_SHORT"));
      const cards=[...follow,...watch].slice(0,6);
      renderDecisionSummary(all,cards);
      if(!cards.length){ const mode=state.testnet&&state.testnet.strategy_mode_label?state.testnet.strategy_mode_label:"当前策略模式"; board.innerHTML=`<div class="empty-board">${esc(mode)} 暂无可测试信号。后台仍在监控交易对；出现允许策略的 FOLLOW_LONG / FOLLOW_SHORT 后才会自动生成模拟盘买卖方案。</div>`; return; }
      board.innerHTML=cards.map(renderStrategyCard).join("");
    }
    function renderEvents(){ const list=document.getElementById("eventList"); if(!list)return; const text=[`价格流 ${state.priceConnected?"正常":"异常"}`,`大单流 ${state.tradeConnected?"正常":"异常"}`,`爆仓流 ${state.liqConnected?"正常":"异常"}`,`事件 ${state.events.length}`]; const latest=state.events.slice(0,4).map(ev=>{ const cls=ev.side==="BUY"?"buy":"sell"; return `<div class="event"><div class="event-side ${cls}">${ev.label}</div><div><div class="event-title"><span>${base(ev.symbol)}</span><span>${money(ev.notional)}</span></div><div class="event-meta">${new Date(ev.ts).toLocaleTimeString()} · 后台记录</div></div></div>`; }).join(""); list.innerHTML=`<div class="event"><div></div><div><div class="event-title">后台监控状态</div><div class="event-meta">${text.join(" · ")}</div></div></div>${latest}`; }
    function compactRows(){ return rows().slice(0,18).map(r=>({symbol:r.symbol,base:r.base,label:r.label,follow:r.follow,score:r.score,strategy:r.strategy,strategy_label:r.strategyLabel,main_signal:r.mainSignal,signal_variant:r.signalVariant,test_tier:r.testTier||"",price:r.price,forecast_side:r.forecast.side,forecast_5m_prob:Number(r.forecast.prob5.toFixed(1)),forecast_5m_expected_pct:Number(r.forecast.expected5Pct.toFixed(3)),required_cost_pct:Number(r.cost.requiredPct.toFixed(3)),net_edge_pct:Number(r.forecast.netEdgePct.toFixed(3)),take_profit_pct:r.forecast.targets?Number(r.forecast.targets.takeProfit.toFixed(3)):null,trail_arm_pct:r.forecast.targets?Number(r.forecast.targets.trailArm.toFixed(3)):null,funding_cost_pct:Number(r.cost.fundingPct.toFixed(4)),price_1m_pct:Number(r.p1.toFixed(3)),price_3m_pct:Number(r.p3.toFixed(3)),price_5m_pct:Number(r.p5.toFixed(3)),volume_24h_usd:Math.round(r.m.quoteVolume||0),volume_spike:r.cm.volSpike,atr_pct:r.cm.atrPct,channel_high_55:r.cm.high55,channel_low_20:r.cm.low20,ema_trend_gap_pct:r.cm.emaTrendGapPct,trend_ret_24h:r.cm.ret24h,trend_ret_72h:r.cm.ret72h,btc_ema_trend_gap_pct:r.btcCm&&r.btcCm.emaTrendGapPct,btc_trend_ret_24h:r.btcCm&&r.btcCm.ret24h,net_60s_usd:Math.round(r.f60.net),net_5m_usd:Math.round(r.f5.net),long_liq_5m_usd:Math.round(r.l5.longLiq||0),short_liq_5m_usd:Math.round(r.l5.shortLiq||0),sweep_side:r.sweepSide||"",reclaim_level:r.reclaimLevel||0,sweep_depth_pct:r.sweepDepthPct||0,largest_usd:Math.round(r.f60.largest||r.f5.largest),streak_side:r.f60.lastSide,streak_count:r.f60.streak,oi_5m_pct:r.d.oi5Pct,oi_15m_pct:r.d.oi15Pct,taker_ratio:r.d.takerRatio,book_spread_pct:r.d.bookSpreadPct,book_imbalance:r.d.bookImbalance,bid_depth_usd:r.d.bidDepthUsd,ask_depth_usd:r.d.askDepthUsd,risks:r.risks,reasons:r.reasons})); }
    function compactEvents(){ return state.events.slice(0,40).map(e=>({symbol:e.symbol,base:base(e.symbol),label:e.label,side:e.side,price:e.price,notional:Math.round(e.notional),time:new Date(e.ts).toLocaleTimeString()})); }
    function trimOld(){ const cut=now()-6*60*1000; for(const map of [state.trades,state.liquidations]){ for(const [sym,list] of map){ while(list.length&&list[0].ts<cut)list.shift(); if(!list.length)map.delete(sym); } } }

    const loggedSignalKeys = new Set();
    function logSignals(){
      const all=rows();
      const follow=all.filter(isAutoSignal);
      const prices={};
      for(const row of all){ if(row.price)prices[row.symbol]=row.price; }
      const toLog=follow.filter(r=>{
        const key=r.symbol+"|"+r.follow+"|"+r.mainSignal+"|"+r.signalVariant+"|"+Math.floor(Date.now()/60000);
        if(loggedSignalKeys.has(key))return false;
        loggedSignalKeys.add(key);
        if(loggedSignalKeys.size>500)loggedSignalKeys.clear();
        return true;
      });
      if(!toLog.length&&Object.keys(prices).length<1)return;
      const positionSymbols=new Set(((state.testnet&&state.testnet.positions)||[]).map(p=>p.symbol));
      const marketRows=all.filter((r,i)=>i<90||positionSymbols.has(r.symbol)||r.follow==="FOLLOW_LONG"||r.follow==="FOLLOW_SHORT").map(r=>({
        symbol:r.symbol, follow:r.follow, signal:r.signal, score:r.score, strategy:r.strategy, strategy_label:r.strategyLabel,
        main_signal:r.mainSignal, signal_variant:r.signalVariant, test_tier:r.testTier||"",
        raw_follow:r.rawFollow, raw_strategy:r.rawStrategy, raw_strategy_label:r.rawStrategyLabel,
        price:r.price,
	        price_1m_pct:r.p1, price_3m_pct:r.p3, price_5m_pct:r.p5,
	        net_60s_usd:Math.round(r.f60.net), net_5m_usd:Math.round(r.f5.net),
	        long_liq_5m_usd:Math.round(r.l5.longLiq||0), short_liq_5m_usd:Math.round(r.l5.shortLiq||0),
	        sweep_side:r.sweepSide||"", reclaim_level:r.reclaimLevel||0, sweep_depth_pct:r.sweepDepthPct||0,
        forecast_side:r.forecast.side, forecast_5m_prob:Number(r.forecast.prob5.toFixed(1)),
        net_edge_pct:Number(r.forecast.netEdgePct.toFixed(3)),
        take_profit_pct:r.forecast.targets?Number(r.forecast.targets.takeProfit.toFixed(3)):null,
        trail_arm_pct:r.forecast.targets?Number(r.forecast.targets.trailArm.toFixed(3)):null,
        funding_rate:r.d.fundingRate,
        book_spread_pct:r.d.bookSpreadPct,
        book_imbalance:r.d.bookImbalance,
        bid_depth_usd:r.d.bidDepthUsd,
        ask_depth_usd:r.d.askDepthUsd,
        channel_high_55:r.cm.high55,
        channel_low_20:r.cm.low20,
        ema_trend_gap_pct:r.cm.emaTrendGapPct,
        trend_ret_24h:r.cm.ret24h,
        trend_ret_72h:r.cm.ret72h,
        btc_ema_trend_gap_pct:r.btcCm&&r.btcCm.emaTrendGapPct,
        btc_trend_ret_24h:r.btcCm&&r.btcCm.ret24h,
        risks:r.risks,
      }));
      const payload=toLog.map(r=>({
        symbol:r.symbol, follow:r.follow, score:r.score, strategy:r.strategy, strategy_label:r.strategyLabel,
        main_signal:r.mainSignal, signal_variant:r.signalVariant, test_tier:r.testTier||"",
        raw_follow:r.rawFollow, raw_strategy:r.rawStrategy, raw_strategy_label:r.rawStrategyLabel,
        raw_forecast_side:r.rawForecast&&r.rawForecast.side,
        raw_forecast_5m_prob:r.rawForecast?Number(r.rawForecast.prob5.toFixed(1)):null,
        price:r.price,
	        price_1m_pct:r.p1, price_3m_pct:r.p3, price_5m_pct:r.p5,
        net_60s_usd:Math.round(r.f60.net), net_5m_usd:Math.round(r.f5.net),
        flow_60s_imbalance:Number(r.f60.imbalance.toFixed(4)),
        flow_5m_imbalance:Number(r.f5.imbalance.toFixed(4)),
        flow_60s_count:r.f60.count,
        flow_5m_count:r.f5.count,
        largest_usd:Math.round(r.f60.largest||r.f5.largest||0),
        streak_side:r.f60.lastSide, streak_count:r.f60.streak,
        volume_spike:r.cm.volSpike, volume_24h_usd:Math.round((r.m&&r.m.quoteVolume)||0),
        channel_high_55:r.cm.high55,
        channel_low_20:r.cm.low20,
        ema_trend_gap_pct:r.cm.emaTrendGapPct,
        trend_ret_24h:r.cm.ret24h,
        trend_ret_72h:r.cm.ret72h,
        btc_ema_trend_gap_pct:r.btcCm&&r.btcCm.emaTrendGapPct,
        btc_trend_ret_24h:r.btcCm&&r.btcCm.ret24h,
        candle_close_location:isNum(r.cm.closeLocation)?Number(r.cm.closeLocation.toFixed(4)):null,
        candle_body_pct:isNum(r.cm.bodyPct)?Number(r.cm.bodyPct.toFixed(4)):null,
        upper_wick_pct:isNum(r.cm.upperWickPct)?Number(r.cm.upperWickPct.toFixed(4)):null,
        lower_wick_pct:isNum(r.cm.lowerWickPct)?Number(r.cm.lowerWickPct.toFixed(4)):null,
        oi_15m_pct:r.d.oi15Pct, taker_ratio:r.d.takerRatio, funding_rate:r.d.fundingRate,
        book_spread_pct:r.d.bookSpreadPct,
        book_imbalance:r.d.bookImbalance,
        bid_depth_usd:r.d.bidDepthUsd,
        ask_depth_usd:r.d.askDepthUsd,
        market_bias:r.mb.bias,
        btc_5m_pct:Number(r.mb.btc.toFixed(4)),
        eth_5m_pct:Number(r.mb.eth.toFixed(4)),
	        liq_long_5m_usd:Math.round(r.l5.longLiq||0),
	        liq_short_5m_usd:Math.round(r.l5.shortLiq||0),
	        long_liq_5m_usd:Math.round(r.l5.longLiq||0),
	        short_liq_5m_usd:Math.round(r.l5.shortLiq||0),
	        sweep_side:r.sweepSide||"",
	        reclaim_level:r.reclaimLevel||0,
	        sweep_depth_pct:r.sweepDepthPct||0,
        forecast_side:r.forecast.side, forecast_5m_prob:Number(r.forecast.prob5.toFixed(1)),
        net_edge_pct:Number(r.forecast.netEdgePct.toFixed(3)),
        take_profit_pct:r.forecast.targets?Number(r.forecast.targets.takeProfit.toFixed(3)):null,
        trail_arm_pct:r.forecast.targets?Number(r.forecast.targets.trailArm.toFixed(3)):null,
        required_cost_pct:Number(r.cost.requiredPct.toFixed(3)),
        funding_cost_pct:Number(r.cost.fundingPct.toFixed(4)),
        risks:r.risks, reasons:r.reasons,
      }));
      fetch("/api/signal/log",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rows:payload,prices,market_rows:marketRows})}).catch(()=>{});
    }

    function esc(value){ return String(value??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m])); }
    function usdt(value){ return "$"+Number(value||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); }
    function drawPnlChart(points){
      const canvas=document.getElementById("pnlChart");
      const left=document.getElementById("chartLeft"), right=document.getElementById("chartRight");
      if(!canvas)return;
      const rect=canvas.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
      canvas.width=Math.max(1,Math.floor(rect.width*ratio)); canvas.height=Math.max(1,Math.floor(rect.height*ratio));
      const ctx=canvas.getContext("2d"); ctx.setTransform(ratio,0,0,ratio,0,0);
      const w=rect.width, h=rect.height, padL=46, padR=12, padT=16, padB=26;
      ctx.clearRect(0,0,w,h); ctx.fillStyle="#fff"; ctx.fillRect(0,0,w,h);
      if(!points||points.length<2){
        ctx.fillStyle="#68758a"; ctx.font="12px Inter, sans-serif"; ctx.fillText("等待收益数据",padL,Math.floor(h/2));
        if(left)left.textContent="等待数据"; if(right){ right.textContent="--"; right.className=""; }
        return;
      }
      const vals=points.map(p=>Number(p.equity||0)).filter(Number.isFinite);
      const minRaw=Math.min(...vals), maxRaw=Math.max(...vals), padVal=Math.max((maxRaw-minRaw)*0.16,Math.max(maxRaw,1)*0.001);
      const min=minRaw-padVal, max=maxRaw+padVal, span=Math.max(max-min,1e-9);
      const first=vals[0], last=vals[vals.length-1];
      const x=i=>padL+(w-padL-padR)*i/Math.max(1,points.length-1);
      const y=v=>padT+(max-v)/span*(h-padT-padB);
      ctx.strokeStyle="#edf1f5"; ctx.lineWidth=1;
      ctx.fillStyle="#68758a"; ctx.font="10px Inter, sans-serif";
      for(let i=0;i<5;i++){ const v=min+(max-min)*i/4, yy=y(v); ctx.beginPath(); ctx.moveTo(padL,yy); ctx.lineTo(w-padR,yy); ctx.stroke(); ctx.fillText(usdt(v),6,yy+3); }
      const color=last>=first?"#087f5b":"#c92a2a";
      const grad=ctx.createLinearGradient(0,padT,0,h-padB); grad.addColorStop(0,last>=first?"rgba(8,127,91,.18)":"rgba(201,42,42,.18)"); grad.addColorStop(1,"rgba(255,255,255,0)");
      ctx.beginPath(); points.forEach((p,i)=>{ const xx=x(i), yy=y(Number(p.equity||0)); if(i)ctx.lineTo(xx,yy); else ctx.moveTo(xx,yy); });
      ctx.lineTo(x(points.length-1),h-padB); ctx.lineTo(x(0),h-padB); ctx.closePath(); ctx.fillStyle=grad; ctx.fill();
      ctx.strokeStyle=color; ctx.lineWidth=2; ctx.beginPath();
      points.forEach((p,i)=>{ const xx=x(i), yy=y(Number(p.equity||0)); if(i)ctx.lineTo(xx,yy); else ctx.moveTo(xx,yy); });
      ctx.stroke();
      ctx.fillStyle=color; vals.forEach((v,i)=>{ if(i===vals.length-1||i===0){ ctx.beginPath(); ctx.arc(x(i),y(v),3,0,Math.PI*2); ctx.fill(); } });
      const pnl=last-first, peak=Math.max(...vals), dd=last-peak;
      if(left)left.textContent=`起始 ${usdt(first)} · 当前 ${usdt(last)} · 回撤 ${dd<0?usdt(dd):"$0.00"}`;
      if(right){ right.textContent=`收益 ${pnl>=0?"+":""}${usdt(pnl)}`; right.className=pnl>=0?"up":"down"; }
    }
    function drawTradeStatsChart(stats){
      const canvas=document.getElementById("tradeStatsChart");
      const left=document.getElementById("tradeStatsLeft"), right=document.getElementById("tradeStatsRight");
      if(!canvas)return;
      const rect=canvas.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
      canvas.width=Math.max(1,Math.floor(rect.width*ratio)); canvas.height=Math.max(1,Math.floor(rect.height*ratio));
      const ctx=canvas.getContext("2d"); ctx.setTransform(ratio,0,0,ratio,0,0);
      const w=rect.width,h=rect.height,padL=36,padR=12,padT=14,padB=24;
      ctx.clearRect(0,0,w,h); ctx.fillStyle="#fff"; ctx.fillRect(0,0,w,h);
      const recent=(stats&&stats.recent||[]).slice(-40), vals=recent.map(x=>Number(x.realized||0));
      if(!vals.length){
        ctx.fillStyle="#68758a"; ctx.font="12px Inter, sans-serif"; ctx.fillText("等待平仓交易",padL,Math.floor(h/2));
        if(left)left.textContent="等待交易"; if(right)right.textContent="--";
        return;
      }
      const cum=[]; vals.reduce((s,v,i)=>{ cum[i]=s+v; return cum[i]; },0);
      const all=[...vals,...cum,0], min=Math.min(...all), max=Math.max(...all), span=Math.max(max-min,0.01);
      const x=i=>padL+(w-padL-padR)*(i+.5)/vals.length;
      const y=v=>padT+(max-v)/span*(h-padT-padB);
      const zeroY=y(0);
      ctx.strokeStyle="#edf1f5"; ctx.lineWidth=1;
      for(let i=0;i<4;i++){ const yy=padT+(h-padT-padB)*i/3; ctx.beginPath(); ctx.moveTo(padL,yy); ctx.lineTo(w-padR,yy); ctx.stroke(); }
      ctx.strokeStyle="#a8b2c1"; ctx.beginPath(); ctx.moveTo(padL,zeroY); ctx.lineTo(w-padR,zeroY); ctx.stroke();
      const barW=Math.max(3,(w-padL-padR)/vals.length*.62);
      vals.forEach((v,i)=>{ const yy=y(v); ctx.fillStyle=v>=0?"rgba(8,127,91,.78)":"rgba(201,42,42,.72)"; ctx.fillRect(x(i)-barW/2,Math.min(yy,zeroY),barW,Math.max(2,Math.abs(zeroY-yy))); });
      ctx.strokeStyle="#162033"; ctx.lineWidth=1.8; ctx.beginPath();
      cum.forEach((v,i)=>{ const xx=x(i), yy=y(v); if(i)ctx.lineTo(xx,yy); else ctx.moveTo(xx,yy); }); ctx.stroke();
      const net=Number(stats.net||0), pf=Number(stats.profit_factor||0);
      const recentWins=recent.filter(x=>Number(x.realized||0)>0).length;
      const recentLosses=recent.filter(x=>Number(x.realized||0)<0).length;
      if(left)left.textContent=`最近 ${vals.length} 笔 · 胜 ${recentWins} / 负 ${recentLosses}`;
      if(right){ right.textContent=`净利 ${net>=0?"+":""}${usdt(net)} · 手续费 ${usdt(stats.fees||0)} · PF ${pf?pf.toFixed(2):"--"}`; right.className=net>=0?"up":"down"; }
    }
    function updateExecutionModeUi(mode){
      const isPaper=(mode||"paper")==="paper";
      document.getElementById("apiHelp").textContent=isPaper
        ?"本地模拟盘不需要 API Key。打开 FOLLOW 自动下单后，策略信号会在本机模拟成交。默认本金 $100，每仓保证金 $10，4x，最多 10 仓。"
        :"Binance Testnet 需要 Futures Testnet / Demo Trading 的 API Key 和 Secret，不要填实盘 Key。";
      document.getElementById("tradeModeNote").textContent=isPaper?"本地模拟盘收益测试":"Binance Futures Testnet";
      document.getElementById("testnetKey").disabled=false;
      document.getElementById("testnetSecret").disabled=false;
    }
    function eventTypeText(type,message){
      const text=String(message||"");
      if(type==="partial"||text.includes("半仓"))return "半仓";
      if(type==="open"||text.includes("自动下单"))return text.includes("加仓")?"加仓":"开仓";
      if(type==="add"||text.includes("加仓"))return "加仓";
      if(type==="close"||text.includes("平仓")||text.includes("已实现"))return "平仓";
      if(type==="skip"||text.includes("跳过"))return "跳过";
      if(type==="error"||text.includes("失败"))return "失败";
      return "事件";
    }
    function eventRealized(e){
      if(e.realized!==null&&e.realized!==undefined)return Number(e.realized);
      const order=e.order_json||e.order||{};
      if(order&&order.realizedPnl!==undefined)return Number(order.realizedPnl||0);
      const match=String(e.message||"").match(/已实现 ([+-]?\d+(?:\.\d+)?) USDT/);
      return match?Number(match[1]):null;
    }
    function eventFee(e){
      const close=e.close||{};
      if(close.fee!==null&&close.fee!==undefined)return Number(close.fee||0);
      const extra=e.extra_json||{};
      if(extra.close&&extra.close.fee!==undefined)return Number(extra.close.fee||0);
      const order=e.order_json||e.order||{};
      const entry=Number(order.entryCost||0), exit=Number(order.exitCost||0);
      return entry||exit?entry+exit:null;
    }
    function renderTradeEvent(e){
      const type=eventTypeText(e.event_type,e.message);
      if(!["开仓","平仓","半仓","加仓"].includes(type))return "";
      const realized=eventRealized(e);
      const fee=eventFee(e);
      const isClose=type==="平仓"||type==="半仓";
      const win=realized!==null&&realized>=0;
      const cls=`trade-log-row ${type==="开仓"?"open":""} ${isClose?"close":""} ${isClose?(win?"win":"loss"):""}`;
      const symbol=e.symbol?String(e.symbol).replace("USDT",""):"--";
      const meta=[
        e.strategy_label||"",
        e.grade?e.grade+"级":"",
        e.margin?Number(e.margin).toFixed(2)+"U保证金":"",
        fee!==null&&isClose?"手续费 "+fee.toFixed(4)+"U":"",
        e.main_signal||"",
      ].filter(Boolean).join(" · ");
      const pnl=realized===null?"":(realized>=0?"+":"")+realized.toFixed(2)+"U";
      const pnlCls=realized===null?"":(realized>=0?"up":"down");
      return `<div class="${cls}">
        <div class="trade-log-time">${new Date(e.ts).toLocaleTimeString()}</div>
        <div class="trade-log-type">${type}</div>
        <div class="trade-log-main"><strong>${esc(symbol)}</strong> · ${esc(e.message||"")}
          ${meta?`<div class="trade-log-meta">${esc(meta)}</div>`:""}
        </div>
        <div class="trade-log-pnl ${pnlCls}">${pnl}</div>
      </div>`;
    }
    function renderBreakdownCard(title,item,labelKey){
      if(!item)return `<div class="trade-breakdown-card"><div class="trade-breakdown-title">${esc(title)}</div><div class="trade-breakdown-main">--</div><div class="trade-breakdown-sub">暂无数据</div></div>`;
      const net=Number(item.net||0), count=Number(item.count||0), wins=Number(item.wins||0), losses=Number(item.losses||0);
      const label=item[labelKey]||"--";
      return `<div class="trade-breakdown-card">
        <div class="trade-breakdown-title">${esc(title)}</div>
        <div class="trade-breakdown-main">${esc(label)} · <span class="${net>=0?"up":"down"}">${net>=0?"+":""}${usdt(net)}</span></div>
        <div class="trade-breakdown-sub">${count} 笔 · 胜 ${wins} / 负 ${losses} · 胜率 ${count?Number(item.win_rate||0).toFixed(1):"--"}%</div>
      </div>`;
    }
    function renderTradeBreakdown(stats){
      const box=document.getElementById("tradeBreakdown");
      if(!box)return;
      const byStrategy=(stats.by_strategy||[]).slice().sort((a,b)=>Number(a.net||0)-Number(b.net||0));
      const byGrade=(stats.by_grade||[]).slice().sort((a,b)=>Number(a.net||0)-Number(b.net||0));
      const byReason=(stats.by_reason||[]).slice().sort((a,b)=>Number(a.net||0)-Number(b.net||0));
      box.innerHTML=[
        renderBreakdownCard("亏损最大信号",byStrategy[0],"label"),
        renderBreakdownCard("亏损最大等级",byGrade[0],"grade"),
        renderBreakdownCard("亏损最大原因",byReason[0],"reason"),
        renderBreakdownCard("最好信号",byStrategy[byStrategy.length-1],"label"),
      ].join("");
    }
    function renderFullTradeTable(stats){
      const body=document.getElementById("fullTradeBody");
      const note=document.getElementById("fullTradeNote");
      if(!body)return;
      const closes=(stats.recent||[]).slice(-200).reverse();
      if(note)note.textContent=`显示 ${closes.length} / ${stats.count||0} 笔平仓交易`;
      if(!closes.length){
        body.innerHTML='<tr><td colspan="9">等待平仓交易。</td></tr>';
        renderTradeBreakdown(stats);
        return;
      }
      body.innerHTML=closes.map((item,idx)=>{
        const realized=Number(item.realized||0);
        const cls=realized>=0?"win":"loss";
        const symbol=(item.symbol||"--").replace("USDT","");
        const margin=item.margin!==null&&item.margin!==undefined?Number(item.margin||0).toFixed(2)+"U":"--";
        const fee=item.fee!==null&&item.fee!==undefined?Number(item.fee||0).toFixed(4)+"U":"--";
        return `<tr class="trade-detail-row ${cls}">
          <td>${idx+1}</td>
          <td>${new Date(item.ts).toLocaleTimeString()}</td>
          <td><strong>${esc(symbol)}</strong><div class="small">${esc(item.symbol||"")}</div></td>
          <td>${esc(item.strategy_label||item.strategy||"--")}<div class="small">${esc(item.main_signal||"")}</div></td>
          <td>${esc(item.grade||"--")}</td>
          <td>${margin}</td>
          <td>${fee}</td>
          <td class="${realized>=0?"up":"down"}">${realized>=0?"+":""}${usdt(realized)}</td>
          <td>${esc(item.reason||"--")}</td>
        </tr>`;
      }).join("");
      renderTradeBreakdown(stats);
    }
    function syncTradeForm(data, force=false){
      const active=document.activeElement;
      const editing=!!(active&&active.closest&&active.closest(".trade-form,.trade-actions"));
      if(!force&&(state.tradeFormDirty||state.savingTradeConfig||editing))return;
      const mode=(data.execution_mode||"paper")==="paper"?"paper":"binance_testnet";
      document.getElementById("executionMode").value=mode;
      document.getElementById("autoTradeToggle").checked=!!data.auto_trade;
      document.getElementById("testnetKey").placeholder=data.has_api_key?"已保存；留空不修改":"第一次必填；保存后不会显示";
      document.getElementById("testnetSecret").placeholder=data.has_api_secret?"已保存；留空不修改":"第一次必填；以后不改可留空";
      document.getElementById("orderUsdt").value=data.order_usdt||10;
      document.getElementById("tradeLeverage").value=data.leverage||4;
      document.getElementById("maxPositions").value=data.max_positions||10;
      document.getElementById("autoCloseMinutes").value=data.auto_close_minutes||5;
      document.getElementById("strategyMode").value="current";
      document.getElementById("strategyModeLabel").value=data.strategy_mode_label||"当前策略：4h突破趋势";
      updateExecutionModeUi(mode);
    }
    function renderTestnetStatus(data, forceForm=false){
      state.testnet=data;
      const note=document.getElementById("tradeConnNote");
      const isPaper=(data.execution_mode||"paper")==="paper";
      note.textContent=data.account_ok?`${isPaper?"本地模拟盘已连接":"Binance Testnet 已连接"} · ${data.strategy_mode_label||"主信号组合"}`:(data.message||"未配置模拟盘 API");
      syncTradeForm(data, forceForm);
      document.getElementById("tradeEquity").textContent=data.account_ok?usdt(data.equity):"--";
      document.getElementById("tradePnl").textContent=data.account_ok?usdt(data.unrealized):"--";
      document.getElementById("tradePnl").className="value "+(Number(data.unrealized||0)>=0?"up":"down");
      document.getElementById("tradePositions").textContent=data.account_ok?(data.positions||[]).length:"--";
      const log=document.getElementById("tradeLog");
      const events=(data.events||[]).slice(0,200);
      log.innerHTML=events.length?events.map(renderTradeEvent).join(""):`<div class="trade-log-row"><div></div><div></div><div class="trade-log-main">${esc(data.message||"等待模拟盘连接。")}</div><div></div></div>`;
      const stats=data.trade_stats||{};
      document.getElementById("statTrades").textContent=stats.count||0;
      document.getElementById("statNet").textContent=(Number(stats.net||0)>=0?"+":"")+usdt(stats.net||0);
      document.getElementById("statNet").className="value "+(Number(stats.net||0)>=0?"up":"down");
      document.getElementById("statWinRate").textContent=(stats.count?Number(stats.win_rate||0).toFixed(1):"--")+"%";
      document.getElementById("statPF").textContent=stats.count?(Number(stats.profit_factor||0).toFixed(2)):"--";
      const byStrategy=document.getElementById("tradeStrategyStats");
      if(byStrategy){
        const rows=(stats.by_strategy||[]).slice(0,5);
        byStrategy.innerHTML=rows.length?rows.map(item=>{
          const net=Number(item.net||0), pf=Number(item.profit_factor||0);
          return `${esc(item.label||item.strategy)} <strong>${item.count||0}</strong> 笔　净利 <span class="${net>=0?"up":"down"}">${net>=0?"+":""}${usdt(net)}</span>　胜率 ${Number(item.win_rate||0).toFixed(1)}%　PF ${pf?pf.toFixed(2):"--"}`;
        }).join("<br>"):"等待主信号交易统计";
      }
      drawPnlChart(data.equity_curve||[]);
      drawTradeStatsChart(stats);
      renderFullTradeTable(stats);
    }
    async function loadTestnetStatus(){
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),8000);
      try{
        const res=await fetch("/api/testnet/status",{signal:controller.signal,cache:"no-store"});
        if(!res.ok)throw new Error("HTTP "+res.status);
        renderTestnetStatus(await res.json());
      }
      catch(err){
        document.getElementById("tradeConnNote").textContent=(err&&err.name==="AbortError")?"模拟盘状态超时，稍后自动重试":"模拟盘状态读取失败，稍后自动重试";
        drawPnlChart([]);
      }
      finally{ clearTimeout(timeout); }
    }
    async function saveTestnetConfig(){
      const payload={
        execution_mode:document.getElementById("executionMode").value,
        auto_trade:document.getElementById("autoTradeToggle").checked,
        order_usdt:Number(document.getElementById("orderUsdt").value||10),
        leverage:Number(document.getElementById("tradeLeverage").value||4),
        max_positions:Number(document.getElementById("maxPositions").value||10),
        auto_close_minutes:Number(document.getElementById("autoCloseMinutes").value||5),
        strategy_mode:"current",
      };
      const key=document.getElementById("testnetKey").value.trim();
      const secret=document.getElementById("testnetSecret").value.trim();
      if(key)payload.api_key=key;
      if(secret)payload.api_secret=secret;
      const btn=document.getElementById("saveTradeCfg");
      state.savingTradeConfig=true;
      btn.disabled=true; btn.textContent="保存中";
      try{
        const res=await fetch("/api/testnet/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
        const data=await res.json();
        state.tradeFormDirty=false;
        renderTestnetStatus(data,true);
        document.getElementById("testnetKey").value="";
        document.getElementById("testnetSecret").value="";
      }catch(err){ document.getElementById("tradeConnNote").textContent="保存失败："+err; }
      finally{ state.savingTradeConfig=false; btn.disabled=false; btn.textContent="保存连接"; }
    }
    function markTradeFormDirty(){
      state.tradeFormDirty=true;
    }
    function handleExecutionModeChange(){
      markTradeFormDirty();
      updateExecutionModeUi(document.getElementById("executionMode").value);
    }

    function loadSignalStats(){
      fetch("/api/signal/stats").then(r=>r.json()).then(data=>{
        const el=document.getElementById("statsPanel");
        if(!el)return;
        if(data.message){ el.innerHTML="<strong>信号统计</strong>　"+data.message; return; }
        const fmt=v=>(v===null||v===undefined)?"--":v;
        const fmtPct=v=>{
          if(v===null||v===undefined)return "--";
          const cls=v>=0?"win":"lose";
          return '<span class="'+cls+'">'+(v>0?"+":"")+v+"%</span>";
        };
        let html="<strong>信号统计</strong>　已回填 "+data.filled+" / "+data.total+" 条信号<br><br>";
        if(data.long)html+="多头信号 <strong>"+data.long.count+"</strong> 条　5m胜率 <strong>"+fmt(data.long.winrate_5m)+"%</strong>　方向均收益 "+fmtPct(data.long.avg_ret_5m)+"　PF "+fmt(data.long.profit_factor_5m)+"<br>";
        if(data.short)html+="空头信号 <strong>"+data.short.count+"</strong> 条　5m胜率 <strong>"+fmt(data.short.winrate_5m)+"%</strong>　方向均收益 "+fmtPct(data.short.avg_ret_5m)+"　PF "+fmt(data.short.profit_factor_5m)+"<br>";
        if(data.groups&&data.groups.length){
          html+="<br><strong>主信号表现</strong><br>";
          for(const item of data.groups.slice(0,6)){
            const mark=item.reliable?"":"<span class=\"small\">样本少</span>";
            html+=esc(item.label)+" <span class=\"small\">"+esc(item.variant)+"</span> <strong>"+item.count+"</strong> 条　1m "+fmtPct(item.avg_ret_1m)+"　3m "+fmtPct(item.avg_ret_3m)+"　5m "+fmtPct(item.expect_5m)+"　PF "+fmt(item.profit_factor_5m)+" "+mark+"<br>";
          }
        }
        if(!data.long&&!data.short)html+="暂无已回填数据，等待信号触发后 5 分钟开始显示统计。";
        el.innerHTML=html;
      }).catch(()=>{});
    }

    function closeSockets(){ for(const ws of state.sockets){ try{ws.close();}catch(_){}} state.sockets=[]; state.priceConnected=false; state.tradeConnected=false; state.liqConnected=false; state.priceError=""; state.tradeError=""; state.liqError=""; state.priceMessages=0; state.tradeMessages=0; state.liqMessages=0; }
    function connectPrice(runId,index=0){ const host=runtime.BINANCE_WS_BASES[index%runtime.BINANCE_WS_BASES.length]; const ws=new WebSocket(`${host}/ws/!ticker@arr`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectPrice(runId,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.priceError=`价格流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.priceConnected=true; state.priceError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.priceConnected=false; setTimeout(()=>{ if(runId===state.runId)connectPrice(runId,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.priceError=`价格流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.priceMessages++; const arr=JSON.parse(e.data); const set=activeSet(), ts=Date.now(); for(const item of arr){ if(!set.has(item.s))continue; const p=Number(item.c||0); if(p>0)rememberPrice(item.s,p,ts); const prev=state.marketMeta.get(item.s)||{}; state.marketMeta.set(item.s,{...prev,symbol:item.s,quoteVolume:Number(item.q||prev.quoteVolume||0),changePct:Number(item.P||prev.changePct||0),lastPrice:p}); } }; }
    function connectTrades(runId){ const syms=activeSymbols(); for(let i=0;i<syms.length;i+=runtime.TRADE_STREAM_CHUNK_SIZE){ connectTradeChunk(runId,syms.slice(i,i+runtime.TRADE_STREAM_CHUNK_SIZE),0); } }
    function connectTradeChunk(runId,syms,index){ if(!syms.length)return; const host=runtime.BINANCE_WS_BASES[index%runtime.BINANCE_WS_BASES.length]; const streams=syms.map(s=>s.toLowerCase()+"@aggTrade").join("/"); const ws=new WebSocket(`${host}/stream?streams=${streams}`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectTradeChunk(runId,syms,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.tradeError=`大单流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.tradeConnected=true; state.tradeError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.tradeConnected=false; setTimeout(()=>{ if(runId===state.runId)connectTradeChunk(runId,syms,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.tradeError=`大单流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.tradeMessages++; const data=JSON.parse(e.data).data||{}; const symbol=data.s; if(!activeSet().has(symbol))return; const p=Number(data.p||0), q=Number(data.q||0), notional=p*q, threshold=tradeThreshold(symbol); if(p>0)rememberPrice(symbol,p,data.T||Date.now()); if(notional<threshold)return; const side=data.m?"SELL":"BUY"; const row={symbol,side,ts:data.T||Date.now(),price:p,qty:q,notional,threshold}; ensureList(state.trades,symbol).push(row); addEvent({...row,label:side==="BUY"?"主动买":"主动卖"}); }; }
    function reconnectTradesOnly(){ state.runId++; const runId=state.runId; for(const ws of state.sockets){ try{ws.close();}catch(_){} } state.sockets=[]; connectPrice(runId); connectTrades(runId); connectLiquidations(runId); }
    function connectLiquidations(runId,index=0){ const host=runtime.BINANCE_WS_BASES[index%runtime.BINANCE_WS_BASES.length]; const ws=new WebSocket(`${host}/ws/!forceOrder@arr`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectLiquidations(runId,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.liqError=`爆仓流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.liqConnected=true; state.liqError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.liqConnected=false; setTimeout(()=>{ if(runId===state.runId)connectLiquidations(runId,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.liqError=`爆仓流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.liqMessages++; const order=(JSON.parse(e.data)||{}).o||{}; const symbol=order.s; if(!activeSet().has(symbol))return; const p=Number(order.ap||order.p||0), q=Number(order.q||0), notional=p*q, threshold=tradeThreshold(symbol); if(notional<threshold)return; const side=order.S||""; const row={symbol,side,ts:order.T||Date.now(),price:p,qty:q,notional,threshold}; ensureList(state.liquidations,symbol).push(row); addEvent({...row,label:side==="BUY"?"空爆":"多爆"}); }; }
    async function start(){ state.runId++; const runId=state.runId; closeSockets(); await refreshMarketUniverse(); connectPrice(runId); connectTrades(runId); connectLiquidations(runId); fetchKlines(); fetchDerivatives(); if(!state.marketTimer)state.marketTimer=setInterval(refreshMarketUniverse,60*1000); if(!state.derivativesTimer)state.derivativesTimer=setInterval(fetchDerivatives,45*1000); if(!state.klineTimer)state.klineTimer=setInterval(fetchKlines,60*1000); render(); renderEvents(); }
    document.getElementById("refresh").addEventListener("click",start);
    document.getElementById("saveTradeCfg").addEventListener("click",saveTestnetConfig);
    document.getElementById("executionMode").addEventListener("change",handleExecutionModeChange);
    document.getElementById("autoTradeToggle").addEventListener("change",()=>{ markTradeFormDirty(); saveTestnetConfig(); });
    document.getElementById("strategyMode").addEventListener("change",()=>{ markTradeFormDirty(); saveTestnetConfig(); });
    for(const id of ["testnetKey","testnetSecret","orderUsdt","tradeLeverage","maxPositions","autoCloseMinutes","strategyMode"]){
      document.getElementById(id).addEventListener("input",markTradeFormDirty);
    }
    const oldRadarBody=document.getElementById("radarBody");
    if(oldRadarBody)oldRadarBody.addEventListener("click",e=>{
      const btn=e.target.closest(".detail-btn");
      if(!btn)return;
      const symbol=btn.dataset.symbol;
      if(state.expanded.has(symbol))state.expanded.delete(symbol); else state.expanded.add(symbol);
      render();
    });
    document.getElementById("search").addEventListener("input",render);
    document.getElementById("filters").addEventListener("click",e=>{ if(!e.target.dataset.filter)return; state.activeFilter=e.target.dataset.filter; document.querySelectorAll("#filters button").forEach(btn=>btn.classList.toggle("active",btn.dataset.filter===state.activeFilter)); render(); });
    setInterval(()=>{ trimOld(); render(); renderEvents(); logSignals(); },1000);
    setInterval(loadSignalStats,2*60*1000);
    loadTestnetStatus();
    setInterval(loadTestnetStatus,5000);
    setTimeout(loadSignalStats,5000);
    window.addEventListener("resize",()=>{ drawPnlChart((state.testnet&&state.testnet.equity_curve)||[]); drawTradeStatsChart((state.testnet&&state.testnet.trade_stats)||{}); });
    start();
  </script>
</body>
</html>
"""


def register_routes(app, runtime) -> None:



    @app.route("/")
    def index() -> str:
        html = HTML.replace("__SEED_SYMBOLS__", json.dumps(runtime.SEED_SYMBOLS))
        html = html.replace("__MAX_STREAM_SYMBOLS__", json.dumps(runtime.MAX_STREAM_SYMBOLS))
        html = html.replace("__TRADE_STREAM_CHUNK_SIZE__", json.dumps(runtime.TRADE_STREAM_CHUNK_SIZE))
        html = html.replace("__LARGE_TRADE_USD__", json.dumps(runtime.LARGE_TRADE_USD))
        html = html.replace("__MIN_DYNAMIC_TRADE_USD__", json.dumps(runtime.MIN_DYNAMIC_TRADE_USD))
        html = html.replace("__TAKER_FEE_BPS__", json.dumps(runtime.TAKER_FEE_BPS))
        html = html.replace("__SLIPPAGE_BPS__", json.dumps(runtime.SLIPPAGE_BPS))
        html = html.replace("__SAFETY_EDGE_BPS__", json.dumps(runtime.SAFETY_EDGE_BPS))
        html = html.replace("__HOLD_MINUTES__", json.dumps(runtime.HOLD_MINUTES))
        html = html.replace("__BINANCE_WS_BASES__", json.dumps(runtime.BINANCE_WS_BASES))
        html = html.replace("__BINANCE_REST_BASES__", json.dumps(runtime.BINANCE_REST_BASES))
        return render_template_string(html)


    @app.route("/health")
    def health():
        return jsonify({
            "ok": True,
            "mode": "wide_money_flow_radar",
            "seed_symbols": runtime.SEED_SYMBOLS,
            "max_stream_symbols": runtime.MAX_STREAM_SYMBOLS,
            "trade_stream_chunk_size": runtime.TRADE_STREAM_CHUNK_SIZE,
            "large_trade_usd": runtime.LARGE_TRADE_USD,
            "min_dynamic_trade_usd": runtime.MIN_DYNAMIC_TRADE_USD,
            "taker_fee_bps": runtime.TAKER_FEE_BPS,
            "slippage_bps": runtime.SLIPPAGE_BPS,
            "safety_edge_bps": runtime.SAFETY_EDGE_BPS,
            "hold_minutes": runtime.HOLD_MINUTES,
            "binance_ws_bases": runtime.BINANCE_WS_BASES,
            "binance_rest_bases": runtime.BINANCE_REST_BASES,
            "binance_testnet_rest": runtime.BINANCE_TESTNET_REST,
        })


    @app.post("/api/signal/log")
    def signal_log():
        payload = request.get_json(silent=True) or {}
        rows = payload.get("rows") or []
        prices = payload.get("prices") or {}
        market_rows = payload.get("market_rows") or []
        for row in rows:
            log_signal(row)
        fill_prices(prices)
        runtime._auto_trade_signals(rows, prices, market_rows)
        return jsonify({"ok": True, "logged": len(rows)})


    @app.get("/api/signal/stats")
    def signal_stats():
        return jsonify(get_stats())


    @app.get("/api/signal/recent")
    def signal_recent():
        limit = min(int(request.args.get("limit", 50)), 200)
        return jsonify(get_recent(limit))


    @app.get("/api/testnet/status")
    def testnet_status():
        return jsonify(runtime._public_testnet_status())


    @app.get("/api/testnet/events")
    def testnet_events():
        limit = min(int(request.args.get("limit", 500)), 5000)
        return jsonify(get_trade_events(limit))


    @app.get("/api/testnet/closes")
    def testnet_closes():
        limit = min(int(request.args.get("limit", 500)), 5000)
        return jsonify(get_trade_closes(limit))


    @app.post("/api/testnet/config")
    def testnet_config():
        payload = request.get_json(silent=True) or {}
        with runtime._trade_lock:
            prev_mode = str(runtime._testnet_config.get("execution_mode") or "paper")
            if "api_key" in payload:
                runtime._testnet_config["api_key"] = str(payload.get("api_key") or "").strip()
            if payload.get("api_secret"):
                runtime._testnet_config["api_secret"] = str(payload.get("api_secret") or "").strip()
            if "execution_mode" in payload:
                mode = str(payload.get("execution_mode") or "paper").strip()
                runtime._testnet_config["execution_mode"] = "binance_testnet" if mode == "binance_testnet" else "paper"
                if runtime._testnet_config["execution_mode"] != prev_mode:
                    runtime._equity_curve.clear()
            if "auto_trade" in payload:
                runtime._testnet_config["auto_trade"] = bool(payload.get("auto_trade"))
            if "strategy_mode" in payload:
                mode = str(payload.get("strategy_mode") or "primary").strip()
                next_mode = "current" if mode in runtime.STRATEGY_MODE_MAP or mode in runtime.LEGACY_STRATEGY_MODE_ALIASES else "current"
                if next_mode != runtime._strategy_mode():
                    runtime._entry_candidates.clear()
                runtime._testnet_config["strategy_mode"] = next_mode
            for key, cast, default in [
                ("order_usdt", float, runtime.TESTNET_ORDER_USDT),
                ("leverage", int, runtime.TESTNET_LEVERAGE),
                ("max_positions", int, runtime.TESTNET_MAX_POSITIONS),
                ("cooldown_seconds", int, runtime.TESTNET_COOLDOWN_SECONDS),
                ("auto_close_minutes", float, runtime.TESTNET_AUTO_CLOSE_MINUTES),
            ]:
                if key in payload:
                    try:
                        floor = 0 if key == "cooldown_seconds" else 1
                        runtime._testnet_config[key] = max(floor, cast(payload.get(key)))
                    except (TypeError, ValueError):
                        runtime._testnet_config[key] = default
            if runtime._is_paper_mode():
                runtime._event(f"本地模拟盘配置已更新 · 当前策略：{runtime._strategy_mode_label()}", "info")
            elif runtime._testnet_config.get("api_key") and runtime._testnet_config.get("api_secret"):
                runtime._event(f"模拟盘配置已更新 · 当前策略：{runtime._strategy_mode_label()}", "info")
            else:
                runtime._event("模拟盘配置未完整：第一次连接需要 API Key 和 Secret", "warn")
        return jsonify(runtime._public_testnet_status())


    @app.post("/api/ai/analyze")
    def ai_analyze():
        payload = request.get_json(silent=True) or {}
        fallback = runtime.rule_analysis(payload)
        analysis, mode = runtime.call_ai(payload, fallback)
        return jsonify({"analysis": analysis, "mode": mode, "model": runtime.AI_MODEL if mode == "ai" else None})
