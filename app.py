from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from flask import Flask, jsonify, render_template_string, request


app = Flask(__name__)

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
    "TONUSDT", "TRXUSDT", "NEARUSDT", "APTUSDT", "OPUSDT",
    "ARBUSDT", "SEIUSDT", "INJUSDT", "RUNEUSDT", "DOTUSDT",
    "UNIUSDT", "AAVEUSDT", "FILUSDT", "LTCUSDT", "WIFUSDT",
    "ORDIUSDT", "ENAUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "1000BONKUSDT",
]

SEED_SYMBOLS = [
    symbol.strip().upper()
    for symbol in os.environ.get("WATCH_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",")
    if symbol.strip()
]

MAX_STREAM_SYMBOLS = int(os.environ.get("MAX_STREAM_SYMBOLS", "180"))
TRADE_STREAM_CHUNK_SIZE = int(os.environ.get("TRADE_STREAM_CHUNK_SIZE", "60"))
LARGE_TRADE_USD = float(os.environ.get("LARGE_TRADE_USD", "50000"))
MIN_DYNAMIC_TRADE_USD = float(os.environ.get("MIN_DYNAMIC_TRADE_USD", "10000"))

BINANCE_WS = os.environ.get("BINANCE_WS", "wss://fstream.binance.com/market").rstrip("/")
if BINANCE_WS in {"wss://fstream.binance.com", "wss://fstream.binancefuture.com"}:
    BINANCE_WS += "/market"
BINANCE_WS_BASES = [
    url.strip().rstrip("/")
    for url in os.environ.get(
        "BINANCE_WS_BASES",
        "wss://fstream.binance.com/market,wss://fstream.binancefuture.com/market,"
        "wss://fstream.binance.com,wss://fstream.binancefuture.com",
    ).split(",")
    if url.strip()
]
if BINANCE_WS not in BINANCE_WS_BASES:
    BINANCE_WS_BASES.insert(0, BINANCE_WS)

BINANCE_REST = os.environ.get("BINANCE_REST", "https://fapi.binance.com").rstrip("/")
BINANCE_REST_BASES = [
    url.strip().rstrip("/")
    for url in os.environ.get(
        "BINANCE_REST_BASES",
        "https://fapi.binance.com,https://fapi.binancefuture.com",
    ).split(",")
    if url.strip()
]
if BINANCE_REST not in BINANCE_REST_BASES:
    BINANCE_REST_BASES.insert(0, BINANCE_REST)

AI_API_KEY = os.environ.get("AI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
AI_API_BASE = os.environ.get("AI_API_BASE") or (
    "https://api.deepseek.com" if os.environ.get("DEEPSEEK_API_KEY") else "https://api.openai.com/v1"
)
AI_MODEL = os.environ.get("AI_MODEL") or ("deepseek-chat" if os.environ.get("DEEPSEEK_API_KEY") else "gpt-4o-mini")


def rule_analysis(payload: dict) -> str:
    rows = (payload.get("rows") or [])[:15]
    events = payload.get("events") or []
    if not rows:
        return "暂无足够数据。先等待价格流和大单流累计 1-2 分钟。"

    follow = [row for row in rows if row.get("follow") in {"FOLLOW_LONG", "FOLLOW_SHORT"}]
    watch = [row for row in rows if row.get("follow") in {"WATCH_LONG", "WATCH_SHORT"}]
    lines = ["当前大资金结论："]
    if follow:
        names = "、".join(f"{row.get('base')}({row.get('label')}/{row.get('score')})" for row in follow[:5])
        lines.append(f"- 可重点盯盘候选：{names}。")
        lines.append("- 这不是立刻追单，必须等事件流继续同向、价格不反抽/不反砸。")
    elif watch:
        names = "、".join(f"{row.get('base')}({row.get('label')}/{row.get('score')})" for row in watch[:5])
        lines.append(f"- 有资金异动但还不适合跟：{names}。")
        lines.append("- 原因通常是价格没确认、净流不连续，或只有孤立大单。")
    else:
        lines.append("- 当前没有高质量可跟单信号，适合等待。")

    long_count = sum(1 for row in follow if row.get("follow") == "FOLLOW_LONG")
    short_count = sum(1 for row in follow if row.get("follow") == "FOLLOW_SHORT")
    if long_count and short_count:
        lines.append("- 多空候选同时存在，市场分歧大，山寨币追单风险更高。")

    if events:
        freq = {}
        for item in events[:40]:
            name = item.get("base") or item.get("symbol") or ""
            if name:
                freq[name] = freq.get(name, 0) + 1
        active = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
        if active:
            lines.append("- 事件流最活跃：" + "、".join(f"{name}({count})" for name, count in active))

    lines.append("")
    lines.append("跟单条件：")
    lines.append("- 60s 净流和 5m 净流同方向。")
    lines.append("- 价格 5m 方向和资金方向一致。")
    lines.append("- 同币种事件流连续出现，不是孤立一笔。")
    lines.append("- BTC/ETH 没有明显反向压制。")
    lines.append("")
    lines.append("放弃条件：")
    lines.append("- 分数高但价格不动，容易是对倒或诱单。")
    lines.append("- 大单后马上反向，说明跟单窗口已经失效。")
    lines.append("- 山寨币拉升后连续主动卖，优先看成出货风险。")
    return "\n".join(lines)


def call_ai(payload: dict, fallback: str) -> tuple[str, str]:
    if not AI_API_KEY:
        return fallback, "rules"
    compact = {
        "summary": payload.get("summary", {}),
        "rows": (payload.get("rows") or [])[:15],
        "events": (payload.get("events") or [])[:30],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是加密货币合约资金流分析助手。只分析公开行情快照，"
                "输出：哪里有大资金、是否适合跟单、跟单前确认、放弃条件。"
                "不要承诺收益，不要直接喊无脑买卖。"
            ),
        },
        {"role": "user", "content": json.dumps(compact, ensure_ascii=False)},
    ]
    body = json.dumps({"model": AI_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 900}).encode()
    req = urllib.request.Request(
        AI_API_BASE.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip(), "ai"
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
        return fallback + f"\n\nAI 调用失败，已使用内置规则。错误：{exc}", "rules"


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
    button,input { font:inherit; }
    .topbar { height:58px; padding:0 22px; background:rgba(255,255,255,.96); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:10; }
    .brand { display:flex; align-items:center; gap:10px; font-weight:850; }
    .brand-mark { width:30px; height:30px; border-radius:8px; background:var(--ink); color:#fff; display:grid; place-items:center; font-size:13px; font-weight:900; }
    .statusbar { display:flex; align-items:center; gap:8px; color:var(--muted); font-size:12px; }
    .dot { width:8px; height:8px; border-radius:50%; background:#a8b2c1; }
    .dot.ok { background:var(--green); box-shadow:0 0 0 3px rgba(8,127,91,.12); }
    .dot.bad { background:var(--red); box-shadow:0 0 0 3px rgba(201,42,42,.12); }
    .page { max-width:1560px; margin:0 auto; padding:16px 20px 24px; }
    .controls { display:grid; grid-template-columns:1fr auto auto; gap:10px; align-items:center; margin-bottom:12px; }
    .search { width:100%; border:1px solid var(--line); background:var(--surface); border-radius:8px; padding:10px 12px; color:var(--text); outline:none; }
    .segmented { display:flex; background:var(--surface); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .segmented button { border:0; border-right:1px solid var(--line); background:transparent; color:var(--muted); padding:9px 12px; cursor:pointer; min-width:68px; }
    .segmented button:last-child { border-right:0; }
    .segmented button.active { color:#fff; background:var(--ink); }
    .refresh,.ai-btn { border:1px solid var(--ink); background:var(--ink); color:#fff; border-radius:8px; padding:9px 13px; cursor:pointer; white-space:nowrap; }
    .ai-btn:disabled { opacity:.55; cursor:wait; }
    .stats { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin-bottom:12px; }
    .stat { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:12px; min-height:82px; }
    .label { color:var(--muted); font-size:12px; font-weight:750; margin-bottom:8px; }
    .value { color:var(--ink); font-size:22px; font-weight:900; white-space:nowrap; }
    .sub { color:var(--muted); font-size:12px; margin-top:4px; }
    .up { color:var(--green); font-weight:850; }
    .down { color:var(--red); font-weight:850; }
    .layout { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:12px; align-items:start; }
    .panel,.ai-panel { background:var(--surface); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .ai-panel { margin-bottom:12px; }
    .panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 14px; border-bottom:1px solid var(--line); background:var(--surface2); }
    .panel-title { font-weight:850; }
    .panel-note { color:var(--muted); font-size:12px; }
    .ai-body { padding:12px 14px; font-size:13px; line-height:1.65; white-space:pre-wrap; min-height:92px; }
    .table-wrap { overflow-x:auto; }
    table { width:100%; border-collapse:collapse; font-size:12.5px; }
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
    .event-list { max-height:760px; overflow:auto; }
    .event { display:grid; grid-template-columns:58px 1fr; gap:8px; padding:10px 12px; border-bottom:1px solid #edf1f5; }
    .event-side { font-size:11px; font-weight:900; }
    .event-side.buy { color:var(--green); }
    .event-side.sell { color:var(--red); }
    .event-title { display:flex; justify-content:space-between; gap:8px; font-size:12px; font-weight:850; }
    .event-meta { color:var(--muted); font-size:11px; margin-top:3px; }
    .warn { margin-top:12px; border:1px solid #efd897; background:var(--amber-bg); color:#744b00; border-radius:8px; padding:10px 12px; font-size:12px; line-height:1.55; }
    @media (max-width:1100px) { .layout{grid-template-columns:1fr;} .stats{grid-template-columns:repeat(2,minmax(0,1fr));} .controls{grid-template-columns:1fr;} .segmented{overflow-x:auto;} .statusbar{display:none;} }
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
        <button data-filter="follow">可跟</button>
        <button data-filter="long">多头资金</button>
        <button data-filter="short">空头资金</button>
        <button data-filter="alts">山寨</button>
      </div>
      <button class="refresh" id="refresh">重连</button>
    </div>
    <section class="stats">
      <div class="stat"><div class="label">扫描交易对</div><div class="value" id="statSymbols">--</div><div class="sub" id="scopeSub">自动扩展范围</div></div>
      <div class="stat"><div class="label">可跟多头候选</div><div class="value up" id="statLong">--</div><div class="sub">资金与价格同向</div></div>
      <div class="stat"><div class="label">可跟空头候选</div><div class="value down" id="statShort">--</div><div class="sub">资金与价格同向</div></div>
      <div class="stat"><div class="label">60 秒大单流</div><div class="value" id="statFlow">--</div><div class="sub">动态阈值累计</div></div>
      <div class="stat"><div class="label">5 分钟爆仓</div><div class="value" id="statLiq">--</div><div class="sub">强平订单流</div></div>
    </section>
    <section class="ai-panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">AI 跟单分析</div>
          <div class="panel-note">分析哪里有大资金、是否值得跟，不读取账户，不自动下单</div>
        </div>
        <button class="ai-btn" id="aiBtn">分析当前资金流</button>
      </div>
      <div class="ai-body" id="aiOutput">等待行情累计 1-2 分钟后点击分析。没有配置 AI Key 时会使用内置规则分析。</div>
    </section>
    <section class="layout">
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">大资金流动雷达</div>
            <div class="panel-note" id="radarNote">自动扫描高成交额 USDT 永续，寻找可跟单资金流</div>
          </div>
          <div class="panel-note" id="errorNote"></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>交易对</th><th>判断</th><th>分数</th><th>价格</th><th>5m</th><th>24h成交</th>
                <th>60s净流</th><th>5m净流</th><th>最大单</th><th>OI15m</th><th>Taker</th><th>依据</th>
              </tr>
            </thead>
            <tbody id="radarBody"><tr><td colspan="12">正在连接 Binance...</td></tr></tbody>
          </table>
        </div>
      </div>
      <aside class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">实时大单与爆仓</div>
            <div class="panel-note">达到动态阈值后进入事件流</div>
          </div>
        </div>
        <div class="event-list" id="eventList"></div>
      </aside>
    </section>
    <div class="warn">
      这个工具用于发现大资金流动和缩小观察范围，不构成投资建议。“可跟”只是盯盘候选，不代表可以无脑追单；必须结合止损、盘口和 BTC/ETH 大盘方向。
    </div>
  </main>
  <script>
    const SEED_SYMBOLS = __SEED_SYMBOLS__;
    const MAX_STREAM_SYMBOLS = __MAX_STREAM_SYMBOLS__;
    const TRADE_STREAM_CHUNK_SIZE = __TRADE_STREAM_CHUNK_SIZE__;
    const LARGE_TRADE_USD = __LARGE_TRADE_USD__;
    const MIN_DYNAMIC_TRADE_USD = __MIN_DYNAMIC_TRADE_USD__;
    const BINANCE_WS_BASES = __BINANCE_WS_BASES__;
    const BINANCE_REST_BASES = __BINANCE_REST_BASES__;
    const STABLE_SYMBOLS = new Set(["USDCUSDT","BUSDUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT"]);
    const MAJORS = new Set(["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]);

    const state = {
      activeSymbols:[...SEED_SYMBOLS], marketMeta:new Map(), derivatives:new Map(),
      prices:new Map(), priceHistory:new Map(), trades:new Map(), liquidations:new Map(), events:[],
      sockets:[], runId:0, activeFilter:"all",
      priceConnected:false, tradeConnected:false, liqConnected:false,
      priceError:"", tradeError:"", liqError:"", restError:"",
      priceMessages:0, tradeMessages:0, liqMessages:0, derivativesUpdatedAt:0,
      marketTimer:null, derivativesTimer:null,
    };

    function showClientError(message){
      const note=document.getElementById("errorNote");
      const conn=document.getElementById("connText");
      if(note)note.textContent=message;
      if(conn)conn.textContent="页面脚本错误";
    }
    window.addEventListener("error", event=>showClientError("页面脚本错误："+event.message));
    window.addEventListener("unhandledrejection", event=>showClientError("页面异步错误："+(event.reason&&event.reason.message?event.reason.message:event.reason)));

    function activeSymbols(){ return state.activeSymbols.length ? state.activeSymbols : SEED_SYMBOLS; }
    function activeSet(){ return new Set(activeSymbols()); }
    function base(symbol){ return symbol.replace("USDT",""); }
    function now(){ return Date.now(); }
    function ensureList(map, key){ if(!map.has(key)) map.set(key, []); return map.get(key); }
    function cutoff(rows, ms){ const cut = now() - ms; return rows.filter(row => row.ts >= cut); }
    function money(value){ value=Number(value||0); if(Math.abs(value)>=1e9)return "$"+(value/1e9).toFixed(2)+"B"; if(Math.abs(value)>=1e6)return "$"+(value/1e6).toFixed(2)+"M"; if(Math.abs(value)>=1e3)return "$"+(value/1e3).toFixed(0)+"K"; return "$"+value.toFixed(0); }
    function price(value){ value=Number(value||0); if(!value)return "--"; if(value>=100)return "$"+value.toLocaleString(undefined,{maximumFractionDigits:2}); if(value>=1)return "$"+value.toLocaleString(undefined,{maximumFractionDigits:4}); return "$"+value.toLocaleString(undefined,{maximumFractionDigits:8}); }
    function signedPct(value){ value=Number(value||0); const cls=value>=0?"up":"down"; const sign=value>0?"+":""; return `<span class="${cls}">${sign}${value.toFixed(2)}%</span>`; }
    function tradeThreshold(symbol){ const meta=state.marketMeta.get(symbol)||{}; const vol=Number(meta.quoteVolume||0); if(!vol)return LARGE_TRADE_USD; return Math.max(MIN_DYNAMIC_TRADE_USD, Math.min(LARGE_TRADE_USD, vol * 0.00008)); }
    function rememberPrice(symbol, value, ts){ state.prices.set(symbol, value); const rows=ensureList(state.priceHistory, symbol); rows.push({ts, value}); while(rows.length>600 || (rows.length && rows[0].ts<now()-6*60*1000)) rows.shift(); }
    function price5m(symbol){ const rows=state.priceHistory.get(symbol)||[]; if(rows.length<2)return 0; const recent=rows[rows.length-1].value; const old=(rows.find(row=>row.ts>=now()-5*60*1000)||rows[0]).value; return old ? (recent-old)/old*100 : 0; }
    async function fetchJson(path){ let last; for(const host of BINANCE_REST_BASES){ try{ const res=await fetch(host+path,{cache:"no-store"}); if(!res.ok)throw new Error(`${res.status} ${res.statusText}`); return await res.json(); }catch(err){ last=err; } } throw last || new Error("Binance REST unavailable"); }

    async function refreshMarketUniverse(){
      try{
        const data=await fetchJson("/fapi/v1/ticker/24hr");
        const rows=data.filter(x=>x.symbol&&x.symbol.endsWith("USDT")&&!STABLE_SYMBOLS.has(x.symbol))
          .map(x=>({symbol:x.symbol, quoteVolume:Number(x.quoteVolume||0), changePct:Number(x.priceChangePercent||0), count:Number(x.count||0), lastPrice:Number(x.lastPrice||0)}))
          .filter(x=>x.quoteVolume>0).sort((a,b)=>b.quoteVolume-a.quoteVolume);
        const selected=[];
        for(const sym of SEED_SYMBOLS){ if(rows.some(x=>x.symbol===sym) && !selected.includes(sym)) selected.push(sym); }
        for(const item of rows){
          state.marketMeta.set(item.symbol,item);
          if(item.lastPrice>0) rememberPrice(item.symbol,item.lastPrice,Date.now());
          if(!selected.includes(item.symbol)) selected.push(item.symbol);
          if(selected.length>=MAX_STREAM_SYMBOLS) break;
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
            state.derivatives.set(item.symbol,{...prev, fundingRate:Number(item.lastFundingRate||0)*100, updatedAt:ts});
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
      state.derivatives.set(symbol,next);
    }

    function flow(symbol, ms){ const rows=cutoff(state.trades.get(symbol)||[],ms); let buy=0,sell=0,largest=0; for(const row of rows){ if(row.side==="BUY")buy+=row.notional; else sell+=row.notional; largest=Math.max(largest,row.notional); } return {buy,sell,net:buy-sell,total:buy+sell,largest}; }
    function liq(symbol, ms){ const rows=cutoff(state.liquidations.get(symbol)||[],ms); let longLiq=0,shortLiq=0; for(const row of rows){ if(row.side==="SELL")longLiq+=row.notional; else shortLiq+=row.notional; } return {longLiq,shortLiq,total:longLiq+shortLiq}; }
    function derivative(symbol){ return state.derivatives.get(symbol)||{oi15Pct:null,takerRatio:null,fundingRate:null}; }
    function meta(symbol){ return state.marketMeta.get(symbol)||{}; }

    function scoreRow(symbol){
      const f60=flow(symbol,60*1000), f5=flow(symbol,5*60*1000), l5=liq(symbol,5*60*1000), p5=price5m(symbol), d=derivative(symbol), threshold=tradeThreshold(symbol);
      let long=0, short=0; const ratio=f60.total?f60.net/f60.total:0;
      if(ratio>0)long+=Math.min(35,ratio*35); else short+=Math.min(35,Math.abs(ratio)*35);
      const size=Math.min(22,f60.total/threshold*8); if(f60.net>0)long+=size; if(f60.net<0)short+=size;
      if(f5.net>0)long+=Math.min(18,Math.abs(f5.net)/threshold*3); if(f5.net<0)short+=Math.min(18,Math.abs(f5.net)/threshold*3);
      if(p5>0)long+=Math.min(14,p5*2.5); if(p5<0)short+=Math.min(14,Math.abs(p5)*2.5);
      if(d.oi15Pct!==null&&d.oi15Pct>1.2){ if(p5>=0&&f5.net>=0)long+=Math.min(15,d.oi15Pct*3); if(p5<=0&&f5.net<=0)short+=Math.min(15,d.oi15Pct*3); }
      if(d.takerRatio!==null&&d.takerRatio>1.12)long+=Math.min(10,(d.takerRatio-1)*20); if(d.takerRatio!==null&&d.takerRatio<0.9)short+=Math.min(10,(1-d.takerRatio)*20);
      if(d.fundingRate!==null&&d.fundingRate>0.04)long-=4; if(d.fundingRate!==null&&d.fundingRate<-0.04)short-=4;
      long=Math.max(0,Math.min(100,long)); short=Math.max(0,Math.min(100,short));
      const signal=long>=short&&long>=35?"LONG":short>long&&short>=35?"SHORT":"WATCH"; const score=Math.round(Math.max(long,short));
      const reasons=[];
      if(Math.abs(f60.net)>=threshold)reasons.push((f60.net>0?"主动买净流 ":"主动卖净流 ")+money(Math.abs(f60.net)));
      if(f60.largest>=threshold)reasons.push("最大单 "+money(f60.largest));
      if(Math.abs(p5)>=0.6)reasons.push("5m价格 "+(p5>0?"+":"")+p5.toFixed(2)+"%");
      if(d.oi15Pct!==null&&Math.abs(d.oi15Pct)>=1.2)reasons.push("OI15m "+(d.oi15Pct>0?"+":"")+d.oi15Pct.toFixed(2)+"%");
      if(d.takerRatio!==null&&(d.takerRatio>=1.12||d.takerRatio<=0.9))reasons.push("Taker "+d.takerRatio.toFixed(2));
      if(!reasons.length)reasons.push("等待大额资金流");
      const alignedLong=signal==="LONG"&&score>=65&&f60.net>0&&f5.net>0&&p5>=0&&f60.largest>=threshold;
      const alignedShort=signal==="SHORT"&&score>=65&&f60.net<0&&f5.net<0&&p5<=0&&f60.largest>=threshold;
      const follow=alignedLong?"FOLLOW_LONG":alignedShort?"FOLLOW_SHORT":signal==="LONG"?"WATCH_LONG":signal==="SHORT"?"WATCH_SHORT":"WAIT";
      const label=follow==="FOLLOW_LONG"?"可跟多":follow==="FOLLOW_SHORT"?"可跟空":follow==="WATCH_LONG"?"多头异动":follow==="WATCH_SHORT"?"空头异动":"观察";
      return {symbol,base:base(symbol),price:state.prices.get(symbol)||0,p5,f60,f5,l5,d,m:meta(symbol),threshold,signal,score,follow,label,reasons};
    }
    function rows(){ return activeSymbols().map(scoreRow).sort((a,b)=>b.score-a.score||Math.abs(b.f60.net)-Math.abs(a.f60.net)||Number(b.m.quoteVolume||0)-Number(a.m.quoteVolume||0)); }
    function filteredRows(){ const q=document.getElementById("search").value.trim().toUpperCase(); return rows().filter(r=>{ if(q&&!r.symbol.includes(q)&&!r.base.includes(q))return false; if(state.activeFilter==="follow")return r.follow==="FOLLOW_LONG"||r.follow==="FOLLOW_SHORT"; if(state.activeFilter==="long")return r.signal==="LONG"; if(state.activeFilter==="short")return r.signal==="SHORT"; if(state.activeFilter==="alts")return !MAJORS.has(r.symbol); return true; }); }
    function badge(row){ if(row.follow==="FOLLOW_LONG")return '<span class="badge long">可跟多</span>'; if(row.follow==="FOLLOW_SHORT")return '<span class="badge short">可跟空</span>'; if(row.follow==="WATCH_LONG")return '<span class="badge long">多头异动</span>'; if(row.follow==="WATCH_SHORT")return '<span class="badge short">空头异动</span>'; return '<span class="badge watch">观察</span>'; }
    function setDot(id,ok,err){ const el=document.getElementById(id); el.classList.toggle("ok",ok); el.classList.toggle("bad",!!err); }
    function addEvent(ev){ state.events.unshift(ev); state.events=state.events.slice(0,220); }

    function renderStats(all){ document.getElementById("statSymbols").textContent=activeSymbols().length; document.getElementById("statLong").textContent=all.filter(r=>r.follow==="FOLLOW_LONG").length; document.getElementById("statShort").textContent=all.filter(r=>r.follow==="FOLLOW_SHORT").length; document.getElementById("statFlow").textContent=money(all.reduce((s,r)=>s+r.f60.total,0)); document.getElementById("statLiq").textContent=money(all.reduce((s,r)=>s+r.l5.total,0)); setDot("priceDot",state.priceConnected,state.priceError); setDot("tradeDot",state.tradeConnected,state.tradeError); setDot("liqDot",state.liqConnected,state.liqError); const err=[state.priceError,state.tradeError,state.liqError,state.restError].filter(Boolean); document.getElementById("connText").textContent=err.length?"连接错误":`实时连接中 · 价格${state.priceMessages} 大单${state.tradeMessages} 范围${activeSymbols().length}`; document.getElementById("errorNote").textContent=err[0]||""; }
    function render(){ const all=rows(), visible=filteredRows(); renderStats(all); const body=document.getElementById("radarBody"); if(!visible.length){ body.innerHTML='<tr><td colspan="12">当前筛选条件下暂无大资金流。</td></tr>'; return; } body.innerHTML=visible.slice(0,90).map(row=>{ const n60=row.f60.net>=0?"up":"down", n5=row.f5.net>=0?"up":"down"; const reasons=row.reasons.map(x=>`<span class="chip">${x}</span>`).join(""); return `<tr><td><div class="symbol">${row.base}</div><div class="small">${row.symbol}</div></td><td>${badge(row)}</td><td><span class="score">${row.score}</span></td><td class="num">${price(row.price)}</td><td class="num">${signedPct(row.p5)}</td><td class="num">${money(row.m.quoteVolume||0)}</td><td class="num ${n60}">${row.f60.net>=0?"+":"-"}${money(Math.abs(row.f60.net))}</td><td class="num ${n5}">${row.f5.net>=0?"+":"-"}${money(Math.abs(row.f5.net))}</td><td class="num">${money(row.f60.largest||row.f5.largest)}</td><td class="num">${row.d.oi15Pct===null?'<span class="small">--</span>':signedPct(row.d.oi15Pct)}</td><td class="num">${row.d.takerRatio===null?'<span class="small">--</span>':row.d.takerRatio.toFixed(2)}</td><td><div class="reason">${reasons}</div></td></tr>`; }).join(""); }
    function renderEvents(){ const list=document.getElementById("eventList"); if(!state.events.length){ list.innerHTML='<div class="event"><div></div><div><div class="event-title">等待大额事件</div><div class="event-meta">达到阈值后会显示在这里</div></div></div>'; return; } list.innerHTML=state.events.slice(0,120).map(ev=>{ const side=ev.side==="BUY"?"buy":"sell"; return `<div class="event"><div class="event-side ${side}">${ev.label}</div><div><div class="event-title"><span>${base(ev.symbol)}</span><span>${money(ev.notional)}</span></div><div class="event-meta">${price(ev.price)} · ${new Date(ev.ts).toLocaleTimeString()} · 阈值${money(ev.threshold)}</div></div></div>`; }).join(""); }
    function compactRows(){ return rows().slice(0,18).map(r=>({symbol:r.symbol,base:r.base,label:r.label,follow:r.follow,score:r.score,price:r.price,price_5m_pct:Number(r.p5.toFixed(3)),volume_24h_usd:Math.round(r.m.quoteVolume||0),net_60s_usd:Math.round(r.f60.net),net_5m_usd:Math.round(r.f5.net),largest_usd:Math.round(r.f60.largest||r.f5.largest),oi_15m_pct:r.d.oi15Pct,taker_ratio:r.d.takerRatio,reasons:r.reasons})); }
    function compactEvents(){ return state.events.slice(0,40).map(e=>({symbol:e.symbol,base:base(e.symbol),label:e.label,side:e.side,price:e.price,notional:Math.round(e.notional),time:new Date(e.ts).toLocaleTimeString()})); }
    async function runAi(){ const btn=document.getElementById("aiBtn"), out=document.getElementById("aiOutput"); btn.disabled=true; out.textContent="正在分析当前大资金流..."; try{ const all=rows(); const payload={summary:{scanned_symbols:activeSymbols().length,follow_long:all.filter(r=>r.follow==="FOLLOW_LONG").length,follow_short:all.filter(r=>r.follow==="FOLLOW_SHORT").length,large_trade_threshold_usd:LARGE_TRADE_USD,generated_at:new Date().toLocaleString()},rows:compactRows(),events:compactEvents()}; const res=await fetch("/api/ai/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); const data=await res.json(); out.textContent=(data.mode==="ai"?"AI 分析\n\n":"规则分析\n\n")+data.analysis; }catch(err){ out.textContent="分析失败："+err; }finally{ btn.disabled=false; } }
    function trimOld(){ const cut=now()-6*60*1000; for(const map of [state.trades,state.liquidations]){ for(const [sym,list] of map){ while(list.length&&list[0].ts<cut)list.shift(); if(!list.length)map.delete(sym); } } }

    function closeSockets(){ for(const ws of state.sockets){ try{ws.close();}catch(_){}} state.sockets=[]; state.priceConnected=false; state.tradeConnected=false; state.liqConnected=false; state.priceError=""; state.tradeError=""; state.liqError=""; state.priceMessages=0; state.tradeMessages=0; state.liqMessages=0; }
    function connectPrice(runId,index=0){ const host=BINANCE_WS_BASES[index%BINANCE_WS_BASES.length]; const ws=new WebSocket(`${host}/ws/!ticker@arr`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectPrice(runId,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.priceError=`价格流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.priceConnected=true; state.priceError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.priceConnected=false; setTimeout(()=>{ if(runId===state.runId)connectPrice(runId,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.priceError=`价格流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.priceMessages++; const arr=JSON.parse(e.data); const set=activeSet(), ts=Date.now(); for(const item of arr){ if(!set.has(item.s))continue; const p=Number(item.c||0); if(p>0)rememberPrice(item.s,p,ts); const prev=state.marketMeta.get(item.s)||{}; state.marketMeta.set(item.s,{...prev,symbol:item.s,quoteVolume:Number(item.q||prev.quoteVolume||0),changePct:Number(item.P||prev.changePct||0),lastPrice:p}); } }; }
    function connectTrades(runId){ const syms=activeSymbols(); for(let i=0;i<syms.length;i+=TRADE_STREAM_CHUNK_SIZE){ connectTradeChunk(runId,syms.slice(i,i+TRADE_STREAM_CHUNK_SIZE),0); } }
    function connectTradeChunk(runId,syms,index){ if(!syms.length)return; const host=BINANCE_WS_BASES[index%BINANCE_WS_BASES.length]; const streams=syms.map(s=>s.toLowerCase()+"@aggTrade").join("/"); const ws=new WebSocket(`${host}/stream?streams=${streams}`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectTradeChunk(runId,syms,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.tradeError=`大单流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.tradeConnected=true; state.tradeError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.tradeConnected=false; setTimeout(()=>{ if(runId===state.runId)connectTradeChunk(runId,syms,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.tradeError=`大单流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.tradeMessages++; const data=JSON.parse(e.data).data||{}; const symbol=data.s; if(!activeSet().has(symbol))return; const p=Number(data.p||0), q=Number(data.q||0), notional=p*q, threshold=tradeThreshold(symbol); if(p>0)rememberPrice(symbol,p,data.T||Date.now()); if(notional<threshold)return; const side=data.m?"SELL":"BUY"; const row={symbol,side,ts:data.T||Date.now(),price:p,qty:q,notional,threshold}; ensureList(state.trades,symbol).push(row); addEvent({...row,label:side==="BUY"?"主动买":"主动卖"}); }; }
    function reconnectTradesOnly(){ state.runId++; const runId=state.runId; for(const ws of state.sockets){ try{ws.close();}catch(_){} } state.sockets=[]; connectPrice(runId); connectTrades(runId); connectLiquidations(runId); }
    function connectLiquidations(runId,index=0){ const host=BINANCE_WS_BASES[index%BINANCE_WS_BASES.length]; const ws=new WebSocket(`${host}/ws/!forceOrder@arr`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectLiquidations(runId,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.liqError=`爆仓流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.liqConnected=true; state.liqError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.liqConnected=false; setTimeout(()=>{ if(runId===state.runId)connectLiquidations(runId,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.liqError=`爆仓流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.liqMessages++; const order=(JSON.parse(e.data)||{}).o||{}; const symbol=order.s; if(!activeSet().has(symbol))return; const p=Number(order.ap||order.p||0), q=Number(order.q||0), notional=p*q, threshold=tradeThreshold(symbol); if(notional<threshold)return; const side=order.S||""; const row={symbol,side,ts:order.T||Date.now(),price:p,qty:q,notional,threshold}; ensureList(state.liquidations,symbol).push(row); addEvent({...row,label:side==="BUY"?"空爆":"多爆"}); }; }
    async function start(){ state.runId++; const runId=state.runId; closeSockets(); await refreshMarketUniverse(); connectPrice(runId); connectTrades(runId); connectLiquidations(runId); fetchDerivatives(); if(!state.marketTimer)state.marketTimer=setInterval(refreshMarketUniverse,60*1000); if(!state.derivativesTimer)state.derivativesTimer=setInterval(fetchDerivatives,45*1000); render(); renderEvents(); }
    document.getElementById("refresh").addEventListener("click",start);
    document.getElementById("aiBtn").addEventListener("click",runAi);
    document.getElementById("search").addEventListener("input",render);
    document.getElementById("filters").addEventListener("click",e=>{ if(!e.target.dataset.filter)return; state.activeFilter=e.target.dataset.filter; document.querySelectorAll("#filters button").forEach(btn=>btn.classList.toggle("active",btn.dataset.filter===state.activeFilter)); render(); });
    setInterval(()=>{ trimOld(); render(); renderEvents(); },1000);
    start();
  </script>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    html = HTML.replace("__SEED_SYMBOLS__", json.dumps(SEED_SYMBOLS))
    html = html.replace("__MAX_STREAM_SYMBOLS__", json.dumps(MAX_STREAM_SYMBOLS))
    html = html.replace("__TRADE_STREAM_CHUNK_SIZE__", json.dumps(TRADE_STREAM_CHUNK_SIZE))
    html = html.replace("__LARGE_TRADE_USD__", json.dumps(LARGE_TRADE_USD))
    html = html.replace("__MIN_DYNAMIC_TRADE_USD__", json.dumps(MIN_DYNAMIC_TRADE_USD))
    html = html.replace("__BINANCE_WS_BASES__", json.dumps(BINANCE_WS_BASES))
    html = html.replace("__BINANCE_REST_BASES__", json.dumps(BINANCE_REST_BASES))
    return render_template_string(html)


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "mode": "wide_money_flow_radar",
        "seed_symbols": SEED_SYMBOLS,
        "max_stream_symbols": MAX_STREAM_SYMBOLS,
        "trade_stream_chunk_size": TRADE_STREAM_CHUNK_SIZE,
        "large_trade_usd": LARGE_TRADE_USD,
        "min_dynamic_trade_usd": MIN_DYNAMIC_TRADE_USD,
        "binance_ws_bases": BINANCE_WS_BASES,
        "binance_rest_bases": BINANCE_REST_BASES,
    })


@app.post("/api/ai/analyze")
def ai_analyze():
    payload = request.get_json(silent=True) or {}
    fallback = rule_analysis(payload)
    analysis, mode = call_ai(payload, fallback)
    return jsonify({"analysis": analysis, "mode": mode, "model": AI_MODEL if mode == "ai" else None})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
