# Deployment and installation

Run this backend on a **private, persistent host**: a personal Linux machine that remains online, a private VPS, or an appropriately secured Cloud Computer. Do not rely on an ephemeral sandbox for live or continuous trading because it can suspend while inactive.

## 1. Prepare host and secrets

Install Docker Engine and the Compose plugin on the chosen Ubuntu host. Clone this repository into a directory owned by a non-root deployment user. Copy `.env.example` to `.env`, set file permissions to `0600`, and generate unique values locally:

```bash
openssl rand -base64 64                 # JWT_SECRET
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'  # CREDENTIAL_ENCRYPTION_KEY
openssl rand -base64 48                 # POSTGRES_PASSWORD or BOOTSTRAP_PASSPHRASE
chmod 600 .env
```

Use a distinct `BOOTSTRAP_PASSPHRASE` for the Android app unlock session. It is not an Alpaca credential. Never place the Alpaca API key or secret in `.env`; the user enters it into the app over HTTPS and the backend stores only encrypted ciphertext.

## 2. Start database migrations and the API

```bash
cp .env.example .env
# Edit every REPLACE/CHANGE_ME value in .env.
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d
curl --fail http://127.0.0.1:8000/api/v1/health
```

The compose API port binds to `127.0.0.1` only. Do not expose port 8000 directly to the internet.

## 3. Put HTTPS in front

Use Caddy, Nginx, or another maintained reverse proxy. Terminate TLS at the proxy, proxy only to `127.0.0.1:8000`, set strict modern TLS defaults, and restrict public access to the user’s VPN/Tailscale network or a firewall allowlist. Example Nginx principles:

```nginx
server {
  listen 443 ssl http2;
  server_name trading.example.internal;
  # Configure certificate and modern TLS here.
  client_max_body_size 64k;
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
  }
}
```

Allow only TCP/443 in the host firewall. Keep SSH restricted to a VPN or known administrator network. Set `ALLOWED_ORIGINS` to the exact app-facing origin if a web client is added; Android does not use browser CORS.

## 4. Install Android

1. Build `android/app/build/outputs/apk/debug/app-debug.apk` or prepare a signed release AAB.
2. Install the debug APK with `adb install -r app-debug.apk`, or distribute the release through a private testing channel.
3. Enter the full private HTTPS URL and backend unlock passphrase.
4. Connect **paper** credentials first. The backend verifies the result server-side and the app shows the persistent paper banner.
5. Set paper risk limits, run backtests, and monitor paper behavior. Do not assume paper results match live conditions.
6. If and only if you intend to trade real money, connect a separate live key pair, review the red live banner and exact risk-limit fingerprint, then complete the explicit live activation flow.

## 5. Backups, monitoring, and upgrades

Back up the encrypted PostgreSQL volume before upgrades. Store database backups encrypted and separately from the Fernet key; losing either the key or database prevents credential recovery. Monitor `/api/v1/health`, reverse-proxy TLS renewal, database disk capacity, and audit events. Before updating, disable automation, activate the kill switch, take a database backup, run tests, then use `docker compose pull && docker compose up -d`.

## 6. Worker operation

The provided API exposes guarded services and WebSocket status. A production worker should run as a distinct persistent process/container under the same environment: refresh broker state, run approved strategies, call the risk engine, stream Alpaca trade updates, and reconcile state. It must stop submitting new orders if the health check fails or the kill switch is active. See the documented limitations before enabling automation.
