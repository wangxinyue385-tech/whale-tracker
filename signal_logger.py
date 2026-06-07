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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts             INTEGER NOT NULL,
                level          TEXT,
                symbol         TEXT,
                message        TEXT NOT NULL,
                event_type     TEXT,
                order_id       TEXT,
                realized       REAL,
                strategy       TEXT,
                strategy_label TEXT,
                main_signal    TEXT,
                signal_variant TEXT,
                grade          TEXT,
                margin         REAL,
                order_json     TEXT,
                extra_json     TEXT,
                created_at     TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_closes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts             INTEGER NOT NULL,
                symbol         TEXT NOT NULL,
                realized       REAL,
                strategy       TEXT,
                strategy_label TEXT,
                main_signal    TEXT,
                signal_variant TEXT,
                grade          TEXT,
                reason         TEXT,
                margin         REAL,
                fee            REAL DEFAULT NULL,
                gross_realized REAL DEFAULT NULL,
                created_at     TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_events_ts ON trade_events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_events_symbol ON trade_events(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_events_type ON trade_events(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_closes_ts ON trade_closes(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_closes_symbol ON trade_closes(symbol)")
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(signals)").fetchall()}
        for name, ddl in {
            "price_1m": "ALTER TABLE signals ADD COLUMN price_1m REAL DEFAULT NULL",
            "price_3m": "ALTER TABLE signals ADD COLUMN price_3m REAL DEFAULT NULL",
            "ret_1m": "ALTER TABLE signals ADD COLUMN ret_1m REAL DEFAULT NULL",
            "ret_3m": "ALTER TABLE signals ADD COLUMN ret_3m REAL DEFAULT NULL",
            "outcome_1m": "ALTER TABLE signals ADD COLUMN outcome_1m TEXT DEFAULT NULL",
            "outcome_3m": "ALTER TABLE signals ADD COLUMN outcome_3m TEXT DEFAULT NULL",
            "filled_1m": "ALTER TABLE signals ADD COLUMN filled_1m INTEGER DEFAULT 0",
            "filled_3m": "ALTER TABLE signals ADD COLUMN filled_3m INTEGER DEFAULT 0",
        }.items():
            if name not in existing_cols:
                conn.execute(ddl)
        close_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trade_closes)").fetchall()}
        for name, ddl in {
            "fee": "ALTER TABLE trade_closes ADD COLUMN fee REAL DEFAULT NULL",
            "gross_realized": "ALTER TABLE trade_closes ADD COLUMN gross_realized REAL DEFAULT NULL",
        }.items():
            if name not in close_cols:
                conn.execute(ddl)
        conn.commit()


def log_signal(row: dict) -> None:
    follow = row.get("follow", "")
    if follow not in {"FOLLOW_LONG", "FOLLOW_SHORT"}:
        return

    features = {
        "score": row.get("score"),
        "strategy": row.get("strategy"),
        "strategy_label": row.get("strategy_label"),
        "main_signal": row.get("main_signal") or row.get("strategy"),
        "signal_variant": row.get("signal_variant") or "primary",
        "test_variant": "executed",
        "raw_follow": row.get("raw_follow"),
        "raw_strategy": row.get("raw_strategy"),
        "raw_strategy_label": row.get("raw_strategy_label"),
        "raw_forecast_side": row.get("raw_forecast_side"),
        "raw_forecast_prob": row.get("raw_forecast_5m_prob"),
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
        "funding_rate": row.get("funding_rate"),
        "book_spread_pct": row.get("book_spread_pct"),
        "book_imbalance": row.get("book_imbalance"),
        "bid_depth_usd": row.get("bid_depth_usd"),
        "ask_depth_usd": row.get("ask_depth_usd"),
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
        ts_ms = int(time.time() * 1000)
        _insert_signal(conn, row, follow, features, ts_ms)

        raw_follow = row.get("raw_follow")
        if raw_follow in {"FOLLOW_LONG", "FOLLOW_SHORT"} and raw_follow != follow:
            raw_features = {
                **features,
                "strategy": row.get("raw_strategy") or row.get("strategy"),
                "strategy_label": row.get("raw_strategy_label") or row.get("strategy_label"),
                "main_signal": row.get("raw_strategy") or row.get("strategy"),
                "signal_variant": "raw",
                "test_variant": "raw_control",
                "executed_follow": follow,
            }
            _insert_signal(conn, row, raw_follow, raw_features, ts_ms)
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


def _directional_ret(follow: str, ret_pct: float | None) -> float | None:
    if ret_pct is None:
        return None
    return ret_pct if follow == "FOLLOW_LONG" else -ret_pct


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _infer_event_type(item: dict) -> str:
    explicit = item.get("event_type")
    if explicit:
        return str(explicit)
    message = str(item.get("message") or "")
    if "自动下单失败" in message or "自动平仓失败" in message or item.get("level") == "error":
        return "error"
    if "跳过" in message:
        return "skip"
    if "加仓" in message:
        return "add"
    if "平仓" in message or "已实现" in message:
        return "close"
    if "自动下单" in message:
        return "open"
    return "info"


def log_trade_event(item: dict) -> None:
    if _infer_event_type(item) == "skip":
        return
    order = item.get("order") if isinstance(item.get("order"), dict) else {}
    close = item.get("close") if isinstance(item.get("close"), dict) else {}
    symbol = item.get("symbol") or order.get("symbol") or close.get("symbol")
    realized = close.get("realized") if close else order.get("realizedPnl")
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO trade_events (
                ts, level, symbol, message, event_type, order_id, realized,
                strategy, strategy_label, main_signal, signal_variant, grade,
                margin, order_json, extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(item.get("ts") or time.time() * 1000),
                item.get("level"),
                symbol,
                str(item.get("message") or ""),
                _infer_event_type(item),
                order.get("orderId"),
                _num(realized) if realized is not None else None,
                item.get("strategy") or close.get("strategy"),
                item.get("strategy_label") or close.get("strategy_label"),
                item.get("main_signal") or close.get("main_signal"),
                item.get("signal_variant") or close.get("signal_variant"),
                item.get("grade") or close.get("grade"),
                _num(item.get("margin") or close.get("margin")) if (item.get("margin") or close.get("margin")) is not None else None,
                _json_dumps(order) if order else None,
                _json_dumps({k: v for k, v in item.items() if k != "order"}),
            ),
        )
        conn.commit()


def log_trade_close(item: dict) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO trade_closes (
                ts, symbol, realized, strategy, strategy_label, main_signal,
                signal_variant, grade, reason, margin, fee, gross_realized
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(item.get("ts") or time.time() * 1000),
                str(item.get("symbol") or ""),
                _num(item.get("realized")),
                item.get("strategy"),
                item.get("strategy_label"),
                item.get("main_signal"),
                item.get("signal_variant"),
                item.get("grade"),
                item.get("reason"),
                _num(item.get("margin")) if item.get("margin") is not None else None,
                _num(item.get("fee")) if item.get("fee") is not None else None,
                _num(item.get("gross_realized")) if item.get("gross_realized") is not None else None,
            ),
        )
        conn.commit()


def clear_trade_history() -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM trade_events")
        conn.execute("DELETE FROM trade_closes")
        conn.commit()


def get_trade_events(limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit), 5000))
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ts, level, symbol, message, event_type, order_id, realized,
                   strategy, strategy_label, main_signal, signal_variant,
                   grade, margin, order_json, extra_json
            FROM trade_events
            ORDER BY ts DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in ("order_json", "extra_json"):
            if item.get(key):
                try:
                    item[key] = json.loads(item[key])
                except json.JSONDecodeError:
                    pass
        result.append(item)
    return result


def get_trade_closes(limit: int = 400) -> list[dict]:
    limit = max(1, min(int(limit), 5000))
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ts, symbol, realized, strategy, strategy_label, main_signal,
                   signal_variant, grade, reason, margin, fee, gross_realized
            FROM trade_closes
            ORDER BY ts DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return list(reversed([dict(row) for row in rows]))


def _insert_signal(conn: sqlite3.Connection, row: dict, follow: str, features: dict, ts_ms: int) -> None:
    recent_rows = conn.execute(
        "SELECT features FROM signals WHERE symbol=? AND ts>? AND follow=?",
        (row["symbol"], ts_ms - 60_000, follow),
    ).fetchall()
    for recent in recent_rows:
        try:
            recent_features = json.loads(recent["features"] or "{}")
        except json.JSONDecodeError:
            recent_features = {}
        if (
            recent_features.get("main_signal") == features.get("main_signal")
            and recent_features.get("test_variant") == features.get("test_variant")
        ):
            return

    conn.execute(
        """
        INSERT INTO signals (ts, symbol, follow, score, price, features)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            ts_ms,
            row["symbol"],
            follow,
            row.get("score"),
            row.get("price"),
            json.dumps(features, ensure_ascii=False),
        ),
    )


def fill_prices(price_map: dict[str, float]) -> None:
    now_ms = int(time.time() * 1000)

    with _get_conn() as conn:
        for minutes in (1, 3):
            pending = conn.execute(
                f"""
                SELECT id, symbol, follow, price, ts
                FROM signals
                WHERE filled_{minutes}m=0 AND ts <= ?
                """,
                (now_ms - minutes * 60 * 1000,),
            ).fetchall()
            for sig in pending:
                cur = price_map.get(sig["symbol"])
                if cur is None:
                    continue
                entry = sig["price"] or 0
                ret = (cur - entry) / entry * 100 if entry else 0
                conn.execute(
                    f"""
                    UPDATE signals
                    SET price_{minutes}m=?, ret_{minutes}m=?, outcome_{minutes}m=?, filled_{minutes}m=1
                    WHERE id=?
                    """,
                    (cur, round(ret, 4), _calc_outcome(sig["follow"], ret), sig["id"]),
                )

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
            SELECT follow,
                   outcome_1m, outcome_3m, outcome_5m, outcome_15m,
                   ret_1m, ret_3m, ret_5m, ret_15m,
                   filled_1m, filled_3m, filled_15m, features
            FROM signals
            WHERE filled_5m=1
            """
        ).fetchall()

    if not rows:
        return {"total": total, "filled": filled, "message": "暂无已回填数据"}

    import statistics

    enriched = []
    for row in rows:
        try:
            features = json.loads(row["features"] or "{}")
        except json.JSONDecodeError:
            features = {}
        enriched.append({**dict(row), "features": features})

    def summarize(subset: list[dict]) -> dict | None:
        if not subset:
            return None
        n = len(subset)
        wins_5m = sum(1 for r in subset if r["outcome_5m"] == "WIN")
        wins_15m = sum(1 for r in subset if r["outcome_15m"] == "WIN")
        rets_1m = [
            directional
            for r in subset
            if r["filled_1m"] and (directional := _directional_ret(r["follow"], r["ret_1m"])) is not None
        ]
        rets_3m = [
            directional
            for r in subset
            if r["filled_3m"] and (directional := _directional_ret(r["follow"], r["ret_3m"])) is not None
        ]
        rets_5m = [
            directional
            for r in subset
            if (directional := _directional_ret(r["follow"], r["ret_5m"])) is not None
        ]
        rets_15m = [
            directional
            for r in subset
            if r["filled_15m"] and (directional := _directional_ret(r["follow"], r["ret_15m"])) is not None
        ]
        win_ret_5m = [r for r in rets_5m if r > 0]
        lose_ret_5m = [r for r in rets_5m if r < 0]
        gross_win = sum(win_ret_5m)
        gross_loss = abs(sum(lose_ret_5m))
        return {
            "count": n,
            "winrate_1m": round(sum(1 for r in subset if r["outcome_1m"] == "WIN") / len(rets_1m) * 100, 1) if rets_1m else None,
            "winrate_3m": round(sum(1 for r in subset if r["outcome_3m"] == "WIN") / len(rets_3m) * 100, 1) if rets_3m else None,
            "winrate_5m": round(wins_5m / n * 100, 1),
            "winrate_15m": round(wins_15m / len(rets_15m) * 100, 1) if rets_15m else None,
            "avg_ret_1m": round(statistics.mean(rets_1m), 3) if rets_1m else None,
            "avg_ret_3m": round(statistics.mean(rets_3m), 3) if rets_3m else None,
            "avg_ret_5m": round(statistics.mean(rets_5m), 3) if rets_5m else None,
            "avg_ret_15m": round(statistics.mean(rets_15m), 3) if rets_15m else None,
            "avg_win_5m": round(statistics.mean(win_ret_5m), 3) if win_ret_5m else None,
            "avg_loss_5m": round(statistics.mean(lose_ret_5m), 3) if lose_ret_5m else None,
            "profit_factor_5m": round(gross_win / gross_loss, 2) if gross_loss > 0 else (round(gross_win, 2) if gross_win > 0 else 0),
            "expect_5m": round(statistics.mean(rets_5m), 3) if rets_5m else None,
        }

    def bucket(follow_filter: str) -> dict | None:
        return summarize([r for r in enriched if r["follow"] == follow_filter])

    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in enriched:
        features = row["features"]
        main_signal = str(features.get("main_signal") or features.get("strategy") or "unknown")
        label = str(features.get("strategy_label") or main_signal)
        variant = str(features.get("test_variant") or features.get("signal_variant") or "executed")
        grouped.setdefault((main_signal, label, variant), []).append(row)

    groups = []
    for (main_signal, label, variant), subset in grouped.items():
        item = summarize(subset)
        if not item:
            continue
        groups.append({
            **item,
            "main_signal": main_signal,
            "label": label,
            "variant": variant,
            "reliable": item["count"] >= 20,
        })
    groups.sort(key=lambda item: (item["count"] >= 20, item.get("expect_5m") or -999, item.get("winrate_5m") or 0), reverse=True)

    return {
        "total": total,
        "filled": filled,
        "long": bucket("FOLLOW_LONG"),
        "short": bucket("FOLLOW_SHORT"),
        "groups": groups[:12],
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
