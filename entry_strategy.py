from __future__ import annotations


def bind(runtime) -> None:
    names = [name for name in dir(runtime) if name.startswith("_") or name.isupper()]
    globals().update({name: getattr(runtime, name) for name in names})


def _entry_key(symbol: str, follow: str, strategy: str = "") -> str:
    parts = [symbol, follow]
    if strategy:
        parts.append(strategy)
    return "|".join(parts)


def _opportunity_grade(row: dict) -> str:
    prob = _safe_float(row.get("forecast_5m_prob") or row.get("forecast_prob"))
    edge = _safe_float(row.get("net_edge_pct"))
    grade = "B"
    if prob >= 72:
        grade = "A"
    elif prob >= 68:
        grade = "B+"
    elif prob <= LOW_CONFIDENCE_PROB:
        grade = "C"
    if edge >= 0.35:
        grade = "A" if grade in {"A", "B+"} else grade
    return grade


def _market_quality_allows_auto(row: dict) -> bool:
    symbol = str(row.get("symbol") or "")
    if symbol in BANNED_LOW_LIQUIDITY:
        return False
    volume_24h = _safe_float(row.get("volume_24h_usd") or row.get("volume_24h"))
    spread = _safe_float(row.get("book_spread_pct"))
    bid_depth = _safe_float(row.get("bid_depth_usd"))
    ask_depth = _safe_float(row.get("ask_depth_usd"))
    min_volume = 35_000_000 if symbol in MAJOR_SYMBOLS else 85_000_000
    if volume_24h and volume_24h < min_volume:
        return False
    if spread and spread > (0.05 if symbol in MAJOR_SYMBOLS else 0.12):
        return False
    min_depth = 35_000 if symbol in MAJOR_SYMBOLS else 25_000
    if bid_depth and bid_depth < min_depth:
        return False
    if ask_depth and ask_depth < min_depth:
        return False
    return True


def _auto_signal_allowed_for_trade(row: dict) -> bool:
    strategy = str(row.get("strategy") or "").strip()
    one_minute = _strategy_mode() in {"one_minute", "current"}
    if not _strategy_allowed_for_auto(strategy):
        return False
    symbol = str(row.get("symbol") or "")
    if not _market_quality_allows_auto(row):
        return False
    prob = _safe_float(row.get("forecast_5m_prob") or row.get("forecast_prob"))
    edge = _safe_float(row.get("net_edge_pct"))
    score = _safe_float(row.get("score"))
    volume_24h = _safe_float(row.get("volume_24h_usd") or row.get("volume_24h"))
    if strategy == "funding_reversion":
        if prob < (58 if one_minute else 62) or edge < (0.03 if one_minute else 0.06):
            return False
        if symbol not in MAJOR_SYMBOLS and volume_24h and volume_24h < (70_000_000 if one_minute else 120_000_000):
            return False
    if strategy == "liquidity_sweep_reclaim":
        if prob < (63 if one_minute else 66) or edge < (0.06 if one_minute else 0.14) or score < (64 if one_minute else 70):
            return False
    if strategy == "main_flow_direction":
        if score < 54 or prob < 62 or edge < 0.05:
            return False
    if strategy == "flow_momentum":
        if prob < 62 or edge < 0.08 or score < 62:
            return False
    if strategy == "liquidation_reversal":
        if prob < 60 or edge < 0.03 or score < 62:
            return False
    if strategy == "flow_exhaustion_reversal":
        if prob < 60 or edge < 0.03 or score < 62:
            return False
    if _strategy_mode() not in {"test_more", "one_minute"} and _opportunity_grade(row) == "C":
        return False
    return True


def _confirmed_entry_rows(rows: list[dict], market_rows: list[dict] | None, now_ms: int) -> list[dict]:
    source = market_rows or rows or []
    confirmed: list[dict] = []
    for row in source:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        follow = row.get("follow")
        if follow not in {"FOLLOW_LONG", "FOLLOW_SHORT"}:
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
    reserve = max(5.0, equity * 0.20)
    slot_reserve = max(0, int(_testnet_config["max_positions"]) - open_count - 1) * max(1.0, _order_margin_usdt() * 0.35)
    return max(1.0, equity - used - reserve - slot_reserve)


def _recent_strategy_risk_scale(strategy: str) -> float:
    try:
        closes = get_trade_closes(80)
    except Exception:
        closes = []
    rows = [item for item in closes if str(item.get("strategy") or "") == strategy]
    if len(rows) < 4:
        return 1.0
    pnls = [_safe_float(item.get("realized")) for item in rows[-20:]]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0)
    net = sum(pnls)
    if net < 0 and pf < 0.7:
        return 0.45
    if net < 0:
        return 0.70
    if pf >= 1.25 and len(rows) >= 8:
        return 1.10
    return 1.0


def _opportunity_margin_usdt(row: dict, account: dict, open_count: int) -> tuple[float, str]:
    base = _order_margin_usdt()
    prob = _safe_float(row.get("forecast_5m_prob") or row.get("forecast_prob"))
    edge = _safe_float(row.get("net_edge_pct"))
    strategy = str(row.get("strategy") or "")
    multiplier = 1.0
    grade = _opportunity_grade(row)
    if strategy == "sector_lead_lag":
        multiplier += 0.25
    elif strategy == "liquidation_reversal":
        multiplier += 0.15
    elif strategy == "liquidity_sweep_reclaim":
        multiplier += 0.30
    elif strategy == "flow_exhaustion_reversal":
        multiplier += 0.10
    elif strategy == "flow_momentum":
        multiplier -= 0.50
    if prob >= 72:
        multiplier += 1.4
    elif prob >= 68:
        multiplier += 0.75
    elif prob <= LOW_CONFIDENCE_PROB:
        multiplier -= 0.35
    if edge >= 0.35:
        multiplier += 0.65
    elif edge >= 0.22:
        multiplier += 0.25
    elif edge < 0.12:
        multiplier -= 0.25
    target = max(1.0, base * multiplier * _recent_strategy_risk_scale(strategy))
    if strategy == "flow_momentum":
        target = min(target, base * FLOW_MOMENTUM_MAX_MARGIN_MULT)
        if grade == "A":
            grade = "B"
    if strategy == "main_flow_direction":
        target = min(target, base * 0.80)
        if grade == "A":
            grade = "B+"
    if strategy == "liquidity_sweep_reclaim":
        tier = str(row.get("test_tier") or row.get("signal_tier") or "core")
        target = min(target, base * (0.65 if tier == "probe" else 1.25))
    available = _available_margin_usdt(account, open_count)
    equity = _safe_float(account.get("equity") or account.get("wallet"), PAPER_STARTING_BALANCE)
    per_trade_cap = max(base, equity * 0.45)
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
            strategy_label = str(row.get("strategy_label") or ("费率回归" if strategy == "funding_reversion" else "大单动量"))
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
            if symbol in BANNED_LOW_LIQUIDITY:
                _event(f"{symbol} 跳过：流动性过低", "warn", symbol=symbol)
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
                    "signal_variant": row.get("signal_variant") or "primary",
                    "opened_at": now_ms,
                    "order_id": order.get("orderId"),
                    "entry_price": price,
                    "margin": order_margin,
                    "notional": order_notional,
                    "opportunity_grade": opportunity_grade,
                    "entry_cost": _safe_float(order.get("entryCost")) if isinstance(order, dict) else 0.0,
                    "forecast_prob": _safe_float(row.get("forecast_5m_prob") or row.get("forecast_prob")),
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
                    f"{symbol} {('做多' if follow == 'FOLLOW_LONG' else '做空')} {strategy_label} {mode}自动下单 · {opportunity_grade}级 {order_margin:.2f}U保证金",
                    "info",
                    symbol=symbol,
                    order=order,
                    event_type="open",
                    strategy=strategy,
                    strategy_label=strategy_label,
                    main_signal=row.get("main_signal") or strategy,
                    signal_variant=row.get("signal_variant") or "primary",
                    grade=opportunity_grade,
                    margin=order_margin,
                )
            except Exception as exc:  # noqa: BLE001
                _event(f"{symbol} 自动下单失败：{exc}", "error", symbol=symbol)




def bind_exit_strategy(exit_strategy) -> None:
    globals()["_close_due_positions"] = exit_strategy._close_due_positions
    globals()["_strategy_exit_plan"] = exit_strategy._strategy_exit_plan
