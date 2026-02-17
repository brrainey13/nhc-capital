---
summary: 'Admin dashboard architecture — FastAPI backend + React frontend, served via ngrok with Google OAuth.'
read_when:
  - Working on the admin dashboard
  - Modifying the dashboard backend or frontend
  - Debugging dashboard issues
  - Adding new tables or API endpoints
---

# Admin Dashboard

## Architecture

```
Browser → ngrok (Google OAuth) → localhost:8000 → FastAPI
                                                    ├── /api/* (JSON endpoints)
                                                    └── /* (React SPA static files)
```

## Stack

- **Backend:** FastAPI + asyncpg (`admin-dashboard/backend/main.py`)
- **Frontend:** React + Vite + TypeScript (`admin-dashboard/frontend/`)
- **Database:** PostgreSQL `nhl_betting` (read-only access, 28 tables)
- **Auth:** ngrok Google OAuth (5 team emails)
- **NL Query:** OpenRouter free tier (API key in `.env`, gitignored)

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/tables` | GET | List allowed tables with row counts |
| `/api/tables/{name}/schema` | GET | Column info for a table |
| `/api/tables/{name}/data` | GET | Paginated rows with operator-based filters & sorting |
| `/api/tables/{name}/grouped` | GET | Group-by aggregation (value + count) |
| `/api/query` | POST | Run arbitrary read-only SQL |
| `/api/nl-query` | POST | Natural language → SQL via OpenRouter |
| `/api/usage` | GET | OpenClaw session token usage |

### Filtering (`/api/tables/{name}/data`)

Filters are passed as JSON in `?filters=` query param. Supports operator-based format:

```json
[
  {"column": "team_id", "operator": "eq", "value": 5},
  {"column": "save_pct", "operator": "gte", "value": 0.92},
  {"column": "player_name", "operator": "contains", "value": "connor"}
]
```

Operators: `contains`, `equals`, `starts_with`, `ends_with` (text); `eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `between` (numeric); `before`, `after`, `between` (date).

### NL Query (`/api/nl-query`)

Single-pass: sends schema + question to OpenRouter free model → gets SQL → executes → returns results. Fallback chain: `openrouter/free` → `qwen/qwen3-coder:free` → `llama-3.3-70b-instruct:free` → `deepseek-r1:free`.

## Frontend Features

- **Virtualized scrolling** — @tanstack/react-virtual, infinite scroll, loads 200 rows at a time
- **Operator-based filters** — "+ Add Filter" button → column → operator → value. Filter pills with × to remove
- **Group-by** — in toolbar, click group value to auto-add filter
- **Sticky headers** during scroll
- **NL Query page** — "Ask in English" + "Raw SQL" toggle
- **Full viewport layout** — table fills remaining space below nav

## Deployment (Deterministic)

**The ONLY way to deploy is `scripts/deploy-dashboard`:**

```bash
scripts/deploy-dashboard              # Build + health check (no restart)
scripts/deploy-dashboard --restart-server  # Blue-green server swap
scripts/deploy-dashboard --restart-ngrok   # Restart ngrok tunnel
scripts/deploy-dashboard --all             # Full deploy (CI + build + restart all)
```

Blue-green deploy: starts standby on :8001 → health check → swaps to :8000 → kills old. Near-zero downtime.

**Do NOT:**
- Manually run `uvicorn` or `ngrok` commands
- Restart services without running tests first
- Deploy without building the frontend

## Security (Defense in Depth)

Two layers of authentication — both must pass:

### Layer 1: ngrok OAuth (network level)
- All traffic through ngrok requires Google OAuth login
- Only 5 team emails allowed (configured in deploy script)
- Unauthenticated requests → 302 redirect to Google login

### Layer 2: Backend AuthMiddleware (application level)
- Every `/api/*` endpoint (except `/api/health`) requires auth
- Auth methods (any one grants access):
  1. **ngrok OAuth header:** `ngrok-auth-user-email` (must be in `ALLOWED_EMAILS` set)
  2. **API key:** `X-API-Key` header or `?api_key=` query param (set `DASHBOARD_API_KEY` in `.env`)
- Unauthenticated → 401, wrong email → 403
- `/api/health` is public (for monitoring/health checks)
- Frontend static files (non-`/api/` paths) are always served

### Other protections
- SQL queries regex-checked: INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE blocked
- Backend binds to `127.0.0.1` — only reachable via ngrok or localhost
- CORS locked to ngrok domain + localhost origins
- Tables auto-discovered — no manual allowlist to maintain
