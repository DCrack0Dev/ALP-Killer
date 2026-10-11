"""Deterministic, testable pre-trade risk engine shared by backtest, paper, and live paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAUSED = "PAUSED"
    KILL_SWITCHED = "KILL_SWITCHED"


@dataclass(frozen=True)
class RiskResult:
    decision: Decision
    reason_code: str
    reason: str
    details: dict[str, Any]


@dataclass(frozen=True)
class TradeContext:
    environment: str
    verified_environment: str
    automation_enabled: bool
    kill_switch_active: bool
    reduce_only: bool
    is_position_reduction: bool
    data_timestamp: datetime
    now: datetime
    spread_bps: float
    liquidity_usd: float
    estimated_notional: float
    instrument_exposure: float
    portfolio_exposure_pct: float
    open_positions: int
    daily_loss: float
    weekly_loss: float
    drawdown_pct: float
    orders_last_hour: int
    duplicate_order: bool
    news_blackout_active: bool
    shorting_allowed: bool
    is_short_sale: bool
    latency_ms: float
    estimated_risk_pct: float
    estimated_slippage_bps: float


class RiskEngine:
    """Hard gates; no ML, news, or strategy code can bypass these checks."""

    @staticmethod
    def evaluate(config: dict[str, Any], context: TradeContext) -> RiskResult:
        def reject(code: str, reason: str, **details: Any) -> RiskResult:
            return RiskResult(Decision.REJECTED, code, reason, details)

        if context.kill_switch_active:
            return RiskResult(
                Decision.KILL_SWITCHED, "KILL_SWITCH_ACTIVE", "Emergency kill switch is active", {}
            )
        if context.environment not in {"paper", "live"}:
            return reject(
                "INVALID_EXECUTION_MODE",
                "Only verified paper or live modes may submit broker orders",
            )
        if context.environment != context.verified_environment:
            return reject(
                "ENVIRONMENT_MISMATCH",
                "Requested mode does not match the server-verified broker environment",
            )
        if not context.automation_enabled:
            return RiskResult(
                Decision.PAUSED,
                "AUTOMATION_DISABLED",
                "Automation is disabled for this environment",
                {},
            )
        if context.reduce_only and not context.is_position_reduction:
            return RiskResult(
                Decision.PAUSED, "REDUCE_ONLY", "Only position-reducing orders are permitted", {}
            )
        age_seconds = (context.now - context.data_timestamp).total_seconds()
        if age_seconds < 0 or age_seconds > config["stale_data_seconds"]:
            return reject(
                "STALE_DATA",
                "Market data is stale or has an invalid timestamp",
                age_seconds=age_seconds,
            )
        if context.spread_bps > config["max_spread_bps"]:
            return reject(
                "SPREAD_LIMIT",
                "Quoted spread exceeds the configured maximum",
                spread_bps=context.spread_bps,
            )
        if context.liquidity_usd < config["min_liquidity_usd"]:
            return reject("LIQUIDITY_LIMIT", "Available liquidity is below the configured minimum")
        if not context.is_position_reduction and context.estimated_risk_pct > config["max_risk_per_trade_pct"]:
            return reject(
                "TRADE_RISK_LIMIT",
                "Estimated loss at the protective stop exceeds the configured risk per trade",
                estimated_risk_pct=context.estimated_risk_pct,
            )
        if context.estimated_slippage_bps > config["max_slippage_bps"]:
            return reject(
                "SLIPPAGE_LIMIT",
                "Current executable price differs from the reference beyond the configured slippage limit",
                slippage_bps=context.estimated_slippage_bps,
            )
        if not context.is_position_reduction and context.estimated_notional > config["max_position_notional"]:
            return reject(
                "POSITION_NOTIONAL_LIMIT", "Order notional exceeds the maximum position notional"
            )
        if not context.is_position_reduction and (
            context.instrument_exposure + context.estimated_notional
            > config["max_instrument_exposure"]
        ):
            return reject(
                "INSTRUMENT_EXPOSURE_LIMIT", "Instrument exposure limit would be exceeded"
            )
        if not context.is_position_reduction and context.portfolio_exposure_pct > config["max_portfolio_exposure"]:
            return reject("PORTFOLIO_EXPOSURE_LIMIT", "Portfolio exposure limit would be exceeded")
        if (
            context.open_positions >= config["max_open_positions"]
            and not context.is_position_reduction
        ):
            return reject("OPEN_POSITION_LIMIT", "Maximum number of open positions reached")
        if context.daily_loss >= config["max_daily_loss"]:
            return RiskResult(Decision.PAUSED, "DAILY_LOSS_LIMIT", "Daily loss limit reached", {})
        if context.weekly_loss >= config["max_weekly_loss"]:
            return RiskResult(Decision.PAUSED, "WEEKLY_LOSS_LIMIT", "Weekly loss limit reached", {})
        if context.drawdown_pct >= config["max_drawdown_pct"]:
            return RiskResult(
                Decision.PAUSED, "DRAWDOWN_LIMIT", "Maximum drawdown response is active", {}
            )
        if context.orders_last_hour >= config["max_order_frequency_per_hour"]:
            return reject("ORDER_FREQUENCY_LIMIT", "Maximum order frequency reached")
        if context.news_blackout_active:
            return reject("NEWS_BLACKOUT", "News blackout window is active")
        if context.duplicate_order:
            return reject("DUPLICATE_ORDER", "Duplicate order intent detected")
        if context.is_short_sale and not context.shorting_allowed:
            return reject(
                "SHORT_NOT_ALLOWED", "Short selling or borrowing eligibility is not verified"
            )
        if context.latency_ms > 2000:
            return reject("LATENCY_LIMIT", "Execution latency is unsuitable for automated entry")
        return RiskResult(
            Decision.APPROVED, "ALL_GATES_PASSED", "All pre-trade risk gates passed", {}
        )


def utcnow() -> datetime:
    return datetime.now(UTC)
