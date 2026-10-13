"""Persistent paper-analysis worker. Live routing is intentionally unsupported here."""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker import BrokerAdapter
from app.config import Settings, get_settings
from app.db import create_database_engine, create_session_factory
from app.models import (
    AutomationState,
    BrokerConnection,
    KillSwitchState,
    MarketDataMetadata,
    MarketRegime,
    MLModelVersion,
    MLScore,
    NewsEvent,
    RiskConfiguration,
    Signal,
    StrategyConfig,
    SystemHealthEvent,
)
from app.schemas import Environment, OrderIntentRequest
from app.services.audit import record_audit
from app.services.connection import adapter_for_connection
from app.services.execution import execute_order_intent
from app.services.market_analysis import average_true_range, build_supervised_market_data
from app.services.ml import TransparentMLBaseline
from app.services.news import AlpacaNewsProvider, is_fresh
from app.services.regime import MarketObservation, MarketRegimeRouter
from app.services.strategies import TrendContinuationStrategy

LOGGER = logging.getLogger("alpaca_killer.worker")
WORKER_COMPONENT = "paper-worker"
DEFAULT_POLL_SECONDS = 300


def _parse_time(value: Any) -> datetime | None:
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


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _record_no_trade(
    db: Session,
    *,
    environment: str,
    symbol: str,
    now: datetime,
    reason: str,
    regime: str = "NO_TRADE",
    explanation: dict[str, Any] | None = None,
) -> Signal:
    signal = Signal(
        environment=environment,
        instrument=symbol,
        strategy_name="swing_trend_continuation_v1",
        side="buy",
        status="NO_TRADE",
        generated_at=now,
        expires_at=now + timedelta(minutes=5),
        explanation={"reasons": [reason], **(explanation or {})},
    )
    db.add(signal)
    db.flush()
    if regime:
        db.add(
            MarketRegime(
                environment=environment,
                instrument=symbol,
                regime=regime,
                direction="flat",
                confidence=0.0,
                data_timestamp=now,
                expires_at=now + timedelta(minutes=5),
                explanation={"reasons": [reason]},
            )
        )
    return signal


def _save_news(db: Session, environment: str, events: list[Any]) -> None:
    for event in events:
        if event.duplicate_group and db.scalar(
            select(NewsEvent.id).where(
                NewsEvent.environment == environment,
                NewsEvent.duplicate_group == event.duplicate_group,
            )
        ):
            continue
        db.add(
            NewsEvent(
                environment=environment,
                source=event.source,
                published_at=event.published_at,
                received_at=event.received_at,
                affected_instruments=event.affected_instruments,
                event_type=event.event_type,
                sentiment=event.sentiment,
                impact=event.impact,
                duplicate_group=event.duplicate_group,
                confidence=event.confidence,
            )
        )


def _eligible_quantity(
    *,
    entry: float,
    stop: float,
    equity: float,
    config: dict[str, Any],
    total_exposure: float,
    fractionable: bool,
) -> float:
    risk_per_share = entry - stop
    if risk_per_share <= 0 or entry <= 0 or equity <= 0:
        return 0.0
    risk_budget = equity * float(config["max_risk_per_trade_pct"])
    available_portfolio_value = max(
        0.0, equity * float(config["max_portfolio_exposure"]) - total_exposure
    )
    notional_limit = min(
        float(config["max_position_notional"]),
        float(config["max_instrument_exposure"]),
        available_portfolio_value,
    )
    quantity = min(risk_budget / risk_per_share, notional_limit / entry)
    return round(quantity, 6) if fractionable else float(math.floor(quantity))


def _analyze_symbol(
    db: Session,
    *,
    adapter: BrokerAdapter,
    connection: BrokerConnection,
    symbol: str,
    asset: dict[str, Any],
    risk_config: dict[str, Any],
    now: datetime,
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    fernet: Fernet,
) -> str:
    environment = connection.environment
    if not bool(asset.get("tradable", False)) or str(asset.get("status", "active")).lower() != "active":
        _record_no_trade(
            db, environment=environment, symbol=symbol, now=now, reason="Instrument is not tradable"
        )
        return "NO_TRADE"

    quotes = adapter.get_quotes([symbol])
    quote = quotes.get(symbol)
    if not isinstance(quote, dict):
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Alpaca returned no latest quote",
        )
        return "NO_TRADE"
    bid = _float(quote.get("bid_price", quote.get("bp")))
    ask = _float(quote.get("ask_price", quote.get("ap")))
    bid_size = _float(quote.get("bid_size", quote.get("bs")))
    ask_size = _float(quote.get("ask_size", quote.get("as")))
    quote_time = _parse_time(quote.get("timestamp", quote.get("t")))
    if (
        bid is None
        or ask is None
        or bid_size is None
        or ask_size is None
        or quote_time is None
        or bid <= 0
        or ask < bid
        or quote_time > now + timedelta(seconds=5)
        or (now - quote_time).total_seconds() > int(risk_config["stale_data_seconds"])
    ):
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Missing, contradictory, future, or stale quote",
        )
        return "NO_TRADE"
    midpoint = (bid + ask) / 2
    spread_bps = (ask - bid) / midpoint * 10_000 if midpoint > 0 else float("inf")
    liquidity_usd = bid * bid_size + ask * ask_size

    bars = adapter.get_daily_bars(symbol, now - timedelta(days=1100), limit=1000)
    if len(bars) < 135:
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="At least 135 daily bars are required for the time-ordered baseline",
        )
        return "NO_TRADE"
    latest_bar_time = _parse_time(bars[-1].get("timestamp"))
    if latest_bar_time is None or (now - latest_bar_time).total_seconds() > 5 * 86_400:
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Daily history is stale",
        )
        return "NO_TRADE"

    provider = AlpacaNewsProvider(adapter)
    try:
        news_events = provider.fetch(
            [symbol], max_age_seconds=int(risk_config["news_blackout_minutes"]) * 60
        )
    except Exception:
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Approved news provider unavailable; fail-closed",
        )
        return "NO_TRADE"
    _save_news(db, environment, news_events)
    fresh_events = [
        event
        for event in news_events
        if is_fresh(
            event,
            max_age_seconds=int(risk_config["news_blackout_minutes"]) * 60,
            now=now,
        )
    ]
    news_blocked = bool(fresh_events)

    try:
        supervised = build_supervised_market_data(bars, horizon=5)
        model = TransparentMLBaseline()
        model.fit(supervised.features, supervised.labels)
        score = model.score(
            supervised.latest_features,
            feature_timestamp=quote_time,
            expected_return=supervised.expected_return,
            expected_volatility=supervised.expected_volatility,
        )
    except Exception:
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Time-ordered ML training or calibration failed",
            explanation={"news_blackout_active": news_blocked},
        )
        return "NO_TRADE"

    training_range = f"{bars[30].get('timestamp')}..{bars[-6].get('timestamp')}"
    model_version = db.scalar(
        select(MLModelVersion)
        .where(
            MLModelVersion.name == "daily_swing_logistic",
            MLModelVersion.version == score.model_version,
            MLModelVersion.training_range == training_range,
        )
        .limit(1)
    )
    if model_version is None:
        model_version = MLModelVersion(
            name="daily_swing_logistic",
            version=score.model_version,
            training_range=training_range,
            calibration_status=score.calibration_status,
            metadata_json={
                "features": [
                    "return_1d",
                    "return_5d",
                    "return_20d",
                    "sma10_vs_sma30",
                    "volatility_20d",
                    "log_volume_ratio_20d",
                ],
                "label": "positive five-session forward return",
                "walk_forward": "TimeSeriesSplit(n_splits=3,gap=5)",
            },
        )
        db.add(model_version)
        db.flush()
    db.add(
        MLScore(
            environment=environment,
            instrument=symbol,
            model_version_id=model_version.id,
            probability_favorable=score.probability_favorable,
            expected_return=score.expected_return,
            expected_volatility=score.expected_volatility,
            stop_probability=score.stop_probability,
            feature_timestamp=score.feature_timestamp,
        )
    )

    observation = MarketObservation(
        instrument=symbol,
        closes=[float(bar["close"]) for bar in bars],
        volumes=[float(bar.get("volume", 0)) for bar in bars],
        spread_bps=spread_bps,
        liquidity_usd=liquidity_usd,
        data_timestamp=quote_time,
        high_risk_event=news_blocked,
    )
    regime = MarketRegimeRouter().classify(observation)
    explanation = {
        "direction": regime.direction,
        "confidence": regime.confidence,
        "reasons": regime.reasons,
        "contradictions": regime.contradictions,
        "features_used": regime.features_used,
        "news_blackout_active": news_blocked,
        "fresh_news_event_ids": [event.event_id for event in fresh_events],
        "ml": {
            "probability_favorable": score.probability_favorable,
            "expected_return": score.expected_return,
            "expected_volatility": score.expected_volatility,
            "stop_probability": score.stop_probability,
            "calibration_status": score.calibration_status,
            "model_version": score.model_version,
        },
    }
    db.add(
        MarketRegime(
            environment=environment,
            instrument=symbol,
            regime=regime.regime,
            direction=regime.direction,
            confidence=regime.confidence,
            data_timestamp=regime.data_timestamp,
            expires_at=regime.expires_at,
            explanation=explanation,
        )
    )
    db.add(
        MarketDataMetadata(
            environment=environment,
            instrument=symbol,
            source="alpaca_stock_market_data",
            data_timestamp=quote_time,
            quality="fresh",
        )
    )

    strategy = TrendContinuationStrategy().evaluate(
        symbol,
        {"regime": regime.regime},
        {"spread_bps": spread_bps, "liquidity_usd": liquidity_usd},
        {"blocked": news_blocked},
        {"probability_favorable": score.probability_favorable},
    )
    held_position = any(
        str(position.get("symbol", "")).upper() == symbol for position in positions
    )
    has_open_order = any(
        str(order.get("symbol", "")).upper() == symbol for order in open_orders
    )
    if strategy.status != "SETUP" or strategy.side != "buy" or held_position or has_open_order:
        reasons = strategy.reasons or ["No eligible long setup"]
        if strategy.side == "sell":
            reasons = ["Short-selling route is disabled until borrow eligibility is verified"]
        if held_position:
            reasons = ["Position already exists; no automatic pyramiding"]
        if has_open_order:
            reasons = ["An Alpaca open order already exists for this instrument"]
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="; ".join(reasons),
            regime=regime.regime,
            explanation=explanation,
        )
        return "NO_TRADE"

    try:
        atr = average_true_range(bars, period=14)
    except (KeyError, TypeError, ValueError):
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Protective-stop volatility estimate unavailable",
            regime=regime.regime,
            explanation=explanation,
        )
        return "NO_TRADE"
    entry = ask
    stop = entry - 2 * atr
    target = entry + 4 * atr
    equity = _float(account.get("equity"))
    if equity is None or equity <= 0:
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Broker equity unavailable for position sizing",
            regime=regime.regime,
            explanation=explanation,
        )
        return "NO_TRADE"
    total_exposure = sum(abs(_float(position.get("market_value")) or 0.0) for position in positions)
    quantity = _eligible_quantity(
        entry=entry,
        stop=stop,
        equity=equity,
        config=risk_config,
        total_exposure=total_exposure,
        fractionable=bool(asset.get("fractionable", False)),
    )
    if quantity <= 0:
        _record_no_trade(
            db,
            environment=environment,
            symbol=symbol,
            now=now,
            reason="Configured risk and exposure limits permit no positive order size",
            regime=regime.regime,
            explanation=explanation,
        )
        return "NO_TRADE"

    signal = Signal(
        environment=environment,
        instrument=symbol,
        strategy_name=strategy.strategy,
        side="buy",
        status="SETUP",
        generated_at=now,
        expires_at=min(regime.expires_at, now + timedelta(minutes=5)),
        explanation={
            **explanation,
            "entry_conditions": strategy.entry_conditions,
            "invalidation": strategy.invalidation,
            "stop_price": stop,
            "target_price": target,
            "quantity": quantity,
            "risk_budget": equity * float(risk_config["max_risk_per_trade_pct"]),
            "news_blackout_active": False,
        },
    )
    db.add(signal)
    db.flush()
    intent = execute_order_intent(
        db,
        user_id=connection.user_id,
        request=OrderIntentRequest(
            environment=Environment.PAPER,
            symbol=symbol,
            side="buy",
            quantity=quantity,
            reference_price=entry,
            quote_timestamp=quote_time,
            stop_price=stop,
            target_price=target,
            signal_id=signal.id,
        ),
        fernet=fernet,
    )
    return "ORDER_SUBMITTED" if intent.status in {"accepted", "new", "pending_new"} else intent.status


def run_cycle(
    db: Session,
    *,
    fernet: Fernet,
    now: datetime | None = None,
    adapter_factory: Any = adapter_for_connection,
) -> dict[str, int]:
    """Run one conservative scan; only connected paper accounts with explicit automation are considered."""
    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    counters = {"accounts": 0, "symbols": 0, "setups": 0, "no_trade": 0, "failed": 0}
    connections = db.scalars(
        select(BrokerConnection).where(
            BrokerConnection.environment == "paper",
            BrokerConnection.disconnected_at.is_(None),
        )
    ).all()
    healthy = True
    for connection in connections:
        automation = db.scalar(
            select(AutomationState).where(
                AutomationState.user_id == connection.user_id,
                AutomationState.environment == "paper",
            )
        )
        kill = db.scalar(
            select(KillSwitchState).where(KillSwitchState.user_id == connection.user_id)
        )
        if not automation or not automation.enabled or (kill and kill.active):
            continue
        risk = db.scalar(
            select(RiskConfiguration).where(
                RiskConfiguration.user_id == connection.user_id,
                RiskConfiguration.environment == "paper",
            )
        )
        watchlist_config = db.scalar(
            select(StrategyConfig).where(
                StrategyConfig.environment == "paper",
                StrategyConfig.strategy_name == "watchlist",
                StrategyConfig.enabled.is_(True),
            )
        )
        if risk is None or not risk.complete or watchlist_config is None:
            healthy = False
            counters["failed"] += 1
            continue
        symbols = [str(item).upper() for item in watchlist_config.config_json.get("symbols", [])]
        if not symbols:
            healthy = False
            counters["failed"] += 1
            continue
        counters["accounts"] += 1
        try:
            adapter: BrokerAdapter = adapter_factory(connection, fernet)
            account = adapter.get_account()
            clock = adapter.get_market_clock()
            assets = {str(asset.get("symbol", "")).upper(): asset for asset in adapter.get_assets()}
            if (
                str(account.get("status", "")).upper() != "ACTIVE"
                or bool(account.get("trading_blocked", False))
            ):
                healthy = False
                counters["failed"] += 1
                continue
            if not bool(clock.get("is_open", False)):
                continue
            positions = adapter.get_positions()
            open_orders = adapter.get_open_orders()
            for symbol in symbols:
                counters["symbols"] += 1
                asset = assets.get(symbol)
                if asset is None:
                    _record_no_trade(
                        db,
                        environment="paper",
                        symbol=symbol,
                        now=reference_time,
                        reason="Instrument absent from Alpaca's active asset list",
                    )
                    counters["no_trade"] += 1
                    continue
                try:
                    status = _analyze_symbol(
                        db,
                        adapter=adapter,
                        connection=connection,
                        symbol=symbol,
                        asset=asset,
                        risk_config=risk.config_json,
                        now=reference_time,
                        account=account,
                        positions=positions,
                        open_orders=open_orders,
                        fernet=fernet,
                    )
                    if status == "ORDER_SUBMITTED":
                        counters["setups"] += 1
                    else:
                        counters["no_trade"] += 1
                except Exception as exc:
                    # Do not log provider exception text; SDK errors can include request details.
                    LOGGER.warning(
                        "symbol_scan_failed",
                        extra={"symbol": symbol, "error_type": type(exc).__name__},
                    )
                    _record_no_trade(
                        db,
                        environment="paper",
                        symbol=symbol,
                        now=reference_time,
                        reason="Analysis pipeline error; fail-closed",
                    )
                    counters["failed"] += 1
        except Exception as exc:
            LOGGER.warning(
                "paper_account_scan_failed",
                extra={"error_type": type(exc).__name__},
            )
            healthy = False
            counters["failed"] += 1
    db.add(
        SystemHealthEvent(
            component=WORKER_COMPONENT,
            status="HEALTHY" if healthy else "DEGRADED",
            message="Paper worker completed cycle" if healthy else "Paper worker cycle had a blocked dependency",
            environment="paper",
        )
    )
    record_audit(
        db,
        event_type="PAPER_WORKER_CYCLE",
        actor="paper-worker",
        environment="paper",
        payload={"counters": counters, "healthy": healthy},
    )
    db.commit()
    return counters


def _disarm_paper_automation_on_start(db: Session) -> None:
    active = db.scalars(
        select(AutomationState).where(
            AutomationState.environment == "paper", AutomationState.enabled.is_(True)
        )
    ).all()
    for automation in active:
        automation.enabled = False
        automation.enabled_at = None
        record_audit(
            db,
            event_type="PAPER_WORKER_RESTARTED_AUTOMATION_DISABLED",
            actor="paper-worker",
            environment="paper",
            payload={"automation_id": automation.id, "explicit_reenable_required": True},
        )
    connections = db.scalars(
        select(BrokerConnection).where(
            BrokerConnection.environment == "paper",
            BrokerConnection.disconnected_at.is_(None),
            BrokerConnection.automation_enabled.is_(True),
        )
    ).all()
    for connection in connections:
        connection.automation_enabled = False
    db.commit()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    settings: Settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    poll_seconds = max(30, int(os.getenv("WORKER_POLL_SECONDS", DEFAULT_POLL_SECONDS)))
    with session_factory() as db:
        _disarm_paper_automation_on_start(db)
    while True:
        try:
            with session_factory() as db:
                counters = run_cycle(db, fernet=settings.credential_fernet())
            LOGGER.info("paper_worker_cycle_complete", extra={"counters": counters})
        except Exception as exc:
            LOGGER.error("paper_worker_cycle_failed", extra={"error_type": type(exc).__name__})
            try:
                with session_factory() as db:
                    db.add(
                        SystemHealthEvent(
                            component=WORKER_COMPONENT,
                            status="UNHEALTHY",
                            message="Worker cycle failed before completing scan",
                            environment="paper",
                        )
                    )
                    db.commit()
            except Exception as health_exc:  # noqa: BLE001 - health write must never stop the loop
                LOGGER.error(
                    "paper_worker_health_write_failed", extra={"error_type": type(health_exc).__name__}
                )
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
