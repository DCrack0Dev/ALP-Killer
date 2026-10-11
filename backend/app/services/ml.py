"""Time-aware transparent ML baseline. Scores filter setups and never call a broker."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit


@dataclass(frozen=True)
class MLScoreResult:
    probability_favorable: float
    expected_return: float
    expected_volatility: float
    stop_probability: float
    expected_holding_period: str
    calibration_status: str
    model_version: str
    feature_timestamp: datetime


class TransparentMLBaseline:
    """Logistic-regression baseline for walk-forward research; fit only with time-ordered data."""

    version = "logistic-regression-v1"

    def __init__(self) -> None:
        self._model: CalibratedClassifierCV | None = None
        self._feature_count: int | None = None

    def fit(self, features: Sequence[Sequence[float]], labels: Sequence[int]) -> None:
        if len(features) < 100 or len(features) != len(labels):
            raise ValueError("At least 100 time-ordered labeled observations are required")
        array = np.asarray(features, dtype=float)
        if array.ndim != 2 or not np.isfinite(array).all():
            raise ValueError("Features must be a finite two-dimensional matrix")
        if len(set(labels)) < 2:
            raise ValueError("Labels must contain both outcome classes")
        base = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=7)
        # Each validation fold trains strictly on earlier samples; five rows are purged
        # at each boundary so a five-session forward label cannot overlap validation.
        ordered_cv = TimeSeriesSplit(n_splits=3, gap=5)
        self._model = CalibratedClassifierCV(
            base, method="sigmoid", cv=ordered_cv, ensemble=True
        )
        self._model.fit(array, np.asarray(labels, dtype=int))
        self._feature_count = array.shape[1]

    def score(
        self,
        feature_vector: Sequence[float],
        feature_timestamp: datetime,
        expected_return: float,
        expected_volatility: float,
    ) -> MLScoreResult:
        if self._model is None or self._feature_count is None:
            raise RuntimeError("Model has not been trained on a time-ordered training window")
        vector = np.asarray(feature_vector, dtype=float).reshape(1, -1)
        if vector.shape[1] != self._feature_count or not np.isfinite(vector).all():
            raise ValueError("Feature vector shape or values are invalid")
        favorable = float(self._model.predict_proba(vector)[0, 1])
        return MLScoreResult(
            probability_favorable=favorable,
            expected_return=expected_return,
            expected_volatility=expected_volatility,
            stop_probability=1 - favorable,
            expected_holding_period="strategy-defined",
            calibration_status="purged-time-series-sigmoid-calibrated",
            model_version=self.version,
            feature_timestamp=feature_timestamp,
        )
