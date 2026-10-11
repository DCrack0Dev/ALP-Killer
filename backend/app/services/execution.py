"""Order intent flow: use broker-authoritative market data, risk-check, submit once, reconcile."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AutomationState,
    BrokerConnection,
    BrokerOrder,
    KillSwitchState,
    OrderIntent,
    PnLSnapshot,
    RiskConfiguration,
    RiskDecision,
    Signal,
)
from app.schemas import OrderIntentRequest
from app.services.audit import record_audit
from app.services.connection import adapter_for_connection
from app.services.risk import Decision, RiskEngine, TradeContext

ACTIVE_INTENT_STATUSES = {
    "PENDING_RISK",
    "SUBMISSION_UNCERTAIN",
    "accepted",
    "new",
    "pending_new",
    "partially_filled",
}


def _client_order_id(request: OrderIntentRequest) -> str:
    """Use a stable signal identity so retries reconcile instead of duplicating orders."""
    canonical = "|".join(
        [
            request.environment.value,
            request.symbol.upper(),
            request.side,
            f"{request.quantity:.8f}",
            request.signal_id or "manual-guarded",
        ]
    )
    return f"ak-{hashlib.sha256(canonical.encode()).hexdigest()[:28]}"


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _pause(
    db: Session,
    intent: OrderIntent,
    *,
    reason_code: str,
    reason: str,
    details: dict[str, Any] | None = None,
    decision: Decision = Decision.PAUSED,
) -> OrderIntent:
    intent.status = "PAUSED"
    db.add(
        RiskDecision(
            environment=intent.environment,
            order_intent_id=intent.id,
            decision=decision.value,
            reason_code=reason_code,
            reason=reason,
            details_json=details or {},
        )
    )
    return intent


def _weekly_loss(db: Session, environment: str, now: datetime) -> float:
    rows = db.scalars(
        select(PnLSnapshot)
        .where(
            PnLSnapshot.environment == environment,
            PnLSnapshot.captured_at >= now - timedelta(days=7),
        )
        .order_by(PnLSnapshot.captured_at.desc())
    ).all()
    # Keep only the most recent snapshot for each UTC day to avoid double-counting intraday updates.
    latest_by_day: dict[date, PnLSnapshot] = {}
    for row in rows:
        captured = _as_utc(row.captured_at)
        if captured is not None:
            latest_by_day.setdefault(captured.date(), row)
    return max(0.0, -sum(float(row.daily_pnl) for row in latest_by_day.values()))


def execute_order_intent(
    db: Session,
    *,
    user_id: str,
    request: OrderIntentRequest,
    fernet: Fernet,
    allow_live_trading: bool = False,
) -> OrderIntent:
    """Execute only after current broker quotes and every hard risk gate have been verified."""
    environment = request.environment.value
    if environment not in {"paper", "live"}:
        raise ValueError("Broker order submission is unavailable in backtest mode")

    client_order_id = _client_order_id(request)
    existing = db.scalar(select(OrderIntent).where(OrderIntent.client_order_id == client_order_id))
    if existing is not None:
        return existing

    intent = OrderIntent(
        environment=environment,
        instrument=request.symbol.upper(),
        side=request.side,
        quantity=request.quantity,
        estimated_notional=request.quantity * request.reference_price,
        client_order_id=client_order_id,
        status="PENDING_RISK",
        signal_id=request.signal_id,
        payload_json={"reference_price": request.reference_price},
    )
    db.add(intent)
    db.flush()

    if environment == "live" and not allow_live_trading:
        return _pause(
            db,
            intent,
            reason_code="LIVE_DISABLED_BY_DEPLOYMENT",
            reason="Live order routing is disabled by deployment policy; no broker request was made",
        )

    signal = db.scalar(select(Signal).where(Signal.id == request.signal_id))
    signal_expiry = _as_utc(signal.expires_at) if signal is not None else None
    if (
        signal is None
        or signal.status != "SETUP"
        or signal.environment != environment
        or signal.instrument.upper() != intent.instrument
        or signal.side != intent.side
        or signal_expiry is None
        or signal_expiry <= datetime.now(UTC)
    ):
        return _pause(
            db,
            intent,
            reason_code="VALIDATED_SIGNAL_REQUIRED",
            reason="A matching, unexpired server-generated setup is required; no broker request was made",
            decision=Decision.REJECTED,
        )

    connection = db.scalar(
        select(BrokerConnection).where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.environment == environment,
            BrokerConnection.disconnected_at.is_(None),
        )
    )
    configuration = db.scalar(
        select(RiskConfiguration).where(
            RiskConfiguration.user_id == user_id,
            RiskConfiguration.environment == environment,
        )
    )
    automation = db.scalar(
        select(AutomationState).where(
            AutomationState.user_id == user_id,
            AutomationState.environment == environment,
        )
    )
    kill_switch = db.scalar(select(KillSwitchState).where(KillSwitchState.user_id == user_id))
    if connection is None or configuration is None or not configuration.complete:
        return _pause(
            db,
            intent,
            reason_code="RISK_CONFIGURATION_REQUIRED",
            reason="A verified connection and complete risk configuration are required",
            decision=Decision.PAUSED,
        )

    adapter = adapter_for_connection(connection, fernet)
    started = perf_counter()
    try:
        quote_map = adapter.get_quotes([intent.instrument])
        quote = quote_map.get(intent.instrument) or quote_map.get(intent.instrument.upper())
        account = adapter.get_account()
        positions = adapter.get_positions()
    except Exception:
        return _pause(
            db,
            intent,
            reason_code="BROKER_RECONCILIATION_FAILED",
            reason="Broker quote, account, or position state could not be reconciled; no order was sent",
        )
    latency_ms = (perf_counter() - started) * 1000
    if not isinstance(quote, dict):
        return _pause(
            db,
            intent,
            reason_code="BROKER_QUOTE_MISSING",
            reason="Alpaca returned no current quote for the instrument; no order was sent",
        )

    bid = _number(quote.get("bid_price", quote.get("bp")))
    ask = _number(quote.get("ask_price", quote.get("ap")))
    bid_size = _number(quote.get("bid_size", quote.get("bs")))
    ask_size = _number(quote.get("ask_size", quote.get("as")))
    quote_timestamp = _as_utc(quote.get("timestamp", quote.get("t")))
    if (
        bid is None
        or ask is None
        or bid_size is None
        or ask_size is None
        or quote_timestamp is None
        or bid <= 0
        or ask < bid
        or bid_size < 0
        or ask_size < 0
    ):
        return _pause(
            db,
            intent,
            reason_code="BROKER_QUOTE_INVALID",
            reason="Alpaca returned an incomplete or invalid quote; no order was sent",
        )

    now = datetime.now(UTC)
    executable_price = ask if request.side == "buy" else bid
    midpoint = (bid + ask) / 2
    spread_bps = ((ask - bid) / midpoint) * 10_000 if midpoint > 0 else float("inf")
    liquidity_usd = bid * bid_size + ask * ask_size
    estimated_slippage_bps = (
        abs(executable_price - request.reference_price) / request.reference_price * 10_000
    )
    intent.estimated_notional = request.quantity * executable_price
    intent.payload_json = {
        **intent.payload_json,
        "executable_price": executable_price,
        "broker_quote_timestamp": quote_timestamp.isoformat(),
        "spread_bps": spread_bps,
        "liquidity_usd": liquidity_usd,
        "estimated_slippage_bps": estimated_slippage_bps,
    }

    if request.side == "buy" and not (0 < request.quantity):
        return _pause(
            db,
            intent,
            reason_code="INVALID_ORDER_QUANTITY",
            reason="Order quantity is invalid; no order was sent",
            decision=Decision.REJECTED,
        )

    current_position = next(
        (
            position
            for position in positions
            if str(position.get("symbol", "")).upper() == intent.instrument
        ),
        None,
    )
    current_qty = _number((current_position or {}).get("qty")) or 0.0
    is_reduction = request.side == "sell" and current_qty > 0
    if is_reduction and request.quantity > current_qty + 1e-9:
        return _pause(
            db,
            intent,
            reason_code="REDUCTION_EXCEEDS_POSITION",
            reason="Sell quantity exceeds the reconciled long position; no order was sent",
            decision=Decision.REJECTED,
        )

    equity = _number(account.get("equity"))
    if equity is None or equity <= 0:
        return _pause(
            db,
            intent,
            reason_code="ACCOUNT_EQUITY_UNAVAILABLE",
            reason="A valid broker equity value is required for risk sizing; no order was sent",
        )

    risk_amount = 0.0
    if not is_reduction:
        stop_price = request.stop_price
        target_price = request.target_price
        if (
            stop_price is None
            or target_price is None
            or (request.side == "buy" and stop_price >= executable_price)
            or (request.side == "sell" and stop_price <= executable_price)
            or (request.side == "buy" and target_price <= executable_price)
            or (request.side == "sell" and target_price >= executable_price)
        ):
            return _pause(
                db,
                intent,
                reason_code="PROTECTIVE_STOP_REQUIRED",
                reason="A valid protective stop on the loss side of the executable price is required",
                decision=Decision.REJECTED,
            )
        risk_amount = request.quantity * abs(executable_price - stop_price)
        reward_amount = request.quantity * abs(target_price - executable_price)
        if reward_amount < 2 * risk_amount:
            return _pause(
                db,
                intent,
                reason_code="MINIMUM_REWARD_RISK_REQUIRED",
                reason="The attached target must be at least two times the stop risk",
                decision=Decision.REJECTED,
            )
    estimated_risk_pct = risk_amount / equity

    market_value = abs(_number((current_position or {}).get("market_value")) or 0.0)
    total_market_value = sum(
        abs(_number(position.get("market_value")) or 0.0) for position in positions
    )
    latest_pnl = db.scalar(
        select(PnLSnapshot)
        .where(PnLSnapshot.environment == environment)
        .order_by(PnLSnapshot.captured_at.desc())
    )
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    todays_rows = db.scalars(
        select(PnLSnapshot)
        .where(PnLSnapshot.environment == environment, PnLSnapshot.captured_at >= today)
        .order_by(PnLSnapshot.captured_at.desc())
    ).all()
    daily_pnl = float(todays_rows[0].daily_pnl) if todays_rows else 0.0
    daily_loss = max(0.0, -daily_pnl)
    weekly_loss = _weekly_loss(db, environment, now)
    drawdown_pct = float(latest_pnl.drawdown) if latest_pnl else 0.0

    one_hour_ago = now - timedelta(hours=1)
    orders_last_hour = int(
        db.scalar(
            select(func.count(BrokerOrder.id)).where(
                BrokerOrder.environment == environment,
                BrokerOrder.created_at >= one_hour_ago,
            )
        )
        or 0
    )
    recent_intent = db.scalar(
        select(OrderIntent.id)
        .where(
            OrderIntent.environment == environment,
            OrderIntent.instrument == intent.instrument,
            OrderIntent.side == intent.side,
            OrderIntent.id != intent.id,
            OrderIntent.created_at >= now - timedelta(seconds=60),
            OrderIntent.status.in_(ACTIVE_INTENT_STATUSES),
        )
        .limit(1)
    )
    duplicate_order = recent_intent is not None

    # Short sales remain blocked until borrow eligibility and account-specific policy are wired in.
    shorting_allowed = False
    is_short_sale = request.side == "sell" and not is_reduction
    context = TradeContext(
        environment=environment,
        verified_environment=connection.environment,
        automation_enabled=bool(automation and automation.enabled),
        kill_switch_active=bool(kill_switch and kill_switch.active),
        reduce_only=bool(automation and automation.reduce_only)
        or bool(configuration.config_json.get("reduce_only", False)),
        is_position_reduction=is_reduction,
        data_timestamp=quote_timestamp,
        now=now,
        spread_bps=spread_bps,
        liquidity_usd=liquidity_usd,
        estimated_notional=float(intent.estimated_notional),
        instrument_exposure=market_value,
        portfolio_exposure_pct=(
            total_market_value + (0.0 if is_reduction else float(intent.estimated_notional))
        )
        / equity,
        open_positions=len(positions),
        daily_loss=daily_loss,
        weekly_loss=weekly_loss,
        drawdown_pct=drawdown_pct,
        orders_last_hour=orders_last_hour,
        duplicate_order=duplicate_order,
        news_blackout_active=bool(signal.explanation.get("news_blackout_active", False)),
        shorting_allowed=shorting_allowed,
        is_short_sale=is_short_sale,
        latency_ms=latency_ms,
        estimated_risk_pct=estimated_risk_pct,
        estimated_slippage_bps=estimated_slippage_bps,
    )
    result = RiskEngine.evaluate(configuration.config_json, context)
    db.add(
        RiskDecision(
            environment=environment,
            order_intent_id=intent.id,
            decision=result.decision.value,
            reason_code=result.reason_code,
            reason=result.reason,
            details_json={
                **result.details,
                "server_quote_timestamp": quote_timestamp.isoformat(),
                "executable_price": executable_price,
                "estimated_risk_pct": estimated_risk_pct,
                "estimated_slippage_bps": estimated_slippage_bps,
                "spread_bps": spread_bps,
                "liquidity_usd": liquidity_usd,
            },
        )
    )
    record_audit(
        db,
        event_type="PRE_TRADE_RISK_DECISION",
        actor=user_id,
        environment=environment,
        correlation_id=intent.client_order_id,
        payload={
            "decision": result.decision.value,
            "reason_code": result.reason_code,
            "intent_id": intent.id,
        },
    )
    if result.decision != Decision.APPROVED:
        intent.status = "RISK_REJECTED" if result.decision == Decision.REJECTED else "PAUSED"
        return intent

    submitted: dict[str, Any] | None
    try:
        submitted = adapter.submit_order(
            intent.instrument,
            intent.side,
            request.quantity,
            intent.client_order_id,
            request.stop_price if not is_reduction else None,
            request.target_price if not is_reduction else None,
        )
    except Exception:
        # A timeout is ambiguous. Query Alpaca by client_order_id before any future retry.
        submitted = adapter.get_order_by_client_id(intent.client_order_id)
        if submitted is None:
            intent.status = "SUBMISSION_UNCERTAIN"
            record_audit(
                db,
                event_type="ORDER_SUBMISSION_UNCERTAIN",
                actor=user_id,
                environment=environment,
                correlation_id=intent.client_order_id,
                payload={"intent_id": intent.id},
            )
            return intent
    if submitted is None:
        intent.status = "SUBMISSION_UNCERTAIN"
        return intent
    broker_id = str(submitted.get("id", ""))
    if not broker_id:
        intent.status = "SUBMISSION_UNCERTAIN"
        return intent

    intent.status = str(submitted.get("status", "accepted"))
    db.add(
        BrokerOrder(
            environment=environment,
            order_intent_id=intent.id,
            broker_order_id=broker_id,
            broker_status=intent.status,
            raw_status_json=submitted,
        )
    )
    record_audit(
        db,
        event_type="ORDER_SUBMITTED",
        actor=user_id,
        environment=environment,
        correlation_id=intent.client_order_id,
        payload={"intent_id": intent.id, "broker_order_id": broker_id, "status": intent.status},
    )
    return intent
