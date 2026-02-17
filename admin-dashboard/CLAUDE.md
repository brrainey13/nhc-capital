# CLAUDE.md — Admin Dashboard

Read `docs/admin-dashboard.md` for full architecture, endpoints, and deploy process.

## Quick Context

- **Python:** `admin-dashboard/.venv/bin/python` — **always use this, never system Python**
- **Setup:** `cd admin-dashboard && python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`
- **Backend:** `backend/main.py` — FastAPI + asyncpg, read-only SQL
- **Frontend:** `frontend/` — React + Vite + TypeScript
- **Tests:** `backend/tests/test_api.py` (28 tests)
- **Deploy:** `scripts/deploy-dashboard` — blue-green on ports 8000/8001. **The ONLY way to deploy.**
- **Public URL:** `https://alexzander-tightfisted-ambagiously.ngrok-free.dev`
- **Auth:** ngrok Google OAuth (5 team emails)

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/databases` | GET | List available databases |
| `/api/tables` | GET | List all tables (auto-discovered) with row counts + database |
| `/api/tables/{name}/schema` | GET | Column info |
| `/api/tables/{name}/data` | GET | Paginated rows with operator-based filters & sorting |
| `/api/tables/{name}/grouped` | GET | Group-by aggregation |
| `/api/query` | POST | Run arbitrary read-only SQL (`db` param selects database) |
| `/api/nl-query` | POST | Natural language → SQL (`db` param selects database) |
| `/api/usage` | GET | OpenClaw session token usage |

## Multi-Database

Tables are **auto-discovered** from all configured databases on startup. No hardcoded allowlist.
- `nhl_betting` — NHL data (28 tables)
- `polymarket` — Polymarket + crypto data (7+ tables)
- Adding a new DB: add it to `DATABASE_URLS` dict in `main.py`, restart server. Tables appear automatically.

## Frontend Features

- Virtualized scrolling (@tanstack/react-virtual) — infinite scroll, loads 200 rows at a time
- Operator-based filters: "+ Add Filter" → column → operator → value. Stacked AND logic
- Group-by with click-to-filter
- NL Query page: "Ask in English" + "Raw SQL" toggle
- Full viewport layout — table fills remaining space below nav

## Rules

- **All filtering/sorting is server-side** — parameterized SQL, never client-side on 200K+ row tables
- **Tables auto-discovered** — add a DB to `DATABASE_URLS` in `main.py`, tables appear on restart
- **CORS locked** to ngrok domain + localhost origins
- **Binds to `127.0.0.1` only** — never `0.0.0.0`
- **NL query uses OpenRouter free tier** — API key in `.env` (gitignored), fallback chain across free models
- **Update `docs/admin-dashboard.md`** when you add endpoints or change architecture
