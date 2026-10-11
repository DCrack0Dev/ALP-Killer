# Known limitations

This is a security-first foundation, not a claim of profitable or universally eligible trading.

- **Alpaca eligibility varies.** Asset classes, shortability, market-data entitlement, live-account access, and country availability depend on the user’s Alpaca account. Validation reports a broker result rather than pretending that every instrument or account can trade.
- **Paper is not live.** Alpaca documents that paper simulation does not model market impact, latency slippage, queue position, price improvement, regulatory fees, or dividends. The backtester separately models configurable spread/slippage/latency but cannot recreate all live microstructure.
- **Market-data synchronization and worker scheduling require deployment configuration.** The repository contains the guarded API, protocol abstractions, and deployment architecture; a production worker must be configured with the user’s approved universe, data entitlement, session calendar, news provider, and operational monitoring before unattended automation. It must remain fail-closed on any data or broker discrepancy.
- **News is an interface, not invented content.** No news provider is bundled. Configure a licensed/approved provider and persist source timestamps/deduplication before it is allowed to block or confirm a setup.
- **ML is an intentionally transparent baseline.** Logistic regression is included for time-ordered research. It needs point-in-time feature datasets, walk-forward training, calibration checks, and model governance before influencing a deployed strategy.
- **No broker order is placed from Android.** The Android app is intentionally unable to submit directly to Alpaca; it submits only a guarded order intent to the backend.
- **Broker reconciliation must be strengthened for a live worker.** The execution service queries account/positions and uses idempotent client IDs. A live deployment needs continuous trade-update streaming, fill ingestion, market-calendar handling, and a recovery runbook exercised against paper accounts.
- **Android biometric lock and push notification provider are extension points.** Keystore session storage is included; an FCM project or equivalent and biometric policy must be selected during final deployment.

The safe default is **no trade** when any prerequisite is missing, stale, contradictory, or outside configured limits.
