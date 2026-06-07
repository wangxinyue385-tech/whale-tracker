from __future__ import annotations

import csv
import math
import statistics
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
    "TONUSDT", "TRXUSDT",
]

BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
CACHE_DIR = Path(".backtest_cache")
COST_PCT = 0.16  # 5 bps taker + 3 bps slippage per side.


@dataclass
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    quote_volume: float


@dataclass
class Trade:
    strategy: str
    symbol: str
    side: int
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    gross_pct: float
    net_pct: float
    reason: str


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m == 13:
            y += 1
            m = 1
    return months


def download_month(symbol: str, interval: str, year: int, month: int) -> Path | None:
    CACHE_DIR.mkdir(exist_ok=True)
    filename = f"{symbol}-{interval}-{year}-{month:02d}.zip"
    path = CACHE_DIR / filename
    if path.exists() and path.stat().st_size > 100:
        return path
    url = f"{BASE_URL}/{symbol}/{interval}/{filename}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "research-backtest/1.0"})
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    if len(data) < 100:
        return None
    path.write_bytes(data)
    return path


def load_symbol(symbol: str, interval: str, months: list[tuple[int, int]]) -> list[Bar]:
    bars: list[Bar] = []
    for year, month in months:
        path = download_month(symbol, interval, year, month)
        if not path:
            continue
        try:
            with zipfile.ZipFile(path) as zf:
                name = zf.namelist()[0]
                text = zf.read(name).decode()
        except (zipfile.BadZipFile, IndexError, UnicodeDecodeError):
            continue
        for row in csv.reader(text.splitlines()):
            if not row or row[0] == "open_time":
                continue
            try:
                bars.append(Bar(
                    ts=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    quote_volume=float(row[7]),
                ))
            except (ValueError, IndexError):
                continue
    bars.sort(key=lambda x: x.ts)
    return bars


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if not values:
        return out
    k = 2 / (period + 1)
    value = values[0]
    for i, item in enumerate(values):
        value = item if i == 0 else item * k + value * (1 - k)
        if i >= period - 1:
            out[i] = value
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, item in enumerate(values):
        total += item
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def rolling_high(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(period, len(values)):
        out[i] = max(values[i - period:i])
    return out


def rolling_low(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(period, len(values)):
        out[i] = min(values[i - period:i])
    return out


def ret(closes: list[float], i: int, period: int) -> float | None:
    if i < period or closes[i - period] <= 0:
        return None
    return closes[i] / closes[i - period] - 1


def true_range_pct(rows: list[Bar]) -> list[float]:
    out: list[float] = [0.0] * len(rows)
    for i, row in enumerate(rows):
        prev_close = rows[i - 1].close if i else row.open
        tr = max(row.high - row.low, abs(row.high - prev_close), abs(row.low - prev_close))
        out[i] = tr / row.close if row.close else 0.0
    return out


def indicators(rows: list[Bar]) -> dict[str, list[float | None] | list[float]]:
    closes = [x.close for x in rows]
    highs = [x.high for x in rows]
    lows = [x.low for x in rows]
    vols = [x.quote_volume for x in rows]
    tr = true_range_pct(rows)
    return {
        "ema24": ema(closes, 24),
        "ema48": ema(closes, 48),
        "ema96": ema(closes, 96),
        "vol24": sma(vols, 24),
        "atr24": sma(tr, 24),
        "high20": rolling_high(highs, 20),
        "low20": rolling_low(lows, 20),
        "high55": rolling_high(highs, 55),
        "low55": rolling_low(lows, 55),
    }


def resample(rows: list[Bar], hours: int) -> list[Bar]:
    if hours <= 1:
        return rows
    bucket_ms = hours * 60 * 60 * 1000
    out: list[Bar] = []
    cur_key: int | None = None
    cur: Bar | None = None
    for row in rows:
        key = row.ts // bucket_ms * bucket_ms
        if cur_key != key:
            if cur:
                out.append(cur)
            cur_key = key
            cur = Bar(key, row.open, row.high, row.low, row.close, row.quote_volume)
        elif cur:
            cur.high = max(cur.high, row.high)
            cur.low = min(cur.low, row.low)
            cur.close = row.close
            cur.quote_volume += row.quote_volume
    if cur:
        out.append(cur)
    return out


def btc_regime(btc_rows: list[Bar]) -> dict[int, tuple[int, float]]:
    ind = indicators(btc_rows)
    closes = [x.close for x in btc_rows]
    out: dict[int, tuple[int, float]] = {}
    for i, row in enumerate(btc_rows):
        ema48 = ind["ema48"][i]
        ema96 = ind["ema96"][i]
        r24 = ret(closes, i, 24)
        regime = 0
        if ema48 and ema96 and r24 is not None:
            if ema48 > ema96 and r24 > 0:
                regime = 1
            elif ema48 < ema96 and r24 < 0:
                regime = -1
        out[row.ts] = (regime, r24 or 0.0)
    return out


def expand_regime_to_hourly(regime: dict[int, tuple[int, float]], hours: int) -> dict[int, tuple[int, float]]:
    if hours <= 1:
        return regime
    out: dict[int, tuple[int, float]] = {}
    step = 60 * 60 * 1000
    for ts, value in regime.items():
        for i in range(hours):
            out[ts + i * step] = value
    return out


def close_trade(strategy: str, symbol: str, side: int, entry_ts: int, entry: float, row: Bar, reason: str) -> Trade:
    gross = side * (row.close / entry - 1) * 100
    return Trade(strategy, symbol, side, entry_ts, row.ts, entry, row.close, gross, gross - COST_PCT, reason)


def trend_pullback(symbol: str, rows: list[Bar], btc: dict[int, tuple[int, float]]) -> list[Trade]:
    ind = indicators(rows)
    closes = [x.close for x in rows]
    trades: list[Trade] = []
    pos = 0
    entry = 0.0
    entry_ts = 0
    peak = 0.0
    trough = math.inf
    for i, row in enumerate(rows):
        if i < 120:
            continue
        ema24 = ind["ema24"][i]
        ema96 = ind["ema96"][i]
        atr = ind["atr24"][i]
        vol24 = ind["vol24"][i]
        if not ema24 or not ema96 or not atr or not vol24:
            continue
        regime = btc.get(row.ts, (0, 0.0))[0]
        r12 = ret(closes, i, 12)
        r24 = ret(closes, i, 24)
        volume_ok = row.quote_volume >= vol24 * 0.55
        if pos:
            peak = max(peak, row.high)
            trough = min(trough, row.low)
            gross_now = pos * (row.close / entry - 1)
            trend_broken = (pos == 1 and row.close < ema24) or (pos == -1 and row.close > ema24)
            giveback = (pos == 1 and row.close < peak * (1 - max(atr * 1.8, 0.012))) or (
                pos == -1 and row.close > trough * (1 + max(atr * 1.8, 0.012))
            )
            stale = i - entry_i >= 72 and gross_now <= 0
            if trend_broken or giveback or stale:
                trades.append(close_trade("trend_pullback", symbol, pos, entry_ts, entry, row, "trend_break"))
                pos = 0
            continue
        if r12 is None or r24 is None or not volume_ok:
            continue
        long_trend = row.close > ema96 and ema24 > ema96 and r24 > 0 and regime >= 0
        short_trend = row.close < ema96 and ema24 < ema96 and r24 < 0 and regime <= 0
        long_reclaim = row.low <= ema24 * 1.004 and row.close > ema24 and row.close > row.open and r12 > -0.025
        short_reclaim = row.high >= ema24 * 0.996 and row.close < ema24 and row.close < row.open and r12 < 0.025
        if long_trend and long_reclaim:
            pos, entry, entry_ts, entry_i, peak, trough = 1, row.close, row.ts, i, row.high, row.low
        elif short_trend and short_reclaim:
            pos, entry, entry_ts, entry_i, peak, trough = -1, row.close, row.ts, i, row.high, row.low
    return trades


def donchian_breakout(symbol: str, rows: list[Bar], btc: dict[int, tuple[int, float]]) -> list[Trade]:
    ind = indicators(rows)
    trades: list[Trade] = []
    pos = 0
    entry = 0.0
    entry_ts = 0
    for i, row in enumerate(rows):
        if i < 120:
            continue
        high55 = ind["high55"][i]
        low55 = ind["low55"][i]
        high20 = ind["high20"][i]
        low20 = ind["low20"][i]
        ema48 = ind["ema48"][i]
        ema96 = ind["ema96"][i]
        vol24 = ind["vol24"][i]
        if not high55 or not low55 or not high20 or not low20 or not ema48 or not ema96 or not vol24:
            continue
        regime = btc.get(row.ts, (0, 0.0))[0]
        if pos == 1 and (row.close < low20 or ema48 < ema96):
            trades.append(close_trade("donchian_breakout", symbol, pos, entry_ts, entry, row, "channel_exit"))
            pos = 0
        elif pos == -1 and (row.close > high20 or ema48 > ema96):
            trades.append(close_trade("donchian_breakout", symbol, pos, entry_ts, entry, row, "channel_exit"))
            pos = 0
        if pos:
            continue
        if row.quote_volume < vol24 * 0.70:
            continue
        if row.close > high55 and ema48 > ema96 and regime >= 0:
            pos, entry, entry_ts = 1, row.close, row.ts
        elif row.close < low55 and ema48 < ema96 and regime <= 0:
            pos, entry, entry_ts = -1, row.close, row.ts
    return trades


def donchian_long_only(symbol: str, rows: list[Bar], btc: dict[int, tuple[int, float]]) -> list[Trade]:
    ind = indicators(rows)
    trades: list[Trade] = []
    pos = 0
    entry = 0.0
    entry_ts = 0
    for i, row in enumerate(rows):
        if i < 120:
            continue
        high55 = ind["high55"][i]
        low20 = ind["low20"][i]
        ema48 = ind["ema48"][i]
        ema96 = ind["ema96"][i]
        vol24 = ind["vol24"][i]
        if not high55 or not low20 or not ema48 or not ema96 or not vol24:
            continue
        regime = btc.get(row.ts, (0, 0.0))[0]
        if pos == 1 and (row.close < low20 or ema48 < ema96 or regime < 0):
            trades.append(close_trade("donchian_long_only", symbol, pos, entry_ts, entry, row, "channel_exit"))
            pos = 0
        if pos:
            continue
        if row.quote_volume < vol24 * 0.70:
            continue
        if row.close > high55 and ema48 > ema96 and regime >= 0:
            pos, entry, entry_ts = 1, row.close, row.ts
    return trades


def trend_pullback_long_only(symbol: str, rows: list[Bar], btc: dict[int, tuple[int, float]]) -> list[Trade]:
    ind = indicators(rows)
    closes = [x.close for x in rows]
    trades: list[Trade] = []
    pos = 0
    entry = 0.0
    entry_ts = 0
    peak = 0.0
    for i, row in enumerate(rows):
        if i < 120:
            continue
        ema24 = ind["ema24"][i]
        ema48 = ind["ema48"][i]
        ema96 = ind["ema96"][i]
        atr = ind["atr24"][i]
        vol24 = ind["vol24"][i]
        if not ema24 or not ema48 or not ema96 or not atr or not vol24:
            continue
        regime = btc.get(row.ts, (0, 0.0))[0]
        r24 = ret(closes, i, 24)
        volume_ok = row.quote_volume >= vol24 * 0.55
        if pos:
            peak = max(peak, row.high)
            trend_broken = row.close < ema48 or ema24 < ema96 or regime < 0
            giveback = row.close < peak * (1 - max(atr * 2.4, 0.018))
            if trend_broken or giveback:
                trades.append(close_trade("trend_pullback_long_only", symbol, pos, entry_ts, entry, row, "trend_break"))
                pos = 0
            continue
        if r24 is None or not volume_ok:
            continue
        trend = row.close > ema96 and ema24 > ema48 > ema96 and r24 > 0 and regime >= 0
        reclaim = row.low <= ema24 * 1.006 and row.close > ema24 and row.close > row.open
        if trend and reclaim:
            pos, entry, entry_ts, peak = 1, row.close, row.ts, row.high
    return trades


def hourly_mean_reversion(symbol: str, rows: list[Bar], btc: dict[int, tuple[int, float]]) -> list[Trade]:
    ind = indicators(rows)
    closes = [x.close for x in rows]
    trades: list[Trade] = []
    pos = 0
    entry = 0.0
    entry_ts = 0
    for i, row in enumerate(rows):
        if i < 120:
            continue
        ema24 = ind["ema24"][i]
        atr = ind["atr24"][i]
        if not ema24 or not atr:
            continue
        z = (row.close - ema24) / row.close
        if pos == 1 and (row.close >= ema24 or i - entry_i >= 12):
            trades.append(close_trade("mean_reversion", symbol, pos, entry_ts, entry, row, "revert_or_time"))
            pos = 0
        elif pos == -1 and (row.close <= ema24 or i - entry_i >= 12):
            trades.append(close_trade("mean_reversion", symbol, pos, entry_ts, entry, row, "revert_or_time"))
            pos = 0
        if pos:
            continue
        r6 = ret(closes, i, 6)
        regime = btc.get(row.ts, (0, 0.0))[0]
        if r6 is None:
            continue
        if z < -max(atr * 1.6, 0.018) and r6 < -0.025 and regime >= 0:
            pos, entry, entry_ts, entry_i = 1, row.close, row.ts, i
        elif z > max(atr * 1.6, 0.018) and r6 > 0.025 and regime <= 0:
            pos, entry, entry_ts, entry_i = -1, row.close, row.ts, i
    return trades


def cross_sectional_momentum(data: dict[str, list[Bar]]) -> list[Trade]:
    inds = {sym: indicators(rows) for sym, rows in data.items()}
    by_ts: dict[int, dict[str, int]] = {}
    for sym, rows in data.items():
        for i, row in enumerate(rows):
            by_ts.setdefault(row.ts, {})[sym] = i
    btc_rows = data.get("BTCUSDT", [])
    btc_by_ts = {row.ts: i for i, row in enumerate(btc_rows)}
    btc_closes = [x.close for x in btc_rows]
    trades: list[Trade] = []
    positions: dict[str, tuple[int, float, int, int]] = {}
    for ts in sorted(by_ts):
        if ts % (4 * 60 * 60 * 1000) != 0:
            continue
        btc_i = btc_by_ts.get(ts)
        btc_r24 = ret(btc_closes, btc_i, 24) if btc_i is not None else 0
        ranks: list[tuple[float, str, int]] = []
        for sym, i in by_ts[ts].items():
            rows = data[sym]
            if i < 120:
                continue
            closes = [x.close for x in rows]
            r24 = ret(closes, i, 24)
            ema48 = inds[sym]["ema48"][i]
            vol24 = inds[sym]["vol24"][i]
            if r24 is None or not ema48 or not vol24 or rows[i].quote_volume < vol24 * 0.45:
                continue
            ranks.append((r24, sym, i))
        ranks.sort(reverse=True)
        longs = {sym for r, sym, i in ranks[:4] if r > 0.012 and data[sym][i].close > (inds[sym]["ema48"][i] or 0) and (btc_r24 or 0) >= -0.01}
        shorts = {sym for r, sym, i in ranks[-4:] if r < -0.012 and data[sym][i].close < (inds[sym]["ema48"][i] or 0) and (btc_r24 or 0) <= 0.01}
        target = {sym: 1 for sym in longs}
        target.update({sym: -1 for sym in shorts})
        for sym, (side, entry, entry_ts, bars_held) in list(positions.items()):
            row_i = by_ts[ts].get(sym)
            if row_i is None:
                continue
            row = data[sym][row_i]
            next_side = target.get(sym, 0)
            if next_side != side or bars_held >= 3:
                trades.append(close_trade("cross_sectional_momentum", sym, side, entry_ts, entry, row, "rebalance"))
                positions.pop(sym, None)
            else:
                positions[sym] = (side, entry, entry_ts, bars_held + 1)
        for sym, side in target.items():
            if sym in positions:
                continue
            row_i = by_ts[ts].get(sym)
            if row_i is None:
                continue
            row = data[sym][row_i]
            positions[sym] = (side, row.close, row.ts, 0)
    return trades


def cross_sectional_long_only(data: dict[str, list[Bar]]) -> list[Trade]:
    inds = {sym: indicators(rows) for sym, rows in data.items()}
    by_ts: dict[int, dict[str, int]] = {}
    for sym, rows in data.items():
        for i, row in enumerate(rows):
            by_ts.setdefault(row.ts, {})[sym] = i
    btc_rows = data.get("BTCUSDT", [])
    btc_reg = btc_regime(btc_rows)
    trades: list[Trade] = []
    positions: dict[str, tuple[int, float, int, int]] = {}
    for ts in sorted(by_ts):
        if ts % (4 * 60 * 60 * 1000) != 0:
            continue
        if btc_reg.get(ts, (0, 0.0))[0] < 0:
            target: dict[str, int] = {}
        else:
            ranks: list[tuple[float, str, int]] = []
            for sym, i in by_ts[ts].items():
                rows = data[sym]
                if i < 120:
                    continue
                closes = [x.close for x in rows]
                r24 = ret(closes, i, 24)
                r72 = ret(closes, i, 72)
                ema48 = inds[sym]["ema48"][i]
                vol24 = inds[sym]["vol24"][i]
                if r24 is None or r72 is None or not ema48 or not vol24:
                    continue
                if rows[i].quote_volume < vol24 * 0.45 or rows[i].close < ema48:
                    continue
                ranks.append((r24 + r72 * 0.5, sym, i))
            ranks.sort(reverse=True)
            target = {sym: 1 for score, sym, i in ranks[:3] if score > 0.018}
        for sym, (side, entry, entry_ts, bars_held) in list(positions.items()):
            row_i = by_ts[ts].get(sym)
            if row_i is None:
                continue
            row = data[sym][row_i]
            if sym not in target or bars_held >= 6:
                trades.append(close_trade("cross_sectional_long_only", sym, side, entry_ts, entry, row, "rebalance"))
                positions.pop(sym, None)
            else:
                positions[sym] = (side, entry, entry_ts, bars_held + 1)
        for sym, side in target.items():
            if sym in positions:
                continue
            row_i = by_ts[ts].get(sym)
            if row_i is None:
                continue
            row = data[sym][row_i]
            positions[sym] = (side, row.close, row.ts, 0)
    return trades


def summarize(name: str, trades: list[Trade]) -> str:
    if not trades:
        return f"{name:28s} trades=0"
    nets = [t.net_pct for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss else 99.0
    winrate = len(wins) / len(nets) * 100
    avg = statistics.mean(nets)
    med = statistics.median(nets)
    monthly: dict[str, float] = {}
    for t in trades:
        key = datetime.fromtimestamp(t.exit_ts / 1000, tz=timezone.utc).strftime("%Y-%m")
        monthly[key] = monthly.get(key, 0.0) + t.net_pct
    bad_months = sum(1 for x in monthly.values() if x < 0)
    return (
        f"{name:28s} trades={len(trades):4d} net={sum(nets):8.2f}% "
        f"avg={avg:6.3f}% med={med:6.3f}% win={winrate:5.1f}% "
        f"pf={pf:5.2f} bad_months={bad_months}/{len(monthly)}"
    )


def main() -> int:
    months = month_range(date(2025, 6, 1), date(2026, 5, 1))
    interval = "1h"
    print(f"Loading {len(SYMBOLS)} symbols x {len(months)} months of {interval} Binance UM futures klines...", flush=True)
    data: dict[str, list[Bar]] = {}
    for sym in SYMBOLS:
        rows = load_symbol(sym, interval, months)
        if len(rows) >= 500:
            data[sym] = rows
            print(f"{sym:14s} {len(rows):5d} bars", flush=True)
        else:
            print(f"{sym:14s} missing/short ({len(rows)} bars)", flush=True)
    if "BTCUSDT" not in data:
        print("BTCUSDT data missing", file=sys.stderr)
        return 2
    btc = btc_regime(data["BTCUSDT"])
    all_trades: dict[str, list[Trade]] = {
        "trend_pullback": [],
        "donchian_breakout": [],
        "mean_reversion": [],
        "donchian_long_only": [],
        "trend_pullback_long_only": [],
        "donchian_4h_long_only": [],
    }
    for sym, rows in data.items():
        all_trades["trend_pullback"].extend(trend_pullback(sym, rows, btc))
        all_trades["donchian_breakout"].extend(donchian_breakout(sym, rows, btc))
        all_trades["mean_reversion"].extend(hourly_mean_reversion(sym, rows, btc))
        all_trades["donchian_long_only"].extend(donchian_long_only(sym, rows, btc))
        all_trades["trend_pullback_long_only"].extend(trend_pullback_long_only(sym, rows, btc))
    data_4h = {sym: resample(rows, 4) for sym, rows in data.items()}
    btc_4h = btc_regime(data_4h["BTCUSDT"])
    for sym, rows in data_4h.items():
        all_trades["donchian_4h_long_only"].extend(donchian_long_only(sym, rows, btc_4h))
    all_trades["cross_sectional_momentum"] = cross_sectional_momentum(data)
    all_trades["cross_sectional_long_only"] = cross_sectional_long_only(data)
    print("\nResults include 0.16% round-trip fee/slippage per trade.\n", flush=True)
    for name, trades in all_trades.items():
        print(summarize(name, trades))
    print("\nTop/bottom examples:")
    for name, trades in all_trades.items():
        if not trades:
            continue
        best = sorted(trades, key=lambda x: x.net_pct, reverse=True)[:3]
        worst = sorted(trades, key=lambda x: x.net_pct)[:3]
        print(f"\n{name}")
        for label, items in [("best", best), ("worst", worst)]:
            print(label)
            for t in items:
                side = "LONG" if t.side == 1 else "SHORT"
                print(f"  {t.symbol:12s} {side:5s} net={t.net_pct:7.2f}% gross={t.gross_pct:7.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
