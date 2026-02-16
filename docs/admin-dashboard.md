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

## Running Locally

```bash
cd admin-dashboard/backend
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Frontend is pre-built into `frontend/dist/` and served by FastAPI at `/`.

## Rebuilding Frontend

```bash
cd admin-dashboard/frontend
npm install
npm run build
```

## Security

- SQL queries are regex-checked: INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE are blocked
- Only tables in `ALLOWED_TABLES` set are queryable
- Backend binds to `127.0.0.1` — only reachable via ngrok or localhost
- **TODO:** Lock CORS to ngrok domain (currently `allow_origins=["*"]`)

## Table Allowlist

To add a new table, edit `ALLOWED_TABLES` in `backend/main.py`.
