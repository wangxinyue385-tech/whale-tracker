from __future__ import annotations

import json
import os

from flask import Flask, jsonify, render_template_string


app = Flask(__name__)

DEFAULT_WATCH_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
    "TONUSDT",
    "TRXUSDT",
    "NEARUSDT",
    "APTUSDT",
    "OPUSDT",
    "ARBUSDT",
    "SEIUSDT",
    "INJUSDT",
    "RUNEUSDT",
    "DOTUSDT",
    "UNIUSDT",
    "AAVEUSDT",
    "FILUSDT",
    "LTCUSDT",
    "WIFUSDT",
    "ORDIUSDT",
    "ENAUSDT",
    "1000PEPEUSDT",
    "1000SHIBUSDT",
    "1000BONKUSDT",
]

WATCH_SYMBOLS = [
    symbol.strip().upper()
    for symbol in os.environ.get("WATCH_SYMBOLS", ",".join(DEFAULT_WATCH_SYMBOLS)).split(",")
    if symbol.strip()
]
LARGE_TRADE_USD = float(os.environ.get("LARGE_TRADE_USD", "50000"))
BINANCE_WS = os.environ.get("BINANCE_WS", "wss://fstream.binance.com")
BINANCE_REST = os.environ.get("BINANCE_REST", "https://fapi.binance.com")


HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Binance Flow Radar</title>
  <style>
    :root {
      --bg: #eef2f6;
      --surface: #fff;
      --surface2: #f8fafc;
      --line: #d8e0ea;
      --text: #162033;
      --muted: #68758a;
      --ink: #0f172a;
      --green: #087f5b;
      --green-bg: #e9f8f1;
      --red: #c92a2a;
      --red-bg: #fff0f0;
      --amber: #a16207;
      --amber-bg: #fff8df;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input { font: inherit; }
    .topbar {
      height: 58px;
      padding: 0 22px;
      background: rgba(255, 255, 255, 0.96);
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 850; }
    .brand-mark {
      width: 30px;
      height: 30px;
      border-radius: 8px;
      background: var(--ink);
      color: #fff;
      display: grid;
      place-items: center;
      font-size: 13px;
      font-weight: 900;
    }
    .statusbar { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #a8b2c1; }
    .dot.ok { background: var(--green); box-shadow: 0 0 0 3px rgba(8, 127, 91, .12); }
    .dot.bad { background: var(--red); box-shadow: 0 0 0 3px rgba(201, 42, 42, .12); }
    .page { max-width: 1500px; margin: 0 auto; padding: 16px 20px 24px; }
    .controls {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }
    .search {
      width: 100%;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      padding: 10px 12px;
      color: var(--text);
      outline: none;
    }
    .segmented {
      display: flex;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .segmented button {
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      padding: 9px 12px;
      cursor: pointer;
      min-width: 68px;
    }
    .segmented button:last-child { border-right: 0; }
    .segmented button.active { color: #fff; background: var(--ink); }
    .refresh {
      border: 1px solid var(--ink);
      background: var(--ink);
      color: #fff;
      border-radius: 8px;
      padding: 9px 13px;
      cursor: pointer;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .stat {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 82px;
    }
    .label { color: var(--muted); font-size: 12px; font-weight: 750; margin-bottom: 8px; }
    .value { color: var(--ink); font-size: 22px; font-weight: 900; white-space: nowrap; }
    .sub { color: var(--muted); font-size: 12px; margin-top: 4px; }
    .up { color: var(--green); font-weight: 850; }
    .down { color: var(--red); font-weight: 850; }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 12px;
      align-items: start;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--surface2);
    }
    .panel-title { font-weight: 850; }
    .panel-note { color: var(--muted); font-size: 12px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    th {
      color: var(--muted);
      text-align: left;
      font-weight: 750;
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
      white-space: nowrap;
    }
    td {
      padding: 10px;
      border-bottom: 1px solid #edf1f5;
      vertical-align: middle;
      white-space: nowrap;
    }
    tbody tr:hover { background: #f9fbfd; }
    .symbol { font-weight: 900; color: var(--ink); font-size: 13px; }
    .small { color: var(--muted); font-size: 11px; }
    .num { font-variant-numeric: tabular-nums; }
    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 86px;
      border-radius: 6px;
      padding: 4px 8px;
      font-weight: 850;
      font-size: 11px;
    }
    .badge.long { background: var(--green-bg); color: var(--green); }
    .badge.short { background: var(--red-bg); color: var(--red); }
    .badge.watch { background: var(--amber-bg); color: var(--amber); }
    .score {
      width: 52px;
      height: 28px;
      border-radius: 6px;
      display: inline-grid;
      place-items: center;
      color: #fff;
      background: var(--ink);
      font-weight: 900;
    }
    .reason {
      display: flex;
      gap: 5px;
      flex-wrap: wrap;
      min-width: 230px;
      white-space: normal;
    }
    .chip {
      border: 1px solid var(--line);
      background: var(--surface2);
      color: var(--text);
      border-radius: 6px;
      padding: 3px 6px;
      font-size: 11px;
    }
    .event-list { max-height: 690px; overflow: auto; }
    .event {
      display: grid;
      grid-template-columns: 58px 1fr;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid #edf1f5;
    }
    .event-side { font-size: 11px; font-weight: 900; }
    .event-side.buy { color: var(--green); }
    .event-side.sell { color: var(--red); }
    .event-title { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; font-weight: 850; }
    .event-meta { color: var(--muted); font-size: 11px; margin-top: 3px; }
    .warn {
      margin-top: 12px;
      border: 1px solid #efd897;
      background: var(--amber-bg);
      color: #744b00;
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 12px;
      line-height: 1.55;
    }
    @media (max-width: 1100px) {
      .layout { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls { grid-template-columns: 1fr; }
      .segmented { overflow-x: auto; }
      .statusbar { display: none; }
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand"><div class="brand-mark">FR</div><div>Binance Flow Radar</div></div>
    <div class="statusbar">
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
        <button data-filter="long">做多压力</button>
        <button data-filter="short">做空压力</button>
        <button data-filter="hot">高分</button>
        <button data-filter="alts">山寨</button>
      </div>
      <button class="refresh" id="refresh">重连</button>
    </div>

    <section class="stats">
      <div class="stat"><div class="label">监控交易对</div><div class="value" id="statSymbols">--</div><div class="sub">浏览器直连 Binance</div></div>
      <div class="stat"><div class="label">强做多压力</div><div class="value up" id="statLong">--</div><div class="sub">评分不低于 60</div></div>
      <div class="stat"><div class="label">强做空压力</div><div class="value down" id="statShort">--</div><div class="sub">评分不低于 60</div></div>
      <div class="stat"><div class="label">60 秒大单流</div><div class="value" id="statFlow">--</div><div class="sub">WebSocket 实时累计</div></div>
      <div class="stat"><div class="label">5 分钟爆仓</div><div class="value" id="statLiq">--</div><div class="sub">强平订单流</div></div>
    </section>

    <section class="layout">
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">资金压力雷达</div>
            <div class="panel-note">大额主动成交、价格短线变化、爆仓流组合评分</div>
          </div>
          <div class="panel-note" id="errorNote"></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>交易对</th>
                <th>信号</th>
                <th>分数</th>
                <th>价格</th>
                <th>5m</th>
                <th>60s 净流</th>
                <th>5m 净流</th>
                <th>最大单</th>
                <th>5m 爆仓</th>
                <th>依据</th>
              </tr>
            </thead>
            <tbody id="radarBody">
              <tr><td colspan="10">正在连接 Binance WebSocket...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <aside class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">实时大单与爆仓</div>
            <div class="panel-note">达到阈值后进入事件流</div>
          </div>
        </div>
        <div class="event-list" id="eventList"></div>
      </aside>
    </section>

    <div class="warn">
      Render 服务器访问 Binance 会被地区限制，所以这版改为浏览器直连 Binance WebSocket。若你的浏览器也无法连接 Binance，页面会显示连接错误。此工具只用于缩小观察范围，不构成投资建议；高分信号也可能是诱多、诱空或出货。
    </div>
  </main>

  <script>
    const WATCH_SYMBOLS = __WATCH_SYMBOLS__;
    const LARGE_TRADE_USD = __LARGE_TRADE_USD__;
    const BINANCE_WS = "__BINANCE_WS__";
    const MAJORS = new Set(["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]);

    const state = {
      trades: new Map(),
      liquidations: new Map(),
      prices: new Map(),
      priceHistory: new Map(),
      events: [],
      sockets: [],
      tradeConnected: false,
      liqConnected: false,
      tradeError: "",
      liqError: "",
      activeFilter: "all",
    };

    function base(symbol) { return symbol.replace("USDT", ""); }
    function now() { return Date.now(); }
    function cutoffRows(rows, ms) {
      const cut = now() - ms;
      return rows.filter(row => row.ts >= cut);
    }
    function ensureList(map, symbol) {
      if (!map.has(symbol)) map.set(symbol, []);
      return map.get(symbol);
    }
    function money(value) {
      value = Number(value || 0);
      if (Math.abs(value) >= 1e9) return "$" + (value / 1e9).toFixed(2) + "B";
      if (Math.abs(value) >= 1e6) return "$" + (value / 1e6).toFixed(2) + "M";
      if (Math.abs(value) >= 1e3) return "$" + (value / 1e3).toFixed(0) + "K";
      return "$" + value.toFixed(0);
    }
    function price(value) {
      value = Number(value || 0);
      if (!value) return "--";
      if (value >= 100) return "$" + value.toLocaleString(undefined, {maximumFractionDigits: 2});
      if (value >= 1) return "$" + value.toLocaleString(undefined, {maximumFractionDigits: 4});
      return "$" + value.toLocaleString(undefined, {maximumFractionDigits: 8});
    }
    function signedPct(value) {
      value = Number(value || 0);
      const cls = value >= 0 ? "up" : "down";
      const sign = value > 0 ? "+" : "";
      return `<span class="${cls}">${sign}${value.toFixed(2)}%</span>`;
    }
    function signalBadge(signal) {
      if (signal === "LONG") return '<span class="badge long">做多压力</span>';
      if (signal === "SHORT") return '<span class="badge short">做空压力</span>';
      return '<span class="badge watch">观察</span>';
    }
    function setDot(id, ok, err) {
      const el = document.getElementById(id);
      el.classList.toggle("ok", ok);
      el.classList.toggle("bad", !!err);
    }
    function addEvent(event) {
      state.events.unshift(event);
      state.events = state.events.slice(0, 160);
    }
    function rememberPrice(symbol, value, ts) {
      state.prices.set(symbol, value);
      const rows = ensureList(state.priceHistory, symbol);
      rows.push({ts, value});
      while (rows.length > 600 || (rows.length && rows[0].ts < now() - 6 * 60 * 1000)) rows.shift();
    }
    function price5m(symbol) {
      const rows = state.priceHistory.get(symbol) || [];
      if (rows.length < 2) return 0;
      const recent = rows[rows.length - 1].value;
      const cut = now() - 5 * 60 * 1000;
      const old = rows.find(row => row.ts >= cut)?.value || rows[0].value;
      return old ? (recent - old) / old * 100 : 0;
    }
    function flow(symbol, ms) {
      const rows = cutoffRows(state.trades.get(symbol) || [], ms);
      let buy = 0, sell = 0, largest = 0;
      for (const row of rows) {
        if (row.side === "BUY") buy += row.notional;
        else sell += row.notional;
        largest = Math.max(largest, row.notional);
      }
      return {buy, sell, net: buy - sell, total: buy + sell, largest};
    }
    function liq(symbol, ms) {
      const rows = cutoffRows(state.liquidations.get(symbol) || [], ms);
      let longLiq = 0, shortLiq = 0, largest = 0;
      for (const row of rows) {
        if (row.side === "SELL") longLiq += row.notional;
        else shortLiq += row.notional;
        largest = Math.max(largest, row.notional);
      }
      return {longLiq, shortLiq, total: longLiq + shortLiq, largest};
    }
    function scoreRow(symbol) {
      const f60 = flow(symbol, 60 * 1000);
      const f5 = flow(symbol, 5 * 60 * 1000);
      const l5 = liq(symbol, 5 * 60 * 1000);
      const p5 = price5m(symbol);
      const netRatio = f60.total ? f60.net / f60.total : 0;
      let longScore = 0;
      let shortScore = 0;
      if (netRatio > 0) longScore += Math.min(38, netRatio * 38);
      else shortScore += Math.min(38, Math.abs(netRatio) * 38);
      const sizePoints = Math.min(24, f60.total / Math.max(LARGE_TRADE_USD, 1) * 5);
      if (f60.net > 0) longScore += sizePoints;
      if (f60.net < 0) shortScore += sizePoints;
      if (f5.net > 0) longScore += Math.min(14, Math.abs(f5.net) / Math.max(LARGE_TRADE_USD, 1) * 2);
      if (f5.net < 0) shortScore += Math.min(14, Math.abs(f5.net) / Math.max(LARGE_TRADE_USD, 1) * 2);
      if (p5 > 0) longScore += Math.min(14, p5 * 2.5);
      if (p5 < 0) shortScore += Math.min(14, Math.abs(p5) * 2.5);
      longScore += Math.min(10, l5.shortLiq / Math.max(LARGE_TRADE_USD, 1) * 3);
      shortScore += Math.min(10, l5.longLiq / Math.max(LARGE_TRADE_USD, 1) * 3);
      longScore = Math.max(0, Math.min(100, longScore));
      shortScore = Math.max(0, Math.min(100, shortScore));
      let signal = "WATCH";
      let score = Math.round(Math.max(longScore, shortScore));
      if (longScore >= 35 && longScore >= shortScore) signal = "LONG";
      if (shortScore >= 35 && shortScore > longScore) signal = "SHORT";
      const reasons = [];
      if (Math.abs(f60.net) >= LARGE_TRADE_USD) reasons.push((f60.net > 0 ? "主动买入净额 " : "主动卖出净额 ") + money(Math.abs(f60.net)));
      if (f60.largest >= LARGE_TRADE_USD) reasons.push("最大单 " + money(f60.largest));
      if (Math.abs(p5) >= 1) reasons.push("5m 价格 " + (p5 > 0 ? "+" : "") + p5.toFixed(2) + "%");
      if (l5.longLiq >= LARGE_TRADE_USD) reasons.push("多头爆仓 " + money(l5.longLiq));
      if (l5.shortLiq >= LARGE_TRADE_USD) reasons.push("空头爆仓 " + money(l5.shortLiq));
      if (!reasons.length) reasons.push("等待大额资金流");
      return {symbol, base: base(symbol), price: state.prices.get(symbol) || 0, p5, f60, f5, l5, signal, score, reasons};
    }
    function rows() {
      return WATCH_SYMBOLS.map(scoreRow).sort((a, b) => {
        return b.score - a.score || Math.abs(b.f60.net) - Math.abs(a.f60.net) || Math.abs(b.f5.net) - Math.abs(a.f5.net);
      });
    }
    function filteredRows() {
      const query = document.getElementById("search").value.trim().toUpperCase();
      return rows().filter(row => {
        if (query && !row.symbol.includes(query) && !row.base.includes(query)) return false;
        if (state.activeFilter === "long") return row.signal === "LONG";
        if (state.activeFilter === "short") return row.signal === "SHORT";
        if (state.activeFilter === "hot") return row.score >= 60;
        if (state.activeFilter === "alts") return !MAJORS.has(row.symbol);
        return true;
      });
    }
    function renderStats(allRows) {
      const strongLong = allRows.filter(row => row.signal === "LONG" && row.score >= 60).length;
      const strongShort = allRows.filter(row => row.signal === "SHORT" && row.score >= 60).length;
      const totalFlow = allRows.reduce((sum, row) => sum + row.f60.total, 0);
      const totalLiq = allRows.reduce((sum, row) => sum + row.l5.total, 0);
      document.getElementById("statSymbols").textContent = WATCH_SYMBOLS.length;
      document.getElementById("statLong").textContent = strongLong;
      document.getElementById("statShort").textContent = strongShort;
      document.getElementById("statFlow").textContent = money(totalFlow);
      document.getElementById("statLiq").textContent = money(totalLiq);
      setDot("tradeDot", state.tradeConnected, state.tradeError);
      setDot("liqDot", state.liqConnected, state.liqError);
      const errors = [state.tradeError, state.liqError].filter(Boolean);
      document.getElementById("connText").textContent = errors.length ? "连接错误" : (state.tradeConnected || state.liqConnected ? "实时连接中" : "连接中");
      document.getElementById("errorNote").textContent = errors[0] || "";
    }
    function renderRadar() {
      const all = rows();
      const visible = filteredRows();
      renderStats(all);
      const body = document.getElementById("radarBody");
      if (!visible.length) {
        body.innerHTML = '<tr><td colspan="10">当前筛选条件下暂无信号。</td></tr>';
        return;
      }
      body.innerHTML = visible.slice(0, 80).map(row => {
        const net60Cls = row.f60.net >= 0 ? "up" : "down";
        const net5Cls = row.f5.net >= 0 ? "up" : "down";
        const reasons = row.reasons.map(x => `<span class="chip">${x}</span>`).join("");
        return `<tr>
          <td><div class="symbol">${row.base}</div><div class="small">${row.symbol}</div></td>
          <td>${signalBadge(row.signal)}</td>
          <td><span class="score">${row.score}</span></td>
          <td class="num">${price(row.price)}</td>
          <td class="num">${signedPct(row.p5)}</td>
          <td class="num ${net60Cls}">${row.f60.net >= 0 ? "+" : "-"}${money(Math.abs(row.f60.net))}</td>
          <td class="num ${net5Cls}">${row.f5.net >= 0 ? "+" : "-"}${money(Math.abs(row.f5.net))}</td>
          <td class="num">${money(row.f60.largest || row.f5.largest)}</td>
          <td class="num">${money(row.l5.total)}</td>
          <td><div class="reason">${reasons}</div></td>
        </tr>`;
      }).join("");
    }
    function renderEvents() {
      const list = document.getElementById("eventList");
      if (!state.events.length) {
        list.innerHTML = '<div class="event"><div></div><div><div class="event-title">等待大额事件</div><div class="event-meta">阈值达到后会显示在这里</div></div></div>';
        return;
      }
      list.innerHTML = state.events.slice(0, 100).map(ev => {
        const sideCls = ev.side === "BUY" ? "buy" : "sell";
        return `<div class="event">
          <div class="event-side ${sideCls}">${ev.label}</div>
          <div>
            <div class="event-title"><span>${base(ev.symbol)}</span><span>${money(ev.notional)}</span></div>
            <div class="event-meta">${price(ev.price)} · ${new Date(ev.ts).toLocaleTimeString()}</div>
          </div>
        </div>`;
      }).join("");
    }
    function trimOldData() {
      const cut = now() - 6 * 60 * 1000;
      for (const map of [state.trades, state.liquidations]) {
        for (const [symbol, list] of map) {
          while (list.length && list[0].ts < cut) list.shift();
          if (!list.length) map.delete(symbol);
        }
      }
    }
    function closeSockets() {
      for (const ws of state.sockets) {
        try { ws.close(); } catch (_) {}
      }
      state.sockets = [];
      state.tradeConnected = false;
      state.liqConnected = false;
      state.tradeError = "";
      state.liqError = "";
    }
    function connectTrades() {
      const streams = WATCH_SYMBOLS.map(symbol => symbol.toLowerCase() + "@aggTrade").join("/");
      const ws = new WebSocket(`${BINANCE_WS}/stream?streams=${streams}`);
      state.sockets.push(ws);
      ws.onopen = () => { state.tradeConnected = true; state.tradeError = ""; renderRadar(); };
      ws.onclose = () => { state.tradeConnected = false; renderRadar(); setTimeout(connectTrades, 3000); };
      ws.onerror = () => { state.tradeError = "浏览器无法连接 Binance 大单流 WebSocket"; renderRadar(); };
      ws.onmessage = event => {
        const payload = JSON.parse(event.data).data || {};
        const symbol = payload.s;
        if (!symbol || !WATCH_SYMBOLS.includes(symbol)) return;
        const ts = payload.T || Date.now();
        const priceValue = Number(payload.p || 0);
        const qty = Number(payload.q || 0);
        const notional = priceValue * qty;
        const side = payload.m ? "SELL" : "BUY";
        rememberPrice(symbol, priceValue, ts);
        if (notional >= LARGE_TRADE_USD) {
          const row = {symbol, side, ts, price: priceValue, qty, notional};
          ensureList(state.trades, symbol).push(row);
          addEvent({...row, label: side === "BUY" ? "主动买" : "主动卖"});
        }
      };
    }
    function connectLiquidations() {
      const ws = new WebSocket(`${BINANCE_WS}/ws/!forceOrder@arr`);
      state.sockets.push(ws);
      ws.onopen = () => { state.liqConnected = true; state.liqError = ""; renderRadar(); };
      ws.onclose = () => { state.liqConnected = false; renderRadar(); setTimeout(connectLiquidations, 3000); };
      ws.onerror = () => { state.liqError = "浏览器无法连接 Binance 爆仓流 WebSocket"; renderRadar(); };
      ws.onmessage = event => {
        const payload = JSON.parse(event.data);
        const order = payload.o || {};
        const symbol = order.s;
        if (!symbol || !WATCH_SYMBOLS.includes(symbol)) return;
        const priceValue = Number(order.ap || order.p || 0);
        const qty = Number(order.q || 0);
        const notional = priceValue * qty;
        if (notional < LARGE_TRADE_USD) return;
        const side = order.S || "";
        const ts = order.T || payload.E || Date.now();
        const row = {symbol, side, ts, price: priceValue, qty, notional};
        ensureList(state.liquidations, symbol).push(row);
        addEvent({...row, label: side === "BUY" ? "空爆" : "多爆"});
      };
    }
    function start() {
      closeSockets();
      connectTrades();
      connectLiquidations();
      renderRadar();
      renderEvents();
    }
    document.getElementById("refresh").addEventListener("click", start);
    document.getElementById("search").addEventListener("input", renderRadar);
    document.getElementById("filters").addEventListener("click", event => {
      if (!event.target.dataset.filter) return;
      state.activeFilter = event.target.dataset.filter;
      document.querySelectorAll("#filters button").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.filter === state.activeFilter);
      });
      renderRadar();
    });
    setInterval(() => { trimOldData(); renderRadar(); renderEvents(); }, 1000);
    start();
  </script>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    html = HTML.replace("__WATCH_SYMBOLS__", json.dumps(WATCH_SYMBOLS))
    html = html.replace("__LARGE_TRADE_USD__", json.dumps(LARGE_TRADE_USD))
    html = html.replace("__BINANCE_WS__", BINANCE_WS.rstrip("/"))
    return render_template_string(html)


@app.route("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "mode": "browser_direct_binance_websocket",
            "watch_symbols": WATCH_SYMBOLS,
            "large_trade_usd": LARGE_TRADE_USD,
        }
    )


@app.route("/debug/binance")
def debug_binance():
    return jsonify(
        {
            "message": "Render no longer fetches Binance. The browser connects directly to Binance WebSocket.",
            "binance_ws": BINANCE_WS,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
