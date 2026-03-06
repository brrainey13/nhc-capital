---
summary: 'Infrastructure overview — Postgres, Tailscale, Mac Mini, Raspberry Pi, networking topology.'
read_when:
  - Setting up a new database or table
  - SSH to another machine
  - Troubleshooting connectivity
  - Understanding the network layout
---

# Infrastructure

## Machines

| Name | IP (Tailscale) | OS | Role |
|---|---|---|---|
| connors-mac-mini | `<tailscale-ip>` | macOS (arm64) | Primary — runs all services |
| raspberrypi | `<tailscale-ip>` | Linux | Secondary — SSH via `ssh <user>@<tailscale-ip>` |
| desktop-8c4f6f1-1 | `<tailscale-ip>` | Linux | Desktop — SSH via `ssh <user>@<tailscale-ip>` |

## PostgreSQL

- **Version:** 17 (Homebrew, auto-starts)
- **Host:** localhost:5432
- **Auth:** trust (no passwords locally)
- **User:** connorrainey (superuser)
- **Databases:** `postgres`, `nhl_betting`, `clawd` (legacy)
- **Connection string:** `postgresql://connorrainey@localhost:5432/<db>`

## Tailscale

All inter-machine communication goes through Tailscale. Run `tailscale status` to see live nodes.

## Public Access

See `docs/networking-security.md` — Cloudflare Tunnel is the ONLY public entry point.
