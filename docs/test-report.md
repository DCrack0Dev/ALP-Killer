# Test report

**Run date:** 2026-10-11

## Backend validation

The backend was validated in a Python 3.12 virtual environment. The following commands completed successfully from `backend/`:

```bash
ruff check app tests
pytest
mypy app
rm -f alpaca_killer.db
alembic upgrade head
python -c 'from app.main import app; print(app.title)'
```

Results: **17 pytest tests passed**, Ruff reported no findings, and Mypy reported no issues across 18 source files. The Alembic initial migration applied successfully to SQLite. The tests cover paper/live endpoint detection, environment mismatch, invalid credentials without secret disclosure, risk gates (including kill switch, stale data, reduce-only, and short eligibility), event-driven backtest assumptions, regime no-trade/high-risk behavior, encrypted credential persistence, session authentication, risk-config access, and kill-switch behavior.

A separate Uvicorn smoke test started the API on a loopback port, called `/api/v1/health`, created a short-lived session through `/api/v1/auth/session`, and retrieved the authenticated risk-config endpoint. It returned health `ok` and an initial incomplete risk configuration as expected.

The test run emitted two third-party deprecation warnings from the installed FastAPI test client/WebSocket dependency stack. They do not originate from project application code and did not affect test results.

## Android validation

The Android client was built using JDK 21, Android SDK Platform 35, Build Tools 35.0.0, and Gradle 8.10.2. The following command completed successfully from `android/`:

```bash
./gradlew --no-daemon testDebugUnitTest assembleDebug bundleRelease
```

Results: debug unit tests passed; the debug APK and release AAB were produced. `aapt dump badging` verified package `com.alpacatalk.trading.debug`, min SDK 26, target SDK 35, and the `INTERNET` permission.

| Artifact | SHA-256 | Status |
| --- | --- | --- |
| `app-debug.apk` | `475694745ef92f36b77e5ebe3436226d67aaef0539372bfca554d971a388774b` | Debug installable APK |
| `app-release.aab` | `7e0eb10d3c8c9f2aba7b79c6758148c2852f9eb76f358cdd673fe27284367061` | Release AAB, unsigned until the documented `RELEASE_*` signing variables are supplied |

## Deliberate non-production test boundaries

No real Alpaca credentials were entered and no broker order was sent. Broker calls are mocked in automated tests. A production deployment must be privately hosted, configured with TLS and a real server key, connected first to an authorized paper account, and validated against the user’s intended Alpaca entitlement before any live activation is considered.
