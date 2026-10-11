# Alpaca Trading Assistant — Android Client

This directory is a Kotlin/Jetpack Compose Android Studio project for a **single-user monitoring and safety-control client**. It connects to the secure backend; it **does not submit Alpaca or broker orders**.

## Requirements

- Android Studio with JDK 17+ and Android SDK Platform 35 installed
- Android device/emulator running API 26 or newer
- A deployed backend URL reachable over HTTPS (or `http://localhost` only in a debug build)

The project uses **minSdk 26**, **compileSdk 35**, Kotlin, Compose Material 3, Navigation Compose, ViewModel/Flow, Ktor + Kotlin serialization, and Android Keystore-backed token storage.

## Open and build

1. Open **this `android/` directory** in Android Studio.
2. Let Android Studio resolve the Gradle Android and Kotlin plugins, then select the `app` configuration.
3. Build the debug APK:

   ```bash
   ./gradlew assembleDebug
   ```

   The repository includes a Gradle wrapper. Do not place SDK paths or credentials in source control.

4. Install a debug APK on a connected device:

   ```bash
   adb install -r app/build/outputs/apk/debug/app-debug.apk
   ```

5. On first launch, enter the backend URL and passphrase, then enter masked Alpaca credentials. The credentials are sent once to `POST /api/v1/connections/validate`, cleared from the form/ViewModel, and never stored on the device.

## Backend API use

The app calls the following backend endpoints through the `ApiClient` abstraction:

| Method | Endpoint | Client use |
|---|---|---|
| POST | `/api/v1/auth/session` | Obtain backend session token |
| POST | `/api/v1/connections/validate` | One-time Alpaca credential validation / server environment detection |
| GET | `/api/v1/account` | Dashboard/account summary |
| GET | `/api/v1/account/environment` | Server-verified paper/live environment |
| GET | `/api/v1/automation/status` | Automation and kill-switch status |
| POST | `/api/v1/automation/disable` | Safe automation disable |
| POST | `/api/v1/kill-switch/activate` | Emergency stop |
| GET | `/api/v1/health` | Offline state and backend health |
| GET | `/api/v1/positions`, `/orders`, `/signals` | Read-only monitoring detail screens |
| GET | `/api/v1/performance`, `/risk/config`, `/audit-log` | Backtest, risk, and audit state screens |

`/api/v1/connections/disconnect` is also attempted during local disconnect. The client never calls an order-create endpoint.

## Security decisions

- `AndroidManifest.xml` requests only `INTERNET`; cleartext traffic is disabled.
- The debug resource overlay permits cleartext only for `localhost` and `127.0.0.1`. Runtime URL policy rejects every other HTTP URL; release builds accept HTTPS only.
- The backend session token is the only persisted secret. It is AES-GCM encrypted with a non-exportable Android Keystore key in app-private storage.
- The backend URL is the only unencrypted persisted value and contains no secret.
- No broker API key or secret is written to SharedPreferences, app files, logs, navigation state, or `TradingUiState`.
- `FLAG_SECURE` blocks screenshots/recent-app previews while the app is open.
- A `PAPER TRADING — NO REAL MONEY IS BEING TRADED` or `LIVE ACCOUNT — REAL ORDERS MAY BE SUBMITTED` banner is rendered only after a backend response provides both a recognized environment and `verified_at`. It is persistent across connected screens.
- When health fails, the app visibly states `BACKEND OFFLINE — AUTOMATION UNAVAILABLE` and disables server safety actions until connectivity returns.

## Release signing (environment variables only)

No keystore, password, or key alias is committed. Set all four variables only in the release build environment:

```bash
export RELEASE_STORE_FILE=/secure/path/release.keystore
export RELEASE_STORE_PASSWORD='...'
export RELEASE_KEY_ALIAS='...'
export RELEASE_KEY_PASSWORD='...'
./gradlew bundleRelease
```

When any variable is absent, the release variant intentionally remains unsigned rather than silently using a debug key. The project `.gitignore` excludes keystores and `.env` files.

## Current scope and safety boundary

The dashboard/account/automation/health screens display typed API-backed state. Positions, orders, signals, backtest, risk, and audit screens retrieve their read-only backend responses on entry, redact credential/token-like fields again before observable UI state, and render a loading, empty, error, or backend response state. They intentionally never fabricate records. Emergency stop is always visible after connection and requires a single clear confirmation before the kill-switch request is made.
