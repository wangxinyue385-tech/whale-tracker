from __future__ import annotations


def bind(runtime) -> None:
    names = [name for name in dir(runtime) if name.startswith("_") or name.isupper()]
    globals().update({name: getattr(runtime, name) for name in names})


def _entry_key(symbol: str, follow: str, strategy: str = "") -> str:
    parts = [symbol, follow]
    if strategy:
        parts.append(strategy)
    return "|".join(parts)


def _field(row: dict, *names: str, default=0):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return default


def _mode_is_loose_test() -> bool:
    return _strategy_mode() in {"test_more", "one_minute"}


def _side_from_follow(follow: str) -> str:
    if follow == "FOLLOW_LONG":
        return "LONG"
    if follow == "FOLLOW_SHORT":
        return "SHORT"
    return "NEUTRAL"


def _opposite_side(side: str) -> str:
    return "SHORT" if side == "LONG" else "LONG" if side == "SHORT" else "NEUTRAL"


def _market_regime(row: dict) -> str:
    """Return LONG_ONLY, SHORT_ONLY, BOTH, or NO_TRADE from broad trend context."""
    symbol = str(row.get("symbol") or "")
    ema_gap = _safe_float(_field(row, "ema_trend_gap_pct", "ema_gap_pct"))
    ret24 = _safe_float(_field(row, "ret_24h", "trend_ret_24h", "price_24h_pct"))
    btc_ema_gap = _safe_float(_field(row, "btc_ema_trend_gap_pct"))
    btc_ret24 = _safe_float(_field(row, "btc_trend_ret_24h", "btc_24h_pct"))
    btc_5m = _safe_float(_field(row, "btc_5m_pct"))
    mb_bias = _safe_float(_field(row, "market_bias", "mb_bias"))

    risk_on = symbol in MAJOR_SYMBOLS or (btc_ema_gap >= -0.03 and btc_ret24 >= -1.2 and btc_5m > -1.3)
    risk_off = symbol in MAJOR_SYMBOLS or (btc_ema_gap <= 0.03 and btc_ret24 <= 1.2 and btc_5m < 1.3)
    local_long = ema_gap >= -0.02 and ret24 >= -0.35
    local_short = ema_gap <= 0.02 and ret24 <= 0.35

    if mb_bias >= 2 and risk_on:
        return "LONG_ONLY"
    if mb_bias <= -2 and risk_off:
        return "SHORT_ONLY"
    if local_long and risk_on and not (btc_ret24 < -2.0 and btc_5m < -1.8):
        return "LONG_ONLY"
    if local_short and risk_off and not (btc_ret24 > 2.0 and btc_5m > 1.8):
        return "SHORT_ONLY"
    if symbol in MAJOR_SYMBOLS or abs(mb_bias) <= 1:
        return "BOTH"
    return "NO_TRADE"


def _regime_allows(row: dict) -> bool:
    side = _side_from_follow(str(row.get("follow") or ""))
    strategy = str(row.get("strategy") or "")
    regime = _market_regime(row)
    row["market_regime"] = regime
    if regime == "NO_TRADE":
        return False
    if regime == "BOTH":
        return True
    if strategy in {"liquidity_sweep_reclaim", "liquidation_reversal", "flow_exhaustion_reversal", "funding_reversion"}:
        score = _safe_float(row.get("score"))
        prob = _safe_float(_field(row, "forecast_5m_prob", "forecast_prob"))
        edge = _safe_float(row.get("net_edge_pct"))
        strong_counter = score >= 72 and prob >= 66 and edge >= 0.14
        return side == regime.replace("_ONLY", "") or strong_counter
    return side == regime.replace("_ONLY", "")


def _opportunity_grade(row: dict) -> str:
    prob = _safe_float(_field(row, "forecast_5m_prob", "forecast_prob"))
    edge = _safe_float(row.get("net_edge_pct"))
    strategy = str(row.get("strategy") or "")
    grade = "B"
    if prob >= 72:
        grade = "A"
    elif prob >= 66:
        grade = "B+"
    elif prob <= LOW_CONFIDENCE_PROB:
        grade = "C"
    if edge >= 0.35:
        grade = "A" if grade in {"A", "B+"} else grade
    if strategy in {"flow_momentum", "funding_reversion"} and grade == "A":
        grade = "B+"
    return grade


def _market_quality_allows_auto(row: dict) -> bool:
    symbol = str(row.get("symbol") or "")
    if symbol in BANNED_LOW_LIQUIDITY:
        return False
    volume_24h = _safe_float(_field(row, "volume_24h_usd", "volume_24h"))
    spread = _safe_float(row.get("book_spread_pct"))
    bid_depth = _safe_float(row.get("bid_depth_usd"))
    ask_depth = _safe_float(row.get("ask_depth_usd"))
    min_volume = 25_000_000 if symbol in MAJOR_SYMBOLS else 45_000_000
    if volume_24h and volume_24h < min_volume:
        return False
    if spread and spread > (0.06 if symbol in MAJOR_SYMBOLS else 0.14):
        return False
    min_depth = 25_000 if symbol in MAJOR_SYMBOLS else 18_000
    if bid_depth and bid_depth < min_depth:
        return False
    if ask_depth and ask_depth < min_depth:
        return False
    return True


def _auto_signal_allowed_for_trade(row: dict) -> bool:
    strategy = str(row.get("strategy") or "").strip()
    if not _strategy_allowed_for_auto(strategy):
        return False
    if not _market_quality_allows_auto(row):
        return False
    if not _regime_allows(row):
        return False

    loose = _mode_is_loose_test()
    prob = _safe_float(_field(row, "forecast_5m_prob", "forecast_prob"))
    edge = _safe_float(row.get("net_edge_pct"))
    score = _safe_float(row.get("score"))
    volume_24h = _safe_float(_field(row, "volume_24h_usd", "volume_24h"))

    if strategy == "main_flow_direction":
        return score >= 54 and prob >= 60 and edge >= 0.04
    if strategy == "flow_momentum":
        return prob >= (58 if loose else 62) and edge >= (0.03 if loose else 0.08) and score >= (56 if loose else 62)
    if strategy == "liquidity_sweep_reclaim":
        tier = str(row.get("test_tier") or row.get("signal_tier") or "")
        return prob >= (60 if loose or tier == "probe" else 66) and edge >= (0.03 if loose else 0.12) and score >= (58 if loose else 66)
    if strategy == "funding_reversion":
        if symbol := str(row.get("symbol") or ""):
            if symbol not in MAJOR_SYMBOLS and volume_24h and volume_24h < (55_000_000 if loose else 90_000_000):
                return False
        return prob >= (56 if loose else 61) and edge >= (0.02 if loose else 0.05)
    if strategy in {"liquidation_reversal", "flow_exhaustion_reversal"}:
        return prob >= (57 if loose else 61) and edge >= (0.02 if loose else 0.05) and score >= (58 if loose else 62)

    if _strategy_mode() not in {"test_more", "one_minute"} and _opportunity_grade(row) == "C":
        return False
    return True


def _confirmed_entry_rows(rows: list[dict], market_rows: list[dict] | None, now_ms: int) -> list[dict]:
    source = market_rows or rows or []
    confirmed: list[dict] = []
    for row in source:
        symbol = str(row.get("symbol") or "").strip()
        follow = row.get("follow")
        if not symbol or follow not in {"FOLLOW_LONG", "FOLLOW_SHORT"}:
            continue
        if not _auto_signal_allowed_for_trade(row):
            continue
        confirmed.append({**row, "entry_confirm_count": 1})
    return confirmed


def _order_margin_usdt() -> float:
    return max(1.0, float(_testnet_config["order_usdt"]))


def _order_notional_usdt(margin: float | None = None) -> float:
    return max(1.0, float(margin if margin is not None else _order_margin_usdt())) * max(1, int(_testnet_config["leverage"]))


def _available_margin_usdt(account: dict, open_count: int) -> float:
    equity = _safe_float(account.get("equity") or account.get("wallet"), PAPER_STARTING_BALANCE)
    used = sum(_safe_float(pos.get("margin")) for pos in account.get("positions", []))
    reserve = max(5.0, equity * 0.25)
    slot_reserve = max(0, int(_testnet_config["max_positions"]) - open_count - 1) * max(1.0, _order_margin_usdt() * 0.30)
    return max(1.0, equity - used - reserve - slot_reserve)


def _recent_strategy_risk_scale(strategy: str) -> float:
    try:
        closes = get_trade_closes(100)
    except Exception:
        closes = []
    rows = [item for item in closes if str(item.get("strategy") or "") == strategy]
    if len(rows) < 6:
        return 1.0
    pnls = [_safe_float(item.get("realized")) for item in rows[-24:]]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0)
    net = sum(pnls)
    if net < 0 and pf < 0.75:
        return 0.40
    if net < 0:
        return 0.65
    if pf >= 1.35 and len(rows) >= 12:
        return 1.10
    return 1.0


def _opportunity_margin_usdt(row: dict, account: dict, open_count: int) -> tuple[float, str]:
    base = _order_margin_usdt()
    prob = _safe_float(_field(row, "forecast_5m_prob", "forecast_prob"))
    edge = _safe_float(row.get("net_edge_pct"))
    strategy = str(row.get("strategy") or "")
    grade = _opportunity_grade(row)

    if strategy == "main_flow_direction":
        multiplier = 0.80
    elif strategy == "liquidity_sweep_reclaim":
        tier = str(row.get("test_tier") or row.get("signal_tier") or "probe")
        multiplier = 0.35 if tier == "probe" else 0.55
    elif strategy in {"flow_momentum", "funding_reversion"}:
        multiplier = 0.35
    elif strategy in {"liquidation_reversal", "flow_exhaustion_reversal"}:
        multiplier = 0.40
    else:
        multiplier = 0.45

    if prob >= 72 and edge >= 0.22:
        multiplier += 0.20
    elif prob <= LOW_CONFIDENCE_PROB or edge < 0.06:
        multiplier -= 0.10
    if _market_regime(row) in {"LONG_ONLY", "SHORT_ONLY"} and _side_from_follow(str(row.get("follow") or "")) == _market_regime(row).replace("_ONLY", ""):
        multiplier += 0.10

    target = max(1.0, base * max(0.20, multiplier) * _recent_strategy_risk_scale(strategy))
    available = _available_margin_usdt(account, open_count)
    equity = _safe_float(account.get("equity") or account.get("wallet"), PAPER_STARTING_BALANCE)
    per_trade_cap = max(base * 0.50, equity * (0.16 if strategy != "main_flow_direction" else 0.25))
    margin = min(target, available, per_trade_cap)
    return max(1.0, margin), grade


def _auto_trade_signals(rows: list[dict], prices: dict[str, float], market_rows: list[dict] | None = None) -> None:
    _remember_prices(prices)
    _update_market_snapshots(market_rows)
    if not _testnet_config.get("auto_trade"):
        return
    if not _is_paper_mode() and (not _testnet_config.get("api_key") or not _testnet_config.get("api_secret")):
        _event("自动下单已开启，但模拟盘 API 未配置", "warn")
        return
    with _trade_lock:
        account = _paper_account_snapshot() if _is_paper_mode() else _account_snapshot()
        _close_due_positions(account)
        positions = _position_map(_paper_account_snapshot() if _is_paper_mode() else _account_snapshot())
        open_count = len(positions)
        now_ms = int(time.time() * 1000)
        rows = _confirmed_entry_rows(rows, market_rows, now_ms)
        if not rows:
            return
        for row in rows:
            symbol = str(row.get("symbol") or "")
            follow = row.get("follow")
            strategy = str(row.get("strategy") or "flow_momentum")
            strategy_label = str(row.get("strategy_label") or ("主方向测试" if strategy == "main_flow_direction" else "宽松测试"))
            if follow not in {"FOLLOW_LONG", "FOLLOW_SHORT"} or not symbol:
                continue
            if not _auto_signal_allowed_for_trade(row):
                continue
            if open_count >= int(_testnet_config["max_positions"]):
                _event(f"{symbol} 跳过：持仓数量已达上限", "warn", symbol=symbol)
                continue
            cooldown_key = f"{symbol}|{follow}"
            symbol_cooldown_key = f"{symbol}|*"
            cooldown_seconds = max(0, int(_testnet_config["cooldown_seconds"]))
            if cooldown_seconds and (
                now_ms - _trade_cooldown.get(cooldown_key, 0) < cooldown_seconds * 1000
                or now_ms - _trade_cooldown.get(symbol_cooldown_key, 0) < cooldown_seconds * 1000
            ):
                continue
            if symbol in positions:
                _event(f"{symbol} 跳过：已有模拟盘持仓", "warn", symbol=symbol)
                continue
            try:
                price = float(row.get("price") or prices.get(symbol) or 0)
                order_margin, opportunity_grade = _opportunity_margin_usdt(row, account, open_count)
                order_notional = _order_notional_usdt(order_margin)
                exit_plan = _strategy_exit_plan(row, strategy)
                if _is_paper_mode():
                    order = _paper_place_market_order(symbol, follow, price, order_margin)
                else:
                    _set_leverage(symbol)
                    order = _place_market_order(symbol, follow, price, order_margin)
                _trade_cooldown[cooldown_key] = now_ms
                _trade_cooldown[symbol_cooldown_key] = now_ms
                _entry_candidates.pop(_entry_key(symbol, str(follow), strategy), None)
                _auto_positions[symbol] = {
                    "follow": follow,
                    "strategy": strategy,
                    "strategy_label": strategy_label,
                    "main_signal": row.get("main_signal") or strategy,
                    "signal_variant": row.get("signal_variant") or row.get("test_tier") or "loose_test",
                    "market_regime": row.get("market_regime") or _market_regime(row),
                    "opened_at": now_ms,
                    "order_id": order.get("orderId"),
                    "entry_price": price,
                    "margin": order_margin,
                    "notional": order_notional,
                    "opportunity_grade": opportunity_grade,
                    "entry_cost": _safe_float(order.get("entryCost")) if isinstance(order, dict) else 0.0,
                    "forecast_prob": _safe_float(_field(row, "forecast_5m_prob", "forecast_prob")),
                    "net_edge_pct": _safe_float(row.get("net_edge_pct")),
                    "exit_stop_pct": exit_plan["stop_pct"],
                    "exit_r_pct": exit_plan["r_pct"],
                    "take_profit_pct": exit_plan["take_profit_pct"],
                    "trail_arm_pct": exit_plan["trail_arm_pct"],
                    "exit_fail_seconds": exit_plan["fail_seconds"],
                    "exit_timeout_seconds": exit_plan["timeout_seconds"],
                    "peak_pnl": 0.0,
                    "peak_pnl_pct": 0.0,
                    "last_favorable_pct": 0.0,
                    "last_favorable_at": now_ms,
                    "last_progress_at": now_ms,
                    "invalid_snapshots": 0,
                }
                open_count += 1
                mode = "本地模拟盘" if _is_paper_mode() else "Binance Testnet"
                _event(
                    f"{symbol} {('做多' if follow == 'FOLLOW_LONG' else '做空')} {strategy_label} {mode}自动下单 · {opportunity_grade}级 {order_margin:.2f}U保证金 · {row.get('market_regime') or _market_regime(row)}",
                    "info",
                    symbol=symbol,
                    order=order,
                    event_type="open",
                    strategy=strategy,
                    strategy_label=strategy_label,
                    main_signal=row.get("main_signal") or strategy,
                    signal_variant=row.get("signal_variant") or row.get("test_tier") or "loose_test",
                    grade=opportunity_grade,
                    margin=order_margin,
                )
            except Exception as exc:  # noqa: BLE001
                _event(f"{symbol} 自动下单失败：{exc}", "error", symbol=symbol)


def bind_exit_strategy(exit_strategy) -> None:
    globals()["_close_due_positions"] = exit_strategy._close_due_positions
    globals()["_strategy_exit_plan"] = exit_strategy._strategy_exit_plan
