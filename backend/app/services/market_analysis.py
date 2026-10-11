"""Leakage-aware feature construction for daily-bar walk-forward scoring."""

from __future__ import annotations

from dataclasses import dataclass
from math import log
from statistics import fmean, pstdev
from typing import Any


@dataclass(frozen=True)
class SupervisedMarketData:
    features: list[list[float]]
    labels: list[int]
    forward_returns: list[float]
    latest_features: list[float]
    expected_return: float
    expected_volatility: float


def build_supervised_market_data(
    bars: list[dict[str, Any]], *, horizon: int = 5
) -> SupervisedMarketData:
    """Use only bars at or before each feature timestamp; exclude unlabeled tail rows."""
    ordered = sorted(bars, key=lambda bar: str(bar.get("timestamp", "")))
    closes = [float(bar["close"]) for bar in ordered]
    volumes = [max(0.0, float(bar.get("volume", 0.0))) for bar in ordered]
    if any(not value > 0 for value in closes):
        raise ValueError("All market closes must be positive")
    if len(closes) < 100 + 30 + horizon:
        raise ValueError("At least 135 daily bars are required for time-ordered training")

    def feature_at(index: int) -> list[float]:
        sma10 = fmean(closes[index - 9 : index + 1])
        sma30 = fmean(closes[index - 29 : index + 1])
        daily_returns = [
            closes[j] / closes[j - 1] - 1 for j in range(index - 19, index + 1)
        ]
        average_volume = fmean(volumes[index - 19 : index + 1])
        volume_ratio_log = log((volumes[index] + 1.0) / (average_volume + 1.0))
        return [
            closes[index] / closes[index - 1] - 1,
            closes[index] / closes[index - 5] - 1,
            closes[index] / closes[index - 20] - 1,
            sma10 / sma30 - 1,
            pstdev(daily_returns),
            volume_ratio_log,
        ]

    features: list[list[float]] = []
    labels: list[int] = []
    forward_returns: list[float] = []
    # Labels at i are known only after horizon future bars; the last horizon samples are withheld.
    for index in range(30, len(closes) - horizon):
        forward_return = closes[index + horizon] / closes[index] - 1
        features.append(feature_at(index))
        forward_returns.append(forward_return)
        labels.append(int(forward_return > 0))
    latest_features = feature_at(len(closes) - 1)
    return SupervisedMarketData(
        features=features,
        labels=labels,
        forward_returns=forward_returns,
        latest_features=latest_features,
        expected_return=fmean(forward_returns),
        expected_volatility=pstdev(forward_returns),
    )


def average_true_range(bars: list[dict[str, Any]], period: int = 14) -> float:
    ordered = sorted(bars, key=lambda bar: str(bar.get("timestamp", "")))
    if len(ordered) < period + 1:
        raise ValueError("Insufficient bars to calculate average true range")
    ranges: list[float] = []
    for index in range(len(ordered) - period, len(ordered)):
        high = float(ordered[index]["high"])
        low = float(ordered[index]["low"])
        previous_close = float(ordered[index - 1]["close"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = fmean(ranges)
    if atr <= 0:
        raise ValueError("Average true range is invalid")
    return atr
