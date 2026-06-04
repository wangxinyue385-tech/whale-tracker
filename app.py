"""
signal_logger.py
信号记录与回填模块 — 集成到 app.py 后自动记录 FOLLOW 信号并在 5/15 分钟后回填价格结果
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("SIGNAL_DB_PATH", "signals.db")
_lock = threading.Lock()


# ─────────────────────────────────────────
# 数据库初始化
# ─────────────────────────────────────────

def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            INTEGER NOT NULL,          -- 信号时间戳 ms
                symbol        TEXT    NOT NULL,
                follow        TEXT    NOT NULL,          -- FOLLOW_LONG / FOLLOW_SHORT
                score         INTEGER,
                price         REAL,                      -- 信号时价格
                features      TEXT,                      -- JSON，所有特征快照

                price_5m      REAL    DEFAULT NULL,      -- 5分钟后价格
                price_15m     REAL    DEFAULT NULL,      -- 15分钟后价格
                ret_5m        REAL    DEFAULT NULL,      -- 5分钟收益率 %
                ret_15m       REAL    DEFAULT NULL,      -- 15分钟收益率 %
                outcome_5m    TEXT    DEFAULT NULL,      -- WIN / LOSS / FLAT
                outcome_15m   TEXT    DEFAULT NULL,

                filled_5m     INTEGER DEFAULT 0,        -- 是否已回填
                filled_15m    INTEGER DEFAULT 0,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts     ON signals(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON signals(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_follow ON signals(follow)")
        conn.commit()


@contextmanager
def _get_conn():
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


# ─────────────────────────────────────────
# 写入信号
# ─────────────────────────────────────────

def log_signal(row: dict):
    """
    row 是 scoreRow() 返回的对象（JS 侧 compactRows() 格式）
    只记录 FOLLOW_LONG / FOLLOW_SHORT
    """
    follow = row.get("follow", "")
    if follow not in ("FOLLOW_LONG", "FOLLOW_SHORT"):
        return

    features = {
        "score":          row.get("score"),
        "price_1m_pct":   row.get("price_1m_pct"),
        "price_5m_pct":   row.get("price_5m_pct"),
        "net_60s_usd":    row.get("net_60s_usd"),
        "net_5m_usd":     row.get("net_5m_usd"),
        "largest_usd":    row.get("largest_usd"),
        "streak_side":    row.get("streak_side"),
        "streak_count":   row.get("streak_count"),
        "volume_spike":   row.get("volume_spike"),
        "oi_15m_pct":     row.get("oi_15m_pct"),
        "taker_ratio":    row.get("taker_ratio"),
        "forecast_side":  row.get("forecast_side"),
        "forecast_prob":  row.get("forecast_5m_prob"),
        "net_edge_pct":   row.get("net_edge_pct"),
        "required_cost":  row.get("required_cost_pct"),
        "funding_cost":   row.get("funding_cost_pct"),
        "volume_24h":     row.get("volume_24h_usd"),
        "risks":          row.get("risks", []),
        "reasons":        row.get("reasons", []),
    }

    with _get_conn() as conn:
        # 避免同一 symbol 在 60s 内重复记录
        recent = conn.execute(
            "SELECT id FROM signals WHERE symbol=? AND ts>? AND follow=? LIMIT 1",
            (row["symbol"], int(time.time() * 1000) - 60_000, follow)
        ).fetchone()
        if recent:
            return

        conn.execute(
            """INSERT INTO signals (ts, symbol, follow, score, price, features)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                int(time.time() * 1000),
                row["symbol"],
                follow,
                row.get("score"),
                row.get("price"),
                json.dumps(features, ensure_ascii=False),
            )
        )
        conn.commit()


# ─────────────────────────────────────────
# 回填价格（由后台线程调用）
# ─────────────────────────────────────────

def _calc_outcome(follow: str, ret_pct: float) -> str:
    """
    WIN  = 方向正确且收益 > 0.15%
    LOSS = 方向错误且亏损 > 0.15%
    FLAT = 变动不大
    """
    threshold = 0.15
    if follow == "FOLLOW_LONG":
        if ret_pct > threshold:   return "WIN"
        if ret_pct < -threshold:  return "LOSS"
    elif follow == "FOLLOW_SHORT":
        if ret_pct < -threshold:  return "WIN"
        if ret_pct > threshold:   return "LOSS"
    return "FLAT"


def fill_prices(price_map: dict[str, float]):
    """
    price_map: { "SOLUSDT": 182.5, ... }  当前实时价格
    每次 render 循环调用即可（已内置冷却，不会重复回填）
    """
    now_ms = int(time.time() * 1000)

    with _get_conn() as conn:
        # 回填 5m
        pending_5m = conn.execute(
            """SELECT id, symbol, follow, price, ts
               FROM signals
               WHERE filled_5m=0 AND ts <= ?""",
            (now_ms - 5 * 60 * 1000,)
        ).fetchall()

        for sig in pending_5m:
            cur = price_map.get(sig["symbol"])
            if cur is None:
                continue
            entry = sig["price"] or 0
            ret = (cur - entry) / entry * 100 if entry else 0
            outcome = _calc_outcome(sig["follow"], ret)
            conn.execute(
                """UPDATE signals
                   SET price_5m=?, ret_5m=?, outcome_5m=?, filled_5m=1
                   WHERE id=?""",
                (cur, round(ret, 4), outcome, sig["id"])
            )

        # 回填 15m
        pending_15m = conn.execute(
            """SELECT id, symbol, follow, price, ts
               FROM signals
               WHERE filled_15m=0 AND ts <= ?""",
            (now_ms - 15 * 60 * 1000,)
        ).fetchall()

        for sig in pending_15m:
            cur = price_map.get(sig["symbol"])
            if cur is None:
                continue
            entry = sig["price"] or 0
            ret = (cur - entry) / entry * 100 if entry else 0
            outcome = _calc_outcome(sig["follow"], ret)
            conn.execute(
                """UPDATE signals
                   SET price_15m=?, ret_15m=?, outcome_15m=?, filled_15m=1
                   WHERE id=?""",
                (cur, round(ret, 4), outcome, sig["id"])
            )

        conn.commit()


# ─────────────────────────────────────────
# 统计接口（供 /api/signal/stats 使用）
# ─────────────────────────────────────────

def get_stats() -> dict:
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        filled = conn.execute("SELECT COUNT(*) FROM signals WHERE filled_5m=1").fetchone()[0]

        rows = conn.execute(
            """SELECT follow, outcome_5m, outcome_15m, ret_5m, ret_15m
               FROM signals WHERE filled_5m=1"""
        ).fetchall()

    if not rows:
        return {"total": total, "filled": filled, "message": "暂无已回填数据"}

    import statistics

    def bucket(follow_filter):
        subset = [r for r in rows if r["follow"] == follow_filter]
        if not subset:
            return None
        wins_5m  = sum(1 for r in subset if r["outcome_5m"]  == "WIN")
        wins_15m = sum(1 for r in subset if r["outcome_15m"] == "WIN")
        rets_5m  = [r["ret_5m"]  for r in subset if r["ret_5m"]  is not None]
        rets_15m = [r["ret_15m"] for r in subset if r["ret_15m"] is not None]
        n = len(subset)
        win_ret_5m  = [r for r in rets_5m  if r > 0]
        lose_ret_5m = [r for r in rets_5m  if r < 0]
        return {
            "count":        n,
            "winrate_5m":   round(wins_5m  / n * 100, 1),
            "winrate_15m":  round(wins_15m / n * 100, 1) if wins_15m else None,
            "avg_ret_5m":   round(statistics.mean(rets_5m),  3) if rets_5m  else None,
            "avg_ret_15m":  round(statistics.mean(rets_15m), 3) if rets_15m else None,
            "avg_win_5m":   round(statistics.mean(win_ret_5m),   3) if win_ret_5m  else None,
            "avg_loss_5m":  round(statistics.mean(lose_ret_5m),  3) if lose_ret_5m else None,
            "expect_5m":    round(
                (wins_5m / n) * (statistics.mean(win_ret_5m) if win_ret_5m else 0)
                + ((n - wins_5m) / n) * (statistics.mean(lose_ret_5m) if lose_ret_5m else 0),
                3
            ) if rets_5m else None,
        }

    return {
        "total":   total,
        "filled":  filled,
        "long":    bucket("FOLLOW_LONG"),
        "short":   bucket("FOLLOW_SHORT"),
    }


def get_recent(limit: int = 50) -> list:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT ts, symbol, follow, score, price,
                      price_5m, ret_5m, outcome_5m,
                      price_15m, ret_15m, outcome_15m,
                      features
               FROM signals
               ORDER BY ts DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["features"] = json.loads(d["features"] or "{}")
        except Exception:
            d["features"] = {}
        result.append(d)
    return result
