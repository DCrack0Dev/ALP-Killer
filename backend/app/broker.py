"""Broker-neutral Alpaca adapter using only the official alpaca-py SDK."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest, StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus, OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetAssetsRequest,
    GetOrdersRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"


class BrokerError(RuntimeError):
    """Safe broker failure that never includes credentials."""


class EnvironmentMismatchError(BrokerError):
    pass


@dataclass(frozen=True)
class VerifiedAccount:
    environment: str
    account_id: str
    account_status: str
    trading_blocked: bool


class BrokerAdapter(Protocol):
    def get_account(self) -> dict[str, Any]: ...
    def get_assets(self) -> list[dict[str, Any]]: ...
    def get_positions(self) -> list[dict[str, Any]]: ...
    def get_open_orders(self) -> list[dict[str, Any]]: ...
    def get_quotes(self, symbols: list[str]) -> dict[str, Any]: ...
    def get_daily_bars(self, symbol: str, start: datetime, limit: int = 1000) -> list[dict[str, Any]]: ...
    def get_market_clock(self) -> dict[str, Any]: ...
    def get_news(self, symbols: list[str], since: datetime) -> list[dict[str, Any]]: ...
    def submit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
        stop_price: float | None = None,
        target_price: float | None = None,
    ) -> dict[str, Any]: ...
    def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None: ...
    def cancel_order(self, broker_order_id: str) -> None: ...


def _model_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return value
    return {key: item for key, item in vars(value).items() if not key.startswith("_")}


class AlpacaAdapter:
    """Production adapter with explicit environment. It never switches endpoint implicitly."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        environment: str,
        client_factory: Callable[..., TradingClient] = TradingClient,
        data_client_factory: Callable[..., StockHistoricalDataClient] = StockHistoricalDataClient,
        news_client_factory: Callable[..., NewsClient] = NewsClient,
    ) -> None:
        if environment not in {"paper", "live"}:
            raise ValueError("environment must be paper or live")
        self.environment = environment
        self._client = client_factory(api_key, api_secret, paper=environment == "paper")
        self._data_client = data_client_factory(api_key, api_secret)
        self._news_client = news_client_factory(api_key, api_secret)

    @staticmethod
    def validate_credentials(
        api_key: str,
        api_secret: str,
        requested_environment: str | None = None,
        client_factory: Callable[..., TradingClient] = TradingClient,
    ) -> VerifiedAccount:
        """Probe both official trading environments; the successful account determines mode."""
        if requested_environment not in {None, "paper", "live"}:
            raise BrokerError("A broker connection must target paper, live, or auto-detect")
        successes: list[VerifiedAccount] = []
        for environment in ("paper", "live"):
            try:
                client = client_factory(api_key, api_secret, paper=environment == "paper")
                account = client.get_account()
                account_id = str(getattr(account, "id", ""))
                if not account_id:
                    raise BrokerError("Account response did not contain an identifier")
                successes.append(
                    VerifiedAccount(
                        environment=environment,
                        account_id=account_id,
                        account_status=str(getattr(account, "status", "UNKNOWN")),
                        trading_blocked=bool(getattr(account, "trading_blocked", False)),
                    )
                )
            except Exception:  # SDK transport/auth exceptions are intentionally normalized.
                continue
        if not successes:
            raise BrokerError(
                "Credentials could not be verified with Alpaca paper or live trading APIs"
            )
        if len(successes) != 1:
            raise BrokerError(
                "Ambiguous environment verification; reconnect with a separate Alpaca key pair"
            )
        verified = successes[0]
        if requested_environment and verified.environment != requested_environment:
            raise EnvironmentMismatchError(
                f"Credentials were verified for {verified.environment}, not the requested environment"
            )
        return verified

    def get_account(self) -> dict[str, Any]:
        return _model_to_dict(self._client.get_account())

    def get_assets(self) -> list[dict[str, Any]]:
        request = GetAssetsRequest(status=AssetStatus.ACTIVE)
        return [_model_to_dict(asset) for asset in self._client.get_all_assets(filter=request)]

    def get_positions(self) -> list[dict[str, Any]]:
        return [_model_to_dict(position) for position in self._client.get_all_positions()]

    def get_open_orders(self) -> list[dict[str, Any]]:
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True)
        return [_model_to_dict(order) for order in self._client.get_orders(filter=request)]

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = self._data_client.get_stock_latest_quote(request)
        return {symbol: _model_to_dict(quote) for symbol, quote in quotes.items()}

    def get_daily_bars(self, symbol: str, start: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        request = StockBarsRequest(
            symbol_or_symbols=symbol.upper(),
            timeframe=TimeFrame.Day,
            start=start,
            limit=limit,
        )
        response = self._data_client.get_stock_bars(request)
        raw_data = response.get("data", {}) if isinstance(response, dict) else getattr(response, "data", {})
        bars = raw_data.get(symbol.upper(), []) if isinstance(raw_data, dict) else []
        return [_model_to_dict(bar) for bar in bars]

    def get_market_clock(self) -> dict[str, Any]:
        return _model_to_dict(self._client.get_clock())

    def get_news(self, symbols: list[str], since: datetime) -> list[dict[str, Any]]:
        if not symbols:
            return []
        request = NewsRequest(
            start=since,
            end=datetime.now(UTC),
            sort="desc",
            symbols=",".join(sorted({symbol.upper() for symbol in symbols})),
            limit=100,
            include_content=False,
        )
        response = self._news_client.get_news(request)
        raw_data = response.get("data", {}) if isinstance(response, dict) else getattr(response, "data", {})
        news_items: list[Any] = []
        if isinstance(raw_data, dict):
            for value in raw_data.values():
                if isinstance(value, list):
                    news_items.extend(value)
        return [_model_to_dict(item) for item in news_items]

    def submit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
        stop_price: float | None = None,
        target_price: float | None = None,
    ) -> dict[str, Any]:
        if side not in {"buy", "sell"}:
            raise BrokerError("Unsupported order side")
        bracket = side == "buy" and stop_price is not None and target_price is not None
        stop_loss = StopLossRequest(stop_price=stop_price) if bracket and stop_price else None
        take_profit = (
            TakeProfitRequest(limit_price=target_price) if bracket and target_price else None
        )
        request = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
            order_class=OrderClass.BRACKET if bracket else None,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        return _model_to_dict(self._client.submit_order(order_data=request))

    def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        try:
            return _model_to_dict(self._client.get_order_by_client_id(client_order_id))
        except Exception:
            return None

    def cancel_order(self, broker_order_id: str) -> None:
        self._client.cancel_order_by_id(broker_order_id)

    def stream_trade_updates(self) -> None:
        """Streaming is run by the worker process, not the Android foreground process."""
        raise NotImplementedError("Attach Alpaca TradingStream in the persistent worker deployment")
