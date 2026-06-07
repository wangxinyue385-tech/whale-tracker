from __future__ import annotations

import json
import hashlib
import hmac
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

from flask import Flask
from signal_logger import (
    clear_trade_history,
    get_trade_closes,
    init_db,
    log_trade_close,
    log_trade_event,
)


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

MAX_STREAM_SYMBOLS = int(os.environ.get("MAX_STREAM_SYMBOLS", "220"))
TRADE_STREAM_CHUNK_SIZE = int(os.environ.get("TRADE_STREAM_CHUNK_SIZE", "60"))
LARGE_TRADE_USD = float(os.environ.get("LARGE_TRADE_USD", "50000"))
MIN_DYNAMIC_TRADE_USD = float(os.environ.get("MIN_DYNAMIC_TRADE_USD", "10000"))
TAKER_FEE_BPS = float(os.environ.get("TAKER_FEE_BPS", "5"))
SLIPPAGE_BPS = float(os.environ.get("SLIPPAGE_BPS", "3"))
SAFETY_EDGE_BPS = float(os.environ.get("SAFETY_EDGE_BPS", "8"))
HOLD_MINUTES = float(os.environ.get("HOLD_MINUTES", "15"))
STRATEGY_VERSION = "2026-06-07-4h-trend-v1"
STRATEGY_VERSION_FILE = os.environ.get("STRATEGY_VERSION_FILE", ".strategy_version")

BINANCE_WS = os.environ.get("BINANCE_WS", "wss://fstream.binance.com").rstrip("/")
BINANCE_WS_BASES = [
    url.strip().rstrip("/")
    for url in os.environ.get(
        "BINANCE_WS_BASES",
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
TESTNET_AUTO_CLOSE_MINUTES = float(os.environ.get("TESTNET_AUTO_CLOSE_MINUTES", "1"))
TESTNET_ORDER_USDT = float(os.environ.get("TESTNET_ORDER_USDT", "10"))
TESTNET_LEVERAGE = int(os.environ.get("TESTNET_LEVERAGE", "4"))
TESTNET_MAX_POSITIONS = int(os.environ.get("TESTNET_MAX_POSITIONS", "15"))
TESTNET_COOLDOWN_SECONDS = int(os.environ.get("TESTNET_COOLDOWN_SECONDS", "8"))
TESTNET_STRATEGY_MODE = os.environ.get("TESTNET_STRATEGY_MODE", "current")
PAPER_STARTING_BALANCE = float(os.environ.get("PAPER_STARTING_BALANCE", "100"))
ENTRY_CONFIRM_SNAPSHOTS = int(os.environ.get("ENTRY_CONFIRM_SNAPSHOTS", "1"))
ENTRY_CONFIRM_MAX_GAP_SECONDS = int(os.environ.get("ENTRY_CONFIRM_MAX_GAP_SECONDS", "8"))
EXIT_MIN_HOLD_SECONDS = int(os.environ.get("EXIT_MIN_HOLD_SECONDS", "10"))
EXIT_TAKE_PROFIT_PCT = float(os.environ.get("EXIT_TAKE_PROFIT_PCT", "1.20"))
EXIT_PROFIT_ARM_PCT = float(os.environ.get("EXIT_PROFIT_ARM_PCT", "0.80"))
EXIT_TRAIL_KEEP_RATIO = float(os.environ.get("EXIT_TRAIL_KEEP_RATIO", "0.35"))
EXIT_BREAKEVEN_ARM_PCT = float(os.environ.get("EXIT_BREAKEVEN_ARM_PCT", "0.45"))
EXIT_BREAKEVEN_FLOOR_PCT = float(os.environ.get("EXIT_BREAKEVEN_FLOOR_PCT", "0.02"))
EXIT_HARD_STOP_PCT = float(os.environ.get("EXIT_HARD_STOP_PCT", "-0.35"))
FLOW_EXIT_HARD_STOP_PCT = float(os.environ.get("FLOW_EXIT_HARD_STOP_PCT", "-0.28"))
EXHAUSTION_EXIT_HARD_STOP_PCT = float(os.environ.get("EXHAUSTION_EXIT_HARD_STOP_PCT", "-0.32"))
SECTOR_EXIT_HARD_STOP_PCT = float(os.environ.get("SECTOR_EXIT_HARD_STOP_PCT", "-0.30"))
LIQUIDATION_EXIT_HARD_STOP_PCT = float(os.environ.get("LIQUIDATION_EXIT_HARD_STOP_PCT", "-0.35"))
EXIT_STALL_SECONDS = int(os.environ.get("EXIT_STALL_SECONDS", "35"))
EXIT_STALL_MIN_PEAK_PCT = float(os.environ.get("EXIT_STALL_MIN_PEAK_PCT", "0.12"))
EXIT_STALL_LOSS_PCT = float(os.environ.get("EXIT_STALL_LOSS_PCT", "-0.14"))
EXIT_PROGRESS_EPS_PCT = float(os.environ.get("EXIT_PROGRESS_EPS_PCT", "0.03"))
EXIT_MAX_HOLD_SECONDS = int(os.environ.get("EXIT_MAX_HOLD_SECONDS", "75"))
EXIT_MAX_HOLD_SUPPORT_FLOOR_PCT = float(os.environ.get("EXIT_MAX_HOLD_SUPPORT_FLOOR_PCT", "-0.20"))
FUNDING_EXIT_TAKE_PROFIT_PCT = float(os.environ.get("FUNDING_EXIT_TAKE_PROFIT_PCT", "0.55"))
FUNDING_EXIT_HARD_STOP_PCT = float(os.environ.get("FUNDING_EXIT_HARD_STOP_PCT", "-0.28"))
FUNDING_EXIT_NORMAL_RATE_PCT = float(os.environ.get("FUNDING_EXIT_NORMAL_RATE_PCT", "0.035"))
FUNDING_EXIT_MAX_HOLD_SECONDS = int(os.environ.get("FUNDING_EXIT_MAX_HOLD_SECONDS", "900"))
EXIT_REVERSE_SCORE = float(os.environ.get("EXIT_REVERSE_SCORE", "70"))
EXIT_HOLD_MIN_SCORE = float(os.environ.get("EXIT_HOLD_MIN_SCORE", "65"))
EXIT_INVALID_SNAPSHOTS = int(os.environ.get("EXIT_INVALID_SNAPSHOTS", "2"))
LOW_CONFIDENCE_PROB = float(os.environ.get("LOW_CONFIDENCE_PROB", "68"))
LOW_CONFIDENCE_TAKE_PROFIT_USDT = float(os.environ.get("LOW_CONFIDENCE_TAKE_PROFIT_USDT", "0.03"))
POSITION_ADD_COOLDOWN_SECONDS = int(os.environ.get("POSITION_ADD_COOLDOWN_SECONDS", "45"))
POSITION_MAX_ADDS = int(os.environ.get("POSITION_MAX_ADDS", "0"))
POSITION_ADD_GROSS_LOSS_USDT = float(os.environ.get("POSITION_ADD_GROSS_LOSS_USDT", "0.03"))
POSITION_PROFIT_FLOOR_USDT = float(os.environ.get("POSITION_PROFIT_FLOOR_USDT", "0.06"))
POSITION_PROFIT_PULLBACK_USDT = float(os.environ.get("POSITION_PROFIT_PULLBACK_USDT", "0.04"))
POSITION_UNSUPPORTED_GRACE_SECONDS = int(os.environ.get("POSITION_UNSUPPORTED_GRACE_SECONDS", "45"))
FLOW_POSITION_UNSUPPORTED_GRACE_SECONDS = int(os.environ.get("FLOW_POSITION_UNSUPPORTED_GRACE_SECONDS", "25"))
FLOW_MOMENTUM_MAX_MARGIN_MULT = float(os.environ.get("FLOW_MOMENTUM_MAX_MARGIN_MULT", "1.15"))

_trade_lock = threading.Lock()
_testnet_config = {
    "execution_mode": os.environ.get("EXECUTION_MODE", "paper"),
    "api_key": os.environ.get("BINANCE_TESTNET_API_KEY", ""),
    "api_secret": os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
    "auto_trade": os.environ.get("TESTNET_AUTO_TRADE", "1") == "1",
    "order_usdt": TESTNET_ORDER_USDT,
    "leverage": TESTNET_LEVERAGE,
    "max_positions": TESTNET_MAX_POSITIONS,
    "cooldown_seconds": TESTNET_COOLDOWN_SECONDS,
    "auto_close_minutes": TESTNET_AUTO_CLOSE_MINUTES,
    "strategy_mode": TESTNET_STRATEGY_MODE,
}
_trade_cooldown: dict[str, int] = {}
_entry_candidates: dict[str, dict] = {}
_auto_positions: dict[str, dict] = {}
_trade_events: list[dict] = []
_equity_curve: list[dict] = []
_trade_closes: list[dict] = []
_exchange_cache = {"ts": 0.0, "symbols": {}}
_testnet_time_cache = {"ts": 0.0, "offset_ms": 0}
_last_prices: dict[str, float] = {}
_market_snapshots: dict[str, dict] = {}
_market_snapshot_version = 0
_paper_cash = PAPER_STARTING_BALANCE
_paper_positions: dict[str, dict] = {}
_loss_cooldowns: dict[str, int] = {}
_strategy_cooldowns: dict[str, int] = {}
BANNED_LOW_LIQUIDITY = {
    "CLOUSDT", "BABYUSDT", "BZUSDT", "HOMEUSDT",
    "XAGUSDT", "PORTALUSDT", "0GUSDT",
    "ALLOUSDT", "SLXUSDT", "BLUAIUSDT", "SKYAIUSDT", "CBRSUSDT",
}
MAJOR_SYMBOLS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
PRIMARY_AUTO_STRATEGIES = {"main_flow_direction"}
CURRENT_AUTO_STRATEGIES = {"main_flow_direction"}
TEST_MORE_AUTO_STRATEGIES = {
    "main_flow_direction",
    "liquidity_sweep_reclaim",
    "flow_momentum",
    "liquidation_reversal",
    "flow_exhaustion_reversal",
    "funding_reversion",
}
ONE_MINUTE_AUTO_STRATEGIES = {
    "main_flow_direction",
}
STRATEGY_MODE_MAP = {
    "primary": PRIMARY_AUTO_STRATEGIES,
    "liquidity_sweep_reclaim": {"liquidity_sweep_reclaim"},
    "test_more": TEST_MORE_AUTO_STRATEGIES,
    "one_minute": ONE_MINUTE_AUTO_STRATEGIES,
    "current": CURRENT_AUTO_STRATEGIES,
}
LEGACY_STRATEGY_MODE_ALIASES = {
    "exhaustion_sector": "primary",
    "exhaustion_liquidation": "primary",
    "sector_liquidation": "primary",
    "flow_exhaustion_reversal": "primary",
    "sector_lead_lag": "primary",
    "liquidation_reversal": "primary",
}
STRATEGY_MODE_LABELS = {
    "primary": "主信号：4h突破趋势",
    "liquidity_sweep_reclaim": "主信号：极端扫单反转",
    "test_more": "主信号+子信号：多策略测试",
    "one_minute": "主信号：4h突破趋势",
    "current": "当前策略：4h突破趋势",
}


def _strategy_mode() -> str:
    mode = str(_testnet_config.get("strategy_mode") or "current").strip()
    if mode in STRATEGY_MODE_MAP:
        return mode
    if mode in LEGACY_STRATEGY_MODE_ALIASES:
        return LEGACY_STRATEGY_MODE_ALIASES[mode]
    return "current"


def _strategy_allowed_for_auto(strategy: str) -> bool:
    strategy = str(strategy or "").strip()
    return bool(strategy) and strategy in STRATEGY_MODE_MAP[_strategy_mode()]


def _strategy_mode_label() -> str:
    return STRATEGY_MODE_LABELS.get(_strategy_mode(), STRATEGY_MODE_LABELS["current"])


def _reset_paper_state(reason: str = "") -> None:
    global _paper_cash
    _paper_cash = PAPER_STARTING_BALANCE
    _paper_positions.clear()
    _auto_positions.clear()
    _trade_events.clear()
    _trade_closes.clear()
    _equity_curve.clear()
    _entry_candidates.clear()
    _trade_cooldown.clear()
    _loss_cooldowns.clear()
    _strategy_cooldowns.clear()
    clear_trade_history()
    if reason:
        _event(reason, "info", event_type="info")


def _reset_if_strategy_changed() -> None:
    try:
        current = ""
        if os.path.exists(STRATEGY_VERSION_FILE):
            with open(STRATEGY_VERSION_FILE, "r", encoding="utf-8") as handle:
                current = handle.read().strip()
        if current == STRATEGY_VERSION:
            return
        _reset_paper_state(f"策略已更新到 {STRATEGY_VERSION}，模拟盘战绩已归零")
        with open(STRATEGY_VERSION_FILE, "w", encoding="utf-8") as handle:
            handle.write(STRATEGY_VERSION)
    except Exception as exc:  # noqa: BLE001
        _event(f"策略版本记录失败：{exc}", "warn", event_type="warn")


def _public_testnet_get(path: str, params: dict | None = None) -> dict:
    query = f"?{urlencode(params or {})}" if params else ""
    req = urllib.request.Request(BINANCE_TESTNET_REST + path + query, method="GET")
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _testnet_timestamp_ms(force_refresh: bool = False) -> int:
    now_ts = time.time()
    if force_refresh or now_ts - float(_testnet_time_cache["ts"]) > 30:
        try:
            data = _public_testnet_get("/fapi/v1/time")
            server_ms = int(data.get("serverTime") or 0)
            if server_ms > 0:
                _testnet_time_cache["offset_ms"] = server_ms - int(now_ts * 1000)
                _testnet_time_cache["ts"] = now_ts
        except Exception:  # noqa: BLE001
            _testnet_time_cache["ts"] = now_ts
    return int(time.time() * 1000) + int(_testnet_time_cache.get("offset_ms") or 0)


def _signed_testnet_request(method: str, path: str, params: dict | None = None) -> dict:
    cfg = _testnet_config
    if not cfg.get("api_key") or not cfg.get("api_secret"):
        raise RuntimeError("模拟盘 API Key/Secret 未配置")
    last_error = None
    for attempt in range(2):
        payload = dict(params or {})
        payload["timestamp"] = _testnet_timestamp_ms(force_refresh=attempt > 0)
        payload["recvWindow"] = 10000
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
            last_error = RuntimeError(f"Binance testnet {exc.code}: {detail}")
            if '"code":-1021' in detail or "Timestamp" in detail:
                continue
            raise last_error from exc
    raise last_error or RuntimeError("Binance testnet request failed")


def _event(message: str, level: str = "info", **extra) -> None:
    if str(extra.get("event_type") or "") == "skip" or "跳过" in str(message or ""):
        return
    item = {"ts": int(time.time() * 1000), "message": message, "level": level, **extra}
    _trade_events.insert(0, item)
    del _trade_events[80:]
    try:
        log_trade_event(item)
    except Exception:
        pass


_reset_if_strategy_changed()


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


def _is_paper_mode() -> bool:
    return str(_testnet_config.get("execution_mode") or "paper") == "paper"


def _remember_prices(prices: dict[str, float] | None) -> None:
    for symbol, value in (prices or {}).items():
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if symbol and price > 0:
            _last_prices[str(symbol)] = price


def _safe_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _update_market_snapshots(rows: list[dict] | None) -> None:
    global _market_snapshot_version
    if rows:
        _market_snapshot_version += 1
    now_ms = int(time.time() * 1000)
    for row in rows or []:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        _market_snapshots[symbol] = {
            "ts": now_ms,
            "version": _market_snapshot_version,
            "symbol": symbol,
            "follow": row.get("follow"),
            "signal": row.get("signal"),
            "score": _safe_float(row.get("score")),
            "strategy": row.get("strategy") or "flow_momentum",
            "strategy_label": row.get("strategy_label") or "",
            "main_signal": row.get("main_signal") or row.get("strategy") or "flow_momentum",
            "signal_variant": row.get("signal_variant") or "primary",
            "price": _safe_float(row.get("price")),
            "price_1m_pct": _safe_float(row.get("price_1m_pct")),
            "price_3m_pct": _safe_float(row.get("price_3m_pct")),
            "price_5m_pct": _safe_float(row.get("price_5m_pct")),
            "net_60s_usd": _safe_float(row.get("net_60s_usd")),
            "net_5m_usd": _safe_float(row.get("net_5m_usd")),
            "long_liq_5m_usd": _safe_float(row.get("long_liq_5m_usd")),
            "short_liq_5m_usd": _safe_float(row.get("short_liq_5m_usd")),
            "sweep_side": row.get("sweep_side") or "",
            "reclaim_level": _safe_float(row.get("reclaim_level")),
            "sweep_depth_pct": _safe_float(row.get("sweep_depth_pct")),
            "forecast_5m_prob": _safe_float(row.get("forecast_5m_prob")),
            "net_edge_pct": _safe_float(row.get("net_edge_pct")),
            "take_profit_pct": _safe_float(row.get("take_profit_pct")),
            "trail_arm_pct": _safe_float(row.get("trail_arm_pct")),
            "funding_rate": _safe_float(row.get("funding_rate")),
            "book_spread_pct": _safe_float(row.get("book_spread_pct")),
            "book_imbalance": _safe_float(row.get("book_imbalance")),
            "bid_depth_usd": _safe_float(row.get("bid_depth_usd")),
            "ask_depth_usd": _safe_float(row.get("ask_depth_usd")),
            "risks": row.get("risks") or [],
        }
    cutoff = now_ms - 10 * 60 * 1000
    for symbol, row in list(_market_snapshots.items()):
        if int(row.get("ts") or 0) < cutoff:
            _market_snapshots.pop(symbol, None)


import entry_strategy
import exit_strategy


entry_strategy.bind(__import__(__name__))
exit_strategy.bind(__import__(__name__))
exit_strategy.bind_entry_strategy(entry_strategy)
entry_strategy.bind_exit_strategy(exit_strategy)

_auto_signal_allowed_for_trade = entry_strategy._auto_signal_allowed_for_trade
_auto_trade_signals = entry_strategy._auto_trade_signals
_opportunity_grade = entry_strategy._opportunity_grade

_close_due_positions = exit_strategy._close_due_positions
_strategy_hard_stop_pct = exit_strategy._strategy_hard_stop_pct


def _public_testnet_status() -> dict:
    cfg = _testnet_config
    closes = _trade_closes[-200:]
    events = [
        item for item in _trade_events[:300]
        if str(item.get("event_type") or "") not in {"skip", "info"} and "跳过" not in str(item.get("message") or "")
    ]
    wins = [item for item in closes if _safe_float(item.get("realized")) > 0]
    losses = [item for item in closes if _safe_float(item.get("realized")) < 0]
    gross_win = sum(_safe_float(item.get("realized")) for item in wins)
    gross_loss = abs(sum(_safe_float(item.get("realized")) for item in losses))
    by_strategy = []
    by_grade = []
    by_reason = []
    grouped_closes: dict[tuple[str, str], list[dict]] = {}
    grouped_grades: dict[str, list[dict]] = {}
    grouped_reasons: dict[str, list[dict]] = {}

    def reason_bucket(reason: str) -> str:
        if "止损" in reason:
            return "止损"
        if "止盈" in reason or "净利落袋" in reason or "微利" in reason:
            return "止盈/落袋"
        if "不支持持仓" in reason or "信号衰减" in reason or "不再触发" in reason:
            return "信号衰减"
        if "无进展" in reason or "走势转弱" in reason:
            return "无进展/转弱"
        if "缺少新策略快照" in reason or "到时" in reason or "持仓" in reason:
            return "到时/缺快照"
        return "其他"

    for item in closes:
        strategy = str(item.get("strategy") or item.get("main_signal") or "unknown")
        label = str(item.get("strategy_label") or strategy)
        grouped_closes.setdefault((strategy, label), []).append(item)
        grouped_grades.setdefault(str(item.get("grade") or "--"), []).append(item)
        grouped_reasons.setdefault(reason_bucket(str(item.get("reason") or "")), []).append(item)
    for (strategy, label), items in grouped_closes.items():
        item_wins = [_safe_float(row.get("realized")) for row in items if _safe_float(row.get("realized")) > 0]
        item_losses = [_safe_float(row.get("realized")) for row in items if _safe_float(row.get("realized")) < 0]
        item_gross_win = sum(item_wins)
        item_gross_loss = abs(sum(item_losses))
        by_strategy.append({
            "strategy": strategy,
            "label": label,
            "count": len(items),
            "net": sum(_safe_float(row.get("realized")) for row in items),
            "wins": len(item_wins),
            "losses": len(item_losses),
            "win_rate": (len(item_wins) / len(items) * 100) if items else 0,
            "profit_factor": (item_gross_win / item_gross_loss) if item_gross_loss > 0 else (item_gross_win if item_gross_win > 0 else 0),
        })
    for grade, items in grouped_grades.items():
        item_wins = [_safe_float(row.get("realized")) for row in items if _safe_float(row.get("realized")) > 0]
        item_losses = [_safe_float(row.get("realized")) for row in items if _safe_float(row.get("realized")) < 0]
        by_grade.append({
            "grade": grade,
            "count": len(items),
            "net": sum(_safe_float(row.get("realized")) for row in items),
            "wins": len(item_wins),
            "losses": len(item_losses),
            "win_rate": (len(item_wins) / len(items) * 100) if items else 0,
        })
    for reason, items in grouped_reasons.items():
        item_wins = [_safe_float(row.get("realized")) for row in items if _safe_float(row.get("realized")) > 0]
        item_losses = [_safe_float(row.get("realized")) for row in items if _safe_float(row.get("realized")) < 0]
        by_reason.append({
            "reason": reason,
            "count": len(items),
            "net": sum(_safe_float(row.get("realized")) for row in items),
            "wins": len(item_wins),
            "losses": len(item_losses),
            "win_rate": (len(item_wins) / len(items) * 100) if items else 0,
        })
    by_strategy.sort(key=lambda row: _safe_float(row.get("net")), reverse=True)
    by_grade.sort(key=lambda row: _safe_float(row.get("net")))
    by_reason.sort(key=lambda row: _safe_float(row.get("net")))
    trade_stats = {
        "count": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "net": sum(_safe_float(item.get("realized")) for item in closes),
        "fees": sum(_safe_float(item.get("fee")) for item in closes),
        "win_rate": (len(wins) / len(closes) * 100) if closes else 0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (gross_win if gross_win > 0 else 0),
        "avg_win": (gross_win / len(wins)) if wins else 0,
        "avg_loss": (gross_loss / len(losses)) if losses else 0,
        "recent": closes[-200:],
        "by_strategy": by_strategy,
        "by_grade": by_grade,
        "by_reason": by_reason,
    }
    base = {
        "rest": BINANCE_TESTNET_REST,
        "execution_mode": cfg.get("execution_mode") or "paper",
        "configured": bool(cfg.get("api_key") and cfg.get("api_secret")),
        "has_api_key": bool(cfg.get("api_key")),
        "has_api_secret": bool(cfg.get("api_secret")),
        "auto_trade": bool(cfg.get("auto_trade")),
        "order_usdt": cfg.get("order_usdt"),
        "leverage": cfg.get("leverage"),
        "max_positions": cfg.get("max_positions"),
        "cooldown_seconds": cfg.get("cooldown_seconds"),
        "auto_close_minutes": cfg.get("auto_close_minutes"),
        "strategy_mode": _strategy_mode(),
        "strategy_mode_label": _strategy_mode_label(),
        "allowed_strategies": sorted(STRATEGY_MODE_MAP[_strategy_mode()]),
        "events": events[:200],
        "equity_curve": _equity_curve[-120:],
        "trade_stats": trade_stats,
    }
    if _is_paper_mode():
        account = _paper_account_snapshot()
        _close_due_positions(account)
        account = _paper_account_snapshot()
        return {
            **base,
            "configured": True,
            "account_ok": True,
            "message": "本地模拟盘已启用，无需 API Key",
            **account,
            "events": events[:200],
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
        return {**base, "account_ok": True, **account, "events": events[:20], "equity_curve": _equity_curve[-120:]}
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


from ui import register_routes


register_routes(app, runtime=__import__(__name__))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
