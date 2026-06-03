from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from flask import Flask, jsonify, render_template_string, request


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
BINANCE_WS = os.environ.get("BINANCE_WS", "wss://fstream.binance.com/market").rstrip("/")
if BINANCE_WS in {"wss://fstream.binance.com", "wss://fstream.binancefuture.com"}:
    BINANCE_WS += "/market"
BINANCE_WS_BASES = [
    url.strip().rstrip("/")
    for url in os.environ.get(
        "BINANCE_WS_BASES",
        "wss://fstream.binance.com/market,wss://fstream.binancefuture.com/market",
    ).split(",")
    if url.strip()
]
if BINANCE_WS.rstrip("/") not in BINANCE_WS_BASES:
    BINANCE_WS_BASES.insert(0, BINANCE_WS.rstrip("/"))
BINANCE_REST = os.environ.get("BINANCE_REST", "https://fapi.binance.com")
BINANCE_REST_BASES = [
    url.strip().rstrip("/")
    for url in os.environ.get(
        "BINANCE_REST_BASES",
        "https://fapi.binance.com,https://fapi.binancefuture.com",
    ).split(",")
    if url.strip()
]
if BINANCE_REST.rstrip("/") not in BINANCE_REST_BASES:
    BINANCE_REST_BASES.insert(0, BINANCE_REST.rstrip("/"))
AI_API_KEY = os.environ.get("AI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
AI_API_BASE = os.environ.get("AI_API_BASE") or (
    "https://api.deepseek.com" if os.environ.get("DEEPSEEK_API_KEY") else "https://api.openai.com/v1"
)
AI_MODEL = os.environ.get("AI_MODEL") or ("deepseek-chat" if os.environ.get("DEEPSEEK_API_KEY") else "gpt-4o-mini")


def money_short(value: float) -> str:
    value = float(value or 0)
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def rule_based_analysis(payload: dict) -> str:
    rows = payload.get("rows") or []
    events = payload.get("events") or []
    signals = payload.get("signals") or []
    rows = rows[:12]
    hot = [row for row in rows if int(row.get("score") or 0) >= 50]
    long_rows = [row for row in hot if row.get("signal") == "LONG"]
    short_rows = [row for row in hot if row.get("signal") == "SHORT"]
    top = rows[0] if rows else None

    lines = []
    if not rows:
        return "暂无足够数据。先等待价格流和大单流累计 1-3 分钟，再分析。"

    lines.append("当前结论：")
    if top and int(top.get("score") or 0) >= 60:
        lines.append(
            f"- 最强信号是 {top.get('base')}，方向为 {top.get('signal')}，评分 {top.get('score')}。"
        )
    else:
        lines.append("- 当前没有特别强的一致性信号，适合观察，不适合追单。")

    if long_rows and short_rows:
        lines.append("- 多空压力同时出现，说明资金分歧较大，优先等突破或假突破确认。")
    elif long_rows:
        names = "、".join(row.get("base", "") for row in long_rows[:4])
        lines.append(f"- 做多压力集中在 {names}，但需要价格同步上行才更有交易意义。")
    elif short_rows:
        names = "、".join(row.get("base", "") for row in short_rows[:4])
        lines.append(f"- 做空压力集中在 {names}，若价格没有继续下行，可能是诱空或吸筹。")

    completed5m = [item for item in signals if item.get("result_5m_pct") is not None]
    if completed5m:
        wins = [item for item in completed5m if float(item.get("result_5m_pct") or 0) > 0]
        avg = sum(float(item.get("result_5m_pct") or 0) for item in completed5m) / len(completed5m)
        lines.append(
            f"- 最近已复盘 5m 信号 {len(completed5m)} 个，胜率 {len(wins) / len(completed5m) * 100:.0f}%，平均结果 {avg:+.2f}%。"
        )
        if len(completed5m) >= 8 and avg <= 0:
            lines.append("- 当前规则近期平均表现不佳，强信号也应降仓或只观察。")

    lines.append("")
    lines.append("入场前要等的确认：")
    lines.append("- 资金净流连续 2-3 个刷新周期保持同方向，而不是单笔大单闪过。")
    lines.append("- 价格方向和资金方向一致：主动买净流配合价格抬高，主动卖净流配合价格走低。")
    lines.append("- 最大单不是孤立一笔，事件流里同币种要连续出现。")

    lines.append("")
    lines.append("失效/避开的情况：")
    lines.append("- 分数高但价格不动，可能是对倒、吸筹或诱单，不要直接追。")
    lines.append("- 拉升后出现连续主动卖，尤其是山寨币，优先当作出货风险。")
    lines.append("- BTC/ETH 方向和山寨信号相反时，山寨信号要降级处理。")

    if events:
        event_symbols = {}
        for event in events[:30]:
            symbol = event.get("base") or event.get("symbol") or ""
            event_symbols[symbol] = event_symbols.get(symbol, 0) + 1
        active = sorted(event_symbols.items(), key=lambda x: x[1], reverse=True)[:3]
        if active:
            lines.append("")
            lines.append("事件流活跃：")
            lines.append("- " + "、".join(f"{name}({count}次)" for name, count in active if name))

    lines.append("")
    lines.append("仓位建议：这不是自动买卖信号。用小仓试错，先设止损，再考虑入场。")
    return "\n".join(lines)


def call_ai_analysis(payload: dict, fallback: str) -> tuple[str, str]:
    if not AI_API_KEY:
        return fallback, "rules"

    compact = {
        "summary": payload.get("summary", {}),
        "rows": (payload.get("rows") or [])[:12],
        "events": (payload.get("events") or [])[:25],
        "signals": (payload.get("signals") or [])[:20],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个加密货币合约资金流分析助手。你只基于用户给出的公开行情快照分析，"
                "不要承诺收益，不要说一定涨跌。输出中文，结构包括：当前判断、可交易条件、"
                "风险/诱多诱空、观察优先级。保持简洁。"
            ),
        },
        {
            "role": "user",
            "content": "请分析这份 Binance USDT 永续资金流快照：\n" + json.dumps(compact, ensure_ascii=False),
        },
    ]
    body = json.dumps({"model": AI_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 900}).encode()
    url = AI_API_BASE.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"].strip()
        return content or fallback, "ai"
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
        return fallback + f"\n\nAI 调用失败，已使用内置规则分析。错误：{exc}", "rules"


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
    .ai-panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 12px;
      overflow: hidden;
    }
    .ai-body {
      padding: 12px 14px;
      color: var(--text);
      font-size: 13px;
      line-height: 1.65;
      white-space: pre-wrap;
      min-height: 92px;
    }
    .ai-btn {
      border: 1px solid var(--ink);
      background: var(--ink);
      color: #fff;
      border-radius: 8px;
      padding: 8px 12px;
      cursor: pointer;
      white-space: nowrap;
    }
    .ai-btn:disabled { opacity: .55; cursor: wait; }
    .review-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      margin-top: 12px;
    }
    .review-meta {
      color: var(--muted);
      font-size: 12px;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }
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

    <section class="ai-panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">AI 资金流分析</div>
          <div class="panel-note">基于当前表格快照，不读取账户，不自动下单</div>
        </div>
        <button class="ai-btn" id="aiBtn">分析当前行情</button>
      </div>
      <div class="ai-body" id="aiOutput">等待行情累计后点击分析。没有配置 AI Key 时会使用内置规则分析。</div>
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
                <th>OI 15m</th>
                <th>Taker</th>
                <th>60s 净流</th>
                <th>5m 净流</th>
                <th>最大单</th>
                <th>5m 爆仓</th>
                <th>依据</th>
              </tr>
            </thead>
            <tbody id="radarBody">
              <tr><td colspan="12">正在连接 Binance WebSocket...</td></tr>
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

    <section class="panel review-grid">
      <div class="panel-head">
        <div>
          <div class="panel-title">信号复盘</div>
          <div class="panel-note">自动记录评分不低于 60 的信号，跟踪 1/3/5/15 分钟后结果</div>
        </div>
        <div class="review-meta" id="signalStats">等待强信号</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>交易对</th>
              <th>方向</th>
              <th>分数</th>
              <th>入场价</th>
              <th>1m</th>
              <th>3m</th>
              <th>5m</th>
              <th>15m</th>
            </tr>
          </thead>
          <tbody id="signalBody">
            <tr><td colspan="9">暂无强信号记录。</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="warn">
      Render 服务器访问 Binance 会被地区限制，所以这版改为浏览器直连 Binance WebSocket。若你的浏览器也无法连接 Binance，页面会显示连接错误。此工具只用于缩小观察范围，不构成投资建议；高分信号也可能是诱多、诱空或出货。
    </div>
  </main>

  <script>
    const WATCH_SYMBOLS = __WATCH_SYMBOLS__;
    const LARGE_TRADE_USD = __LARGE_TRADE_USD__;
    const BINANCE_WS_BASES = __BINANCE_WS_BASES__;
    const BINANCE_REST_BASES = __BINANCE_REST_BASES__;
    const PRICE_STREAMS = ["!markPrice@arr@1s", "!ticker@arr"];
    const SIGNAL_HORIZONS = [
      {key: "m1", label: "1m", ms: 60 * 1000},
      {key: "m3", label: "3m", ms: 3 * 60 * 1000},
      {key: "m5", label: "5m", ms: 5 * 60 * 1000},
      {key: "m15", label: "15m", ms: 15 * 60 * 1000},
    ];
    const MAJORS = new Set(["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]);

    const state = {
      trades: new Map(),
      liquidations: new Map(),
      prices: new Map(),
      priceHistory: new Map(),
      derivatives: new Map(),
      events: [],
      signalLog: [],
      signalCooldown: new Map(),
      sockets: [],
      priceConnected: false,
      tradeConnected: false,
      liqConnected: false,
      priceError: "",
      tradeError: "",
      liqError: "",
      priceMessages: 0,
      tradeMessages: 0,
      liqMessages: 0,
      derivativesUpdatedAt: 0,
      derivativesError: "",
      derivativesTimer: null,
      runId: 0,
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
    function plainSignedPct(value) {
      value = Number(value || 0);
      const sign = value > 0 ? "+" : "";
      return `${sign}${value.toFixed(2)}%`;
    }
    function resultCell(value) {
      if (value === null || value === undefined) return '<span class="small">等待</span>';
      const cls = value >= 0 ? "up" : "down";
      const sign = value > 0 ? "+" : "";
      return `<span class="${cls}">${sign}${value.toFixed(2)}%</span>`;
    }
    function derivative(symbol) {
      return state.derivatives.get(symbol) || {
        oi5Pct: null,
        oi15Pct: null,
        oiValue: 0,
        takerRatio: null,
        takerBuyPct: null,
        fundingRate: null,
        updatedAt: 0,
      };
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
    async function fetchJsonFromBinance(path) {
      let lastError = null;
      for (const baseUrl of BINANCE_REST_BASES) {
        try {
          const res = await fetch(baseUrl + path, {cache: "no-store"});
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
          return await res.json();
        } catch (error) {
          lastError = error;
        }
      }
      throw lastError || new Error("Binance REST unavailable");
    }
    async function fetchDerivativeSymbol(symbol) {
      const current = derivative(symbol);
      const next = {...current, updatedAt: Date.now()};
      try {
        const oiRows = await fetchJsonFromBinance(`/futures/data/openInterestHist?symbol=${encodeURIComponent(symbol)}&period=5m&limit=4`);
        if (Array.isArray(oiRows) && oiRows.length) {
          const latest = Number(oiRows[oiRows.length - 1].sumOpenInterestValue || 0);
          const prev = Number((oiRows[oiRows.length - 2] || {}).sumOpenInterestValue || 0);
          const first = Number(oiRows[0].sumOpenInterestValue || 0);
          next.oiValue = latest;
          next.oi5Pct = prev ? (latest - prev) / prev * 100 : null;
          next.oi15Pct = first ? (latest - first) / first * 100 : null;
        }
      } catch (_) {}
      try {
        const takerRows = await fetchJsonFromBinance(`/futures/data/takerlongshortRatio?symbol=${encodeURIComponent(symbol)}&period=5m&limit=1`);
        if (Array.isArray(takerRows) && takerRows.length) {
          const item = takerRows[takerRows.length - 1];
          const buyVol = Number(item.buyVol || 0);
          const sellVol = Number(item.sellVol || 0);
          const total = buyVol + sellVol;
          next.takerRatio = Number(item.buySellRatio || (sellVol ? buyVol / sellVol : 1));
          next.takerBuyPct = total ? buyVol / total * 100 : null;
        }
      } catch (_) {}
      state.derivatives.set(symbol, next);
    }
    async function fetchDerivatives() {
      state.derivativesError = "";
      try {
        const premium = await fetchJsonFromBinance("/fapi/v1/premiumIndex");
        if (Array.isArray(premium)) {
          const ts = Date.now();
          for (const item of premium) {
            const symbol = item.symbol;
            if (!WATCH_SYMBOLS.includes(symbol)) continue;
            const next = {...derivative(symbol), updatedAt: ts};
            next.fundingRate = Number(item.lastFundingRate || 0) * 100;
            const markPrice = Number(item.markPrice || 0);
            if (markPrice > 0) rememberPrice(symbol, markPrice, ts);
            state.derivatives.set(symbol, next);
          }
        }
        const ranked = rows().slice(0, 14).map(row => row.symbol);
        const targets = Array.from(new Set([...ranked, "BTCUSDT", "ETHUSDT", "SOLUSDT"].filter(symbol => WATCH_SYMBOLS.includes(symbol))));
        for (let i = 0; i < targets.length; i += 4) {
          await Promise.all(targets.slice(i, i + 4).map(fetchDerivativeSymbol));
        }
        state.derivativesUpdatedAt = Date.now();
      } catch (error) {
        state.derivativesError = `衍生品数据受限：${error}`;
      }
      renderRadar();
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
      const d = derivative(symbol);
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
      if (d.oi15Pct !== null && d.oi15Pct > 1.2) {
        if (p5 >= 0 && f5.net >= 0) longScore += Math.min(18, d.oi15Pct * 4);
        if (p5 <= 0 && f5.net <= 0) shortScore += Math.min(18, d.oi15Pct * 4);
      }
      if (d.takerRatio !== null && d.takerRatio > 1.12) longScore += Math.min(12, (d.takerRatio - 1) * 24);
      if (d.takerRatio !== null && d.takerRatio < 0.9) shortScore += Math.min(12, (1 - d.takerRatio) * 24);
      if (d.fundingRate !== null && d.fundingRate > 0.04) longScore -= 5;
      if (d.fundingRate !== null && d.fundingRate < -0.04) shortScore -= 5;
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
      if (d.oi15Pct !== null && Math.abs(d.oi15Pct) >= 1.2) reasons.push("OI 15m " + plainSignedPct(d.oi15Pct));
      if (d.takerRatio !== null && (d.takerRatio >= 1.12 || d.takerRatio <= 0.9)) reasons.push("Taker " + d.takerRatio.toFixed(2));
      if (d.fundingRate !== null && Math.abs(d.fundingRate) >= 0.04) reasons.push("资金费率 " + d.fundingRate.toFixed(4) + "%");
      if (!reasons.length) reasons.push("等待大额资金流");
      return {symbol, base: base(symbol), price: state.prices.get(symbol) || 0, p5, f60, f5, l5, d, signal, score, reasons};
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
      setDot("priceDot", state.priceConnected, state.priceError);
      setDot("tradeDot", state.tradeConnected, state.tradeError);
      setDot("liqDot", state.liqConnected, state.liqError);
      const errors = [state.priceError, state.tradeError, state.liqError, state.derivativesError].filter(Boolean);
      const connectedCount = [state.priceConnected, state.tradeConnected, state.liqConnected].filter(Boolean).length;
      const derivText = state.derivativesUpdatedAt ? " 衍生品OK" : " 衍生品等待";
      document.getElementById("connText").textContent = errors.length ? "连接错误" : (connectedCount ? `实时连接中 · 价格${state.priceMessages} 大单${state.tradeMessages}${derivText}` : "连接中");
      document.getElementById("errorNote").textContent = errors[0] || "";
    }
    function renderRadar() {
      const all = rows();
      const visible = filteredRows();
      renderStats(all);
      maybeRecordSignals(all);
      updateSignalOutcomes();
      renderSignalReview();
      const body = document.getElementById("radarBody");
      if (!visible.length) {
        body.innerHTML = '<tr><td colspan="12">当前筛选条件下暂无信号。</td></tr>';
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
          <td class="num">${row.d.oi15Pct === null ? '<span class="small">--</span>' : signedPct(row.d.oi15Pct)}</td>
          <td class="num">${row.d.takerRatio === null ? '<span class="small">--</span>' : row.d.takerRatio.toFixed(2)}</td>
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
    function loadSignalLog() {
      try {
        const raw = localStorage.getItem("flowRadarSignalLogV1");
        state.signalLog = raw ? JSON.parse(raw) : [];
      } catch (_) {
        state.signalLog = [];
      }
    }
    function saveSignalLog() {
      try {
        localStorage.setItem("flowRadarSignalLogV1", JSON.stringify(state.signalLog.slice(0, 120)));
      } catch (_) {}
    }
    function signalDirection(signal) {
      return signal === "LONG" ? 1 : signal === "SHORT" ? -1 : 0;
    }
    function maybeRecordSignals(allRows) {
      const ts = Date.now();
      let changed = false;
      for (const row of allRows) {
        if (row.score < 60 || !row.price || !["LONG", "SHORT"].includes(row.signal)) continue;
        const key = `${row.symbol}|${row.signal}`;
        const last = state.signalCooldown.get(key) || 0;
        if (ts - last < 3 * 60 * 1000) continue;
        state.signalCooldown.set(key, ts);
        state.signalLog.unshift({
          id: `${ts}-${row.symbol}-${row.signal}`,
          ts,
          symbol: row.symbol,
          base: row.base,
          signal: row.signal,
          score: row.score,
          entryPrice: row.price,
          reasons: row.reasons,
          checks: {m1: null, m3: null, m5: null, m15: null},
        });
        changed = true;
      }
      if (state.signalLog.length > 120) {
        state.signalLog = state.signalLog.slice(0, 120);
        changed = true;
      }
      if (changed) saveSignalLog();
    }
    function updateSignalOutcomes() {
      let changed = false;
      const ts = Date.now();
      for (const item of state.signalLog) {
        const current = state.prices.get(item.symbol);
        if (!current || !item.entryPrice) continue;
        for (const horizon of SIGNAL_HORIZONS) {
          if (item.checks[horizon.key] !== null) continue;
          if (ts - item.ts < horizon.ms) continue;
          const rawPct = (current - item.entryPrice) / item.entryPrice * 100;
          const resultPct = rawPct * signalDirection(item.signal);
          item.checks[horizon.key] = Number(resultPct.toFixed(3));
          changed = true;
        }
      }
      if (changed) saveSignalLog();
    }
    function renderSignalReview() {
      const body = document.getElementById("signalBody");
      const stats = document.getElementById("signalStats");
      if (!state.signalLog.length) {
        body.innerHTML = '<tr><td colspan="9">暂无强信号记录。</td></tr>';
        stats.textContent = "等待强信号";
        return;
      }
      const completed5m = state.signalLog.filter(item => item.checks.m5 !== null);
      const wins5m = completed5m.filter(item => item.checks.m5 > 0).length;
      const avg5m = completed5m.length
        ? completed5m.reduce((sum, item) => sum + item.checks.m5, 0) / completed5m.length
        : 0;
      stats.textContent = completed5m.length
        ? `5m样本 ${completed5m.length} · 胜率 ${(wins5m / completed5m.length * 100).toFixed(0)}% · 平均 ${plainSignedPct(avg5m)}`
        : `已记录 ${state.signalLog.length} 个信号，等待复盘`;
      body.innerHTML = state.signalLog.slice(0, 18).map(item => {
        const signalText = item.signal === "LONG" ? "做多" : "做空";
        const cls = item.signal === "LONG" ? "up" : "down";
        return `<tr>
          <td class="small">${new Date(item.ts).toLocaleTimeString()}</td>
          <td><div class="symbol">${item.base}</div><div class="small">${item.symbol}</div></td>
          <td class="${cls}">${signalText}</td>
          <td><span class="score">${item.score}</span></td>
          <td class="num">${price(item.entryPrice)}</td>
          <td class="num">${resultCell(item.checks.m1)}</td>
          <td class="num">${resultCell(item.checks.m3)}</td>
          <td class="num">${resultCell(item.checks.m5)}</td>
          <td class="num">${resultCell(item.checks.m15)}</td>
        </tr>`;
      }).join("");
    }
    function compactRowsForAi() {
      return rows().slice(0, 15).map(row => ({
        symbol: row.symbol,
        base: row.base,
        signal: row.signal,
        score: row.score,
        price: row.price,
        price_5m_pct: Number(row.p5.toFixed(3)),
        net_60s_usd: Math.round(row.f60.net),
        total_60s_usd: Math.round(row.f60.total),
        net_5m_usd: Math.round(row.f5.net),
        total_5m_usd: Math.round(row.f5.total),
        largest_usd: Math.round(row.f60.largest || row.f5.largest),
        liquidation_5m_usd: Math.round(row.l5.total),
        oi_15m_pct: row.d.oi15Pct,
        taker_ratio: row.d.takerRatio,
        funding_rate_pct: row.d.fundingRate,
        reasons: row.reasons,
      }));
    }
    function compactSignalsForAi() {
      return state.signalLog.slice(0, 20).map(item => ({
        symbol: item.symbol,
        base: item.base,
        signal: item.signal,
        score: item.score,
        entry_price: item.entryPrice,
        time: new Date(item.ts).toLocaleTimeString(),
        result_1m_pct: item.checks.m1,
        result_3m_pct: item.checks.m3,
        result_5m_pct: item.checks.m5,
        result_15m_pct: item.checks.m15,
      }));
    }
    function compactEventsForAi() {
      return state.events.slice(0, 30).map(event => ({
        symbol: event.symbol,
        base: base(event.symbol),
        label: event.label,
        side: event.side,
        price: event.price,
        notional: Math.round(event.notional),
        time: new Date(event.ts).toLocaleTimeString(),
      }));
    }
    async function runAiAnalysis() {
      const btn = document.getElementById("aiBtn");
      const out = document.getElementById("aiOutput");
      btn.disabled = true;
      out.textContent = "正在分析当前资金流...";
      const allRows = rows();
      const payload = {
        summary: {
          watch_symbols: WATCH_SYMBOLS.length,
          price_messages: state.priceMessages,
          trade_messages: state.tradeMessages,
          liquidation_messages: state.liqMessages,
          strong_long: allRows.filter(row => row.signal === "LONG" && row.score >= 60).length,
          strong_short: allRows.filter(row => row.signal === "SHORT" && row.score >= 60).length,
          large_trade_threshold_usd: LARGE_TRADE_USD,
          derivatives_updated_at: state.derivativesUpdatedAt ? new Date(state.derivativesUpdatedAt).toLocaleTimeString() : null,
          derivatives_error: state.derivativesError,
          generated_at: new Date().toLocaleString(),
        },
        rows: compactRowsForAi(),
        events: compactEventsForAi(),
        signals: compactSignalsForAi(),
      };
      try {
        const res = await fetch("/api/ai/analyze", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        out.textContent = (data.mode === "ai" ? "AI 分析\n\n" : "规则分析\n\n") + data.analysis;
      } catch (error) {
        out.textContent = "分析失败：" + error;
      } finally {
        btn.disabled = false;
      }
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
      state.priceConnected = false;
      state.tradeConnected = false;
      state.liqConnected = false;
      state.priceError = "";
      state.tradeError = "";
      state.liqError = "";
      state.priceMessages = 0;
      state.tradeMessages = 0;
      state.liqMessages = 0;
    }
    function connectPrices(runId) {
      connectPriceEndpoint(0, runId);
    }
    function connectPriceEndpoint(index, runId) {
      const baseIndex = index % BINANCE_WS_BASES.length;
      const streamIndex = Math.floor(index / BINANCE_WS_BASES.length) % PRICE_STREAMS.length;
      const baseUrl = BINANCE_WS_BASES[baseIndex];
      const streamName = PRICE_STREAMS[streamIndex];
      const ws = new WebSocket(`${baseUrl}/ws/${streamName}`);
      state.sockets.push(ws);
      let opened = false;
      let movedOn = false;
      const startedMessages = state.priceMessages;
      const tryNext = () => {
        if (movedOn) return;
        movedOn = true;
        setTimeout(() => {
          if (runId === state.runId) connectPriceEndpoint(index + 1, runId);
        }, 900);
      };
      const timeoutId = setTimeout(() => {
        if (runId !== state.runId) return;
        if (!opened && ws.readyState === WebSocket.CONNECTING) {
          state.priceError = `价格流连接超时：${baseUrl}`;
          renderRadar();
          try { ws.close(); } catch (_) {}
          tryNext();
        }
      }, 8000);
      const noDataId = setTimeout(() => {
        if (runId !== state.runId) return;
        if (opened && state.priceMessages === startedMessages) {
          state.priceError = `价格流已连接但未收到数据：${baseUrl}/${streamName}`;
          renderRadar();
          try { ws.close(); } catch (_) {}
          tryNext();
        }
      }, 12000);
      ws.onopen = () => {
        if (runId !== state.runId) return;
        opened = true;
        clearTimeout(timeoutId);
        state.priceConnected = true;
        state.priceError = "";
        renderRadar();
      };
      ws.onclose = () => {
        if (runId !== state.runId) return;
        clearTimeout(timeoutId);
        clearTimeout(noDataId);
        state.priceConnected = false;
        renderRadar();
        if (opened && !movedOn) setTimeout(() => {
          if (runId === state.runId) connectPriceEndpoint(index, runId);
        }, 3000);
        else tryNext();
      };
      ws.onerror = () => {
        if (runId !== state.runId) return;
        state.priceError = `浏览器无法连接 Binance 价格流：${baseUrl}`;
        renderRadar();
      };
      ws.onmessage = event => {
        if (runId !== state.runId) return;
        state.priceMessages++;
        const payload = JSON.parse(event.data);
        const rows = Array.isArray(payload) ? payload : (Array.isArray(payload.data) ? payload.data : []);
        const ts = Date.now();
        for (const item of rows) {
          const symbol = item.s;
          if (!symbol || !WATCH_SYMBOLS.includes(symbol)) continue;
          const priceValue = Number(item.c || item.p || item.i || 0);
          if (priceValue > 0) rememberPrice(symbol, priceValue, ts);
        }
      };
    }
    function connectTrades(runId) {
      const streams = WATCH_SYMBOLS.map(symbol => symbol.toLowerCase() + "@aggTrade").join("/");
      connectTradeEndpoint(streams, 0, runId);
    }
    function connectTradeEndpoint(streams, index, runId) {
      const baseUrl = BINANCE_WS_BASES[index % BINANCE_WS_BASES.length];
      const ws = new WebSocket(`${baseUrl}/stream?streams=${streams}`);
      state.sockets.push(ws);
      let opened = false;
      let movedOn = false;
      const startedMessages = state.tradeMessages;
      const tryNext = () => {
        if (movedOn) return;
        movedOn = true;
        setTimeout(() => {
          if (runId === state.runId) connectTradeEndpoint(streams, index + 1, runId);
        }, 900);
      };
      const timeoutId = setTimeout(() => {
        if (runId !== state.runId) return;
        if (!opened && ws.readyState === WebSocket.CONNECTING) {
          state.tradeError = `大单流连接超时：${baseUrl}`;
          renderRadar();
          try { ws.close(); } catch (_) {}
          tryNext();
        }
      }, 8000);
      const noDataId = setTimeout(() => {
        if (runId !== state.runId) return;
        if (opened && state.tradeMessages === startedMessages) {
          state.tradeError = `大单流已连接但未收到数据：${baseUrl}`;
          renderRadar();
          try { ws.close(); } catch (_) {}
          tryNext();
        }
      }, 12000);
      ws.onopen = () => {
        if (runId !== state.runId) return;
        opened = true;
        clearTimeout(timeoutId);
        state.tradeConnected = true;
        state.tradeError = "";
        renderRadar();
      };
      ws.onclose = () => {
        if (runId !== state.runId) return;
        clearTimeout(timeoutId);
        clearTimeout(noDataId);
        state.tradeConnected = false;
        renderRadar();
        if (opened && !movedOn) setTimeout(() => {
          if (runId === state.runId) connectTradeEndpoint(streams, index, runId);
        }, 3000);
        else tryNext();
      };
      ws.onerror = () => {
        if (runId !== state.runId) return;
        state.tradeError = `浏览器无法连接 Binance 大单流：${baseUrl}`;
        renderRadar();
      };
      ws.onmessage = event => {
        if (runId !== state.runId) return;
        state.tradeMessages++;
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
    function connectLiquidations(runId) {
      connectLiquidationEndpoint(0, runId);
    }
    function connectLiquidationEndpoint(index, runId) {
      const baseUrl = BINANCE_WS_BASES[index % BINANCE_WS_BASES.length];
      const ws = new WebSocket(`${baseUrl}/ws/!forceOrder@arr`);
      state.sockets.push(ws);
      let opened = false;
      let movedOn = false;
      const tryNext = () => {
        if (movedOn) return;
        movedOn = true;
        setTimeout(() => {
          if (runId === state.runId) connectLiquidationEndpoint(index + 1, runId);
        }, 900);
      };
      const timeoutId = setTimeout(() => {
        if (runId !== state.runId) return;
        if (!opened && ws.readyState === WebSocket.CONNECTING) {
          state.liqError = `爆仓流连接超时：${baseUrl}`;
          renderRadar();
          try { ws.close(); } catch (_) {}
          tryNext();
        }
      }, 8000);
      ws.onopen = () => {
        if (runId !== state.runId) return;
        opened = true;
        clearTimeout(timeoutId);
        state.liqConnected = true;
        state.liqError = "";
        renderRadar();
      };
      ws.onclose = () => {
        if (runId !== state.runId) return;
        clearTimeout(timeoutId);
        state.liqConnected = false;
        renderRadar();
        if (opened) setTimeout(() => {
          if (runId === state.runId) connectLiquidationEndpoint(index, runId);
        }, 3000);
        else tryNext();
      };
      ws.onerror = () => {
        if (runId !== state.runId) return;
        state.liqError = `浏览器无法连接 Binance 爆仓流：${baseUrl}`;
        renderRadar();
      };
      ws.onmessage = event => {
        if (runId !== state.runId) return;
        state.liqMessages++;
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
      state.runId++;
      const runId = state.runId;
      closeSockets();
      connectPrices(runId);
      connectTrades(runId);
      connectLiquidations(runId);
      fetchDerivatives();
      if (!state.derivativesTimer) {
        state.derivativesTimer = setInterval(fetchDerivatives, 45 * 1000);
      }
      renderRadar();
      renderEvents();
    }
    loadSignalLog();
    document.getElementById("refresh").addEventListener("click", start);
    document.getElementById("aiBtn").addEventListener("click", runAiAnalysis);
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
    html = html.replace("__BINANCE_WS_BASES__", json.dumps(BINANCE_WS_BASES))
    html = html.replace("__BINANCE_REST_BASES__", json.dumps(BINANCE_REST_BASES))
    return render_template_string(html)


@app.route("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "mode": "browser_direct_binance_websocket",
            "watch_symbols": WATCH_SYMBOLS,
            "large_trade_usd": LARGE_TRADE_USD,
            "binance_ws_bases": BINANCE_WS_BASES,
            "binance_rest_bases": BINANCE_REST_BASES,
        }
    )


@app.route("/debug/binance")
def debug_binance():
    return jsonify(
        {
            "message": "Render no longer fetches Binance. The browser connects directly to Binance WebSocket.",
            "binance_ws_bases": BINANCE_WS_BASES,
            "binance_rest_bases": BINANCE_REST_BASES,
        }
    )


@app.post("/api/ai/analyze")
def ai_analyze():
    payload = request.get_json(silent=True) or {}
    fallback = rule_based_analysis(payload)
    analysis, mode = call_ai_analysis(payload, fallback)
    return jsonify(
        {
            "analysis": analysis,
            "mode": mode,
            "model": AI_MODEL if mode == "ai" else None,
            "has_ai_key": bool(AI_API_KEY),
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
