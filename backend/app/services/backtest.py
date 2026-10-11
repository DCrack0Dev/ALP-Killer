"""A small event-driven MA crossover backtester with explicit execution assumptions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import mean, pstdev
from typing import Any


@dataclass(frozen=True)
class BacktestBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BacktestError(ValueError):
    pass


def run_event_backtest(
    bars: Sequence[BacktestBar],
    *,
    initial_cash: float,
    commission_per_order: float,
    spread_bps: float,
    slippage_bps: float,
    latency_bars: int,
    fast_window: int,
    slow_window: int,
) -> dict[str, Any]:
    """Execute chronologically; a signal at t is filled no earlier than t + latency_bars."""
    if fast_window >= slow_window:
        raise BacktestError("fast_window must be smaller than slow_window")
    if len(bars) <= slow_window + latency_bars + 2:
        raise BacktestError("Not enough bars for the requested windows and latency")
    if any(bars[index].timestamp >= bars[index + 1].timestamp for index in range(len(bars) - 1)):
        raise BacktestError("Bars must be strictly time-ordered")

    cash = initial_cash
    shares = 0.0
    entry_cost = 0.0
    equity_curve: list[float] = []
    trades: list[dict[str, float]] = []
    total_fees = 0.0
    total_slippage = 0.0
    half_cost_bps = (spread_bps / 2) + slippage_bps

    def execution_price(price: float, side: str) -> float:
        factor = half_cost_bps / 10_000
        return price * (1 + factor if side == "buy" else 1 - factor)

    for signal_index in range(slow_window, len(bars) - latency_bars):
        fill_index = signal_index + latency_bars
        closes = [bar.close for bar in bars[: signal_index + 1]]
        fast = mean(closes[-fast_window:])
        slow = mean(closes[-slow_window:])
        prior_fast = mean(closes[-fast_window - 1 : -1])
        prior_slow = mean(closes[-slow_window - 1 : -1])
        buy_signal = prior_fast <= prior_slow and fast > slow
        sell_signal = shares > 0 and prior_fast >= prior_slow and fast < slow
        fill_open = bars[fill_index].open
        if buy_signal and shares == 0:
            price = execution_price(fill_open, "buy")
            quantity = max(0.0, (cash - commission_per_order) / price)
            if quantity > 0:
                trade_value = quantity * price
                cash -= trade_value + commission_per_order
                shares = quantity
                entry_cost = trade_value + commission_per_order
                total_fees += commission_per_order
                total_slippage += quantity * fill_open * (half_cost_bps / 10_000)
                trades.append({"side": 1.0, "price": price, "quantity": quantity})
        elif sell_signal:
            price = execution_price(fill_open, "sell")
            proceeds = shares * price - commission_per_order
            total_fees += commission_per_order
            total_slippage += shares * fill_open * (half_cost_bps / 10_000)
            trades.append(
                {"side": -1.0, "price": price, "quantity": shares, "pnl": proceeds - entry_cost}
            )
            cash += proceeds
            shares = 0.0
            entry_cost = 0.0
        equity_curve.append(cash + shares * bars[fill_index].close)

    if shares > 0:
        exit_price = execution_price(bars[-1].close, "sell")
        proceeds = shares * exit_price - commission_per_order
        total_fees += commission_per_order
        total_slippage += shares * bars[-1].close * (half_cost_bps / 10_000)
        trades.append(
            {"side": -1.0, "price": exit_price, "quantity": shares, "pnl": proceeds - entry_cost}
        )
        cash += proceeds
        equity_curve.append(cash)

    if not equity_curve:
        equity_curve = [initial_cash]
    returns = [
        equity_curve[index] / equity_curve[index - 1] - 1 for index in range(1, len(equity_curve))
    ]
    high_water = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        high_water = max(high_water, equity)
        max_drawdown = max(max_drawdown, 1 - equity / high_water if high_water else 0)
    closed = [trade["pnl"] for trade in trades if "pnl" in trade]
    gains = sum(max(0, result) for result in closed)
    losses = abs(sum(min(0, result) for result in closed))
    mean_return = mean(returns) if returns else 0.0
    volatility = pstdev(returns) if len(returns) > 1 else 0.0
    downside = [min(0, result) for result in returns]
    downside_deviation = sqrt(mean([value * value for value in downside])) if downside else 0.0
    annualizer = sqrt(252)
    metrics = {
        "total_return": cash / initial_cash - 1,
        "annualized_return": (cash / initial_cash) ** (252 / max(len(returns), 1)) - 1,
        "maximum_drawdown": max_drawdown,
        "sharpe": (mean_return / volatility * annualizer) if volatility else 0.0,
        "sortino": (mean_return / downside_deviation * annualizer) if downside_deviation else 0.0,
        "win_rate": (sum(1 for result in closed if result > 0) / len(closed)) if closed else 0.0,
        "profit_factor": (gains / losses) if losses else None,
        "average_win": (gains / sum(1 for result in closed if result > 0)) if gains else 0.0,
        "average_loss": (losses / sum(1 for result in closed if result < 0)) if losses else 0.0,
        "turnover": sum(trade["price"] * trade["quantity"] for trade in trades) / initial_cash,
        "fees": total_fees,
        "estimated_spread_and_slippage": total_slippage,
        "number_of_trades": len(closed),
        "final_equity": cash,
        "exposure": sum(1 for value in equity_curve if value != cash) / len(equity_curve),
    }
    assumptions = {
        "execution": "next available open after configured latency; no candle-close fills",
        "commission_per_order": commission_per_order,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "latency_bars": latency_bars,
        "limitations": [
            "No guarantee of live performance",
            "Does not model exchange queue position, market impact, borrow availability, or halts",
            "Historical bars must be point-in-time and adjusted consistently",
        ],
    }
    return {"metrics": metrics, "assumptions": assumptions, "trades": trades}
