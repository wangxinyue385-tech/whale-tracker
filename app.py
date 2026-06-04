from __future__ import annotations

import json
import hashlib
import hmac
import os
import threading
import time
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

from flask import Flask, jsonify, render_template_string, request
from signal_logger import fill_prices, get_recent, get_stats, init_db, log_signal


app = Flask(__name__)
init_db()

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
TAKER_FEE_BPS = float(os.environ.get("TAKER_FEE_BPS", "5"))
SLIPPAGE_BPS = float(os.environ.get("SLIPPAGE_BPS", "3"))
SAFETY_EDGE_BPS = float(os.environ.get("SAFETY_EDGE_BPS", "8"))
HOLD_MINUTES = float(os.environ.get("HOLD_MINUTES", "15"))

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

BINANCE_TESTNET_REST = os.environ.get("BINANCE_TESTNET_REST", "https://demo-fapi.binance.com").rstrip("/")
TESTNET_AUTO_CLOSE_MINUTES = float(os.environ.get("TESTNET_AUTO_CLOSE_MINUTES", "5"))
TESTNET_ORDER_USDT = float(os.environ.get("TESTNET_ORDER_USDT", "100"))
TESTNET_LEVERAGE = int(os.environ.get("TESTNET_LEVERAGE", "3"))
TESTNET_MAX_POSITIONS = int(os.environ.get("TESTNET_MAX_POSITIONS", "3"))
TESTNET_COOLDOWN_SECONDS = int(os.environ.get("TESTNET_COOLDOWN_SECONDS", "300"))

_trade_lock = threading.Lock()
_testnet_config = {
    "api_key": os.environ.get("BINANCE_TESTNET_API_KEY", ""),
    "api_secret": os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
    "auto_trade": os.environ.get("TESTNET_AUTO_TRADE", "0") == "1",
    "order_usdt": TESTNET_ORDER_USDT,
    "leverage": TESTNET_LEVERAGE,
    "max_positions": TESTNET_MAX_POSITIONS,
    "cooldown_seconds": TESTNET_COOLDOWN_SECONDS,
    "auto_close_minutes": TESTNET_AUTO_CLOSE_MINUTES,
}
_trade_cooldown: dict[str, int] = {}
_auto_positions: dict[str, dict] = {}
_trade_events: list[dict] = []
_equity_curve: list[dict] = []
_exchange_cache = {"ts": 0.0, "symbols": {}}


def _public_testnet_get(path: str, params: dict | None = None) -> dict:
    query = f"?{urlencode(params or {})}" if params else ""
    req = urllib.request.Request(BINANCE_TESTNET_REST + path + query, method="GET")
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _signed_testnet_request(method: str, path: str, params: dict | None = None) -> dict:
    cfg = _testnet_config
    if not cfg.get("api_key") or not cfg.get("api_secret"):
        raise RuntimeError("模拟盘 API Key/Secret 未配置")
    payload = dict(params or {})
    payload["timestamp"] = int(time.time() * 1000)
    payload["recvWindow"] = 5000
    query = urlencode(payload)
    signature = hmac.new(cfg["api_secret"].encode(), query.encode(), hashlib.sha256).hexdigest()
    body = (query + "&signature=" + signature).encode()
    headers = {
        "X-MBX-APIKEY": cfg["api_key"],
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if method == "GET":
        req = urllib.request.Request(BINANCE_TESTNET_REST + path + "?" + body.decode(), headers=headers, method="GET")
    else:
        req = urllib.request.Request(BINANCE_TESTNET_REST + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Binance testnet {exc.code}: {detail}") from exc


def _event(message: str, level: str = "info", **extra) -> None:
    item = {"ts": int(time.time() * 1000), "message": message, "level": level, **extra}
    _trade_events.insert(0, item)
    del _trade_events[80:]


def _exchange_filters(symbol: str) -> dict:
    now_ts = time.time()
    if now_ts - float(_exchange_cache["ts"]) > 3600 or not _exchange_cache["symbols"]:
        data = _public_testnet_get("/fapi/v1/exchangeInfo")
        symbols = {}
        for item in data.get("symbols", []):
            filters = {flt.get("filterType"): flt for flt in item.get("filters", [])}
            lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
            symbols[item["symbol"]] = {
                "step_size": lot.get("stepSize", "0.001"),
                "min_qty": lot.get("minQty", "0"),
            }
        _exchange_cache["symbols"] = symbols
        _exchange_cache["ts"] = now_ts
    return _exchange_cache["symbols"].get(symbol, {"step_size": "0.001", "min_qty": "0"})


def _round_qty(symbol: str, qty: float) -> str:
    filters = _exchange_filters(symbol)
    step = Decimal(str(filters["step_size"]))
    min_qty = Decimal(str(filters["min_qty"]))
    value = Decimal(str(qty))
    rounded = (value / step).to_integral_value(rounding=ROUND_DOWN) * step
    if rounded <= 0 or rounded < min_qty:
        raise RuntimeError(f"{symbol} 数量过小，最小数量 {min_qty}")
    return format(rounded.normalize(), "f")


def _account_snapshot() -> dict:
    data = _signed_testnet_request("GET", "/fapi/v3/account")
    wallet = float(data.get("totalWalletBalance") or 0)
    unrealized = float(data.get("totalUnrealizedProfit") or 0)
    equity = float(data.get("totalMarginBalance") or wallet + unrealized)
    positions = []
    for pos in data.get("positions", []):
        amount = float(pos.get("positionAmt") or 0)
        if abs(amount) <= 0:
            continue
        positions.append({
            "symbol": pos.get("symbol"),
            "amount": amount,
            "entry_price": float(pos.get("entryPrice") or 0),
            "unrealized": float(pos.get("unrealizedProfit") or 0),
        })
    point = {"ts": int(time.time() * 1000), "wallet": wallet, "unrealized": unrealized, "equity": equity}
    _equity_curve.append(point)
    del _equity_curve[:-240]
    return {"wallet": wallet, "unrealized": unrealized, "equity": equity, "positions": positions}


def _position_map(account: dict) -> dict[str, dict]:
    return {pos["symbol"]: pos for pos in account.get("positions", [])}


def _set_leverage(symbol: str) -> None:
    try:
        _signed_testnet_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(_testnet_config["leverage"])})
    except Exception as exc:  # noqa: BLE001
        _event(f"{symbol} 设置杠杆失败：{exc}", "warn", symbol=symbol)


def _place_market_order(symbol: str, follow: str, price: float) -> dict:
    side = "BUY" if follow == "FOLLOW_LONG" else "SELL"
    if price <= 0:
        ticker = _public_testnet_get("/fapi/v1/ticker/price", {"symbol": symbol})
        price = float(ticker.get("price") or 0)
    if price <= 0:
        raise RuntimeError(f"{symbol} 没有可用价格")
    qty = _round_qty(symbol, float(_testnet_config["order_usdt"]) / price)
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
    return _signed_testnet_request("POST", "/fapi/v1/order", params)


def _close_position(symbol: str, amount: float) -> dict:
    side = "SELL" if amount > 0 else "BUY"
    qty = _round_qty(symbol, abs(amount))
    return _signed_testnet_request("POST", "/fapi/v1/order", {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": qty,
        "reduceOnly": "true",
    })


def _close_due_positions(account: dict | None = None) -> None:
    if not _testnet_config.get("api_key") or not _testnet_config.get("api_secret"):
        return
    account = account or _account_snapshot()
    positions = _position_map(account)
    now_ms = int(time.time() * 1000)
    close_ms = float(_testnet_config["auto_close_minutes"]) * 60 * 1000
    for symbol, meta in list(_auto_positions.items()):
        if now_ms - int(meta.get("opened_at", now_ms)) < close_ms:
            continue
        pos = positions.get(symbol)
        if not pos:
            _auto_positions.pop(symbol, None)
            continue
        try:
            _close_position(symbol, float(pos["amount"]))
            _event(f"{symbol} 到时自动平仓", "info", symbol=symbol)
            _auto_positions.pop(symbol, None)
        except Exception as exc:  # noqa: BLE001
            _event(f"{symbol} 自动平仓失败：{exc}", "error", symbol=symbol)


def _auto_trade_signals(rows: list[dict], prices: dict[str, float]) -> None:
    if not _testnet_config.get("auto_trade"):
        return
    rows = [row for row in rows if row.get("follow") in {"FOLLOW_LONG", "FOLLOW_SHORT"}]
    if not rows:
        return
    if not _testnet_config.get("api_key") or not _testnet_config.get("api_secret"):
        _event("自动下单已开启，但模拟盘 API 未配置", "warn")
        return
    with _trade_lock:
        account = _account_snapshot()
        _close_due_positions(account)
        positions = _position_map(_account_snapshot())
        open_count = len(positions)
        now_ms = int(time.time() * 1000)
        for row in rows:
            symbol = str(row.get("symbol") or "")
            follow = row.get("follow")
            if follow not in {"FOLLOW_LONG", "FOLLOW_SHORT"} or not symbol:
                continue
            if open_count >= int(_testnet_config["max_positions"]):
                _event(f"{symbol} 跳过：持仓数量已达上限", "warn", symbol=symbol)
                continue
            cooldown_key = f"{symbol}|{follow}"
            if now_ms - _trade_cooldown.get(cooldown_key, 0) < int(_testnet_config["cooldown_seconds"]) * 1000:
                continue
            if symbol in positions:
                _event(f"{symbol} 跳过：已有模拟盘持仓", "warn", symbol=symbol)
                continue
            try:
                _set_leverage(symbol)
                price = float(row.get("price") or prices.get(symbol) or 0)
                order = _place_market_order(symbol, follow, price)
                _trade_cooldown[cooldown_key] = now_ms
                _auto_positions[symbol] = {"follow": follow, "opened_at": now_ms, "order_id": order.get("orderId")}
                open_count += 1
                _event(f"{symbol} {('做多' if follow == 'FOLLOW_LONG' else '做空')} 模拟盘自动下单", "info", symbol=symbol, order=order)
            except Exception as exc:  # noqa: BLE001
                _event(f"{symbol} 自动下单失败：{exc}", "error", symbol=symbol)


def _public_testnet_status() -> dict:
    cfg = _testnet_config
    base = {
        "rest": BINANCE_TESTNET_REST,
        "configured": bool(cfg.get("api_key") and cfg.get("api_secret")),
        "has_api_key": bool(cfg.get("api_key")),
        "has_api_secret": bool(cfg.get("api_secret")),
        "auto_trade": bool(cfg.get("auto_trade")),
        "order_usdt": cfg.get("order_usdt"),
        "leverage": cfg.get("leverage"),
        "max_positions": cfg.get("max_positions"),
        "cooldown_seconds": cfg.get("cooldown_seconds"),
        "auto_close_minutes": cfg.get("auto_close_minutes"),
        "events": _trade_events[:20],
        "equity_curve": _equity_curve[-120:],
    }
    if cfg.get("api_key") and not cfg.get("api_secret"):
        return {**base, "account_ok": False, "message": "第一次连接还需要填写 Secret"}
    if cfg.get("api_secret") and not cfg.get("api_key"):
        return {**base, "account_ok": False, "message": "第一次连接还需要填写 API Key"}
    if not base["configured"]:
        return {**base, "account_ok": False, "message": "未配置模拟盘 API"}
    try:
        with _trade_lock:
            account = _account_snapshot()
            _close_due_positions(account)
        return {**base, "account_ok": True, **account, "events": _trade_events[:20], "equity_curve": _equity_curve[-120:]}
    except Exception as exc:  # noqa: BLE001
        return {**base, "account_ok": False, "message": str(exc)}


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
        lines.append("- 这些候选已通过成本门槛：预测空间需要大于往返手续费、滑点、资金费风险和安全垫。")
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
    lines.append("- 预测净边际为正：未来 5m 预期空间 > 成本线。")
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
                "输出：哪里有大资金、预测方向和概率、成本线是否通过、是否适合跟单、跟单前确认、放弃条件。"
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
    .layout { display:grid; grid-template-columns:minmax(760px,1fr) 420px; gap:12px; align-items:start; }
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
    .trade-form input { width:100%; border:1px solid var(--line); background:var(--surface); border-radius:6px; padding:7px 8px; color:var(--text); min-width:0; }
    .trade-form .wide { grid-column:1/-1; }
    .trade-actions { display:flex; align-items:center; gap:8px; padding:0 12px 10px; flex-wrap:wrap; }
    .toggle { display:inline-flex; align-items:center; gap:7px; color:var(--text); font-size:12px; font-weight:800; }
    .toggle input { width:16px; height:16px; }
    .trade-status { padding:0 12px 10px; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; }
    .mini-stat { border:1px solid var(--line); background:var(--surface2); border-radius:6px; padding:7px; min-height:50px; }
    .mini-stat .label { margin-bottom:4px; font-size:11px; }
    .mini-stat .value { font-size:16px; }
    .trade-log { border-top:1px solid var(--line); max-height:78px; overflow:auto; padding:7px 12px; color:var(--muted); font-size:12px; line-height:1.5; }
    .trade-log div { border-bottom:1px solid #edf1f5; padding:4px 0; }
    .chart-wrap { padding:10px 12px 12px; height:176px; }
    #pnlChart { width:100%; height:124px; display:block; border:1px solid var(--line); border-radius:8px; background:#fff; }
    .chart-meta { display:flex; justify-content:space-between; gap:10px; color:var(--muted); font-size:12px; margin-top:8px; }
    .api-help { grid-column:1/-1; color:var(--muted); font-size:11px; line-height:1.45; margin-top:-2px; }
    @media (max-width:1200px) { .layout{grid-template-columns:1fr;} .side-stack{position:static; max-height:none; overflow:visible;} .detail-box{grid-template-columns:repeat(2,minmax(0,1fr));} }
    @media (max-width:720px) { .stats{grid-template-columns:repeat(2,minmax(0,1fr));} .controls{grid-template-columns:1fr;} .segmented{overflow-x:auto;} .statusbar{display:none;} .trade-form,.trade-status,.detail-box{grid-template-columns:1fr;} th.optional,td.optional{display:none;} }
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
              <div class="panel-title">大资金流动雷达</div>
              <div class="panel-note" id="radarNote">自动扫描高成交额 USDT 永续，寻找可跟单资金流</div>
            </div>
            <div class="panel-note" id="errorNote"></div>
          </div>
          <div class="table-wrap compact">
            <table>
              <thead>
                <tr>
                  <th>交易对</th><th>判断</th><th>分数</th><th>5m预测</th><th>净边际</th><th>价格</th><th>1m/5m</th><th>5m净流</th><th>风险</th><th>详情</th>
                </tr>
              </thead>
              <tbody id="radarBody"><tr><td colspan="10">正在连接 Binance...</td></tr></tbody>
            </table>
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
              <div class="panel-note" id="tradeConnNote">未连接模拟盘</div>
            </div>
            <button class="ai-btn" id="saveTradeCfg">保存</button>
          </div>
          <div class="trade-form">
            <label class="wide">模拟盘 API Key<input id="testnetKey" autocomplete="off" type="password" placeholder="第一次必填；保存后不会显示"></label>
            <label class="wide">模拟盘 Secret<input id="testnetSecret" autocomplete="off" type="password" placeholder="第一次必填；以后不改可留空"></label>
            <div class="api-help">第一次连接必须同时填 API Key 和 Secret。只填 Binance Futures Testnet / Demo Trading，不要填实盘 Key。</div>
            <label>每笔 USDT<input id="orderUsdt" type="number" min="1" step="1" value="100"></label>
            <label>杠杆<input id="tradeLeverage" type="number" min="1" max="20" step="1" value="3"></label>
            <label>最多持仓<input id="maxPositions" type="number" min="1" max="20" step="1" value="3"></label>
            <label>平仓分钟<input id="autoCloseMinutes" type="number" min="1" step="1" value="5"></label>
          </div>
          <div class="trade-actions">
            <label class="toggle"><input id="autoTradeToggle" type="checkbox">FOLLOW 自动下单</label>
            <span class="panel-note">仅 Testnet</span>
          </div>
          <div class="trade-status">
            <div class="mini-stat"><div class="label">权益</div><div class="value" id="tradeEquity">--</div></div>
            <div class="mini-stat"><div class="label">盈亏</div><div class="value" id="tradePnl">--</div></div>
            <div class="mini-stat"><div class="label">持仓</div><div class="value" id="tradePositions">--</div></div>
          </div>
          <div class="trade-log" id="tradeLog"><div>等待模拟盘连接。</div></div>
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
              <div class="panel-title">实时大单与爆仓</div>
              <div class="panel-note">达到动态阈值后进入事件流</div>
            </div>
          </div>
          <div class="event-list" id="eventList"></div>
        </div>
        <section class="ai-panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">AI 跟单分析</div>
              <div class="panel-note">可选辅助分析</div>
            </div>
            <button class="ai-btn" id="aiBtn">分析</button>
          </div>
          <div class="ai-body" id="aiOutput">等待行情累计后点击分析。没有配置 AI Key 时会使用内置规则分析。</div>
        </section>
      </aside>
    </section>
  </main>
  <script>
    const SEED_SYMBOLS = __SEED_SYMBOLS__;
    const MAX_STREAM_SYMBOLS = __MAX_STREAM_SYMBOLS__;
    const TRADE_STREAM_CHUNK_SIZE = __TRADE_STREAM_CHUNK_SIZE__;
    const LARGE_TRADE_USD = __LARGE_TRADE_USD__;
    const MIN_DYNAMIC_TRADE_USD = __MIN_DYNAMIC_TRADE_USD__;
    const TAKER_FEE_BPS = __TAKER_FEE_BPS__;
    const SLIPPAGE_BPS = __SLIPPAGE_BPS__;
    const SAFETY_EDGE_BPS = __SAFETY_EDGE_BPS__;
    const HOLD_MINUTES = __HOLD_MINUTES__;
    const BINANCE_WS_BASES = __BINANCE_WS_BASES__;
    const BINANCE_REST_BASES = __BINANCE_REST_BASES__;
    const STABLE_SYMBOLS = new Set(["USDCUSDT","BUSDUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT"]);
    const MAJORS = new Set(["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]);
    const ALPHA = {
      minScore:82, minProb:62, minEdgePct:0.25,
      minFlow5x:2.2, minTotal5x:4.0, minLargestX:1.15,
      majorMaxP1:0.45, altMaxP1:0.75, majorMaxP5:1.20, altMaxP5:2.00,
      minFlowImbalance60:0.28, minFlowImbalance5:0.12,
    };

    const state = {
      activeSymbols:[...SEED_SYMBOLS], marketMeta:new Map(), derivatives:new Map(), candles:new Map(),
      prices:new Map(), priceHistory:new Map(), trades:new Map(), liquidations:new Map(), events:[],
      sockets:[], runId:0, activeFilter:"all",
      expanded:new Set(), testnet:null,
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

    function activeSymbols(){ return state.activeSymbols.length ? state.activeSymbols : SEED_SYMBOLS; }
    function activeSet(){ return new Set(activeSymbols()); }
    function base(symbol){ return symbol.replace("USDT",""); }
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
    function baseCostPct(){ return (TAKER_FEE_BPS*2 + SLIPPAGE_BPS*2 + SAFETY_EDGE_BPS) / 100; }
    function fundingCostPct(d, side){
      if(!isNum(d.fundingRate)||side==="NEUTRAL")return 0;
      const next=Number(d.nextFundingTime||0);
      const crossesFunding=next>now() && next-now()<=HOLD_MINUTES*60*1000;
      if(!crossesFunding)return 0;
      if(side==="LONG")return Math.max(0,d.fundingRate);
      if(side==="SHORT")return Math.max(0,-d.fundingRate);
      return 0;
    }
    function costModel(d, side){
      const feePct=TAKER_FEE_BPS*2/100, slippagePct=SLIPPAGE_BPS*2/100, safetyPct=SAFETY_EDGE_BPS/100, fundingPct=fundingCostPct(d,side);
      return {feePct,slippagePct,safetyPct,fundingPct,requiredPct:feePct+slippagePct+safetyPct+fundingPct};
    }
    function tradeThreshold(symbol){ const meta=state.marketMeta.get(symbol)||{}; const vol=Number(meta.quoteVolume||0); if(!vol)return LARGE_TRADE_USD; return Math.max(MIN_DYNAMIC_TRADE_USD, Math.min(LARGE_TRADE_USD, vol * 0.00008)); }
    function rememberPrice(symbol, value, ts){ state.prices.set(symbol, value); const rows=ensureList(state.priceHistory, symbol); rows.push({ts, value}); while(rows.length>600 || (rows.length && rows[0].ts<now()-6*60*1000)) rows.shift(); }
    function price5m(symbol){ const rows=state.priceHistory.get(symbol)||[]; if(rows.length<2)return 0; const recent=rows[rows.length-1].value; const old=(rows.find(row=>row.ts>=now()-5*60*1000)||rows[0]).value; return old ? (recent-old)/old*100 : 0; }
    function priceRet(symbol, ms){ const rows=state.priceHistory.get(symbol)||[]; if(rows.length<2)return 0; const recent=rows[rows.length-1].value; const old=(rows.find(row=>row.ts>=now()-ms)||rows[0]).value; return old ? (recent-old)/old*100 : 0; }
    function candleMetrics(symbol){
      const rows=state.candles.get(symbol)||[];
      if(rows.length<8)return {volSpike:null,rangePct:null,breakout:0,position:null,ret15:null};
      const last=rows[rows.length-1], prev=rows.slice(Math.max(0,rows.length-21),rows.length-1);
      const avgVol=prev.reduce((sum,row)=>sum+Number(row.quoteVolume||0),0)/Math.max(1,prev.length);
      const high=Math.max(...prev.map(row=>row.high)), low=Math.min(...prev.map(row=>row.low));
      const span=Math.max(high-low, last.close*0.0001);
      const position=(last.close-low)/span;
      const rangePct=prev.reduce((sum,row)=>sum+(row.high-row.low)/Math.max(row.close,1)*100,0)/Math.max(1,prev.length);
      const first=rows[Math.max(0,rows.length-16)];
      const lastRange=Math.max(last.high-last.low,last.close*0.0001);
      const closeLocation=(last.close-last.low)/lastRange;
      const bodyPct=last.open?(last.close-last.open)/last.open*100:0;
      const upperWickPct=(last.high-Math.max(last.open,last.close))/Math.max(last.close,1)*100;
      const lowerWickPct=(Math.min(last.open,last.close)-last.low)/Math.max(last.close,1)*100;
      return {
        volSpike: avgVol ? Number(last.quoteVolume||0)/avgVol : null,
        rangePct,
        breakout: last.close>high ? 1 : (last.close<low ? -1 : 0),
        position,
        closeLocation,
        bodyPct,
        upperWickPct,
        lowerWickPct,
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
    function forecastModel(symbol,longScore,shortScore,p1,p3,p5,f60,f5,cm,d,mb){
      const edge=longScore-shortScore;
      let probUp=50 + edge*0.30 + p1*4.5 + p3*1.8 + p5*1.0 + f60.imbalance*5 + f5.imbalance*3 + mb.bias*2;
      if(isNum(cm.ret15))probUp += cm.ret15*0.35;
      if(isNum(cm.closeLocation))probUp += (cm.closeLocation-0.5)*4;
      if(isNum(d.oi15Pct)&&d.oi15Pct<-2.5)probUp += p5>=0 ? -3 : 3;
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
      state.derivatives.set(symbol,next);
    }
    async function fetchKlineSymbol(symbol){
      try{
        const data=await fetchJson(`/fapi/v1/klines?symbol=${encodeURIComponent(symbol)}&interval=1m&limit=30`);
        if(!Array.isArray(data))return;
        state.candles.set(symbol,data.map(row=>({
          openTime:Number(row[0]), open:Number(row[1]), high:Number(row[2]), low:Number(row[3]),
          close:Number(row[4]), volume:Number(row[5]), closeTime:Number(row[6]), quoteVolume:Number(row[7]||0),
        })).filter(row=>row.close>0));
      }catch(_){}
    }
    async function fetchKlines(){
      const targets=[...new Set([...rows().slice(0,28).map(row=>row.symbol),"BTCUSDT","ETHUSDT","SOLUSDT"].filter(symbol=>activeSet().has(symbol)))];
      for(let i=0;i<targets.length;i+=4) await Promise.all(targets.slice(i,i+4).map(fetchKlineSymbol));
      render();
    }

    function flow(symbol, ms){ const rows=cutoff(state.trades.get(symbol)||[],ms); let buy=0,sell=0,largest=0,buyCount=0,sellCount=0,lastSide="",streak=0; for(const row of rows){ if(row.side==="BUY"){buy+=row.notional; buyCount++;} else {sell+=row.notional; sellCount++;} largest=Math.max(largest,row.notional); } for(let i=rows.length-1;i>=0;i--){ if(!lastSide)lastSide=rows[i].side; if(rows[i].side!==lastSide)break; streak++; } return {buy,sell,net:buy-sell,total:buy+sell,largest,buyCount,sellCount,count:rows.length,lastSide,streak,imbalance:buy+sell?(buy-sell)/(buy+sell):0}; }
    function liq(symbol, ms){ const rows=cutoff(state.liquidations.get(symbol)||[],ms); let longLiq=0,shortLiq=0; for(const row of rows){ if(row.side==="SELL")longLiq+=row.notional; else shortLiq+=row.notional; } return {longLiq,shortLiq,total:longLiq+shortLiq}; }
    function derivative(symbol){ return {oi15Pct:null,oi5Pct:null,takerRatio:null,fundingRate:null,nextFundingTime:0,...(state.derivatives.get(symbol)||{})}; }
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
      const signal=long>=short&&long>=35?"LONG":short>long&&short>=35?"SHORT":"WATCH"; const score=Math.round(Math.max(long,short));
      const forecast=forecastModel(symbol,long,short,p1,p3,p5,f60,f5,cm,d,mb);
      const cost=costModel(d,forecast.side);
      forecast.netEdgePct=Math.abs(forecast.expected5Pct)-cost.requiredPct;
      forecast.cost=cost;
      const isMajor=MAJORS.has(symbol);
      const maxP1=isMajor?ALPHA.majorMaxP1:ALPHA.altMaxP1;
      const maxP5=isMajor?ALPHA.majorMaxP5:ALPHA.altMaxP5;
      const repeatLong=f60.buyCount>=2||f60.lastSide==="BUY"&&f60.streak>=2, repeatShort=f60.sellCount>=2||f60.lastSide==="SELL"&&f60.streak>=2;
      const volumeOk=isNum(cm.volSpike)?cm.volSpike>=1.35:f5.total>=threshold*ALPHA.minTotal5x;
      const marketOkLong=isMajor||mb.bias>=0||(mb.btc>-0.08&&mb.eth>-0.10), marketOkShort=isMajor||mb.bias<=0||(mb.btc<0.08&&mb.eth<0.10);
      const oiFallingHard=isNum(d.oi15Pct)&&d.oi15Pct<-2.5;
      const flowSizeOk=Math.abs(f5.net)>=threshold*ALPHA.minFlow5x&&f5.total>=threshold*ALPHA.minTotal5x&&f60.largest>=threshold*ALPHA.minLargestX;
      const flowLong=f60.net>0&&f5.net>0&&f60.imbalance>=ALPHA.minFlowImbalance60&&f5.imbalance>=ALPHA.minFlowImbalance5&&flowSizeOk;
      const flowShort=f60.net<0&&f5.net<0&&f60.imbalance<=-ALPHA.minFlowImbalance60&&f5.imbalance<=-ALPHA.minFlowImbalance5&&flowSizeOk;
      const lateLong=p1>maxP1||p5>maxP5, lateShort=p1<-maxP1||p5<-maxP5;
      const priceLong=p1>=-0.03&&p3>=0.03&&p5>=0.06&&!lateLong;
      const priceShort=p1<=0.03&&p3<=-0.03&&p5<=-0.06&&!lateShort;
      const candleRejectLong=(isNum(cm.closeLocation)&&cm.closeLocation<0.40)||(isNum(cm.upperWickPct)&&cm.upperWickPct>Math.max(0.45,Math.abs(cm.bodyPct)*1.8));
      const candleRejectShort=(isNum(cm.closeLocation)&&cm.closeLocation>0.60)||(isNum(cm.lowerWickPct)&&cm.lowerWickPct>Math.max(0.45,Math.abs(cm.bodyPct)*1.8));
      const candleOkLong=!candleRejectLong&&(!isNum(cm.closeLocation)||cm.closeLocation>=0.50);
      const candleOkShort=!candleRejectShort&&(!isNum(cm.closeLocation)||cm.closeLocation<=0.50);
      const derivativeLong=((isNum(d.oi15Pct)&&d.oi15Pct>=0.6)||(isNum(d.takerRatio)&&d.takerRatio>=1.06)||(!isNum(d.oi15Pct)&&!isNum(d.takerRatio)))&&(!isNum(d.takerRatio)||d.takerRatio>=0.98);
      const derivativeShort=((isNum(d.oi15Pct)&&d.oi15Pct>=0.6)||(isNum(d.takerRatio)&&d.takerRatio<=0.94)||(!isNum(d.oi15Pct)&&!isNum(d.takerRatio)))&&(!isNum(d.takerRatio)||d.takerRatio<=1.04);
      const liqOkLong=l5.longLiq<=Math.max(threshold*2,l5.shortLiq*1.4), liqOkShort=l5.shortLiq<=Math.max(threshold*2,l5.longLiq*1.4);
      const profitOk=forecast.side!=="NEUTRAL"&&forecast.netEdgePct>=ALPHA.minEdgePct;
      const forecastLong=forecast.side==="LONG"&&forecast.prob5>=ALPHA.minProb&&forecast.expected5Pct>0;
      const forecastShort=forecast.side==="SHORT"&&forecast.prob5>=ALPHA.minProb&&forecast.expected5Pct<0;
      const alignedLong=signal==="LONG"&&score>=ALPHA.minScore&&forecastLong&&profitOk&&flowLong&&priceLong&&repeatLong&&volumeOk&&marketOkLong&&!oiFallingHard&&derivativeLong&&candleOkLong&&liqOkLong;
      const alignedShort=signal==="SHORT"&&score>=ALPHA.minScore&&forecastShort&&profitOk&&flowShort&&priceShort&&repeatShort&&volumeOk&&marketOkShort&&!oiFallingHard&&derivativeShort&&candleOkShort&&liqOkShort;
      const risks=[];
      if(signal!=="WATCH"&&!profitOk)risks.push("成本不过");
      if(cost.fundingPct>0)risks.push("资金费成本");
      if(signal==="LONG"&&!priceLong)risks.push("价格未确认"); if(signal==="SHORT"&&!priceShort)risks.push("价格未确认");
      if(signal==="LONG"&&lateLong)risks.push("追涨过热"); if(signal==="SHORT"&&lateShort)risks.push("追空过热");
      if(signal==="LONG"&&!flowLong)risks.push("净流不连续"); if(signal==="SHORT"&&!flowShort)risks.push("净流不连续");
      if(signal==="LONG"&&!repeatLong)risks.push("孤立大单"); if(signal==="SHORT"&&!repeatShort)risks.push("孤立大单");
      if(signal!=="WATCH"&&!flowSizeOk)risks.push("资金强度不足");
      if(!volumeOk)risks.push("量能不足");
      if(signal==="LONG"&&!marketOkLong)risks.push("大盘反向"); if(signal==="SHORT"&&!marketOkShort)risks.push("大盘反向");
      if(oiFallingHard)risks.push("OI下降");
      if(signal==="LONG"&&!derivativeLong)risks.push("衍生品未确认"); if(signal==="SHORT"&&!derivativeShort)risks.push("衍生品未确认");
      if(signal==="LONG"&&!candleOkLong)risks.push("K线收弱"); if(signal==="SHORT"&&!candleOkShort)risks.push("K线收强");
      if(signal==="LONG"&&!liqOkLong)risks.push("爆仓反向"); if(signal==="SHORT"&&!liqOkShort)risks.push("爆仓反向");
      const reasons=[];
      if(alignedLong||alignedShort)reasons.push("Alpha过滤通过");
      if(Math.abs(f60.net)>=threshold)reasons.push((f60.net>0?"主动买净流 ":"主动卖净流 ")+money(Math.abs(f60.net)));
      if(flowSizeOk)reasons.push("5m资金强度 "+(Math.abs(f5.net)/Math.max(threshold,1)).toFixed(1)+"x");
      if(f60.largest>=threshold)reasons.push("最大单 "+money(f60.largest));
      if(isNum(cm.volSpike))reasons.push("量能 "+cm.volSpike.toFixed(1)+"x");
      if(Math.abs(p5)>=0.25)reasons.push("5m价格 "+(p5>0?"+":"")+p5.toFixed(2)+"%");
      if(isNum(cm.closeLocation))reasons.push("收盘位置 "+Math.round(cm.closeLocation*100)+"%");
      if(isNum(d.oi15Pct)&&Math.abs(d.oi15Pct)>=1.2)reasons.push("OI15m "+(d.oi15Pct>0?"+":"")+d.oi15Pct.toFixed(2)+"%");
      if(isNum(d.takerRatio)&&(d.takerRatio>=1.12||d.takerRatio<=0.9))reasons.push("Taker "+d.takerRatio.toFixed(2));
      if(!reasons.length)reasons.push("等待大额资金流");
      const follow=alignedLong?"FOLLOW_LONG":alignedShort?"FOLLOW_SHORT":signal==="LONG"?"WATCH_LONG":signal==="SHORT"?"WATCH_SHORT":"WAIT";
      const label=follow==="FOLLOW_LONG"?"策略多":follow==="FOLLOW_SHORT"?"策略空":follow==="WATCH_LONG"?"多头异动":follow==="WATCH_SHORT"?"空头异动":"观察";
      return {symbol,base:base(symbol),price:state.prices.get(symbol)||0,p1,p3,p5,f60,f5,l5,d,m:meta(symbol),cm,mb,threshold,signal,score,follow,label,forecast,cost,risks,reasons};
    }
    function rows(){ return activeSymbols().map(scoreRow).sort((a,b)=>b.score-a.score||Math.abs(b.f60.net)-Math.abs(a.f60.net)||Number(b.m.quoteVolume||0)-Number(a.m.quoteVolume||0)); }
    function filteredRows(){ const q=document.getElementById("search").value.trim().toUpperCase(); return rows().filter(r=>{ if(q&&!r.symbol.includes(q)&&!r.base.includes(q))return false; if(state.activeFilter==="follow")return r.follow==="FOLLOW_LONG"||r.follow==="FOLLOW_SHORT"; if(state.activeFilter==="long")return r.signal==="LONG"; if(state.activeFilter==="short")return r.signal==="SHORT"; if(state.activeFilter==="alts")return !MAJORS.has(r.symbol); return true; }); }
    function badge(row){ if(row.follow==="FOLLOW_LONG")return '<span class="badge long">策略多</span>'; if(row.follow==="FOLLOW_SHORT")return '<span class="badge short">策略空</span>'; if(row.follow==="WATCH_LONG")return '<span class="badge long">多头异动</span>'; if(row.follow==="WATCH_SHORT")return '<span class="badge short">空头异动</span>'; return '<span class="badge watch">观察</span>'; }
    function setDot(id,ok,err){ const el=document.getElementById(id); el.classList.toggle("ok",ok); el.classList.toggle("bad",!!err); }
    function addEvent(ev){ state.events.unshift(ev); state.events=state.events.slice(0,220); }

    function renderStats(all){ document.getElementById("statSymbols").textContent=activeSymbols().length; document.getElementById("statLong").textContent=all.filter(r=>r.follow==="FOLLOW_LONG").length; document.getElementById("statShort").textContent=all.filter(r=>r.follow==="FOLLOW_SHORT").length; document.getElementById("statCost").textContent=baseCostPct().toFixed(2)+"%"; document.getElementById("statLiq").textContent=money(all.reduce((s,r)=>s+r.l5.total,0)); setDot("priceDot",state.priceConnected,state.priceError); setDot("tradeDot",state.tradeConnected,state.tradeError); setDot("liqDot",state.liqConnected,state.liqError); const err=[state.priceError,state.tradeError,state.liqError,state.restError].filter(Boolean); document.getElementById("connText").textContent=err.length?"连接错误":`实时连接中 · 价格${state.priceMessages} 大单${state.tradeMessages} 范围${activeSymbols().length}`; document.getElementById("errorNote").textContent=err[0]||""; }
    function detailItem(label,value){ return `<div class="detail-item"><div class="detail-label">${label}</div><div class="detail-value">${value}</div></div>`; }
    function renderDetail(row){
      const reasons=row.reasons.map(x=>`<span class="chip">${x}</span>`).join("");
      const risks=(row.risks.length?row.risks:["--"]).map(x=>`<span class="chip">${x}</span>`).join("");
      const streak=row.f60.lastSide?(row.f60.lastSide==="BUY"?"买":"卖")+row.f60.streak:"--";
      const closeLoc=isNum(row.cm.closeLocation)?Math.round(row.cm.closeLocation*100)+"%":"--";
      const flowText=`60s ${money(row.f60.net)} / 5m ${money(row.f5.net)} / 最大 ${money(row.f60.largest||row.f5.largest)}`;
      const marketText=`BTC ${signedPlain(row.mb.btc,2)} / ETH ${signedPlain(row.mb.eth,2)} / bias ${row.mb.bias}`;
      return `<tr class="detail-row"><td colspan="10"><div class="detail-box">
        ${detailItem("依据",`<div class="reason">${reasons}</div>`)}
        ${detailItem("风险",`<div class="reason">${risks}</div>`)}
        ${detailItem("资金流",flowText)}
        ${detailItem("连续",streak)}
        ${detailItem("OI / Taker",`${pctOrDash(row.d.oi15Pct)} / ${ratioOrDash(row.d.takerRatio)}`)}
        ${detailItem("量能 / 收盘位置",`${isNum(row.cm.volSpike)?row.cm.volSpike.toFixed(1)+"x":"--"} / ${closeLoc}`)}
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
    function render(){ const all=rows(), visible=filteredRows(); renderStats(all); const body=document.getElementById("radarBody"); if(!visible.length){ body.innerHTML='<tr><td colspan="10">当前筛选条件下暂无大资金流。</td></tr>'; return; } body.innerHTML=visible.slice(0,90).map(renderRow).join(""); }
    function renderEvents(){ const list=document.getElementById("eventList"); if(!state.events.length){ list.innerHTML='<div class="event"><div></div><div><div class="event-title">等待大额事件</div><div class="event-meta">达到阈值后会显示在这里</div></div></div>'; return; } list.innerHTML=state.events.slice(0,120).map(ev=>{ const side=ev.side==="BUY"?"buy":"sell"; return `<div class="event"><div class="event-side ${side}">${ev.label}</div><div><div class="event-title"><span>${base(ev.symbol)}</span><span>${money(ev.notional)}</span></div><div class="event-meta">${price(ev.price)} · ${new Date(ev.ts).toLocaleTimeString()} · 阈值${money(ev.threshold)}</div></div></div>`; }).join(""); }
    function compactRows(){ return rows().slice(0,18).map(r=>({symbol:r.symbol,base:r.base,label:r.label,follow:r.follow,score:r.score,price:r.price,forecast_side:r.forecast.side,forecast_5m_prob:Number(r.forecast.prob5.toFixed(1)),forecast_5m_expected_pct:Number(r.forecast.expected5Pct.toFixed(3)),required_cost_pct:Number(r.cost.requiredPct.toFixed(3)),net_edge_pct:Number(r.forecast.netEdgePct.toFixed(3)),funding_cost_pct:Number(r.cost.fundingPct.toFixed(4)),price_1m_pct:Number(r.p1.toFixed(3)),price_5m_pct:Number(r.p5.toFixed(3)),volume_24h_usd:Math.round(r.m.quoteVolume||0),volume_spike:r.cm.volSpike,net_60s_usd:Math.round(r.f60.net),net_5m_usd:Math.round(r.f5.net),largest_usd:Math.round(r.f60.largest||r.f5.largest),streak_side:r.f60.lastSide,streak_count:r.f60.streak,oi_15m_pct:r.d.oi15Pct,taker_ratio:r.d.takerRatio,risks:r.risks,reasons:r.reasons})); }
    function compactEvents(){ return state.events.slice(0,40).map(e=>({symbol:e.symbol,base:base(e.symbol),label:e.label,side:e.side,price:e.price,notional:Math.round(e.notional),time:new Date(e.ts).toLocaleTimeString()})); }
    async function runAi(){ const btn=document.getElementById("aiBtn"), out=document.getElementById("aiOutput"); btn.disabled=true; out.textContent="正在分析当前大资金流..."; try{ const all=rows(); const payload={summary:{scanned_symbols:activeSymbols().length,follow_long:all.filter(r=>r.follow==="FOLLOW_LONG").length,follow_short:all.filter(r=>r.follow==="FOLLOW_SHORT").length,large_trade_threshold_usd:LARGE_TRADE_USD,taker_fee_bps:TAKER_FEE_BPS,slippage_bps:SLIPPAGE_BPS,safety_edge_bps:SAFETY_EDGE_BPS,base_required_cost_pct:Number(baseCostPct().toFixed(3)),hold_minutes:HOLD_MINUTES,generated_at:new Date().toLocaleString()},rows:compactRows(),events:compactEvents()}; const res=await fetch("/api/ai/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); const data=await res.json(); out.textContent=(data.mode==="ai"?"AI 分析\n\n":"规则分析\n\n")+data.analysis; }catch(err){ out.textContent="分析失败："+err; }finally{ btn.disabled=false; } }
    function trimOld(){ const cut=now()-6*60*1000; for(const map of [state.trades,state.liquidations]){ for(const [sym,list] of map){ while(list.length&&list[0].ts<cut)list.shift(); if(!list.length)map.delete(sym); } } }

    const loggedSignalKeys = new Set();
    function logSignals(){
      const all=rows();
      const follow=all.filter(r=>r.follow==="FOLLOW_LONG"||r.follow==="FOLLOW_SHORT");
      const prices={};
      for(const row of all){ if(row.price)prices[row.symbol]=row.price; }
      const toLog=follow.filter(r=>{
        const key=r.symbol+"|"+r.follow+"|"+Math.floor(Date.now()/60000);
        if(loggedSignalKeys.has(key))return false;
        loggedSignalKeys.add(key);
        if(loggedSignalKeys.size>500)loggedSignalKeys.clear();
        return true;
      });
      if(!toLog.length&&Object.keys(prices).length<1)return;
      const payload=toLog.map(r=>({
        symbol:r.symbol, follow:r.follow, score:r.score, price:r.price,
        price_1m_pct:r.p1, price_5m_pct:r.p5,
        net_60s_usd:Math.round(r.f60.net), net_5m_usd:Math.round(r.f5.net),
        flow_60s_imbalance:Number(r.f60.imbalance.toFixed(4)),
        flow_5m_imbalance:Number(r.f5.imbalance.toFixed(4)),
        flow_60s_count:r.f60.count,
        flow_5m_count:r.f5.count,
        largest_usd:Math.round(r.f60.largest||r.f5.largest||0),
        streak_side:r.f60.lastSide, streak_count:r.f60.streak,
        volume_spike:r.cm.volSpike, volume_24h_usd:Math.round((r.m&&r.m.quoteVolume)||0),
        candle_close_location:isNum(r.cm.closeLocation)?Number(r.cm.closeLocation.toFixed(4)):null,
        candle_body_pct:isNum(r.cm.bodyPct)?Number(r.cm.bodyPct.toFixed(4)):null,
        upper_wick_pct:isNum(r.cm.upperWickPct)?Number(r.cm.upperWickPct.toFixed(4)):null,
        lower_wick_pct:isNum(r.cm.lowerWickPct)?Number(r.cm.lowerWickPct.toFixed(4)):null,
        oi_15m_pct:r.d.oi15Pct, taker_ratio:r.d.takerRatio,
        market_bias:r.mb.bias,
        btc_5m_pct:Number(r.mb.btc.toFixed(4)),
        eth_5m_pct:Number(r.mb.eth.toFixed(4)),
        liq_long_5m_usd:Math.round(r.l5.longLiq||0),
        liq_short_5m_usd:Math.round(r.l5.shortLiq||0),
        forecast_side:r.forecast.side, forecast_5m_prob:Number(r.forecast.prob5.toFixed(1)),
        net_edge_pct:Number(r.forecast.netEdgePct.toFixed(3)),
        required_cost_pct:Number(r.cost.requiredPct.toFixed(3)),
        funding_cost_pct:Number(r.cost.fundingPct.toFixed(4)),
        risks:r.risks, reasons:r.reasons,
      }));
      fetch("/api/signal/log",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rows:payload,prices})}).catch(()=>{});
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
      const w=rect.width, h=rect.height, pad=26;
      ctx.clearRect(0,0,w,h); ctx.fillStyle="#fff"; ctx.fillRect(0,0,w,h);
      ctx.strokeStyle="#edf1f5"; ctx.lineWidth=1;
      for(let i=0;i<4;i++){ const y=pad+(h-pad*2)*i/3; ctx.beginPath(); ctx.moveTo(pad,y); ctx.lineTo(w-pad,y); ctx.stroke(); }
      if(!points||points.length<2){
        ctx.fillStyle="#68758a"; ctx.font="12px Inter, sans-serif"; ctx.fillText("连接模拟盘后显示收益曲线",pad,Math.floor(h/2));
        if(left)left.textContent="等待数据"; if(right){ right.textContent="--"; right.className=""; }
        return;
      }
      const vals=points.map(p=>Number(p.equity||0)).filter(Number.isFinite);
      const min=Math.min(...vals), max=Math.max(...vals), span=Math.max(max-min,Math.max(max,1)*0.001);
      const first=vals[0], last=vals[vals.length-1];
      const x=i=>pad+(w-pad*2)*i/Math.max(1,points.length-1);
      const y=v=>pad+(max-v)/span*(h-pad*2);
      ctx.strokeStyle=last>=first?"#087f5b":"#c92a2a"; ctx.lineWidth=2.5; ctx.beginPath();
      points.forEach((p,i)=>{ const xx=x(i), yy=y(Number(p.equity||0)); if(i)ctx.lineTo(xx,yy); else ctx.moveTo(xx,yy); });
      ctx.stroke();
      ctx.fillStyle="#162033"; ctx.font="12px Inter, sans-serif"; ctx.fillText(usdt(max),8,18); ctx.fillText(usdt(min),8,h-10);
      const pnl=last-first;
      if(left)left.textContent=`起始 ${usdt(first)} · 当前 ${usdt(last)}`;
      if(right){ right.textContent=`收益 ${pnl>=0?"+":""}${usdt(pnl)}`; right.className=pnl>=0?"up":"down"; }
    }
    function renderTestnetStatus(data){
      state.testnet=data;
      const note=document.getElementById("tradeConnNote");
      note.textContent=data.account_ok?"模拟盘已连接":(data.message||"未配置模拟盘 API");
      document.getElementById("autoTradeToggle").checked=!!data.auto_trade;
      document.getElementById("testnetKey").placeholder=data.has_api_key?"已保存；留空不修改":"第一次必填；保存后不会显示";
      document.getElementById("testnetSecret").placeholder=data.has_api_secret?"已保存；留空不修改":"第一次必填；以后不改可留空";
      document.getElementById("orderUsdt").value=data.order_usdt||100;
      document.getElementById("tradeLeverage").value=data.leverage||3;
      document.getElementById("maxPositions").value=data.max_positions||3;
      document.getElementById("autoCloseMinutes").value=data.auto_close_minutes||5;
      document.getElementById("tradeEquity").textContent=data.account_ok?usdt(data.equity):"--";
      document.getElementById("tradePnl").textContent=data.account_ok?usdt(data.unrealized):"--";
      document.getElementById("tradePnl").className="value "+(Number(data.unrealized||0)>=0?"up":"down");
      document.getElementById("tradePositions").textContent=data.account_ok?(data.positions||[]).length:"--";
      const log=document.getElementById("tradeLog");
      const events=(data.events||[]).slice(0,8);
      log.innerHTML=events.length?events.map(e=>`<div class="${e.level==="error"?"down":e.level==="warn"?"":"up"}">${new Date(e.ts).toLocaleTimeString()} · ${esc(e.message)}</div>`).join(""):`<div>${esc(data.message||"等待模拟盘连接。")}</div>`;
      drawPnlChart(data.equity_curve||[]);
    }
    async function loadTestnetStatus(){
      try{ const res=await fetch("/api/testnet/status"); renderTestnetStatus(await res.json()); }
      catch(err){ document.getElementById("tradeConnNote").textContent="模拟盘状态读取失败"; drawPnlChart([]); }
    }
    async function saveTestnetConfig(){
      const payload={
        auto_trade:document.getElementById("autoTradeToggle").checked,
        order_usdt:Number(document.getElementById("orderUsdt").value||100),
        leverage:Number(document.getElementById("tradeLeverage").value||3),
        max_positions:Number(document.getElementById("maxPositions").value||3),
        auto_close_minutes:Number(document.getElementById("autoCloseMinutes").value||5),
      };
      const key=document.getElementById("testnetKey").value.trim();
      const secret=document.getElementById("testnetSecret").value.trim();
      if(key)payload.api_key=key;
      if(secret)payload.api_secret=secret;
      const btn=document.getElementById("saveTradeCfg");
      btn.disabled=true; btn.textContent="保存中";
      try{
        const res=await fetch("/api/testnet/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
        renderTestnetStatus(await res.json());
        document.getElementById("testnetKey").value="";
        document.getElementById("testnetSecret").value="";
      }catch(err){ document.getElementById("tradeConnNote").textContent="保存失败："+err; }
      finally{ btn.disabled=false; btn.textContent="保存连接"; }
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
        if(data.long)html+="多头信号 <strong>"+data.long.count+"</strong> 条　5m胜率 <strong>"+fmt(data.long.winrate_5m)+"%</strong>　均收益 "+fmtPct(data.long.avg_ret_5m)+"　期望值 "+fmtPct(data.long.expect_5m)+"<br>";
        if(data.short)html+="空头信号 <strong>"+data.short.count+"</strong> 条　5m胜率 <strong>"+fmt(data.short.winrate_5m)+"%</strong>　均收益 "+fmtPct(data.short.avg_ret_5m)+"　期望值 "+fmtPct(data.short.expect_5m)+"<br>";
        if(!data.long&&!data.short)html+="暂无已回填数据，等待信号触发后 5 分钟开始显示统计。";
        el.innerHTML=html;
      }).catch(()=>{});
    }

    function closeSockets(){ for(const ws of state.sockets){ try{ws.close();}catch(_){}} state.sockets=[]; state.priceConnected=false; state.tradeConnected=false; state.liqConnected=false; state.priceError=""; state.tradeError=""; state.liqError=""; state.priceMessages=0; state.tradeMessages=0; state.liqMessages=0; }
    function connectPrice(runId,index=0){ const host=BINANCE_WS_BASES[index%BINANCE_WS_BASES.length]; const ws=new WebSocket(`${host}/ws/!ticker@arr`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectPrice(runId,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.priceError=`价格流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.priceConnected=true; state.priceError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.priceConnected=false; setTimeout(()=>{ if(runId===state.runId)connectPrice(runId,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.priceError=`价格流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.priceMessages++; const arr=JSON.parse(e.data); const set=activeSet(), ts=Date.now(); for(const item of arr){ if(!set.has(item.s))continue; const p=Number(item.c||0); if(p>0)rememberPrice(item.s,p,ts); const prev=state.marketMeta.get(item.s)||{}; state.marketMeta.set(item.s,{...prev,symbol:item.s,quoteVolume:Number(item.q||prev.quoteVolume||0),changePct:Number(item.P||prev.changePct||0),lastPrice:p}); } }; }
    function connectTrades(runId){ const syms=activeSymbols(); for(let i=0;i<syms.length;i+=TRADE_STREAM_CHUNK_SIZE){ connectTradeChunk(runId,syms.slice(i,i+TRADE_STREAM_CHUNK_SIZE),0); } }
    function connectTradeChunk(runId,syms,index){ if(!syms.length)return; const host=BINANCE_WS_BASES[index%BINANCE_WS_BASES.length]; const streams=syms.map(s=>s.toLowerCase()+"@aggTrade").join("/"); const ws=new WebSocket(`${host}/stream?streams=${streams}`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectTradeChunk(runId,syms,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.tradeError=`大单流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.tradeConnected=true; state.tradeError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.tradeConnected=false; setTimeout(()=>{ if(runId===state.runId)connectTradeChunk(runId,syms,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.tradeError=`大单流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.tradeMessages++; const data=JSON.parse(e.data).data||{}; const symbol=data.s; if(!activeSet().has(symbol))return; const p=Number(data.p||0), q=Number(data.q||0), notional=p*q, threshold=tradeThreshold(symbol); if(p>0)rememberPrice(symbol,p,data.T||Date.now()); if(notional<threshold)return; const side=data.m?"SELL":"BUY"; const row={symbol,side,ts:data.T||Date.now(),price:p,qty:q,notional,threshold}; ensureList(state.trades,symbol).push(row); addEvent({...row,label:side==="BUY"?"主动买":"主动卖"}); }; }
    function reconnectTradesOnly(){ state.runId++; const runId=state.runId; for(const ws of state.sockets){ try{ws.close();}catch(_){} } state.sockets=[]; connectPrice(runId); connectTrades(runId); connectLiquidations(runId); }
    function connectLiquidations(runId,index=0){ const host=BINANCE_WS_BASES[index%BINANCE_WS_BASES.length]; const ws=new WebSocket(`${host}/ws/!forceOrder@arr`); state.sockets.push(ws); const next=()=>setTimeout(()=>{ if(runId===state.runId)connectLiquidations(runId,index+1); },1000); const timeout=setTimeout(()=>{ if(runId!==state.runId)return; if(ws.readyState===WebSocket.CONNECTING){ state.liqError=`爆仓流超时：${host}`; try{ws.close();}catch(_){} next(); } },8000); ws.onopen=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.liqConnected=true; state.liqError=""; render(); }; ws.onclose=()=>{ if(runId!==state.runId)return; clearTimeout(timeout); state.liqConnected=false; setTimeout(()=>{ if(runId===state.runId)connectLiquidations(runId,index); },3000); }; ws.onerror=()=>{ if(runId!==state.runId)return; state.liqError=`爆仓流连接失败：${host}`; render(); }; ws.onmessage=e=>{ if(runId!==state.runId)return; state.liqMessages++; const order=(JSON.parse(e.data)||{}).o||{}; const symbol=order.s; if(!activeSet().has(symbol))return; const p=Number(order.ap||order.p||0), q=Number(order.q||0), notional=p*q, threshold=tradeThreshold(symbol); if(notional<threshold)return; const side=order.S||""; const row={symbol,side,ts:order.T||Date.now(),price:p,qty:q,notional,threshold}; ensureList(state.liquidations,symbol).push(row); addEvent({...row,label:side==="BUY"?"空爆":"多爆"}); }; }
    async function start(){ state.runId++; const runId=state.runId; closeSockets(); await refreshMarketUniverse(); connectPrice(runId); connectTrades(runId); connectLiquidations(runId); fetchKlines(); fetchDerivatives(); if(!state.marketTimer)state.marketTimer=setInterval(refreshMarketUniverse,60*1000); if(!state.derivativesTimer)state.derivativesTimer=setInterval(fetchDerivatives,45*1000); if(!state.klineTimer)state.klineTimer=setInterval(fetchKlines,60*1000); render(); renderEvents(); }
    document.getElementById("refresh").addEventListener("click",start);
    document.getElementById("aiBtn").addEventListener("click",runAi);
    document.getElementById("saveTradeCfg").addEventListener("click",saveTestnetConfig);
    document.getElementById("radarBody").addEventListener("click",e=>{
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
    setInterval(loadTestnetStatus,5000);
    setTimeout(loadSignalStats,5000);
    setTimeout(loadTestnetStatus,1000);
    window.addEventListener("resize",()=>drawPnlChart((state.testnet&&state.testnet.equity_curve)||[]));
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
    html = html.replace("__TAKER_FEE_BPS__", json.dumps(TAKER_FEE_BPS))
    html = html.replace("__SLIPPAGE_BPS__", json.dumps(SLIPPAGE_BPS))
    html = html.replace("__SAFETY_EDGE_BPS__", json.dumps(SAFETY_EDGE_BPS))
    html = html.replace("__HOLD_MINUTES__", json.dumps(HOLD_MINUTES))
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
        "taker_fee_bps": TAKER_FEE_BPS,
        "slippage_bps": SLIPPAGE_BPS,
        "safety_edge_bps": SAFETY_EDGE_BPS,
        "hold_minutes": HOLD_MINUTES,
        "binance_ws_bases": BINANCE_WS_BASES,
        "binance_rest_bases": BINANCE_REST_BASES,
        "binance_testnet_rest": BINANCE_TESTNET_REST,
    })


@app.post("/api/signal/log")
def signal_log():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    prices = payload.get("prices") or {}
    for row in rows:
        log_signal(row)
    fill_prices(prices)
    _auto_trade_signals(rows, prices)
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
    return jsonify(_public_testnet_status())


@app.post("/api/testnet/config")
def testnet_config():
    payload = request.get_json(silent=True) or {}
    with _trade_lock:
        if "api_key" in payload:
            _testnet_config["api_key"] = str(payload.get("api_key") or "").strip()
        if payload.get("api_secret"):
            _testnet_config["api_secret"] = str(payload.get("api_secret") or "").strip()
        if "auto_trade" in payload:
            _testnet_config["auto_trade"] = bool(payload.get("auto_trade"))
        for key, cast, default in [
            ("order_usdt", float, TESTNET_ORDER_USDT),
            ("leverage", int, TESTNET_LEVERAGE),
            ("max_positions", int, TESTNET_MAX_POSITIONS),
            ("cooldown_seconds", int, TESTNET_COOLDOWN_SECONDS),
            ("auto_close_minutes", float, TESTNET_AUTO_CLOSE_MINUTES),
        ]:
            if key in payload:
                try:
                    _testnet_config[key] = max(1, cast(payload.get(key)))
                except (TypeError, ValueError):
                    _testnet_config[key] = default
        if _testnet_config.get("api_key") and _testnet_config.get("api_secret"):
            _event("模拟盘配置已更新", "info")
        else:
            _event("模拟盘配置未完整：第一次连接需要 API Key 和 Secret", "warn")
    return jsonify(_public_testnet_status())


@app.post("/api/ai/analyze")
def ai_analyze():
    payload = request.get_json(silent=True) or {}
    fallback = rule_analysis(payload)
    analysis, mode = call_ai(payload, fallback)
    return jsonify({"analysis": analysis, "mode": mode, "model": AI_MODEL if mode == "ai" else None})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
