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
BINANCE_REST_FALLBACKS = [
    url.strip().rstrip("/")
    for url in os.environ.get(
        "BINANCE_REST_FALLBACKS",
        "https://fapi.binance.com,https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com,https://fapi4.binance.com",
    ).split(",")
    if url.strip()
]
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
