# Official Alpaca Integration Notes

**Verified:** 2026-10-11

- Live Trading API calls use `https://api.alpaca.markets`; paper Trading API calls use `https://paper-api.alpaca.markets`. Live and paper API credentials are separate and cannot be interchanged.
- Validation therefore probes `GET /v2/account` through the official `alpaca-py` `TradingClient` separately with `paper=True` and `paper=False`. A client-selected label is never used as evidence of environment.
- `TradingClient(api_key, secret_key, paper=True|False)` is the official Python client configuration. Alpaca documents `client_order_id` and retrieval by client order ID, which supports idempotent reconciliation after ambiguous network errors.
- Alpaca paper trading is a simulation. Its documented limitations include no market impact, latency slippage, order-queue position, price improvement, regulatory fees, or dividends; the app presents paper results as non-predictive.
- Order-state reconciliation must use broker updates and account/position reads, not HTTP submission success alone.

## Sources

1. https://docs.alpaca.markets/us/docs/authentication
2. https://docs.alpaca.markets/us/docs/paper-trading
3. https://docs.alpaca.markets/us/docs/working-with-orders
4. https://alpaca.markets/sdks/python/api_reference/trading/trading-client.html
