# CLAUDE.md — Admin Dashboard

Read `docs/admin-dashboard.md` for full architecture, endpoints, and deploy process.

## Quick Context

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
| `/api/tables` | GET | List allowed tables with row counts |
| `/api/tables/{name}/schema` | GET | Column info |
| `/api/tables/{name}/data` | GET | Paginated rows with operator-based filters & sorting |
| `/api/tables/{name}/grouped` | GET | Group-by aggregation |
| `/api/query` | POST | Run arbitrary read-only SQL |
| `/api/nl-query` | POST | Natural language → SQL (via OpenRouter free tier) |
| `/api/usage` | GET | OpenClaw session token usage |

## Frontend Features

- Virtualized scrolling (@tanstack/react-virtual) — infinite scroll, loads 200 rows at a time
- Operator-based filters: "+ Add Filter" → column → operator → value. Stacked AND logic
- Group-by with click-to-filter
- NL Query page: "Ask in English" + "Raw SQL" toggle
- Full viewport layout — table fills remaining space below nav

## Rules

- **All filtering/sorting is server-side** — parameterized SQL, never client-side on 200K+ row tables
- **28 tables in `ALLOWED_TABLES`** — edit the set in `main.py` to add more
- **CORS locked** to ngrok domain + localhost origins
- **Binds to `127.0.0.1` only** — never `0.0.0.0`
- **NL query uses OpenRouter free tier** — API key in `.env` (gitignored), fallback chain across free models
- **Update `docs/admin-dashboard.md`** when you add endpoints or change architecture
