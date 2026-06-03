from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
import websocket
from flask import Flask, jsonify, render_template_string


app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BINANCE_REST = os.environ.get("BINANCE_REST", "https://fapi.binance.com")
BINANCE_WS = os.environ.get("BINANCE_WS", "wss://fstream.binance.com")

SNAPSHOT_INTERVAL = int(os.environ.get("SNAPSHOT_INTERVAL", "12"))
RADAR_SYMBOL_LIMIT = int(os.environ.get("RADAR_SYMBOL_LIMIT", "45"))
LARGE_TRADE_USD = float(os.environ.get("LARGE_TRADE_USD", "80000"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "12"))

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
    s.strip().upper()
    for s in os.environ.get("WATCH_SYMBOLS", ",".join(DEFAULT_WATCH_SYMBOLS)).split(",")
    if s.strip()
]

MAJORS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
SYMBOL_BLOCKLIST = {
    "USDCUSDT",
    "BUSDUSDT",
    "FDUSDUSDT",
    "TUSDUSDT",
    "USDPUSDT",
    "DAIUSDT",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct_change(new: float, old: float) -> float:
    if not old:
        return 0.0
    return (new - old) / old * 100


def fmt_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "")


class MarketState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.trade_tape: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=1400))
        self.liquidations: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=700))
        self.recent_events: deque[dict[str, Any]] = deque(maxlen=240)
        self.radar: list[dict[str, Any]] = []
        self.summary: dict[str, Any] = {}
        self.meta: dict[str, Any] = {
            "updated_at": 0,
            "snapshot_interval": SNAPSHOT_INTERVAL,
            "large_trade_usd": LARGE_TRADE_USD,
            "watch_symbols": WATCH_SYMBOLS,
            "threads_started": False,
            "snapshot_status": "not_started",
            "ws_trade_connected": False,
            "ws_liq_connected": False,
            "snapshot_error": None,
        }

    def add_large_trade(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.trade_tape[event["symbol"]].append(event)
            self.recent_events.appendleft(event)

    def add_liquidation(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.liquidations[event["symbol"]].append(event)
            self.recent_events.appendleft(event)

    def set_ws_status(self, key: str, value: bool) -> None:
        with self.lock:
            self.meta[key] = value

    def set_snapshot_error(self, error: str | None) -> None:
        with self.lock:
            self.meta["snapshot_error"] = error
            self.meta["snapshot_status"] = "error" if error else self.meta.get("snapshot_status")

    def set_snapshot_status(self, status: str) -> None:
        with self.lock:
            self.meta["snapshot_status"] = status

    def mark_threads_started(self) -> None:
        with self.lock:
            self.meta["threads_started"] = True

    def flow_for(self, symbol: str, seconds: int) -> dict[str, Any]:
        cutoff = time.time() - seconds
        with self.lock:
            rows = [x for x in self.trade_tape.get(symbol, []) if x["ts"] >= cutoff]
        buy = sum(x["notional"] for x in rows if x["side"] == "BUY")
        sell = sum(x["notional"] for x in rows if x["side"] == "SELL")
        largest = max((x["notional"] for x in rows), default=0.0)
        return {
            "buy_usd": round(buy, 2),
            "sell_usd": round(sell, 2),
            "net_usd": round(buy - sell, 2),
            "total_usd": round(buy + sell, 2),
            "largest_usd": round(largest, 2),
            "buy_count": sum(1 for x in rows if x["side"] == "BUY"),
            "sell_count": sum(1 for x in rows if x["side"] == "SELL"),
        }

    def liq_for(self, symbol: str, seconds: int) -> dict[str, Any]:
        cutoff = time.time() - seconds
        with self.lock:
            rows = [x for x in self.liquidations.get(symbol, []) if x["ts"] >= cutoff]
        long_liq = sum(x["notional"] for x in rows if x["side"] == "SELL")
        short_liq = sum(x["notional"] for x in rows if x["side"] == "BUY")
        largest = max((x["notional"] for x in rows), default=0.0)
        return {
            "long_liq_usd": round(long_liq, 2),
            "short_liq_usd": round(short_liq, 2),
            "total_usd": round(long_liq + short_liq, 2),
            "largest_usd": round(largest, 2),
            "count": len(rows),
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "radar": list(self.radar),
                "events": list(self.recent_events)[:80],
                "summary": dict(self.summary),
                "meta": dict(self.meta),
            }

    def set_radar(self, radar: list[dict[str, Any]], summary: dict[str, Any]) -> None:
        with self.lock:
            self.radar = radar
            self.summary = summary
            self.meta["updated_at"] = now_ms()
            self.meta["snapshot_error"] = None


STATE = MarketState()
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "BinanceFlowRadar/1.0"})


def request_json(path: str, params: dict[str, Any] | None = None, timeout: float = 8) -> Any:
    url = BINANCE_REST + path
    response = HTTP.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def get_exchange_symbols() -> set[str]:
    data = request_json("/fapi/v1/exchangeInfo", timeout=10)
    symbols = set()
    for item in data.get("symbols", []):
        if (
            item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and item.get("symbol") not in SYMBOL_BLOCKLIST
        ):
            symbols.add(item["symbol"])
    return symbols


def get_all_tickers() -> dict[str, dict[str, Any]]:
    rows = request_json("/fapi/v1/ticker/24hr", timeout=10)
    return {x["symbol"]: x for x in rows if x.get("symbol", "").endswith("USDT")}


def get_funding_map() -> dict[str, float]:
    rows = request_json("/fapi/v1/premiumIndex", timeout=10)
    return {x["symbol"]: float(x.get("lastFundingRate") or 0) * 100 for x in rows}


def get_symbol_micro(symbol: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "symbol": symbol,
        "oi_5m_pct": 0.0,
        "oi_15m_pct": 0.0,
        "oi_value": 0.0,
        "taker_ratio": 1.0,
        "taker_buy_pct": 50.0,
        "price_5m_pct": 0.0,
        "quote_volume_5m": 0.0,
    }
    try:
        oi_rows = request_json(
            "/futures/data/openInterestHist",
            {"symbol": symbol, "period": "5m", "limit": 4},
            timeout=6,
        )
        if isinstance(oi_rows, list) and oi_rows:
            latest = float(oi_rows[-1].get("sumOpenInterestValue") or 0)
            result["oi_value"] = latest
            if len(oi_rows) >= 2:
                prev = float(oi_rows[-2].get("sumOpenInterestValue") or 0)
                result["oi_5m_pct"] = round(pct_change(latest, prev), 2)
            if len(oi_rows) >= 4:
                first = float(oi_rows[0].get("sumOpenInterestValue") or 0)
                result["oi_15m_pct"] = round(pct_change(latest, first), 2)
    except Exception:
        pass

    try:
        taker_rows = request_json(
            "/futures/data/takerlongshortRatio",
            {"symbol": symbol, "period": "5m", "limit": 1},
            timeout=6,
        )
        if isinstance(taker_rows, list) and taker_rows:
            item = taker_rows[-1]
            buy_vol = float(item.get("buyVol") or 0)
            sell_vol = float(item.get("sellVol") or 0)
            ratio = float(item.get("buySellRatio") or (buy_vol / sell_vol if sell_vol else 1))
            total = buy_vol + sell_vol
            result["taker_ratio"] = round(ratio, 3)
            result["taker_buy_pct"] = round(buy_vol / total * 100, 1) if total else 50.0
    except Exception:
        pass

    try:
        klines = request_json(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": "1m", "limit": 6},
            timeout=6,
        )
        if isinstance(klines, list) and len(klines) >= 2:
            open_price = float(klines[0][1])
            last_price = float(klines[-1][4])
            quote_volume = sum(float(k[7]) for k in klines[-5:])
            result["price_5m_pct"] = round(pct_change(last_price, open_price), 2)
            result["quote_volume_5m"] = round(quote_volume, 2)
    except Exception:
        pass

    return result


def choose_candidates(symbols: set[str], tickers: dict[str, dict[str, Any]]) -> list[str]:
    available_watch = [s for s in WATCH_SYMBOLS if s in symbols]
    ranked = sorted(
        [
            s
            for s in symbols
            if s in tickers and s not in SYMBOL_BLOCKLIST
        ],
        key=lambda s: float(tickers[s].get("quoteVolume") or 0),
        reverse=True,
    )
    merged = []
    for symbol in available_watch + ranked:
        if symbol not in merged:
            merged.append(symbol)
        if len(merged) >= RADAR_SYMBOL_LIMIT:
            break
    return merged


def reason_list(row: dict[str, Any]) -> list[str]:
    reasons = []
    if abs(row["flow_60s"]["net_usd"]) >= LARGE_TRADE_USD:
        side = "主动买入" if row["flow_60s"]["net_usd"] > 0 else "主动卖出"
        reasons.append(f"{side}净额 {money_short(abs(row['flow_60s']['net_usd']))}")
    if row["oi_15m_pct"] >= 2:
        reasons.append(f"OI 15m +{row['oi_15m_pct']}%")
    elif row["oi_15m_pct"] <= -2:
        reasons.append(f"OI 15m {row['oi_15m_pct']}%")
    if row["taker_ratio"] >= 1.15:
        reasons.append(f"主动买卖比 {row['taker_ratio']}")
    elif row["taker_ratio"] <= 0.87:
        reasons.append(f"主动买卖比 {row['taker_ratio']}")
    if row["liq_5m"]["long_liq_usd"] >= LARGE_TRADE_USD:
        reasons.append(f"多头爆仓 {money_short(row['liq_5m']['long_liq_usd'])}")
    if row["liq_5m"]["short_liq_usd"] >= LARGE_TRADE_USD:
        reasons.append(f"空头爆仓 {money_short(row['liq_5m']['short_liq_usd'])}")
    if abs(row["funding_rate"]) >= 0.03:
        reasons.append(f"资金费率 {row['funding_rate']:.4f}%")
    if not reasons:
        reasons.append("暂无强资金流证据")
    return reasons[:4]


def score_symbol(row: dict[str, Any]) -> dict[str, Any]:
    flow = row["flow_60s"]
    liq = row["liq_5m"]
    total_flow = flow["total_usd"]
    net_ratio = flow["net_usd"] / total_flow if total_flow else 0.0

    long_score = 0.0
    short_score = 0.0

    if net_ratio > 0:
        long_score += min(35, net_ratio * 35)
    else:
        short_score += min(35, abs(net_ratio) * 35)

    flow_size_points = min(18, total_flow / max(LARGE_TRADE_USD, 1) * 4)
    long_score += flow_size_points if flow["net_usd"] > 0 else 0
    short_score += flow_size_points if flow["net_usd"] < 0 else 0

    taker_ratio = row["taker_ratio"]
    if taker_ratio > 1:
        long_score += min(18, (taker_ratio - 1) * 28)
    else:
        short_score += min(18, (1 - taker_ratio) * 28)

    if row["oi_15m_pct"] > 0:
        if row["price_5m_pct"] >= 0:
            long_score += min(22, row["oi_15m_pct"] * 4)
        else:
            short_score += min(22, row["oi_15m_pct"] * 4)

    if row["price_5m_pct"] > 0:
        long_score += min(12, row["price_5m_pct"] * 2)
    else:
        short_score += min(12, abs(row["price_5m_pct"]) * 2)

    long_score += min(10, liq["short_liq_usd"] / max(LARGE_TRADE_USD, 1) * 3)
    short_score += min(10, liq["long_liq_usd"] / max(LARGE_TRADE_USD, 1) * 3)

    if row["funding_rate"] > 0.04:
        long_score -= 8
    if row["funding_rate"] < -0.04:
        short_score -= 8

    long_score = clamp(long_score, 0, 100)
    short_score = clamp(short_score, 0, 100)

    if long_score >= short_score and long_score >= 35:
        signal = "LONG_PRESSURE"
        score = round(long_score)
    elif short_score > long_score and short_score >= 35:
        signal = "SHORT_PRESSURE"
        score = round(short_score)
    else:
        signal = "WATCH"
        score = round(max(long_score, short_score))

    return {
        "signal": signal,
        "score": score,
        "long_score": round(long_score),
        "short_score": round(short_score),
        "reasons": reason_list(row),
    }


def money_short(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def build_radar() -> None:
    STATE.set_snapshot_status("fetching_exchange_info")
    symbols = get_exchange_symbols()
    STATE.set_snapshot_status("fetching_tickers")
    tickers = get_all_tickers()
    funding = get_funding_map()
    candidates = choose_candidates(symbols, tickers)

    micro_map: dict[str, dict[str, Any]] = {}
    STATE.set_snapshot_status("fetching_microstructure")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_symbol_micro, symbol): symbol for symbol in candidates}
        for future in as_completed(futures):
            data = future.result()
            micro_map[data["symbol"]] = data

    radar = []
    for symbol in candidates:
        ticker = tickers.get(symbol, {})
        micro = micro_map.get(symbol, {"symbol": symbol})
        price = float(ticker.get("lastPrice") or 0)
        row = {
            "symbol": symbol,
            "base": fmt_symbol(symbol),
            "is_major": symbol in MAJORS,
            "price": price,
            "change_24h_pct": round(float(ticker.get("priceChangePercent") or 0), 2),
            "volume_24h": round(float(ticker.get("quoteVolume") or 0), 2),
            "trade_count_24h": int(float(ticker.get("count") or 0)),
            "funding_rate": round(funding.get(symbol, 0.0), 5),
            "oi_5m_pct": micro.get("oi_5m_pct", 0.0),
            "oi_15m_pct": micro.get("oi_15m_pct", 0.0),
            "oi_value": round(micro.get("oi_value", 0.0), 2),
            "taker_ratio": micro.get("taker_ratio", 1.0),
            "taker_buy_pct": micro.get("taker_buy_pct", 50.0),
            "price_5m_pct": micro.get("price_5m_pct", 0.0),
            "quote_volume_5m": micro.get("quote_volume_5m", 0.0),
            "flow_60s": STATE.flow_for(symbol, 60),
            "flow_5m": STATE.flow_for(symbol, 300),
            "liq_5m": STATE.liq_for(symbol, 300),
        }
        row.update(score_symbol(row))
        radar.append(row)

    radar.sort(
        key=lambda x: (
            x["score"],
            abs(x["flow_60s"]["net_usd"]),
            abs(x["oi_15m_pct"]),
            x["volume_24h"],
        ),
        reverse=True,
    )
    strong_long = sum(1 for x in radar if x["signal"] == "LONG_PRESSURE" and x["score"] >= 60)
    strong_short = sum(1 for x in radar if x["signal"] == "SHORT_PRESSURE" and x["score"] >= 60)
    big_flow_60s = sum(x["flow_60s"]["total_usd"] for x in radar)
    liq_5m = sum(x["liq_5m"]["total_usd"] for x in radar)
    summary = {
        "symbols": len(radar),
        "strong_long": strong_long,
        "strong_short": strong_short,
        "large_flow_60s": round(big_flow_60s, 2),
        "liquidation_5m": round(liq_5m, 2),
        "binance_rest": BINANCE_REST,
    }
    STATE.set_radar(radar, summary)
    STATE.set_snapshot_status("ready")


def snapshot_loop() -> None:
    while True:
        started = time.time()
        try:
            build_radar()
        except Exception as exc:
            logging.exception("snapshot failed")
            STATE.set_snapshot_error(str(exc))
        elapsed = time.time() - started
        time.sleep(max(2, SNAPSHOT_INTERVAL - elapsed))


def trade_ws_loop() -> None:
    streams = "/".join(f"{symbol.lower()}@aggTrade" for symbol in WATCH_SYMBOLS)
    if not streams:
        return
    url = f"{BINANCE_WS}/stream?streams={streams}"

    def on_open(_: websocket.WebSocketApp) -> None:
        logging.info("trade websocket connected")
        STATE.set_ws_status("ws_trade_connected", True)

    def on_close(_: websocket.WebSocketApp, __: Any, ___: Any) -> None:
        logging.info("trade websocket closed")
        STATE.set_ws_status("ws_trade_connected", False)

    def on_error(_: websocket.WebSocketApp, error: Any) -> None:
        logging.warning("trade websocket error: %s", error)
        STATE.set_ws_status("ws_trade_connected", False)

    def on_message(_: websocket.WebSocketApp, raw: str) -> None:
        try:
            payload = json.loads(raw).get("data", {})
            symbol = payload.get("s")
            price = float(payload.get("p") or 0)
            qty = float(payload.get("q") or 0)
            notional = price * qty
            if not symbol or notional < LARGE_TRADE_USD:
                return
            side = "SELL" if payload.get("m") else "BUY"
            STATE.add_large_trade(
                {
                    "type": "LARGE_TRADE",
                    "ts": (payload.get("T") or now_ms()) / 1000,
                    "symbol": symbol,
                    "base": fmt_symbol(symbol),
                    "side": side,
                    "price": price,
                    "qty": qty,
                    "notional": round(notional, 2),
                }
            )
        except Exception:
            logging.exception("failed to parse trade message")

    while True:
        ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message,
        )
        ws.run_forever(ping_interval=20, ping_timeout=10)
        STATE.set_ws_status("ws_trade_connected", False)
        time.sleep(3)


def liquidation_ws_loop() -> None:
    url = f"{BINANCE_WS}/ws/!forceOrder@arr"

    def on_open(_: websocket.WebSocketApp) -> None:
        logging.info("liquidation websocket connected")
        STATE.set_ws_status("ws_liq_connected", True)

    def on_close(_: websocket.WebSocketApp, __: Any, ___: Any) -> None:
        logging.info("liquidation websocket closed")
        STATE.set_ws_status("ws_liq_connected", False)

    def on_error(_: websocket.WebSocketApp, error: Any) -> None:
        logging.warning("liquidation websocket error: %s", error)
        STATE.set_ws_status("ws_liq_connected", False)

    def on_message(_: websocket.WebSocketApp, raw: str) -> None:
        try:
            payload = json.loads(raw)
            order = payload.get("o", {})
            symbol = order.get("s")
            price = float(order.get("ap") or order.get("p") or 0)
            qty = float(order.get("q") or 0)
            notional = price * qty
            if not symbol or notional < LARGE_TRADE_USD:
                return
            side = order.get("S", "")
            STATE.add_liquidation(
                {
                    "type": "LIQUIDATION",
                    "ts": (order.get("T") or payload.get("E") or now_ms()) / 1000,
                    "symbol": symbol,
                    "base": fmt_symbol(symbol),
                    "side": side,
                    "price": price,
                    "qty": qty,
                    "notional": round(notional, 2),
                }
            )
        except Exception:
            logging.exception("failed to parse liquidation message")

    while True:
        ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message,
        )
        ws.run_forever(ping_interval=20, ping_timeout=10)
        STATE.set_ws_status("ws_liq_connected", False)
        time.sleep(3)


def start_background_threads() -> None:
    if getattr(app, "_radar_threads_started", False):
        return
    app._radar_threads_started = True
    STATE.mark_threads_started()
    for target, name in [
        (snapshot_loop, "snapshot-loop"),
        (trade_ws_loop, "trade-ws"),
        (liquidation_ws_loop, "liquidation-ws"),
    ]:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()


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
      --surface: #ffffff;
      --surface-2: #f7f9fb;
      --line: #d7dee8;
      --text: #142033;
      --muted: #627086;
      --blue: #2563eb;
      --green: #087f5b;
      --green-bg: #e9f8f1;
      --red: #c92a2a;
      --red-bg: #fff0f0;
      --amber: #b7791f;
      --amber-bg: #fff7df;
      --ink: #0f172a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input, select { font: inherit; }
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
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 800; }
    .brand-mark {
      width: 30px;
      height: 30px;
      border-radius: 8px;
      background: var(--ink);
      color: #fff;
      display: grid;
      place-items: center;
      font-size: 13px;
      letter-spacing: 0;
    }
    .statusbar { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #9aa5b5; }
    .dot.ok { background: var(--green); box-shadow: 0 0 0 3px rgba(8, 127, 91, 0.12); }
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
    .label { color: var(--muted); font-size: 12px; font-weight: 700; margin-bottom: 8px; }
    .value { color: var(--ink); font-size: 22px; font-weight: 900; white-space: nowrap; }
    .sub { color: var(--muted); font-size: 12px; margin-top: 4px; }
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
      background: var(--surface-2);
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
    .up { color: var(--green); font-weight: 800; }
    .down { color: var(--red); font-weight: 800; }
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
      min-width: 260px;
      white-space: normal;
    }
    .chip {
      border: 1px solid var(--line);
      background: var(--surface-2);
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
    .event-main { min-width: 0; }
    .event-title { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; font-weight: 850; }
    .event-meta { color: var(--muted); font-size: 11px; margin-top: 3px; }
    .warn {
      margin-top: 12px;
      border: 1px solid #efd897;
      background: var(--amber-bg);
      color: #7a4d00;
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
      <span id="updatedAt">等待数据</span>
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
      <button class="refresh" id="refresh">刷新</button>
    </div>

    <section class="stats">
      <div class="stat"><div class="label">监控交易对</div><div class="value" id="statSymbols">--</div><div class="sub">USDT 永续</div></div>
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
            <div class="panel-note">大额主动成交、OI、taker 方向、资金费率、爆仓组合评分</div>
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
                <th>Taker 比</th>
                <th>60s 净流</th>
                <th>最大单</th>
                <th>5m 爆仓</th>
                <th>资金费率</th>
                <th>依据</th>
              </tr>
            </thead>
            <tbody id="radarBody">
              <tr><td colspan="12">正在连接 Binance 数据源...</td></tr>
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
      这套雷达只用于缩小观察范围，不构成投资建议。OI 增加只能说明新仓位进入，不能单独证明庄家方向；高分信号也可能是诱多、诱空或出货，实际交易请结合止损、仓位和自己的交易计划。
    </div>
  </main>

  <script>
    let rawData = null;
    let activeFilter = "all";
    const majorSymbols = new Set(["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]);

    function money(value) {
      value = Number(value || 0);
      if (Math.abs(value) >= 1e9) return "$" + (value / 1e9).toFixed(2) + "B";
      if (Math.abs(value) >= 1e6) return "$" + (value / 1e6).toFixed(2) + "M";
      if (Math.abs(value) >= 1e3) return "$" + (value / 1e3).toFixed(0) + "K";
      return "$" + value.toFixed(0);
    }

    function price(value) {
      value = Number(value || 0);
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
      if (signal === "LONG_PRESSURE") return '<span class="badge long">做多压力</span>';
      if (signal === "SHORT_PRESSURE") return '<span class="badge short">做空压力</span>';
      return '<span class="badge watch">观察</span>';
    }

    function applyFilter(rows) {
      const query = document.getElementById("search").value.trim().toUpperCase();
      return rows.filter(row => {
        if (query && !row.symbol.includes(query) && !row.base.includes(query)) return false;
        if (activeFilter === "long") return row.signal === "LONG_PRESSURE";
        if (activeFilter === "short") return row.signal === "SHORT_PRESSURE";
        if (activeFilter === "hot") return row.score >= 60;
        if (activeFilter === "alts") return !majorSymbols.has(row.symbol);
        return true;
      });
    }

    function renderStats(data) {
      const s = data.summary || {};
      document.getElementById("statSymbols").textContent = s.symbols ?? "--";
      document.getElementById("statLong").textContent = s.strong_long ?? "--";
      document.getElementById("statShort").textContent = s.strong_short ?? "--";
      document.getElementById("statFlow").textContent = money(s.large_flow_60s);
      document.getElementById("statLiq").textContent = money(s.liquidation_5m);

      const meta = data.meta || {};
      document.getElementById("tradeDot").classList.toggle("ok", !!meta.ws_trade_connected);
      document.getElementById("liqDot").classList.toggle("ok", !!meta.ws_liq_connected);
      document.getElementById("updatedAt").textContent = meta.updated_at
        ? "更新 " + new Date(meta.updated_at).toLocaleTimeString()
        : "等待数据";
      document.getElementById("errorNote").textContent = meta.snapshot_error ? "数据源错误：" + meta.snapshot_error : "";
    }

    function renderRadar() {
      if (!rawData) return;
      const rows = applyFilter(rawData.radar || []);
      const body = document.getElementById("radarBody");
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="12">当前筛选条件下暂无强信号。</td></tr>';
        return;
      }
      body.innerHTML = rows.slice(0, 80).map(row => {
        const net = row.flow_60s?.net_usd || 0;
        const largest = row.flow_60s?.largest_usd || 0;
        const liq = row.liq_5m?.total_usd || 0;
        const netCls = net >= 0 ? "up" : "down";
        const reasons = (row.reasons || []).map(x => `<span class="chip">${x}</span>`).join("");
        return `<tr>
          <td><div class="symbol">${row.base}</div><div class="small">${row.symbol}</div></td>
          <td>${signalBadge(row.signal)}</td>
          <td><span class="score">${row.score}</span></td>
          <td class="num">${price(row.price)}</td>
          <td class="num">${signedPct(row.price_5m_pct)}</td>
          <td class="num">${signedPct(row.oi_15m_pct)}</td>
          <td class="num">${row.taker_ratio}</td>
          <td class="num ${netCls}">${net >= 0 ? "+" : "-"}${money(Math.abs(net))}</td>
          <td class="num">${money(largest)}</td>
          <td class="num">${money(liq)}</td>
          <td class="num">${Number(row.funding_rate || 0).toFixed(4)}%</td>
          <td><div class="reason">${reasons}</div></td>
        </tr>`;
      }).join("");
    }

    function renderEvents(data) {
      const list = document.getElementById("eventList");
      const events = data.events || [];
      if (!events.length) {
        list.innerHTML = '<div class="event"><div></div><div class="event-main"><div class="event-title">等待大额事件</div><div class="event-meta">阈值达到后会显示在这里</div></div></div>';
        return;
      }
      list.innerHTML = events.slice(0, 80).map(ev => {
        const side = ev.side === "BUY" ? "buy" : "sell";
        const label = ev.type === "LIQUIDATION"
          ? (ev.side === "BUY" ? "空爆" : "多爆")
          : (ev.side === "BUY" ? "主动买" : "主动卖");
        return `<div class="event">
          <div class="event-side ${side}">${label}</div>
          <div class="event-main">
            <div class="event-title"><span>${ev.base}</span><span>${money(ev.notional)}</span></div>
            <div class="event-meta">${price(ev.price)} · ${new Date(ev.ts * 1000).toLocaleTimeString()}</div>
          </div>
        </div>`;
      }).join("");
    }

    async function load() {
      const res = await fetch("/api/radar", {cache: "no-store"});
      rawData = await res.json();
      renderStats(rawData);
      renderRadar();
      renderEvents(rawData);
    }

    document.getElementById("refresh").addEventListener("click", load);
    document.getElementById("search").addEventListener("input", renderRadar);
    document.getElementById("filters").addEventListener("click", event => {
      if (!event.target.dataset.filter) return;
      activeFilter = event.target.dataset.filter;
      document.querySelectorAll("#filters button").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.filter === activeFilter);
      });
      renderRadar();
    });

    load().catch(console.error);
    setInterval(() => load().catch(console.error), 2000);
  </script>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    start_background_threads()
    return render_template_string(HTML)


@app.route("/api/radar")
def api_radar() -> Any:
    start_background_threads()
    return jsonify(STATE.snapshot())


@app.route("/health")
def health() -> Any:
    start_background_threads()
    data = STATE.snapshot()
    return jsonify(
        {
            "ok": data["meta"].get("updated_at", 0) > 0,
            "updated_at": data["meta"].get("updated_at"),
            "snapshot_error": data["meta"].get("snapshot_error"),
            "snapshot_status": data["meta"].get("snapshot_status"),
            "threads_started": data["meta"].get("threads_started"),
            "ws_trade_connected": data["meta"].get("ws_trade_connected"),
            "ws_liq_connected": data["meta"].get("ws_liq_connected"),
        }
    )


start_background_threads()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
