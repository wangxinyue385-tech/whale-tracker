from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("SIGNAL_DB_PATH", "signals.db")
_lock = threading.Lock()

# ── 成本常量（和 app.py 保持一致）────────────────────────────────────────────
TAKER_FEE_BPS  = float(os.environ.get("TAKER_FEE_BPS",  "5"))
SLIPPAGE_BPS   = float(os.environ.get("SLIPPAGE_BPS",   "3"))
# 胜负判定：价格涨跌超过来回成本 + 0.05% 才算有意义
_ROUND_TRIP_COST_PCT = (TAKER_FEE_BPS * 2 + SLIPPAGE_BPS * 2) / 100  # 约 0.16%
WIN_THRESHOLD  = _ROUND_TRIP_COST_PCT + 0.05   # ≈ 0.21%  涨跌超过这个才算赢
FLAT_THRESHOLD = _ROUND_TRIP_COST_PCT           # ≈ 0.16%  在此范围内算平局


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
                strategy    TEXT NOT NULL DEFAULT 'flow_momentum',
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_ts       ON signals(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol   ON signals(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_follow   ON signals(follow)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy)")

        # ── 迁移旧表：补 strategy 列 ──────────────────────────────────────────
        cols = [r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()]
        if "strategy" not in cols:
            conn.execute(
                "ALTER TABLE signals ADD COLUMN strategy TEXT NOT NULL DEFAULT 'flow_momentum'"
            )
        conn.commit()


def log_signal(row: dict) -> None:
    follow = row.get("follow", "")
    if follow not in {"FOLLOW_LONG", "FOLLOW_SHORT"}:
        return

    strategy = str(row.get("strategy") or "flow_momentum")

    features = {
        "score":                row.get("score"),
        "strategy_label":       row.get("strategy_label"),
        "price_1m_pct":         row.get("price_1m_pct"),
        "price_5m_pct":         row.get("price_5m_pct"),
        "net_60s_usd":          row.get("net_60s_usd"),
        "net_5m_usd":           row.get("net_5m_usd"),
        "flow_60s_imbalance":   row.get("flow_60s_imbalance"),
        "flow_5m_imbalance":    row.get("flow_5m_imbalance"),
        "flow_60s_count":       row.get("flow_60s_count"),
        "flow_5m_count":        row.get("flow_5m_count"),
        "largest_usd":          row.get("largest_usd"),
        "streak_side":          row.get("streak_side"),
        "streak_count":         row.get("streak_count"),
        "volume_spike":         row.get("volume_spike"),
        "candle_close_location":row.get("candle_close_location"),
        "candle_body_pct":      row.get("candle_body_pct"),
        "upper_wick_pct":       row.get("upper_wick_pct"),
        "lower_wick_pct":       row.get("lower_wick_pct"),
        "oi_15m_pct":           row.get("oi_15m_pct"),
        "taker_ratio":          row.get("taker_ratio"),
        "funding_rate":         row.get("funding_rate"),
        "market_bias":          row.get("market_bias"),
        "btc_5m_pct":           row.get("btc_5m_pct"),
        "eth_5m_pct":           row.get("eth_5m_pct"),
        "liq_long_5m_usd":      row.get("liq_long_5m_usd"),
        "liq_short_5m_usd":     row.get("liq_short_5m_usd"),
        "forecast_side":        row.get("forecast_side"),
        "forecast_prob":        row.get("forecast_5m_prob"),
        "net_edge_pct":         row.get("net_edge_pct"),
        "required_cost":        row.get("required_cost_pct"),
        "funding_cost":         row.get("funding_cost_pct"),
        "volume_24h":           row.get("volume_24h_usd"),
        "risks":                row.get("risks", []),
        "reasons":              row.get("reasons", []),
    }

    with _get_conn() as conn:
        # 同一币种 + 同一方向 + 同一策略，60 秒内不重复记录
        recent = conn.execute(
            """
            SELECT id FROM signals
            WHERE symbol=? AND ts>? AND follow=? AND strategy=?
            LIMIT 1
            """,
            (row["symbol"], int(time.time() * 1000) - 60_000, follow, strategy),
        ).fetchone()
        if recent:
            return

        conn.execute(
            """
            INSERT INTO signals (ts, symbol, follow, strategy, score, price, features)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(time.time() * 1000),
                row["symbol"],
                follow,
                strategy,
                row.get("score"),
                row.get("price"),
                json.dumps(features, ensure_ascii=False),
            ),
        )
        conn.commit()


def _calc_outcome(follow: str, ret_pct: float) -> str:
    """
    胜负判定基于价格涨跌幅（不含杠杆），并扣除来回成本。
    WIN  = 净收益为正且超过成本门槛
    LOSS = 净亏损超过成本门槛（即价格反向超过成本）
    FLAT = 在成本范围内，结果不明确
    """
    if follow == "FOLLOW_LONG":
        net = ret_pct - _ROUND_TRIP_COST_PCT   # 扣除来回手续费+滑点
        if net > WIN_THRESHOLD - _ROUND_TRIP_COST_PCT:
            return "WIN"
        if net < -(WIN_THRESHOLD - _ROUND_TRIP_COST_PCT):
            return "LOSS"
    elif follow == "FOLLOW_SHORT":
        net = -ret_pct - _ROUND_TRIP_COST_PCT  # 做空时价格下跌才赚
        if net > WIN_THRESHOLD - _ROUND_TRIP_COST_PCT:
            return "WIN"
        if net < -(WIN_THRESHOLD - _ROUND_TRIP_COST_PCT):
            return "LOSS"
    return "FLAT"


def fill_prices(price_map: dict[str, float]) -> None:
    now_ms = int(time.time() * 1000)

    with _get_conn() as conn:
        # ── 回填 5m 结果 ─────────────────────────────────────────────────────
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

        # ── 回填 15m 结果 ────────────────────────────────────────────────────
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
        total  = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        filled = conn.execute("SELECT COUNT(*) FROM signals WHERE filled_5m=1").fetchone()[0]
        rows   = conn.execute(
            """
            SELECT follow, strategy, outcome_5m, outcome_15m, ret_5m, ret_15m, features
            FROM signals
            WHERE filled_5m=1
            """
        ).fetchall()

    if not rows:
        return {"total": total, "filled": filled, "message": "暂无已回填数据"}

    import statistics

    def bucket(follow_filter: str, strategy_filter: str | None = None) -> dict | None:
        subset = [
            r for r in rows
            if r["follow"] == follow_filter
            and (strategy_filter is None or r["strategy"] == strategy_filter)
        ]
        if not subset:
            return None
        n = len(subset)
        wins_5m   = sum(1 for r in subset if r["outcome_5m"]  == "WIN")
        losses_5m = sum(1 for r in subset if r["outcome_5m"]  == "LOSS")
        wins_15m  = sum(1 for r in subset if r["outcome_15m"] == "WIN")
        rets_5m   = [r["ret_5m"]  for r in subset if r["ret_5m"]  is not None]
        rets_15m  = [r["ret_15m"] for r in subset if r["ret_15m"] is not None]
        win_rets  = [r for r in rets_5m if r > 0]
        lose_rets = [r for r in rets_5m if r < 0]

        # ── 按退出原因分组（从 features 里取 risks） ─────────────────────────
        exit_groups: dict[str, list[float]] = {}
        for r in subset:
            try:
                feats = json.loads(r["features"] or "{}")
                risks = feats.get("risks") or ["无风险标记"]
                key = risks[0] if risks else "无风险标记"
            except (json.JSONDecodeError, TypeError):
                key = "解析失败"
            exit_groups.setdefault(key, []).append(r["ret_5m"] or 0)

        exit_summary = {
            k: {
                "count": len(v),
                "avg_ret": round(statistics.mean(v), 3) if v else None,
            }
            for k, v in sorted(exit_groups.items(), key=lambda x: -len(x[1]))
        }

        return {
            "count":       n,
            "wins_5m":     wins_5m,
            "losses_5m":   losses_5m,
            "flat_5m":     n - wins_5m - losses_5m,
            "winrate_5m":  round(wins_5m / n * 100, 1),
            "winrate_15m": round(wins_15m / n * 100, 1) if any(r["outcome_15m"] for r in subset) else None,
            "avg_ret_5m":  round(statistics.mean(rets_5m),  3) if rets_5m  else None,
            "avg_ret_15m": round(statistics.mean(rets_15m), 3) if rets_15m else None,
            "avg_win_5m":  round(statistics.mean(win_rets),  3) if win_rets  else None,
            "avg_loss_5m": round(statistics.mean(lose_rets), 3) if lose_rets else None,
            # 期望值 = 均收益（已含方向，负号由 _calc_outcome 处理）
            "expect_5m":   round(statistics.mean(rets_5m), 3) if rets_5m else None,
            # 盈亏比
            "rr_ratio":    round(
                abs(statistics.mean(win_rets)) / abs(statistics.mean(lose_rets)), 2
            ) if win_rets and lose_rets else None,
            "exit_groups": exit_summary,
        }

    # ── 总体分组 ─────────────────────────────────────────────────────────────
    result = {
        "total":  total,
        "filled": filled,
        "long":   bucket("FOLLOW_LONG"),
        "short":  bucket("FOLLOW_SHORT"),
    }

    # ── 按策略分组 ───────────────────────────────────────────────────────────
    strategies = list({r["strategy"] for r in rows})
    by_strategy: dict[str, dict] = {}
    for strat in strategies:
        by_strategy[strat] = {
            "long":  bucket("FOLLOW_LONG",  strat),
            "short": bucket("FOLLOW_SHORT", strat),
        }
    result["by_strategy"] = by_strategy

    # ── 按币种分组（只列出信号数 >= 5 的） ──────────────────────────────────
    symbols = list({r["follow"] + "|" + dict(r)["strategy"] for r in rows})  # noqa
    symbol_rows: dict[str, list] = {}
    for r in rows:
        symbol_rows.setdefault(r["follow"] + "|" + str(dict(r).get("strategy", "")), [])

    sym_map: dict[str, list] = {}
    for r in rows:
        try:
            sym = json.loads(r["features"] or "{}").get("volume_24h")  # 用 volume 做占位
        except Exception:
            sym = None
        # 直接用 DB row 里没有 symbol 字段，需从上层查
        pass

    # 重新查一次含 symbol 字段
    with _get_conn() as conn:
        sym_rows = conn.execute(
            """
            SELECT symbol, follow, strategy, outcome_5m, ret_5m
            FROM signals
            WHERE filled_5m=1
            """
        ).fetchall()

    sym_buckets: dict[str, list] = {}
    for r in sym_rows:
        key = r["symbol"]
        sym_buckets.setdefault(key, []).append(r)

    by_symbol = {}
    for sym, bucket_rows in sym_buckets.items():
        if len(bucket_rows) < 5:
            continue
        import statistics as _st
        rets = [r["ret_5m"] for r in bucket_rows if r["ret_5m"] is not None]
        wins = sum(1 for r in bucket_rows if r["outcome_5m"] == "WIN")
        by_symbol[sym] = {
            "count":      len(bucket_rows),
            "winrate_5m": round(wins / len(bucket_rows) * 100, 1),
            "avg_ret_5m": round(_st.mean(rets), 3) if rets else None,
        }
    result["by_symbol"] = dict(
        sorted(by_symbol.items(), key=lambda x: -x[1]["count"])
    )

    return result


def get_recent(limit: int = 50) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ts, symbol, follow, strategy, score, price,
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
