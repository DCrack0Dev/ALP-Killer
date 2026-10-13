# Alpaca Killer

A **single-user Android app and secure FastAPI backend** for a risk-gated Alpaca trading assistant. It implements separate **backtest**, **paper**, and **live** modes. The Android app is a control surface; credential validation, strategy evaluation, risk control, execution, reconciliation, and audit records are server-side.

> **Risk notice:** This software is for research and execution automation. It can lose money. Backtests and Alpaca paper trading are simulations, not evidence of future performance. Nothing in this repository is personalized investment advice.

## Safety properties

- The backend verifies paper versus live by probing the official `alpaca-py` Trading API clients. A UI label cannot choose the environment.
- Live credentials do **not** enable automation. Live activation requires a verified live connection, complete risk limits, an exact risk-configuration fingerprint, and the literal confirmation `I_UNDERSTAND_LIVE_TRADING`.
- An emergency kill switch disables both modes and blocks future automated order intents. Deactivation never silently re-enables automation.
- Every order intent receives a deterministic client order ID. Ambiguous submission failures are reconciled by that ID before any retry.
- The risk engine is the sole route to broker order submission. It blocks stale data, environment mismatch, disabled automation, kill switch, spread/liquidity/position/exposure/loss/order-frequency/news/shorting/latency failures.
- The Android client now supports paper risk-limit entry, paper watchlist management, worker-heartbeat visibility, and explicit paper-only enable/disable controls. Paper enablement fails closed unless the verified paper account, risk configuration, watchlist, and worker heartbeat are ready.
- Docker Compose starts the API, PostgreSQL, and a separate paper worker. Automation remains disabled by default; every worker restart disarms it and requires explicit re-enable. The free Render deployment is API-only and not suitable for an always-on worker.
- Broker key and secret inputs are Pydantic `SecretStr` values, sent only over HTTPS, encrypted server-side with a Fernet key, and omitted from responses and audit payloads. Android keeps them only in masked UI state, clears them after submission, and stores only its short-lived backend session token via the Android Keystore.

## Repository layout

```text
android/                 Kotlin + Jetpack Compose Android Studio project
backend/                 FastAPI, SQLAlchemy, Alembic, alpaca-py, tests
docs/                    deployment, API, security, rollback, limitations
research/                official Alpaca integration notes
docker-compose.yml       private backend + PostgreSQL deployment
.env.example             safe environment template
```

## Local backend development

1. Create and activate a virtual environment from `backend/`.
2. Install dependencies: `python -m pip install -e '.[dev]'`.
3. Export only local development values, then migrate:

```bash
export APP_ENV=development
export JWT_SECRET='development-only-long-secret'
export BOOTSTRAP_PASSPHRASE='development-only-passphrase'
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

4. Inspect the authenticated API schema at `http://127.0.0.1:8000/docs`.
5. Run `pytest`, `ruff check app tests`, and `mypy app` before changes are accepted.

No real Alpaca credentials are required by the test suite. Use paper credentials before considering live deployment.

## Android build and install

See [android/README.md](android/README.md). The app defaults to an offline-safe state and shows **BACKEND OFFLINE — AUTOMATION UNAVAILABLE** if the API cannot be reached.

## Production deployment

Use [docs/deployment.md](docs/deployment.md) for a private VPS or always-on local host, including HTTPS/reverse proxy, firewall, environment-key generation, database migration, paper worker operation, and Android trust configuration. The ordinary Manus sandbox and free Render web services are intentionally not production hosts for continuous automation because they can suspend.

## Documentation

- [Architecture](docs/architecture.md) and [diagram source](docs/architecture.mmd)
- [API documentation](docs/api.md)
- [Threat model and security notes](docs/threat-model.md)
- [Emergency stop and rollback](docs/rollback-and-emergency-stop.md)
- [Known limitations](docs/known-limitations.md)
- [Official Alpaca integration research](research/alpaca-official-integration-notes.md)

## Commands

```bash
# Backend verification
cd backend
. .venv/bin/activate
ruff check app tests
pytest
mypy app

# Android debug APK (after Android SDK setup)
cd ../android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Scope of broker permissions

The implementation uses only Alpaca Trading and Market Data API credentials. It never requests or implements withdrawals, transfers, funding actions, broker dashboard scraping, mobile-login automation, or MT5 automation.
