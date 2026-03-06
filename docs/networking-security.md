---
summary: 'Network exposure rules — Cloudflare Tunnel is the ONLY public entry point. No raw ports or ad-hoc tunnels.'
read_when:
  - Exposing any service to the internet
  - Setting up tunnels, proxies, or port forwarding
  - Working on the admin dashboard
  - Running any server that listens on a port
  - Security audit or review
---

# Networking & Security

## Golden Rule

**The ONLY way anything on this machine reaches the public internet is through the Cloudflare tunnel.**

No exceptions. No "just for testing." No ad-hoc tunnels. No raw port exposure.

## Current Setup

### Cloudflare Tunnel (Production)

- **Domain:** `dashboard.nhc-capital.com`
- **Auth:** Cloudflare Access, locked to team emails only:
  - `<team-email-1>`
  - `<team-email-2>`
  - `<team-email-3>`
  - `<team-email-4>`
  - `<team-email-5>`
- **Backend:** Proxies to `http://localhost:8000` (FastAPI admin dashboard)
- **Process:** Runs as a background process on the Mac Mini

### Deployment

Configured through `scripts/deploy-dashboard` and the managed Cloudflare tunnel service.

## What Is NOT Allowed

1. **Cloudflare quick tunnels** (`cloudflared tunnel --url`) — no auth, URL is guessable
2. **Raw port binding on 0.0.0.0** for external access — use `127.0.0.1` for local services
3. **SSH port forwarding to expose services** — Tailscale only for internal access
4. **Any other tunnel service** without explicit team approval

## Internal Access (OK Without Tunnel)

- **Tailscale:** Internal network access between Mac Mini, Raspberry Pi, Linux desktop
- **localhost:** Services bound to `127.0.0.1` are fine (Postgres, uvicorn dev, etc.)
- **Docker bridge networks:** Internal container networking is fine

## Backend Security

- FastAPI dashboard: read-only SQL only (INSERT/UPDATE/DELETE/DROP blocked by regex)
- Table allowlist: only approved tables are queryable
- CORS: Should be locked to the Cloudflare domain

## Deployment

**Use `scripts/deploy-dashboard` for ALL deployments.** No ad-hoc restarts.

The script runs CI, builds frontend, restarts services, and health checks — in that order.
Agents must NOT manually start uvicorn or `cloudflared`. See `docs/admin-dashboard.md`.

## Checklist Before Exposing Anything

1. Is it going through Cloudflare Tunnel? If no, stop.
2. Does it have authentication? (Cloudflare Access handles this)
3. Is the service read-only or appropriately permissioned?
4. Are credentials/secrets excluded from responses?
5. Is CORS locked down to the Cloudflare domain?
6. Did you deploy via `scripts/deploy-dashboard`? If no, stop.
