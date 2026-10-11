# Hosting research — Render

**Checked:** 2026-10-11. Prices can change; verify them in the Render dashboard before provisioning.

## Relevant official pricing

Render's official pricing page lists the Hobby workspace tier as $0/month plus compute; the smallest always-on service/worker plan (0.5 CPU, 512 MB) as $7/month; and the smallest paid PostgreSQL plan (256 MB) as $6/month. A split always-on API + worker + paid PostgreSQL baseline is therefore approximately **$20/month**, before usage-based bandwidth, storage, and build costs. Prices are stated in USD.

- Official pricing: https://render.com/pricing
- Official free-plan limitations: https://render.com/docs/free

## Free-tier constraints relevant to this app

- Free web services spin down after 15 minutes without inbound traffic; the next request can take about a minute to wake them.
- Free web-service files are ephemeral; local SQLite state would be lost on restart, redeploy, or spin-down.
- Free Render Postgres is limited to 1 GB, has no backups, and expires 30 days after creation. It can be upgraded during the grace period, but should not be treated as a durable trading database.
- The free service is not suitable as an unattended always-on trading worker. Render explicitly says free instances are not for production.

## Deployment interpretation

This app should not run unattended trading from free compute or an expiring database. Do not provision paid resources without the user's explicit approval of the specific monthly spend and network exposure. Render's web-service type is internet-facing; application-level authentication and TLS protect it, but it is not a network-private endpoint. A truly private endpoint for an Android phone requires a VPN/tailnet or a private service reachable through an approved network path.
