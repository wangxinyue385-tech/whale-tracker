from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("SIGNAL_DB_PATH", "signals.db")
_lock = threading.Lock()


@contextmanager
def _get_conn():
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          INTEGER NOT NULL,
                symbol      TEXT NOT NULL,
                follow      TEXT NOT NULL,
                score       INTEGER,
                price       REAL,
                features    TEXT,
                price_5m    REAL DEFAULT NULL,
                price_15m   REAL DEFAULT NULL,
                ret_5m      REAL DEFAULT NULL,
                ret_15m     REAL DEFAULT NULL,
                outcome_5m  TEXT DEFAULT NULL,
                outcome_15m TEXT DEFAULT NULL,
                filled_5m   INTEGER DEFAULT 0,
                filled_15m  INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_follow ON signals(follow)")
        conn.commit()


def log_signal(row: dict) -> None:
    follow = row.get("follow", "")
    if follow not in {"FOLLOW_LONG", "FOLLOW_SHORT"}:
        return

    features = {
        "score": row.get("score"),
        "price_1m_pct": row.get("price_1m_pct"),
        "price_5m_pct": row.get("price_5m_pct"),
        "net_60s_usd": row.get("net_60s_usd"),
        "net_5m_usd": row.get("net_5m_usd"),
        "flow_60s_imbalance": row.get("flow_60s_imbalance"),
        "flow_5m_imbalance": row.get("flow_5m_imbalance"),
        "flow_60s_count": row.get("flow_60s_count"),
        "flow_5m_count": row.get("flow_5m_count"),
        "largest_usd": row.get("largest_usd"),
        "streak_side": row.get("streak_side"),
        "streak_count": row.get("streak_count"),
        "volume_spike": row.get("volume_spike"),
        "candle_close_location": row.get("candle_close_location"),
        "candle_body_pct": row.get("candle_body_pct"),
        "upper_wick_pct": row.get("upper_wick_pct"),
        "lower_wick_pct": row.get("lower_wick_pct"),
        "oi_15m_pct": row.get("oi_15m_pct"),
        "taker_ratio": row.get("taker_ratio"),
        "market_bias": row.get("market_bias"),
        "btc_5m_pct": row.get("btc_5m_pct"),
        "eth_5m_pct": row.get("eth_5m_pct"),
        "liq_long_5m_usd": row.get("liq_long_5m_usd"),
        "liq_short_5m_usd": row.get("liq_short_5m_usd"),
        "forecast_side": row.get("forecast_side"),
        "forecast_prob": row.get("forecast_5m_prob"),
        "net_edge_pct": row.get("net_edge_pct"),
        "required_cost": row.get("required_cost_pct"),
        "funding_cost": row.get("funding_cost_pct"),
        "volume_24h": row.get("volume_24h_usd"),
        "risks": row.get("risks", []),
        "reasons": row.get("reasons", []),
    }

    with _get_conn() as conn:
        recent = conn.execute(
            "SELECT id FROM signals WHERE symbol=? AND ts>? AND follow=? LIMIT 1",
            (row["symbol"], int(time.time() * 1000) - 60_000, follow),
        ).fetchone()
        if recent:
            return

        conn.execute(
            """
            INSERT INTO signals (ts, symbol, follow, score, price, features)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(time.time() * 1000),
                row["symbol"],
                follow,
                row.get("score"),
                row.get("price"),
                json.dumps(features, ensure_ascii=False),
            ),
        )
        conn.commit()


def _calc_outcome(follow: str, ret_pct: float) -> str:
    threshold = 0.15
    if follow == "FOLLOW_LONG":
        if ret_pct > threshold:
            return "WIN"
        if ret_pct < -threshold:
            return "LOSS"
    elif follow == "FOLLOW_SHORT":
        if ret_pct < -threshold:
            return "WIN"
        if ret_pct > threshold:
            return "LOSS"
    return "FLAT"


def fill_prices(price_map: dict[str, float]) -> None:
    now_ms = int(time.time() * 1000)

    with _get_conn() as conn:
        pending_5m = conn.execute(
            """
            SELECT id, symbol, follow, price, ts
            FROM signals
            WHERE filled_5m=0 AND ts <= ?
            """,
            (now_ms - 5 * 60 * 1000,),
        ).fetchall()
        for sig in pending_5m:
            cur = price_map.get(sig["symbol"])
            if cur is None:
                continue
            entry = sig["price"] or 0
            ret = (cur - entry) / entry * 100 if entry else 0
            conn.execute(
                """
                UPDATE signals
                SET price_5m=?, ret_5m=?, outcome_5m=?, filled_5m=1
                WHERE id=?
                """,
                (cur, round(ret, 4), _calc_outcome(sig["follow"], ret), sig["id"]),
            )

        pending_15m = conn.execute(
            """
            SELECT id, symbol, follow, price, ts
            FROM signals
            WHERE filled_15m=0 AND ts <= ?
            """,
            (now_ms - 15 * 60 * 1000,),
        ).fetchall()
        for sig in pending_15m:
            cur = price_map.get(sig["symbol"])
            if cur is None:
                continue
            entry = sig["price"] or 0
            ret = (cur - entry) / entry * 100 if entry else 0
            conn.execute(
                """
                UPDATE signals
                SET price_15m=?, ret_15m=?, outcome_15m=?, filled_15m=1
                WHERE id=?
                """,
                (cur, round(ret, 4), _calc_outcome(sig["follow"], ret), sig["id"]),
            )
        conn.commit()


def get_stats() -> dict:
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        filled = conn.execute("SELECT COUNT(*) FROM signals WHERE filled_5m=1").fetchone()[0]
        rows = conn.execute(
            """
            SELECT follow, outcome_5m, outcome_15m, ret_5m, ret_15m
            FROM signals
            WHERE filled_5m=1
            """
        ).fetchall()

    if not rows:
        return {"total": total, "filled": filled, "message": "暂无已回填数据"}

    import statistics

    def bucket(follow_filter: str) -> dict | None:
        subset = [r for r in rows if r["follow"] == follow_filter]
        if not subset:
            return None
        n = len(subset)
        wins_5m = sum(1 for r in subset if r["outcome_5m"] == "WIN")
        wins_15m = sum(1 for r in subset if r["outcome_15m"] == "WIN")
        rets_5m = [r["ret_5m"] for r in subset if r["ret_5m"] is not None]
        rets_15m = [r["ret_15m"] for r in subset if r["ret_15m"] is not None]
        win_ret_5m = [r for r in rets_5m if r > 0]
        lose_ret_5m = [r for r in rets_5m if r < 0]
        return {
            "count": n,
            "winrate_5m": round(wins_5m / n * 100, 1),
            "winrate_15m": round(wins_15m / n * 100, 1) if any(r["outcome_15m"] for r in subset) else None,
            "avg_ret_5m": round(statistics.mean(rets_5m), 3) if rets_5m else None,
            "avg_ret_15m": round(statistics.mean(rets_15m), 3) if rets_15m else None,
            "avg_win_5m": round(statistics.mean(win_ret_5m), 3) if win_ret_5m else None,
            "avg_loss_5m": round(statistics.mean(lose_ret_5m), 3) if lose_ret_5m else None,
            "expect_5m": round(statistics.mean(rets_5m), 3) if rets_5m else None,
        }

    return {
        "total": total,
        "filled": filled,
        "long": bucket("FOLLOW_LONG"),
        "short": bucket("FOLLOW_SHORT"),
    }


def get_recent(limit: int = 50) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ts, symbol, follow, score, price,
                   price_5m, ret_5m, outcome_5m,
                   price_15m, ret_15m, outcome_15m,
                   features
            FROM signals
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["features"] = json.loads(item["features"] or "{}")
        except json.JSONDecodeError:
            item["features"] = {}
        result.append(item)
    return result
