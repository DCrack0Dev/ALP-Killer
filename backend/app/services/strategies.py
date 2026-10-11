"""Independent strategy modules; outputs are auditable setups or NO_TRADE, never broker calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StrategySetup:
    strategy: str
    status: str
    side: str | None
    entry_conditions: list[str]
    invalidation: str | None
    stop_logic: str | None
    target_logic: str | None
    maximum_holding_time: str | None
    required_data_quality: str
    reasons: list[str]


class Strategy(Protocol):
    def evaluate(
        self,
        instrument: str,
        market_state: dict[str, Any],
        data: dict[str, Any],
        news_context: dict[str, Any],
        ml_score: dict[str, Any],
    ) -> StrategySetup: ...


class TrendContinuationStrategy:
    name = "swing_trend_continuation_v1"

    def evaluate(
        self,
        instrument: str,
        market_state: dict[str, Any],
        data: dict[str, Any],
        news_context: dict[str, Any],
        ml_score: dict[str, Any],
    ) -> StrategySetup:
        regime = market_state.get("regime")
        probability = float(ml_score.get("probability_favorable", 0))
        blocked = news_context.get("blocked", False)
        if regime not in {"SWING_TREND_LONG", "SWING_TREND_SHORT"} or probability < 0.55 or blocked:
            return StrategySetup(
                self.name,
                "NO_TRADE",
                None,
                [],
                None,
                None,
                None,
                None,
                "fresh bars, news, and score",
                ["Trend, ML, or news gate failed"],
            )
        side = "buy" if regime.endswith("LONG") else "sell"
        return StrategySetup(
            self.name,
            "SETUP",
            side,
            ["Trend confirmed", "ML threshold passed", "No news blackout"],
            "Trend invalidates below/above prior swing",
            "ATR-based protective stop",
            "2R target or trailing exit",
            "10 trading days",
            "fresh daily and intraday bars",
            [f"{instrument} {regime}"],
        )


class IntradayMomentumStrategy(TrendContinuationStrategy):
    name = "scalping_intraday_momentum_v1"

    def evaluate(
        self,
        instrument: str,
        market_state: dict[str, Any],
        data: dict[str, Any],
        news_context: dict[str, Any],
        ml_score: dict[str, Any],
    ) -> StrategySetup:
        if market_state.get("regime") not in {"SCALPING_TREND_LONG", "SCALPING_TREND_SHORT"}:
            return StrategySetup(
                self.name,
                "NO_TRADE",
                None,
                [],
                None,
                None,
                None,
                None,
                "fresh quote and liquidity data",
                ["No approved scalping regime"],
            )
        if (
            data.get("spread_bps", 999) > data.get("max_spread_bps", 0)
            or data.get("latency_ms", 99999) > 2000
        ):
            return StrategySetup(
                self.name,
                "NO_TRADE",
                None,
                [],
                None,
                None,
                None,
                None,
                "fresh quote, spread, latency data",
                ["Scalping cost or latency gate failed"],
            )
        result = super().evaluate(
            instrument,
            {
                **market_state,
                "regime": "SWING_TREND_LONG"
                if market_state["regime"].endswith("LONG")
                else "SWING_TREND_SHORT",
            },
            data,
            news_context,
            ml_score,
        )
        return StrategySetup(
            self.name,
            result.status,
            result.side,
            result.entry_conditions,
            result.invalidation,
            "tight ATR-based stop",
            "1-2R target",
            "minutes-hours",
            "fresh quote, spread, and liquidity data",
            result.reasons,
        )
