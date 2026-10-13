# Known limitations

This is a security-first foundation, not a claim of profitable or universally eligible trading.

- **Alpaca eligibility varies.** Asset classes, shortability, market-data entitlement, live-account access, and country availability depend on the user’s Alpaca account. Validation reports a broker result rather than pretending that every instrument or account can trade.
- **Paper is not live.** Alpaca documents that paper simulation does not model market impact, latency slippage, queue position, price improvement, regulatory fees, or dividends. The backtester separately models configurable spread/slippage/latency but cannot recreate all live microstructure.
- **Worker availability is deployment-specific.** Docker Compose now includes a separate paper worker, watchlist editor, worker heartbeat, and explicit paper-automation controls. The worker process disarms automation on restart. The free Render service configured for this repo is API-only and can sleep; it is not suitable for continuous automation. Use an always-on private host and keep monitoring the worker heartbeat.
- **News is an interface, not invented content.** No news provider is bundled. Configure a licensed/approved provider and persist source timestamps/deduplication before it is allowed to block or confirm a setup.
- **ML is an intentionally transparent baseline.** Logistic regression is included for time-ordered research. It needs point-in-time feature datasets, walk-forward training, calibration checks, and model governance before influencing a deployed strategy.
- **No broker order is placed directly from Android.** The app can explicitly enable paper automation, but strategy evaluation, risk checks, and paper order submission remain server-side. The Android client does not expose live activation; the deployment default remains `ALLOW_LIVE_TRADING=false`.
- **Broker reconciliation must be strengthened for a live worker.** The execution service queries account/positions and uses idempotent client IDs. A live deployment needs continuous trade-update streaming, fill ingestion, market-calendar handling, and a recovery runbook exercised against paper accounts.
- **Android biometric lock and push notification provider are extension points.** Keystore session storage is included; an FCM project or equivalent and biometric policy must be selected during final deployment.

The safe default is **no trade** when any prerequisite is missing, stale, contradictory, or outside configured limits.
