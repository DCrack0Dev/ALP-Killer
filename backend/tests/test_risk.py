from datetime import UTC, datetime, timedelta

from app.services.risk import Decision, RiskEngine, TradeContext

CONFIG = {
    "max_risk_per_trade_pct": 0.01,
    "stale_data_seconds": 30,
    "max_spread_bps": 10,
    "max_slippage_bps": 20,
    "min_liquidity_usd": 1_000,
    "max_position_notional": 10_000,
    "max_instrument_exposure": 15_000,
    "max_portfolio_exposure": 0.8,
    "max_open_positions": 5,
    "max_daily_loss": 500,
    "max_weekly_loss": 1_000,
    "max_drawdown_pct": 0.1,
    "max_order_frequency_per_hour": 10,
}


def context(**changes: object) -> TradeContext:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "environment": "paper",
        "verified_environment": "paper",
        "automation_enabled": True,
        "kill_switch_active": False,
        "reduce_only": False,
        "is_position_reduction": False,
        "data_timestamp": now,
        "now": now,
        "spread_bps": 2.0,
        "liquidity_usd": 100_000.0,
        "estimated_notional": 2_000.0,
        "instrument_exposure": 1_000.0,
        "portfolio_exposure_pct": 0.3,
        "open_positions": 1,
        "daily_loss": 0.0,
        "weekly_loss": 0.0,
        "drawdown_pct": 0.01,
        "orders_last_hour": 0,
        "duplicate_order": False,
        "news_blackout_active": False,
        "shorting_allowed": False,
        "is_short_sale": False,
        "latency_ms": 50.0,
        "estimated_risk_pct": 0.001,
        "estimated_slippage_bps": 1.0,
    }
    values.update(changes)
    return TradeContext(**values)  # type: ignore[arg-type]


def test_approves_only_when_every_gate_passes() -> None:
    result = RiskEngine.evaluate(CONFIG, context())
    assert result.decision == Decision.APPROVED


def test_kill_switch_beats_all_other_conditions() -> None:
    result = RiskEngine.evaluate(CONFIG, context(kill_switch_active=True, spread_bps=99))
    assert result.decision == Decision.KILL_SWITCHED
    assert result.reason_code == "KILL_SWITCH_ACTIVE"


def test_rejects_stale_data() -> None:
    result = RiskEngine.evaluate(
        CONFIG, context(data_timestamp=datetime.now(UTC) - timedelta(minutes=2))
    )
    assert result.decision == Decision.REJECTED
    assert result.reason_code == "STALE_DATA"


def test_rejects_environment_mismatch_before_order() -> None:
    result = RiskEngine.evaluate(CONFIG, context(environment="live", verified_environment="paper"))
    assert result.reason_code == "ENVIRONMENT_MISMATCH"


def test_reduce_only_blocks_new_entry() -> None:
    result = RiskEngine.evaluate(CONFIG, context(reduce_only=True, is_position_reduction=False))
    assert result.decision == Decision.PAUSED
    assert result.reason_code == "REDUCE_ONLY"


def test_short_without_borrow_eligibility_is_rejected() -> None:
    result = RiskEngine.evaluate(CONFIG, context(is_short_sale=True, shorting_allowed=False))
    assert result.reason_code == "SHORT_NOT_ALLOWED"


def test_excessive_per_trade_stop_risk_is_rejected() -> None:
    result = RiskEngine.evaluate(CONFIG, context(estimated_risk_pct=0.02))
    assert result.reason_code == "TRADE_RISK_LIMIT"


def test_excessive_executable_slippage_is_rejected() -> None:
    result = RiskEngine.evaluate(CONFIG, context(estimated_slippage_bps=25.0))
    assert result.reason_code == "SLIPPAGE_LIMIT"
