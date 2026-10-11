"""Auditable rule-based market-regime router with hysteresis-oriented output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean


@dataclass(frozen=True)
class MarketObservation:
    instrument: str
    closes: list[float]
    volumes: list[float]
    spread_bps: float
    liquidity_usd: float
    data_timestamp: datetime
    high_risk_event: bool = False
    prior_regime: str | None = None


@dataclass(frozen=True)
class RegimeResult:
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


class MarketRegimeRouter:
    """Classifies conditions but never submits orders or overrides risk controls."""

    def classify(self, observation: MarketObservation) -> RegimeResult:
        now = datetime.now(UTC)
        features = ["close_series", "volume_series", "spread_bps", "liquidity_usd", "event_risk"]
        if len(observation.closes) < 30 or len(observation.volumes) < 20:
            return self._result(
                observation,
                "INSUFFICIENT_DATA",
                "flat",
                0.0,
                "none",
                features,
                ["Insufficient bars"],
                [],
            )
        if (now - observation.data_timestamp).total_seconds() > 120:
            return self._result(
                observation, "NO_TRADE", "flat", 0.0, "none", features, ["Market data is stale"], []
            )
        if observation.high_risk_event:
            return self._result(
                observation,
                "HIGH_RISK_EVENT",
                "flat",
                0.9,
                "none",
                features,
                ["High-impact event blackout"],
                [],
            )
        if observation.spread_bps > 25 or observation.liquidity_usd < 50_000:
            return self._result(
                observation,
                "NO_TRADE",
                "flat",
                0.85,
                "none",
                features,
                ["Spread or liquidity unsuitable"],
                [],
            )
        fast = mean(observation.closes[-10:])
        slow = mean(observation.closes[-30:])
        recent_change = (observation.closes[-1] / observation.closes[-6]) - 1
        volume_ratio = observation.volumes[-1] / max(mean(observation.volumes[-20:]), 1)
        direction = "long" if fast > slow else "short" if fast < slow else "flat"
        trend_strength = abs(fast / slow - 1)
        contradictions: list[str] = []
        if (
            observation.prior_regime
            and observation.prior_regime.startswith("SCALPING")
            and trend_strength < 0.001
        ):
            return self._result(
                observation,
                "REGIME_TRANSITION",
                "flat",
                0.4,
                "none",
                features,
                ["Hysteresis cooldown required"],
                [],
            )
        if trend_strength < 0.0015:
            return self._result(
                observation,
                "RANGE_BOUND",
                "flat",
                0.55,
                "intraday",
                features,
                ["Moving averages converged"],
                [],
            )
        if volume_ratio < 0.7:
            contradictions.append("Volume confirmation is weak")
        if abs(recent_change) > 0.01 and volume_ratio > 1.2:
            regime = "SCALPING_TREND_LONG" if direction == "long" else "SCALPING_TREND_SHORT"
            horizon = "minutes-hours"
        else:
            regime = "SWING_TREND_LONG" if direction == "long" else "SWING_TREND_SHORT"
            horizon = "1-10 days"
        confidence = min(0.95, 0.5 + trend_strength * 50 + min(volume_ratio, 2) * 0.1)
        return self._result(
            observation,
            regime,
            direction,
            confidence,
            horizon,
            features,
            ["Trend and momentum aligned"],
            contradictions,
        )

    @staticmethod
    def _result(
        observation: MarketObservation,
        regime: str,
        direction: str,
        confidence: float,
        horizon: str,
        features: list[str],
        reasons: list[str],
        contradictions: list[str],
    ) -> RegimeResult:
        return RegimeResult(
            instrument=observation.instrument,
            regime=regime,
            direction=direction,
            confidence=round(confidence, 4),
            time_horizon=horizon,
            features_used=features,
            reasons=reasons,
            contradictions=contradictions,
            data_timestamp=observation.data_timestamp,
            expires_at=observation.data_timestamp + timedelta(minutes=5),
        )
