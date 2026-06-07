from __future__ import annotations


def bind(runtime) -> None:
    names = [name for name in dir(runtime) if name.startswith("_") or name.isupper()]
    globals().update({name: getattr(runtime, name) for name in names})


def _strategy_exit_plan(row: dict, strategy: str) -> dict:
    base_r = abs(_strategy_hard_stop_pct(strategy))
    one_minute = _strategy_mode() in {"one_minute", "current"}
    if strategy == "main_flow_direction":
        return {
            "stop_pct": -12.0,
            "r_pct": 99.0,
            "take_profit_pct": 99.0,
            "trail_arm_pct": 99.0,
            "fail_seconds": 0,
            "timeout_seconds": 0,
        }
    if strategy == "liquidity_sweep_reclaim":
        r_pct = max(0.24, min(0.42, base_r)) if one_minute else max(0.45, min(0.65, base_r))
        return {
            "stop_pct": -r_pct,
            "r_pct": r_pct,
            "take_profit_pct": max(0.38, r_pct * 1.55) if one_minute else max(1.20, r_pct * 2.20),
            "trail_arm_pct": max(0.22, r_pct * 0.80) if one_minute else max(0.60, r_pct * 0.80),
            "fail_seconds": 18 if one_minute else 45,
            "timeout_seconds": 55 if one_minute else 120,
        }
    if strategy == "flow_exhaustion_reversal":
        r_pct = max(0.28, min(0.45, base_r)) if one_minute else max(0.85, min(1.25, base_r))
        return {
            "stop_pct": -r_pct,
            "r_pct": r_pct,
            "take_profit_pct": max(0.42, r_pct * 1.45) if one_minute else max(1.45, r_pct * 1.80),
            "trail_arm_pct": max(0.24, r_pct * 0.85) if one_minute else max(0.85, r_pct),
            "fail_seconds": 20 if one_minute else 60,
            "timeout_seconds": 60 if one_minute else 120,
        }
    if strategy == "liquidation_reversal":
        r_pct = max(0.28, min(0.48, base_r)) if one_minute else max(0.90, min(1.35, base_r))
        return {
            "stop_pct": -r_pct,
            "r_pct": r_pct,
            "take_profit_pct": max(0.40, r_pct * 1.45) if one_minute else max(1.25, r_pct * 1.50),
            "trail_arm_pct": max(0.22, r_pct * 0.85) if one_minute else max(0.75, r_pct * 0.90),
            "fail_seconds": 18 if one_minute else 40,
            "timeout_seconds": 50 if one_minute else 75,
        }
    if strategy == "sector_lead_lag":
        r_pct = max(0.75, min(1.20, base_r))
        return {
            "stop_pct": -r_pct,
            "r_pct": r_pct,
            "take_profit_pct": max(1.20, r_pct * 1.60),
            "trail_arm_pct": max(0.75, r_pct),
            "fail_seconds": 120,
            "timeout_seconds": 240,
        }
    r_pct = max(0.24, min(0.40, base_r)) if one_minute else max(0.80, base_r)
    return {
        "stop_pct": -r_pct,
        "r_pct": r_pct,
        "take_profit_pct": max(0.36, min(_safe_float(row.get("take_profit_pct")) or EXIT_TAKE_PROFIT_PCT, 0.75), r_pct * 1.35) if one_minute else max(_safe_float(row.get("take_profit_pct")) or EXIT_TAKE_PROFIT_PCT, r_pct * 1.50),
        "trail_arm_pct": max(0.20, min(_safe_float(row.get("trail_arm_pct")) or EXIT_PROFIT_ARM_PCT, 0.55), r_pct * 0.80) if one_minute else max(_safe_float(row.get("trail_arm_pct")) or EXIT_PROFIT_ARM_PCT, r_pct),
        "fail_seconds": 18 if one_minute else 90,
        "timeout_seconds": 55 if one_minute else EXIT_MAX_HOLD_SECONDS,
    }


def _paper_one_way_cost(notional: float) -> float:
    return max(0.0, float(notional)) * (TAKER_FEE_BPS + SLIPPAGE_BPS) / 10000


def _min_net_profit_usdt(meta: dict | None = None) -> float:
    margin = _safe_float((meta or {}).get("margin"), _order_margin_usdt())
    notional = _safe_float((meta or {}).get("notional"), _order_notional_usdt(margin))
    roundtrip_cost = _paper_one_way_cost(notional) * 2
    return max(POSITION_PROFIT_FLOOR_USDT, LOW_CONFIDENCE_TAKE_PROFIT_USDT, roundtrip_cost * 1.35)


def _paper_mark_price(symbol: str, fallback: float = 0) -> float:
    return float(_last_prices.get(symbol) or fallback or 0)


def _paper_account_snapshot() -> dict:
    positions = []
    unrealized = 0.0
    for symbol, pos in _paper_positions.items():
        amount = float(pos.get("amount") or 0)
        entry = float(pos.get("entry_price") or 0)
        mark = _paper_mark_price(symbol, entry)
        notional = float(pos.get("notional") or abs(amount) * entry)
        margin = float(pos.get("margin") or _order_margin_usdt())
        gross_pnl = (mark - entry) * amount
        exit_cost = _paper_one_way_cost(abs(amount) * mark)
        net_pnl = gross_pnl - exit_cost
        unrealized += net_pnl
        positions.append({
            "symbol": symbol,
            "amount": amount,
            "entry_price": entry,
            "mark_price": mark,
            "margin": margin,
            "notional": notional,
            "entry_cost": float(pos.get("entry_cost") or 0),
            "exit_cost": exit_cost,
            "gross_unrealized": gross_pnl,
            "unrealized": net_pnl,
        })
    equity = _paper_cash + unrealized
    point = {"ts": int(time.time() * 1000), "wallet": _paper_cash, "unrealized": unrealized, "equity": equity}
    _equity_curve.append(point)
    del _equity_curve[:-240]
    return {"wallet": _paper_cash, "unrealized": unrealized, "equity": equity, "positions": positions}


def _paper_place_market_order(symbol: str, follow: str, price: float, margin: float | None = None) -> dict:
    global _paper_cash
    if price <= 0:
        price = _paper_mark_price(symbol)
    if price <= 0:
        raise RuntimeError(f"{symbol} 没有可用价格")
    margin = max(1.0, float(margin if margin is not None else _order_margin_usdt()))
    notional = _order_notional_usdt(margin)
    qty = notional / price
    amount = qty if follow == "FOLLOW_LONG" else -qty
    order_id = uuid.uuid4().hex[:12]
    entry_cost = _paper_one_way_cost(notional)
    _paper_cash -= entry_cost
    existing = _paper_positions.get(symbol)
    if existing and (float(existing.get("amount") or 0) * amount) > 0:
        old_amount = float(existing.get("amount") or 0)
        new_amount = old_amount + amount
        old_notional = float(existing.get("notional") or abs(old_amount) * float(existing.get("entry_price") or price))
        old_entry = float(existing.get("entry_price") or price)
        combined_notional = old_notional + notional
        combined_entry = (old_entry * abs(old_amount) + price * abs(amount)) / max(abs(new_amount), 1e-12)
        existing.update({
            "amount": new_amount,
            "entry_price": combined_entry,
            "margin": float(existing.get("margin") or 0) + margin,
            "notional": combined_notional,
            "entry_cost": float(existing.get("entry_cost") or 0) + entry_cost,
            "order_id": order_id,
        })
        return {"orderId": order_id, "symbol": symbol, "status": "FILLED", "avgPrice": price, "executedQty": qty, "entryCost": entry_cost, "paper": True, "added": True}
    if existing:
        raise RuntimeError(f"{symbol} 已有反向本地模拟持仓")
    _paper_positions[symbol] = {
        "symbol": symbol,
        "amount": amount,
        "entry_price": price,
        "margin": margin,
        "notional": notional,
        "entry_cost": entry_cost,
        "opened_at": int(time.time() * 1000),
        "order_id": order_id,
        "follow": follow,
    }
    return {"orderId": order_id, "symbol": symbol, "status": "FILLED", "avgPrice": price, "executedQty": qty, "entryCost": entry_cost, "paper": True}


def _paper_close_position(symbol: str, amount: float) -> dict:
    global _paper_cash
    pos = _paper_positions.get(symbol)
    if not pos:
        raise RuntimeError(f"{symbol} 没有本地模拟持仓")
    entry = float(pos.get("entry_price") or 0)
    mark = _paper_mark_price(symbol, entry)
    pos_amount = float(pos.get("amount") or amount)
    close_abs = min(abs(float(amount or pos_amount)), abs(pos_amount))
    if close_abs <= 0:
        raise RuntimeError(f"{symbol} 平仓数量无效")
    close_amount = close_abs if pos_amount > 0 else -close_abs
    ratio = close_abs / max(abs(pos_amount), 1e-12)
    gross_pnl = (mark - entry) * close_amount
    exit_cost = _paper_one_way_cost(close_abs * mark)
    entry_cost = float(pos.get("entry_cost") or 0) * ratio
    net_pnl = gross_pnl - entry_cost - exit_cost
    _paper_cash += gross_pnl - exit_cost
    remaining_amount = pos_amount - close_amount
    if abs(remaining_amount) <= max(abs(pos_amount), 1e-12) * 0.01:
        _paper_positions.pop(symbol, None)
    else:
        remain_ratio = 1 - ratio
        pos.update({
            "amount": remaining_amount,
            "margin": float(pos.get("margin") or 0) * remain_ratio,
            "notional": float(pos.get("notional") or abs(pos_amount) * entry) * remain_ratio,
            "entry_cost": float(pos.get("entry_cost") or 0) * remain_ratio,
        })
    return {
        "orderId": uuid.uuid4().hex[:12],
        "symbol": symbol,
        "realizedPnl": net_pnl,
        "grossPnl": gross_pnl,
        "entryCost": entry_cost,
        "exitCost": exit_cost,
        "avgPrice": mark,
        "closedRatio": ratio,
        "closedAmount": close_amount,
        "remainingAmount": remaining_amount,
        "paper": True,
    }


def _set_leverage(symbol: str) -> None:
    try:
        _signed_testnet_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(_testnet_config["leverage"])})
    except Exception as exc:  # noqa: BLE001
        _event(f"{symbol} 设置杠杆失败：{exc}", "warn", symbol=symbol)


def _place_market_order(symbol: str, follow: str, price: float, margin: float | None = None) -> dict:
    side = "BUY" if follow == "FOLLOW_LONG" else "SELL"
    if price <= 0:
        ticker = _public_testnet_get("/fapi/v1/ticker/price", {"symbol": symbol})
        price = float(ticker.get("price") or 0)
    if price <= 0:
        raise RuntimeError(f"{symbol} 没有可用价格")
    qty = _round_qty(symbol, _order_notional_usdt(margin) / price)
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


def _position_margin(symbol: str, pos: dict, meta: dict) -> float:
    margin = _safe_float(pos.get("margin")) or _safe_float(meta.get("margin"))
    if margin > 0:
        return margin
    entry = _safe_float(pos.get("entry_price")) or _safe_float(meta.get("entry_price"))
    amount = abs(_safe_float(pos.get("amount")))
    leverage = max(1, int(_testnet_config["leverage"]))
    return max(1.0, amount * entry / leverage)


def _position_pnl_pct(symbol: str, pos: dict, meta: dict) -> tuple[float, float]:
    pnl = _safe_float(pos.get("unrealized"))
    pnl -= _safe_float(pos.get("entry_cost"))
    margin = _position_margin(symbol, pos, meta)
    return pnl, pnl / margin * 100


def _position_side(pos: dict, meta: dict) -> str:
    amount = _safe_float(pos.get("amount"))
    if amount > 0:
        return "LONG"
    if amount < 0:
        return "SHORT"
    follow = str(meta.get("follow") or "")
    return "LONG" if follow == "FOLLOW_LONG" else "SHORT"


def _position_gross_pnl(pos: dict) -> float:
    if "gross_unrealized" in pos:
        return _safe_float(pos.get("gross_unrealized"))
    return _safe_float(pos.get("unrealized"))


def _same_side_follow(side: str) -> str:
    return "FOLLOW_LONG" if side == "LONG" else "FOLLOW_SHORT"


def _would_open_same_side(symbol: str, side: str, meta: dict, now_ms: int) -> tuple[bool, dict]:
    snap = _market_snapshots.get(symbol) or {}
    if not snap or now_ms - int(snap.get("ts") or 0) > 15 * 1000:
        return False, snap
    cur_strategy = str(meta.get("strategy") or "")
    if cur_strategy and not _strategy_allowed_for_auto(cur_strategy):
        return False, snap
    if snap.get("follow") != _same_side_follow(side):
        return False, snap
    snap_strategy = str(snap.get("strategy") or "")
    if snap_strategy and not _auto_signal_allowed_for_trade(snap):
        return False, snap
    if snap_strategy and cur_strategy and snap_strategy != cur_strategy:
        return False, snap
    return True, snap


def _is_reverse_snapshot(side: str, snap: dict) -> bool:
    follow = snap.get("follow")
    signal = snap.get("signal")
    score = _safe_float(snap.get("score"))
    net_5m = _safe_float(snap.get("net_5m_usd"))
    if side == "LONG":
        return follow == "FOLLOW_SHORT" or (signal == "SHORT" and score >= EXIT_REVERSE_SCORE) or (net_5m < 0 and score >= EXIT_REVERSE_SCORE)
    return follow == "FOLLOW_LONG" or (signal == "LONG" and score >= EXIT_REVERSE_SCORE) or (net_5m > 0 and score >= EXIT_REVERSE_SCORE)


def _snapshot_direction(snap: dict) -> str:
    follow = snap.get("follow")
    signal = snap.get("signal")
    if follow in {"FOLLOW_LONG", "WATCH_LONG"} or signal == "LONG":
        return "LONG"
    if follow in {"FOLLOW_SHORT", "WATCH_SHORT"} or signal == "SHORT":
        return "SHORT"
    return "NEUTRAL"


def _same_direction_still_valid(side: str, snap: dict) -> bool:
    if not _auto_signal_allowed_for_trade(snap):
        return False
    direction = _snapshot_direction(snap)
    if direction != side:
        return False
    follow = snap.get("follow")
    score = _safe_float(snap.get("score"))
    net_60s = _safe_float(snap.get("net_60s_usd"))
    net_5m = _safe_float(snap.get("net_5m_usd"))
    risks = set(snap.get("risks") or [])
    if follow == ("FOLLOW_LONG" if side == "LONG" else "FOLLOW_SHORT"):
        return True
    if score < EXIT_HOLD_MIN_SCORE:
        return False
    fatal = {"大盘反向", "爆仓反向", "OI下降"}
    if side == "LONG":
        return (net_5m >= 0 or net_60s >= 0) and not fatal.intersection(risks)
    return (net_5m <= 0 or net_60s <= 0) and not fatal.intersection(risks)


def _strategy_hard_stop_pct(strategy: str) -> float:
    if strategy == "funding_reversion":
        return FUNDING_EXIT_HARD_STOP_PCT
    if strategy == "flow_momentum":
        return FLOW_EXIT_HARD_STOP_PCT
    if strategy == "main_flow_direction":
        return FLOW_EXIT_HARD_STOP_PCT
    if strategy == "liquidity_sweep_reclaim":
        return -1.05
    if strategy == "flow_exhaustion_reversal":
        return EXHAUSTION_EXIT_HARD_STOP_PCT
    if strategy == "sector_lead_lag":
        return SECTOR_EXIT_HARD_STOP_PCT
    if strategy == "liquidation_reversal":
        return LIQUIDATION_EXIT_HARD_STOP_PCT
    return EXIT_HARD_STOP_PCT


def _strategy_unsupported_grace_seconds(strategy: str) -> int:
    if strategy == "flow_momentum":
        return FLOW_POSITION_UNSUPPORTED_GRACE_SECONDS
    return POSITION_UNSUPPORTED_GRACE_SECONDS


def _register_close_cooldown(symbol: str, strategy: str, realized: float, now_ms: int) -> None:
    if realized >= 0:
        return
    _loss_cooldowns[symbol] = now_ms + 3 * 60 * 1000
    recent = [
        item for item in _trade_closes[-20:]
        if str(item.get("strategy") or "") == strategy
    ]
    losses = [item for item in recent[-6:] if _safe_float(item.get("realized")) < 0]
    if len(losses) >= 3:
        _strategy_cooldowns[strategy] = now_ms + 5 * 60 * 1000
        _event(f"{strategy} 近期连续亏损，自动冷却 5 分钟", "warn", event_type="skip", strategy=strategy)


def _track_hold_support(meta: dict, supported: bool, reverse: bool, snap_version: int) -> int:
    if snap_version and int(meta.get("last_hold_snapshot_version") or 0) == snap_version:
        return int(meta.get("invalid_snapshots") or 0)
    if snap_version:
        meta["last_hold_snapshot_version"] = snap_version
    if supported:
        meta["invalid_snapshots"] = 0
        return 0
    increment = 1
    if reverse and EXIT_INVALID_SNAPSHOTS > 1:
        increment = 2
    count = int(meta.get("invalid_snapshots") or 0) + increment
    meta["invalid_snapshots"] = count
    return count


def _strategy_failure_exit_reason(strategy: str, side: str, snap: dict, meta: dict, age_ms: int, pnl_pct: float, peak_pct: float, reverse: bool, would_open: bool) -> str | None:
    if not snap:
        return None
    net_60s = _safe_float(snap.get("net_60s_usd"))
    net_5m = _safe_float(snap.get("net_5m_usd"))
    p1 = _safe_float(snap.get("price_1m_pct"))
    p5 = _safe_float(snap.get("price_5m_pct"))
    price = _safe_float(snap.get("price"))
    reclaim_level = _safe_float(snap.get("reclaim_level"))
    fail_ms = int(meta.get("exit_fail_seconds") or 90) * 1000
    timeout_ms = int(meta.get("exit_timeout_seconds") or EXIT_MAX_HOLD_SECONDS) * 1000

    if strategy == "liquidity_sweep_reclaim":
        if side == "LONG":
            if reclaim_level > 0 and price > 0 and price < reclaim_level and pnl_pct <= 0.10:
                return f"扫低收回失败，跌回收回位下方 {pnl_pct:.2f}%"
            if net_60s < 0 and net_5m < 0 and pnl_pct <= 0.10:
                return f"扫低收回失败，主动卖流反压 {pnl_pct:.2f}%"
        else:
            if reclaim_level > 0 and price > 0 and price > reclaim_level and pnl_pct <= 0.10:
                return f"扫高收回失败，站回收回位上方 {pnl_pct:.2f}%"
            if net_60s > 0 and net_5m > 0 and pnl_pct <= 0.10:
                return f"扫高收回失败，主动买流反推 {pnl_pct:.2f}%"
        if age_ms >= fail_ms and peak_pct < 0.30 and pnl_pct <= 0.05:
            return f"扫单收回未快速兑现，最高浮盈 {peak_pct:.2f}%"
        if age_ms >= timeout_ms and peak_pct < 0.55:
            return f"扫单收回超时，最高浮盈 {peak_pct:.2f}%"

    if strategy == "flow_exhaustion_reversal":
        if side == "LONG" and net_60s < 0 and net_5m < 0 and pnl_pct <= 0.05:
            return f"耗尽回归失败，主动卖流重新压制 {pnl_pct:.2f}%"
        if side == "SHORT" and net_60s > 0 and net_5m > 0 and pnl_pct <= 0.05:
            return f"耗尽回归失败，主动买流重新推升 {pnl_pct:.2f}%"
        if age_ms >= timeout_ms and peak_pct < 0.35:
            return f"耗尽回归超时，最高浮盈 {peak_pct:.2f}%"

    if strategy == "liquidation_reversal":
        if reverse and pnl_pct <= 0.10:
            return f"爆仓反弹被反穿，当前 {pnl_pct:.2f}%"
        if age_ms >= fail_ms and peak_pct < 0.25 and pnl_pct <= 0.05:
            return f"爆仓反弹未快速收复，最高浮盈 {peak_pct:.2f}%"
        if age_ms >= timeout_ms and peak_pct < 0.45:
            return f"爆仓反弹超时，最高浮盈 {peak_pct:.2f}%"

    if strategy == "sector_lead_lag":
        if side == "LONG" and p5 < -0.35 and net_5m < 0 and pnl_pct <= 0.05:
            return f"板块价差失败，目标币继续跟跌 {p5:.2f}%"
        if side == "SHORT" and p5 > 0.35 and net_5m > 0 and pnl_pct <= 0.05:
            return f"板块价差失败，目标币继续跟涨 {p5:.2f}%"
        if age_ms >= timeout_ms and not would_open and peak_pct < 0.45:
            return f"板块价差回归超时，最高浮盈 {peak_pct:.2f}%"

    return None


def _partial_exit_reason(symbol: str, pos: dict, meta: dict) -> str | None:
    if meta.get("partial_taken"):
        return None
    pnl, pnl_pct = _position_pnl_pct(symbol, pos, meta)
    r_pct = _safe_float(meta.get("exit_r_pct")) or abs(_strategy_hard_stop_pct(str(meta.get("strategy") or "")))
    if r_pct > 0 and pnl_pct >= r_pct:
        return f"1R半仓止盈 {pnl_pct:.2f}% · R {r_pct:.2f}%"
    return None


def _exit_reason(symbol: str, pos: dict, meta: dict, now_ms: int) -> str | None:
    opened_at = int(meta.get("opened_at", now_ms))
    age_ms = now_ms - opened_at
    pnl, pnl_pct = _position_pnl_pct(symbol, pos, meta)
    prev_peak_pct = _safe_float(meta.get("peak_pnl_pct"), pnl_pct)
    prev_peak_pnl = _safe_float(meta.get("peak_pnl"), pnl)
    peak_pct = max(prev_peak_pct, pnl_pct)
    peak_pnl = max(prev_peak_pnl, pnl)
    meta["peak_pnl_pct"] = peak_pct
    meta["peak_pnl"] = peak_pnl
    if peak_pct > prev_peak_pct + EXIT_PROGRESS_EPS_PCT:
        meta["last_progress_at"] = now_ms
    if pnl_pct > _safe_float(meta.get("last_favorable_pct"), -999) + EXIT_PROGRESS_EPS_PCT:
        meta["last_favorable_pct"] = pnl_pct
        meta["last_favorable_at"] = now_ms

    strategy = str(meta.get("strategy") or "flow_momentum")
    min_profit = _min_net_profit_usdt(meta)
    if strategy == "funding_reversion" and pnl_pct >= FUNDING_EXIT_TAKE_PROFIT_PCT:
        return f"费率回归止盈 {pnl_pct:.2f}%"

    take_profit_pct = _safe_float(meta.get("take_profit_pct")) or EXIT_TAKE_PROFIT_PCT
    trail_arm_pct = _safe_float(meta.get("trail_arm_pct")) or EXIT_PROFIT_ARM_PCT
    if pnl_pct >= take_profit_pct:
        return f"动态止盈平仓 {pnl_pct:.2f}% · 目标 {take_profit_pct:.2f}%"

    snap = _market_snapshots.get(symbol) or {}
    side = _position_side(pos, meta)
    snap_fresh = bool(snap and now_ms - int(snap.get("ts") or 0) <= 15 * 1000)
    would_open, _ = _would_open_same_side(symbol, side, meta, now_ms)

    invalid_count = int(meta.get("invalid_snapshots") or 0)
    reverse = False
    supported = False
    if snap_fresh:
        reverse = _is_reverse_snapshot(side, snap)
        supported = _same_direction_still_valid(side, snap)
        invalid_count = _track_hold_support(meta, supported, reverse, int(snap.get("version") or 0))

    if age_ms < EXIT_MIN_HOLD_SECONDS * 1000:
        return None

    if strategy == "main_flow_direction":
        if not snap_fresh:
            return None
        price = _safe_float(snap.get("price")) or _paper_mark_price(symbol, _safe_float(meta.get("entry_price")))
        channel_low = _safe_float(snap.get("channel_low_20"))
        ema_gap = _safe_float(snap.get("ema_trend_gap_pct"))
        btc_ema_gap = _safe_float(snap.get("btc_ema_trend_gap_pct"))
        btc_ret24 = _safe_float(snap.get("btc_trend_ret_24h"))
        btc_ret = _safe_float(snap.get("btc_5m_pct"))
        if side == "LONG" and channel_low > 0 and price > 0 and price < channel_low:
            return f"4h趋势破坏平仓，跌破20根低点 {pnl_pct:.2f}%"
        if side == "LONG" and ema_gap < 0:
            return f"4h EMA趋势转弱平仓，当前 {pnl_pct:.2f}%"
        if side == "LONG" and btc_ema_gap < 0 and btc_ret24 < 0:
            return f"BTC 4h风险关闭平仓，BTC24h {btc_ret24:.2f}% · 当前 {pnl_pct:.2f}%"
        if side == "LONG" and btc_ret <= -1.8:
            return f"BTC风险关闭平仓，BTC短线 {btc_ret:.2f}% · 当前 {pnl_pct:.2f}%"
        return None

    strategy_failure = _strategy_failure_exit_reason(strategy, side, snap, meta, age_ms, pnl_pct, peak_pct, reverse, would_open)
    if strategy_failure:
        if pnl >= min_profit:
            return strategy_failure

    if not would_open and pnl >= min_profit:
        return f"当前不再触发开仓，净利落袋 {pnl:+.2f} USDT"

    entry_prob = _safe_float(meta.get("forecast_prob"))
    if (
        entry_prob > 0
        and entry_prob <= LOW_CONFIDENCE_PROB
        and pnl >= min_profit
        and (not snap_fresh or reverse or not supported)
    ):
        return f"低置信微利平仓，预测 {entry_prob:.1f}% · 净利 {pnl:+.2f} USDT"

    if strategy == "funding_reversion" and snap_fresh:
        funding_rate = _safe_float(snap.get("funding_rate"))
        can_exit_on_normalized_funding = pnl >= min_profit
        if side == "LONG" and funding_rate >= -FUNDING_EXIT_NORMAL_RATE_PCT and can_exit_on_normalized_funding:
            return f"负资金费回归平仓，当前 {funding_rate:.4f}%"
        if side == "SHORT" and funding_rate <= FUNDING_EXIT_NORMAL_RATE_PCT and can_exit_on_normalized_funding:
            return f"正资金费回归平仓，当前 {funding_rate:.4f}%"
        if reverse and pnl >= min_profit:
            return f"费率单被动量反穿盈利平仓，当前 {pnl_pct:.2f}%"

    if would_open and peak_pnl >= min_profit and pnl >= min_profit and peak_pnl - pnl >= POSITION_PROFIT_PULLBACK_USDT:
        return f"仍支持持仓但盈利回撤平仓，最高净利 {peak_pnl:+.2f} 回落到 {pnl:+.2f} USDT"

    if peak_pct >= trail_arm_pct and pnl_pct <= max(0.12, peak_pct * EXIT_TRAIL_KEEP_RATIO):
        return f"移动止盈平仓，最高 {peak_pct:.2f}% 回落到 {pnl_pct:.2f}%"

    r_pct = _safe_float(meta.get("exit_r_pct"))
    if r_pct > 0 and peak_pct >= r_pct and pnl_pct <= max(0.05, r_pct * 0.25):
        return f"1R回吐保护平仓，最高 {peak_pct:.2f}% 回落到 {pnl_pct:.2f}%"

    if peak_pct >= EXIT_BREAKEVEN_ARM_PCT and pnl_pct <= max(0.08, EXIT_BREAKEVEN_FLOOR_PCT):
        return f"浮盈回吐保护平仓，最高 {peak_pct:.2f}% 回落到 {pnl_pct:.2f}%"

    if (
        snap_fresh
        and invalid_count >= EXIT_INVALID_SNAPSHOTS
        and strategy != "funding_reversion"
        and pnl >= min_profit
    ):
        return f"当前策略连续 {invalid_count} 次不支持持仓，盈利平仓"

    progress_age_ms = now_ms - int(meta.get("last_progress_at") or opened_at)
    unsupported_grace_ms = _strategy_unsupported_grace_seconds(strategy) * 1000
    unsupported_since = int(meta.get("unsupported_since") or 0)
    if not would_open:
        if not unsupported_since:
            meta["unsupported_since"] = now_ms
            unsupported_since = now_ms
    else:
        meta.pop("unsupported_since", None)
    if age_ms >= EXIT_STALL_SECONDS * 1000 and peak_pct < EXIT_STALL_MIN_PEAK_PCT and snap_fresh:
        if reverse and pnl >= min_profit:
            return f"走势转弱平仓，最高浮盈 {peak_pct:.2f}%"
        if not supported and pnl >= min_profit:
            return f"信号衰减平仓，最高浮盈 {peak_pct:.2f}%"

    if strategy == "funding_reversion" and age_ms >= FUNDING_EXIT_MAX_HOLD_SECONDS * 1000 and pnl >= min_profit:
        return f"费率回归到时平仓，持仓 {int(age_ms / 1000)} 秒，最高浮盈 {peak_pct:.2f}%"

    if age_ms >= EXIT_MAX_HOLD_SECONDS * 1000:
        if pnl >= min_profit:
            return f"持仓到时盈利平仓，持仓 {int(age_ms / 1000)} 秒，最高浮盈 {peak_pct:.2f}%"
        return None

    close_ms = float(_testnet_config["auto_close_minutes"]) * 60 * 1000
    if not snap_fresh and age_ms >= close_ms and pnl >= min_profit:
        return "缺少新策略快照，到时盈利平仓"

    return None


def _close_due_positions(account: dict | None = None) -> None:
    if not _is_paper_mode() and (not _testnet_config.get("api_key") or not _testnet_config.get("api_secret")):
        return
    account = account or (_paper_account_snapshot() if _is_paper_mode() else _account_snapshot())
    positions = _position_map(account)
    now_ms = int(time.time() * 1000)
    for symbol, meta in list(_auto_positions.items()):
        pos = positions.get(symbol)
        if not pos:
            _auto_positions.pop(symbol, None)
            continue
        side = _position_side(pos, meta)
        would_open, snap = _would_open_same_side(symbol, side, meta, now_ms)
        gross_pnl = _position_gross_pnl(pos)
        _, pnl_pct = _position_pnl_pct(symbol, pos, meta)
        add_count = int(meta.get("add_count") or 0)
        last_add_at = int(meta.get("last_add_at") or 0)
        if (
            would_open
            and _strategy_allowed_for_auto(str(meta.get("strategy") or ""))
            and gross_pnl <= -POSITION_ADD_GROSS_LOSS_USDT
            and pnl_pct > EXIT_HARD_STOP_PCT * 0.70
            and add_count < POSITION_MAX_ADDS
            and now_ms - last_add_at >= POSITION_ADD_COOLDOWN_SECONDS * 1000
        ):
            try:
                add_row = {
                    **snap,
                    "forecast_5m_prob": snap.get("forecast_5m_prob") or meta.get("forecast_prob"),
                    "net_edge_pct": snap.get("net_edge_pct") or meta.get("net_edge_pct"),
                    "strategy": meta.get("strategy"),
                }
                add_margin, add_grade = _opportunity_margin_usdt(add_row, account, len(positions))
                add_margin = max(1.0, min(add_margin * 0.50, _safe_float(meta.get("margin"), _order_margin_usdt())))
                price = _safe_float(snap.get("price")) or _paper_mark_price(symbol, _safe_float(meta.get("entry_price")))
                if _is_paper_mode():
                    order = _paper_place_market_order(symbol, meta.get("follow") or _same_side_follow(side), price, add_margin)
                else:
                    _set_leverage(symbol)
                    order = _place_market_order(symbol, meta.get("follow") or _same_side_follow(side), price, add_margin)
                meta["add_count"] = add_count + 1
                meta["last_add_at"] = now_ms
                meta["margin"] = _safe_float(meta.get("margin")) + add_margin
                meta["notional"] = _safe_float(meta.get("notional")) + _order_notional_usdt(add_margin)
                meta["entry_cost"] = _safe_float(meta.get("entry_cost")) + (_safe_float(order.get("entryCost")) if isinstance(order, dict) else 0.0)
                meta["invalid_snapshots"] = 0
                _event(
                    f"{symbol} 仍触发开仓且浮亏，加仓 · {add_grade}级 {add_margin:.2f}U保证金 · 浮亏 {gross_pnl:+.2f} USDT",
                    "info",
                    symbol=symbol,
                    order=order,
                    event_type="add",
                    strategy=meta.get("strategy"),
                    strategy_label=meta.get("strategy_label"),
                    main_signal=meta.get("main_signal"),
                    signal_variant=meta.get("signal_variant"),
                    grade=add_grade,
                    margin=add_margin,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                _event(f"{symbol} 自动加仓失败：{exc}", "warn", symbol=symbol)
        partial_reason = _partial_exit_reason(symbol, pos, meta)
        if partial_reason:
            try:
                close_amount = float(pos["amount"]) * 0.5
                if _is_paper_mode():
                    order = _paper_close_position(symbol, close_amount)
                else:
                    order = _close_position(symbol, close_amount)
                realized = _safe_float(order.get("realizedPnl")) if isinstance(order, dict) else 0.0
                fee = _safe_float(order.get("entryCost")) + _safe_float(order.get("exitCost")) if isinstance(order, dict) else 0.0
                gross_realized = _safe_float(order.get("grossPnl"), realized + fee) if isinstance(order, dict) else realized
                close_ratio = _safe_float(order.get("closedRatio"), 0.5) if isinstance(order, dict) else 0.5
                remain_ratio = max(0.0, 1.0 - close_ratio)
                meta["partial_taken"] = True
                meta["margin"] = _safe_float(meta.get("margin")) * remain_ratio
                meta["notional"] = _safe_float(meta.get("notional")) * remain_ratio
                meta["entry_cost"] = _safe_float(meta.get("entry_cost")) * remain_ratio
                meta["peak_pnl"] = 0.0
                meta["peak_pnl_pct"] = 0.0
                meta["last_progress_at"] = now_ms
                close_item = {
                    "ts": now_ms,
                    "symbol": symbol,
                    "realized": realized,
                    "fee": fee,
                    "gross_realized": gross_realized,
                    "strategy": meta.get("strategy"),
                    "strategy_label": meta.get("strategy_label"),
                    "main_signal": meta.get("main_signal"),
                    "signal_variant": meta.get("signal_variant"),
                    "grade": meta.get("opportunity_grade"),
                    "reason": partial_reason,
                    "margin": _safe_float(meta.get("margin")) / max(remain_ratio, 0.01) * close_ratio,
                }
                _trade_closes.append(close_item)
                del _trade_closes[:-400]
                try:
                    log_trade_close(close_item)
                except Exception:
                    pass
                extra = f" · 手续费 {fee:.4f} USDT · 净利 {realized:+.4f} USDT" if isinstance(order, dict) else f" · 净利 {realized:+.4f} USDT"
                _event(
                    f"{symbol} {partial_reason}{extra}",
                    "info",
                    symbol=symbol,
                    order=order,
                    close=close_item,
                    event_type="partial",
                    strategy=meta.get("strategy"),
                    strategy_label=meta.get("strategy_label"),
                    main_signal=meta.get("main_signal"),
                    signal_variant=meta.get("signal_variant"),
                    grade=meta.get("opportunity_grade"),
                    margin=close_item["margin"],
                )
                continue
            except Exception as exc:  # noqa: BLE001
                _event(f"{symbol} 半仓止盈失败：{exc}", "warn", symbol=symbol)
        reason = _exit_reason(symbol, pos, meta, now_ms)
        if not reason:
            continue
        try:
            if _is_paper_mode():
                order = _paper_close_position(symbol, float(pos["amount"]))
            else:
                order = _close_position(symbol, float(pos["amount"]))
            realized = _safe_float(order.get("realizedPnl")) if isinstance(order, dict) else 0.0
            fee = _safe_float(order.get("entryCost")) + _safe_float(order.get("exitCost")) if isinstance(order, dict) else 0.0
            gross_realized = _safe_float(order.get("grossPnl"), realized + fee) if isinstance(order, dict) else realized
            close_item = {
                "ts": now_ms,
                "symbol": symbol,
                "realized": realized,
                "fee": fee,
                "gross_realized": gross_realized,
                "strategy": meta.get("strategy"),
                "strategy_label": meta.get("strategy_label"),
                "main_signal": meta.get("main_signal"),
                "signal_variant": meta.get("signal_variant"),
                "grade": meta.get("opportunity_grade"),
                "reason": reason,
                "margin": meta.get("margin"),
            }
            _trade_closes.append(close_item)
            del _trade_closes[:-400]
            _register_close_cooldown(symbol, str(meta.get("strategy") or ""), realized, now_ms)
            try:
                log_trade_close(close_item)
            except Exception:
                pass
            extra = f" · 手续费 {fee:.4f} USDT · 净利 {realized:+.4f} USDT" if isinstance(order, dict) else f" · 净利 {realized:+.4f} USDT"
            _event(
                f"{symbol} {reason}{extra}",
                "info",
                symbol=symbol,
                order=order,
                close=close_item,
                event_type="close",
                strategy=meta.get("strategy"),
                strategy_label=meta.get("strategy_label"),
                main_signal=meta.get("main_signal"),
                signal_variant=meta.get("signal_variant"),
                grade=meta.get("opportunity_grade"),
                margin=meta.get("margin"),
            )
            _auto_positions.pop(symbol, None)
        except Exception as exc:  # noqa: BLE001
            _event(f"{symbol} 自动平仓失败：{exc}", "error", symbol=symbol)




def bind_entry_strategy(entry_strategy) -> None:
    globals()["_auto_signal_allowed_for_trade"] = entry_strategy._auto_signal_allowed_for_trade
    globals()["_opportunity_margin_usdt"] = entry_strategy._opportunity_margin_usdt
