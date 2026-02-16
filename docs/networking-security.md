---
summary: 'Network exposure rules — ngrok is the ONLY public entry point. No raw ports, no Cloudflare quick tunnels.'
read_when:
  - Exposing any service to the internet
  - Setting up tunnels, proxies, or port forwarding
  - Working on the admin dashboard
  - Running any server that listens on a port
  - Security audit or review
---

# Networking & Security

## Golden Rule

**The ONLY way anything on this machine reaches the public internet is through the ngrok tunnel.**

No exceptions. No "just for testing." No quick Cloudflare tunnels. No raw port exposure.

## Current Setup

### ngrok Tunnel (Production)

- **Domain:** `alexzander-tightfisted-ambagiously.ngrok-free.dev`
- **Auth:** Google OAuth, locked to team emails only:
  - `yousefshahin1422@gmail.com`
  - `brrainey13@gmail.com`
  - `connorsrainey@gmail.com`
  - `pgrainey8@gmail.com`
  - `ian.rainey95@gmail.com`
- **Backend:** Proxies to `http://localhost:8000` (FastAPI admin dashboard)
- **Process:** Runs as a background process on the Mac Mini

### Start Command

```bash
ngrok http 8000 \
  --domain=alexzander-tightfisted-ambagiously.ngrok-free.dev \
  --oauth=google \
  --oauth-allow-email=yousefshahin1422@gmail.com \
  --oauth-allow-email=brrainey13@gmail.com \
  --oauth-allow-email=connorsrainey@gmail.com \
  --oauth-allow-email=pgrainey8@gmail.com \
  --oauth-allow-email=ian.rainey95@gmail.com
```

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
- CORS: Should be locked to ngrok domain (TODO: currently `allow_origins=["*"]`)

## Checklist Before Exposing Anything

1. Is it going through ngrok? If no, stop.
2. Does it have authentication? (ngrok OAuth handles this)
3. Is the service read-only or appropriately permissioned?
4. Are credentials/secrets excluded from responses?
5. Is CORS locked down to the ngrok domain?
