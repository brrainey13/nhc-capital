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
- **Database:** PostgreSQL `nhl_betting` (read-only access)
- **Auth:** ngrok Google OAuth (see `docs/networking-security.md`)

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/tables` | GET | List allowed tables with row counts |
| `/api/tables/{name}/schema` | GET | Column info for a table |
| `/api/tables/{name}/data` | GET | Paginated rows (limit/offset) |
| `/api/query` | POST | Run arbitrary read-only SQL |

## Deployment (Deterministic)

**The ONLY way to deploy the dashboard is via the deploy script:**

```bash
scripts/deploy-dashboard              # Build + health check (no restart)
scripts/deploy-dashboard --all        # Build + restart server + restart ngrok
scripts/deploy-dashboard --restart-server  # Just restart uvicorn
scripts/deploy-dashboard --restart-ngrok   # Just restart ngrok
```

The script:
1. Runs `make ci` (lint + test) — **aborts on failure**
2. Builds frontend (`npm run build`)
3. Starts/restarts uvicorn on `127.0.0.1:8000`
4. Starts/restarts ngrok with OAuth
5. Health checks both local and ngrok

**Do NOT:**
- Manually run `uvicorn` or `ngrok` commands
- Restart services without running tests first
- Deploy without building the frontend

## Running Locally (Dev Only)

```bash
cd admin-dashboard/backend
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Frontend dev server (with hot reload):
```bash
cd admin-dashboard/frontend
npm run dev  # localhost:3000, proxies /api to :8000
```

## Security

- SQL queries are regex-checked: INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE are blocked
- Only tables in `ALLOWED_TABLES` set are queryable
- Backend binds to `127.0.0.1` — only reachable via ngrok or localhost
- **TODO:** Lock CORS to ngrok domain (currently `allow_origins=["*"]`)

## Table Allowlist

To add a new table, edit `ALLOWED_TABLES` in `backend/main.py`.
