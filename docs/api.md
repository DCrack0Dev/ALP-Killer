# API documentation

FastAPI exposes a machine-readable OpenAPI document at `/openapi.json` and interactive documentation at `/docs`. Other than `/api/v1/auth/session` and `/api/v1/health`, every HTTP endpoint requires `Authorization: Bearer <short-lived-session-token>`.

| Area | Endpoint | Safety behavior |
| --- | --- | --- |
| Session | `POST /api/v1/auth/session` | Exchanges a backend unlock passphrase for a short-lived session token. |
| Connection | `POST /api/v1/connections/validate` | Validates a submitted credential pair through official Alpaca paper and live client configurations; returns a masked, server-verified environment only. |
| Account | `GET /api/v1/account`, `GET /api/v1/account/environment` | Returns masked account state and verified mode. |
| Connection removal | `POST /api/v1/connections/disconnect` | Disables automation and deletes stored encrypted credential ciphertext. |
| Market | `GET /api/v1/instruments`, `POST /api/v1/instruments/validate`, `GET /api/v1/market/regimes`, `GET /api/v1/signals` | Serves only cached/synchronized state; invalid or unavailable data must result in no trade. |
| Research | `POST /api/v1/backtests`, `GET /api/v1/backtests/{id}` | Backtests run without broker order calls and return explicit execution assumptions. |
| Broker state | `GET /api/v1/positions`, `GET /api/v1/orders`, `GET /api/v1/fills`, `GET /api/v1/performance` | Reads broker/local reconciled state; submission success is never presented as a fill. |
| Risk | `GET/PUT /api/v1/risk/config` | Stores environment-specific risk limits and returns a configuration fingerprint. |
| Automation | `GET /api/v1/automation/status`, `GET/PUT /api/v1/automation/watchlist`, `GET /api/v1/automation/worker-status`, `POST /api/v1/automation/enable-paper`, `POST /api/v1/automation/disable` | Paper enable requires a verified paper account, complete risk limits, a saved watchlist, and a current worker heartbeat. Worker restarts disarm automation and require explicit re-enable. |
| Safety | `POST /api/v1/kill-switch/activate`, `POST /api/v1/kill-switch/deactivate` | Activation disables automation globally; deactivation does not re-enable it. |
| Execution | `POST /api/v1/orders/intents` | Server-only order path. It records pre-trade risk and reaches the broker only after approval. |
| Audit/ops | `GET /api/v1/audit-log`, `GET /api/v1/health`, `WS /api/v1/stream` | Provides redacted audit trace, health, and authenticated status stream. |

## Live activation request

`POST /api/v1/automation/enable-live` requires exactly:

```json
{
  "confirmation": "I_UNDERSTAND_LIVE_TRADING",
  "configuration_fingerprint": "exact SHA-256 fingerprint returned by GET /api/v1/risk/config?environment=live"
}
```

A stale fingerprint is rejected. This Android client does not expose live activation; keep `ALLOW_LIVE_TRADING=false`. Credentials, raw account identifiers, Fernet ciphertext, and auth passphrases never appear in API responses.
