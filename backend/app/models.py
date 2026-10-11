"""Persistent records. All trading-affecting records carry server timestamps and environment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(Timestamped, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    username: Mapped[str] = mapped_column(String(128), unique=True, default="owner", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BrokerConnection(Timestamped, Base):
    __tablename__ = "broker_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(32), default="alpaca", nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    account_id_masked: Mapped[str] = mapped_column(String(64), nullable=False)
    account_status: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("user_id", "broker", "environment", name="uq_connection_environment"),
    )


class AccountEnvironment(Timestamped, Base):
    __tablename__ = "account_environments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("broker_connections.id"), nullable=False, index=True
    )
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    server_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    account_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Instrument(Timestamped, Base):
    __tablename__ = "instruments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    asset_class: Mapped[str] = mapped_column(String(32), default="us_equity", nullable=False)
    tradable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fractionable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shortable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MarketDataMetadata(Timestamped, Base):
    __tablename__ = "market_data_metadata"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    data_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    quality: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)


class MarketRegime(Timestamped, Base):
    __tablename__ = "market_regimes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    regime: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    data_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class StrategyConfig(Timestamped, Base):
    __tablename__ = "strategy_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class NewsEvent(Timestamped, Base):
    __tablename__ = "news_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    affected_instruments: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), nullable=False)
    impact: Mapped[str] = mapped_column(String(16), nullable=False)
    duplicate_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class MLModelVersion(Timestamped, Base):
    __tablename__ = "ml_model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    training_range: Mapped[str] = mapped_column(String(128), nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MLScore(Timestamped, Base):
    __tablename__ = "ml_scores"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("ml_model_versions.id"), nullable=False
    )
    probability_favorable: Mapped[float] = mapped_column(Float, nullable=False)
    expected_return: Mapped[float] = mapped_column(Float, nullable=False)
    expected_volatility: Mapped[float] = mapped_column(Float, nullable=False)
    stop_probability: Mapped[float] = mapped_column(Float, nullable=False)
    feature_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Signal(Timestamped, Base):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class RiskConfiguration(Timestamped, Base):
    __tablename__ = "risk_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "environment", name="uq_risk_environment"),)


class RiskDecision(Timestamped, Base):
    __tablename__ = "risk_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    order_intent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class OrderIntent(Timestamped, Base):
    __tablename__ = "order_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_notional: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    client_order_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class BrokerOrder(Timestamped, Base):
    __tablename__ = "broker_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    order_intent_id: Mapped[str] = mapped_column(
        ForeignKey("order_intents.id"), nullable=False, index=True
    )
    broker_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    broker_status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_status_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Fill(Timestamped, Base):
    __tablename__ = "fills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    broker_order_id: Mapped[str] = mapped_column(
        ForeignKey("broker_orders.id"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PositionSnapshot(Timestamped, Base):
    __tablename__ = "position_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class PnLSnapshot(Timestamped, Base):
    __tablename__ = "pnl_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    daily_pnl: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AuditEvent(Timestamped, Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class SystemHealthEvent(Timestamped, Base):
    __tablename__ = "system_health_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str | None] = mapped_column(String(16), nullable=True)


class KillSwitchState(Timestamped, Base):
    __tablename__ = "kill_switch_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AutomationState(Timestamped, Base):
    __tablename__ = "automation_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "environment", name="uq_automation_environment"),)


class BacktestRun(Timestamped, Base):
    __tablename__ = "backtest_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(16), default="backtest", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
