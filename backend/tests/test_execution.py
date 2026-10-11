from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.db import create_database_engine, create_session_factory, initialize_database
from app.models import (
    AutomationState,
    BrokerConnection,
    BrokerOrder,
    KillSwitchState,
    OrderIntent,
    RiskConfiguration,
    RiskDecision,
    Signal,
    User,
)
from app.schemas import Environment, OrderIntentRequest
from app.services import execution

RISK_CONFIG = {
    "max_risk_per_trade_pct": 0.005,
    "max_position_notional": 5000,
    "max_instrument_exposure": 7000,
    "max_portfolio_exposure": 0.8,
    "max_open_positions": 5,
    "max_daily_loss": 500,
    "max_weekly_loss": 1000,
    "max_drawdown_pct": 0.1,
    "max_order_frequency_per_hour": 10,
    "max_slippage_bps": 25,
    "max_spread_bps": 10,
    "min_liquidity_usd": 5000,
    "stale_data_seconds": 30,
    "news_blackout_minutes": 30,
    "reduce_only": False,
}


class FakeAdapter:
    def __init__(self, quote: dict[str, object] | None = None) -> None:
        self.quote = quote
        self.submitted: list[tuple[str, str, float, str]] = []

    def get_quotes(self, _symbols: list[str]) -> dict[str, dict[str, object]]:
        return {"AAPL": self.quote} if self.quote is not None else {}

    def get_account(self) -> dict[str, object]:
        return {"equity": "50000.00"}

    def get_positions(self) -> list[dict[str, object]]:
        return []

    def submit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
        stop_price: float | None = None,
        target_price: float | None = None,
    ) -> dict[str, str]:
        assert stop_price is not None and target_price is not None
        self.submitted.append((symbol, side, quantity, client_order_id))
        return {"id": "paper-order-1", "status": "accepted"}

    def get_order_by_client_id(self, _client_order_id: str) -> None:
        return None


def setup_session(tmp_path: Path, environment: str = "paper"):
    engine = create_database_engine(f"sqlite:///{tmp_path / f'{environment}.db'}")
    initialize_database(engine)
    db = create_session_factory(engine)()
    user = User(username="owner")
    db.add(user)
    db.flush()
    db.add(
        BrokerConnection(
            user_id=user.id,
            broker="alpaca",
            environment=environment,
            account_id_masked="****1234",
            account_status="ACTIVE",
            trading_blocked=False,
            automation_enabled=True,
            encrypted_api_key="encrypted-key",
            encrypted_api_secret="encrypted-secret",
            verified_at=datetime.now(UTC),
        )
    )
    db.add(
        RiskConfiguration(
            user_id=user.id,
            environment=environment,
            config_json=RISK_CONFIG,
            complete=True,
        )
    )
    db.add(AutomationState(user_id=user.id, environment=environment, enabled=True))
    db.add(KillSwitchState(user_id=user.id, active=False))
    db.commit()
    return db, user.id


def add_setup_signal(db, signal_id: str, environment: str = "paper") -> None:
    now = datetime.now(UTC)
    db.add(
        Signal(
            id=signal_id,
            environment=environment,
            instrument="AAPL",
            strategy_name="swing_trend_continuation_v1",
            side="buy",
            status="SETUP",
            generated_at=now,
            expires_at=now + timedelta(minutes=5),
            explanation={"news_blackout_active": False},
        )
    )
    db.commit()


def make_request(**changes: object) -> OrderIntentRequest:
    values: dict[str, object] = {
        "environment": Environment.PAPER,
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 10,
        "reference_price": 100.02,
        "quote_timestamp": datetime(2000, 1, 1, tzinfo=UTC),
        "stop_price": 98,
        "target_price": 104.06,
        "signal_id": "signal-1",
    }
    values.update(changes)
    return OrderIntentRequest(**values)


def settings() -> Settings:
    return Settings(
        app_env="test",
        jwt_secret="test-jwt-secret-with-at-least-thirty-two-characters",
        bootstrap_passphrase="test-passphrase-with-at-least-sixteen-characters",
    )


def test_execution_uses_current_broker_quote_not_client_market_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    db, user_id = setup_session(tmp_path)
    add_setup_signal(db, "signal-1")
    adapter = FakeAdapter(
        {
            "bid_price": 100.00,
            "ask_price": 100.02,
            "bid_size": 1000,
            "ask_size": 1000,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    monkeypatch.setattr(execution, "adapter_for_connection", lambda *_args: adapter)

    intent = execution.execute_order_intent(
        db,
        user_id=user_id,
        request=make_request(),
        fernet=settings().credential_fernet(),
    )
    db.commit()

    assert intent.status == "accepted"
    assert len(adapter.submitted) == 1
    assert adapter.submitted[0][0:3] == ("AAPL", "buy", 10)
    stored = db.scalar(select(OrderIntent).where(OrderIntent.id == intent.id))
    assert stored is not None
    assert stored.payload_json["executable_price"] == 100.02
    assert stored.payload_json["spread_bps"] < 3
    assert stored.payload_json["liquidity_usd"] > 200_000
    assert (
        db.scalar(select(BrokerOrder).where(BrokerOrder.order_intent_id == intent.id)) is not None
    )
    risk_decision = db.scalar(select(RiskDecision).where(RiskDecision.order_intent_id == intent.id))
    assert risk_decision is not None
    assert risk_decision.decision == "APPROVED"
    db.close()


def test_excessive_stop_risk_prevents_order_submission(tmp_path: Path, monkeypatch) -> None:
    db, user_id = setup_session(tmp_path)
    add_setup_signal(db, "too-risky")
    adapter = FakeAdapter(
        {
            "bid_price": 100.00,
            "ask_price": 100.02,
            "bid_size": 1000,
            "ask_size": 1000,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    monkeypatch.setattr(execution, "adapter_for_connection", lambda *_args: adapter)

    intent = execution.execute_order_intent(
        db,
        user_id=user_id,
        request=make_request(quantity=150, signal_id="too-risky"),
        fernet=settings().credential_fernet(),
    )
    db.commit()

    assert intent.status == "RISK_REJECTED"
    assert adapter.submitted == []
    decision = db.scalar(select(RiskDecision).where(RiskDecision.order_intent_id == intent.id))
    assert decision is not None
    assert decision.reason_code == "TRADE_RISK_LIMIT"
    db.close()


def test_missing_authoritative_quote_fails_closed(tmp_path: Path, monkeypatch) -> None:
    db, user_id = setup_session(tmp_path)
    add_setup_signal(db, "missing-quote")
    adapter = FakeAdapter(quote=None)
    monkeypatch.setattr(execution, "adapter_for_connection", lambda *_args: adapter)

    intent = execution.execute_order_intent(
        db,
        user_id=user_id,
        request=make_request(signal_id="missing-quote"),
        fernet=settings().credential_fernet(),
    )
    db.commit()

    assert intent.status == "PAUSED"
    assert adapter.submitted == []
    decision = db.scalar(select(RiskDecision).where(RiskDecision.order_intent_id == intent.id))
    assert decision is not None
    assert decision.reason_code == "BROKER_QUOTE_MISSING"
    db.close()


def test_live_order_is_blocked_before_adapter_access_even_with_live_connection(
    tmp_path: Path, monkeypatch
) -> None:
    db, user_id = setup_session(tmp_path, environment="live")
    called = False

    def adapter_must_not_be_created(*_args):
        nonlocal called
        called = True
        raise AssertionError("Live routing must stop before creating an adapter")

    monkeypatch.setattr(execution, "adapter_for_connection", adapter_must_not_be_created)
    request = make_request(environment=Environment.LIVE, signal_id="live-never")

    intent = execution.execute_order_intent(
        db,
        user_id=user_id,
        request=request,
        fernet=settings().credential_fernet(),
        allow_live_trading=False,
    )
    db.commit()

    assert intent.status == "PAUSED"
    assert called is False
    decision = db.scalar(select(RiskDecision).where(RiskDecision.order_intent_id == intent.id))
    assert decision is not None
    assert decision.reason_code == "LIVE_DISABLED_BY_DEPLOYMENT"
    db.close()
