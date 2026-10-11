from datetime import UTC, datetime, timedelta

import pytest

from app.services.backtest import BacktestBar, BacktestError, run_event_backtest
from app.services.regime import MarketObservation, MarketRegimeRouter


def bars(count: int = 90) -> list[BacktestBar]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    result: list[BacktestBar] = []
    for index in range(count):
        close = 100 + index * 0.25 + (0.5 if index % 7 else -0.3)
        result.append(
            BacktestBar(
                start + timedelta(days=index),
                close - 0.1,
                close + 0.4,
                close - 0.4,
                close,
                10_000 + index * 100,
            )
        )
    return result


def test_backtest_uses_next_open_and_reports_cost_assumptions() -> None:
    result = run_event_backtest(
        bars(),
        initial_cash=100_000,
        commission_per_order=1,
        spread_bps=2,
        slippage_bps=3,
        latency_bars=1,
        fast_window=5,
        slow_window=20,
    )
    assert result["assumptions"]["execution"].startswith("next available open")
    assert "maximum_drawdown" in result["metrics"]
    assert result["metrics"]["fees"] >= 0


def test_backtest_rejects_unordered_time_series() -> None:
    bad = bars()
    bad[10] = BacktestBar(
        bad[9].timestamp, bad[10].open, bad[10].high, bad[10].low, bad[10].close, bad[10].volume
    )
    with pytest.raises(BacktestError, match="time-ordered"):
        run_event_backtest(
            bad,
            initial_cash=1_000,
            commission_per_order=0,
            spread_bps=0,
            slippage_bps=0,
            latency_bars=0,
            fast_window=5,
            slow_window=20,
        )


def test_regime_router_returns_no_trade_for_illiquid_quote() -> None:
    observation = MarketObservation(
        "AAPL", [100 + index for index in range(35)], [1_000] * 35, 50, 10, datetime.now(UTC)
    )
    result = MarketRegimeRouter().classify(observation)
    assert result.regime == "NO_TRADE"


def test_regime_router_flags_high_risk_event() -> None:
    observation = MarketObservation(
        "AAPL",
        [100 + index for index in range(35)],
        [1_000] * 35,
        2,
        100_000,
        datetime.now(UTC),
        high_risk_event=True,
    )
    result = MarketRegimeRouter().classify(observation)
    assert result.regime == "HIGH_RISK_EVENT"
