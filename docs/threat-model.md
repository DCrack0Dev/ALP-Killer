# Threat model and security notes

## Assets and trust boundaries

The highest-value assets are Alpaca API secrets, the server credential-encryption key, backend unlock passphrase, session tokens, order authority, and audit integrity. Android is treated as a potentially lost device. The reverse proxy is the network boundary. The FastAPI process and PostgreSQL database are the server trust boundary. Alpaca is an external broker boundary reached only through its official API/SDK.

## Controls

| Threat | Control |
| --- | --- |
| User mislabels live credentials as paper | Backend probes official paper and live clients and persists the successful environment; mismatch is rejected. |
| Accidental live activation | Connecting live credentials leaves automation off. Explicit activation requires verified live mode, risk configuration, exact fingerprint, and literal acknowledgement. |
| Credential disclosure in app, logs, or API | Android clears broker input after setup and stores no broker credential. Backend uses `SecretStr`, Fernet ciphertext, redacted audit payloads, masked identifiers, and no secret response fields. |
| Stolen Android device | Keystore-backed encrypted session storage, optional biometric lock extension point, backend session expiry, disconnect action, and no persistent broker secret. |
| Replay or duplicate order after timeout | Deterministic client order ID, local unique constraint, and broker query by client ID before any recovery action. |
| Strategy/model bypasses controls | Strategies, news, and ML return data only. The execution service calls the central deterministic risk engine before its only broker order call. |
| Bad/late market data | Freshness, spread, liquidity, latency, and data-quality gates return no trade rather than guessing. |
| Backend compromise | Restrict host/VPN access; enforce TLS; keep `.env` 0600; rotate unlock passphrase, JWT secret, and Fernet key after incident; rebuild credentials and disconnect broker connections. |
| Database loss or tampering | Encrypted backups, off-host retention, restricted database network access, append-only audit rows, and migration discipline. |
| Android foreground/background termination | The app has no continuous execution duty. A persistent server worker owns execution and reconciliation. |

## Operational rules

- Use HTTPS with certificate validation. Cleartext is disabled in the Android manifest except controlled local debug testing.
- Do not use a reverse proxy public URL without firewall/VPN constraints.
- Do not log HTTP request bodies for connection or session endpoints.
- Rotate API keys through Alpaca, then disconnect/reconnect in the app; never edit ciphertext manually.
- The kill switch should be activated before server maintenance, deployment rollback, suspected compromise, or any unexplained order discrepancy.
- Reconcile broker account, positions, orders, and fills after process restart before enabling automation.

## Out of scope

This project intentionally does not handle bank transfers, withdrawals, funding, brokerage web automation, MT5, credential sharing, multi-user authorization, regulatory suitability checks, tax reporting, or a guarantee of strategy profitability.
