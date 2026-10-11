# Rollback and emergency stop

## Immediate stop

1. In the Android app, open **Emergency Stop** and confirm activation. This calls `POST /api/v1/kill-switch/activate`.
2. Confirm the API response states `kill_switch_active: true` and automation is disabled.
3. Independently verify open orders and positions in the Alpaca dashboard or through the official API. The kill switch blocks **new automated** orders; it does not cancel or close existing orders/positions by design.
4. Cancel or manage existing orders and positions according to your own trading decision. Do not assume an HTTP timeout means an order did not reach the broker.
5. Preserve the audit log, application logs, and exact timestamp before restarting anything.

## Planned maintenance

1. Activate the kill switch.
2. Wait for any in-flight broker reconciliation to complete and inspect open orders/positions.
3. Create an encrypted PostgreSQL backup and copy it off-host.
4. Stop the API/worker. Update code or configuration.
5. Run database migration and tests. Restart API/worker.
6. Verify `/api/v1/health`, connection environment, risk configuration, broker positions, open orders, and audit continuity.
7. Deactivate the kill switch. Automation stays disabled until separately enabled for the relevant environment.

## Application rollback

Use the prior tagged container image or Git revision. Restore the matching database backup only if schema/data compatibility requires it. Do not roll back encrypted connection data without retaining the matching `CREDENTIAL_ENCRYPTION_KEY`; otherwise the backend cannot decrypt those credentials. After a rollback, re-run broker reconciliation before any automation enablement.

## Suspected credential compromise

1. Activate the kill switch.
2. Revoke the affected API key in the official Alpaca dashboard.
3. Use **Disconnect** in the app to delete stored ciphertext.
4. Rotate the backend unlock passphrase, JWT secret, and credential-encryption key. A Fernet key rotation requires re-encrypting valid connection records or reconnecting them.
5. Review access logs and the audit trail, then reconnect with newly issued credentials only after the host is secured.
