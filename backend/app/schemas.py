"""Pydantic contracts. Secrets are input-only SecretStr fields and never response fields."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Environment(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    VALIDATING = "VALIDATING"
    CONNECTED_PAPER = "CONNECTED_PAPER"
    CONNECTED_LIVE = "CONNECTED_LIVE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SUSPENDED = "SUSPENDED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"


class UnlockRequest(BaseModel):
    passphrase: SecretStr = Field(min_length=8, max_length=512)


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class ConnectionValidateRequest(BaseModel):
    requested_environment: Environment | None = None
    api_key: SecretStr = Field(min_length=4, max_length=256)
    api_secret: SecretStr = Field(min_length=8, max_length=512)


class AccountSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    broker: str = "alpaca"
    environment: Environment
    account_id_masked: str
    account_status: str
    trading_blocked: bool
    automation_enabled: bool
    verified_at: datetime
    equity: str | None = None
    buying_power: str | None = None
    cash: str | None = None
    daily_pnl: str | None = None
    drawdown: str | None = None
    open_positions: int | None = None
    last_updated: datetime | None = None


class ConnectionResponse(AccountSummary):
    state: ConnectionState


class RiskConfigInput(BaseModel):
    max_risk_per_trade_pct: float = Field(gt=0, le=0.05)
    max_position_notional: float = Field(gt=0)
    max_instrument_exposure: float = Field(gt=0)
    max_portfolio_exposure: float = Field(gt=0, le=1.0)
    max_open_positions: int = Field(gt=0, le=100)
    max_daily_loss: float = Field(gt=0)
    max_weekly_loss: float = Field(gt=0)
    max_drawdown_pct: float = Field(gt=0, le=1.0)
    max_order_frequency_per_hour: int = Field(gt=0, le=500)
    max_slippage_bps: float = Field(gt=0, le=500)
    max_spread_bps: float = Field(gt=0, le=500)
    min_liquidity_usd: float = Field(gt=0)
    stale_data_seconds: int = Field(gt=0, le=3600)
    news_blackout_minutes: int = Field(ge=0, le=1440)
    reduce_only: bool = False


class RiskConfigResponse(BaseModel):
    environment: Environment
    complete: bool
    config: RiskConfigInput | None
    configuration_fingerprint: str | None


class LiveEnableRequest(BaseModel):
    confirmation: str = Field(pattern="^I_UNDERSTAND_LIVE_TRADING$")
    configuration_fingerprint: str = Field(min_length=32, max_length=128)


class AutomationResponse(BaseModel):
    environment: Environment
    enabled: bool
    reduce_only: bool
    kill_switch_active: bool
    message: str


class KillSwitchRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class Bar(BaseModel):
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @field_validator("high")
    @classmethod
    def high_must_not_be_zero(cls, value: float) -> float:
        return value


class BacktestRequest(BaseModel):
    symbol: str = Field(pattern="^[A-Za-z0-9./-]{1,20}$")
    bars: list[Bar] = Field(min_length=30, max_length=50000)
    initial_cash: float = Field(default=100000, gt=0)
    commission_per_order: float = Field(default=0, ge=0)
    spread_bps: float = Field(default=2, ge=0, le=1000)
    slippage_bps: float = Field(default=3, ge=0, le=1000)
    latency_bars: int = Field(default=1, ge=0, le=10)
    fast_window: int = Field(default=10, ge=2, le=200)
    slow_window: int = Field(default=30, ge=3, le=500)


class BacktestResponse(BaseModel):
    id: str
    status: str
    metrics: dict[str, Any]
    assumptions: dict[str, Any]


class OrderIntentRequest(BaseModel):
    environment: Environment
    symbol: str = Field(pattern="^[A-Za-z0-9./-]{1,20}$")
    side: str = Field(pattern="^(buy|sell)$")
    quantity: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    quote_timestamp: datetime
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    signal_id: str = Field(min_length=1, max_length=36)


class OrderIntentResponse(BaseModel):
    intent_id: str
    status: str
    client_order_id: str
    message: str


class RegimeSnapshot(BaseModel):
    instrument: str
    regime: str
    direction: str
    confidence: float
    time_horizon: str
    features_used: list[str]
    reasons: list[str]
    contradictions: list[str]
    data_timestamp: datetime
    expires_at: datetime


class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: datetime
    automation_available: bool
