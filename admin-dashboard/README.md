# NHC Admin Dashboard

Database explorer for the NHC Capital PostgreSQL database. Browse tables, view schemas, and run read-only SQL queries.

## Stack
- **Backend:** FastAPI + asyncpg (Python)
- **Frontend:** React + Vite + TypeScript
- **Database:** PostgreSQL 17

## Setup
```bash
cd admin-dashboard
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

## Quick Start
```bash
./run.sh
```
- Backend: http://localhost:8000
- Frontend: http://localhost:3000

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/health | Health check |
| GET | /api/tables | List tables with row counts |
| GET | /api/tables/{name}/schema | Column info |
| GET | /api/tables/{name}/data | Paginated data (?limit=100&offset=0) |
| POST | /api/query | Run read-only SQL |

## Tests
```bash
cd admin-dashboard && .venv/bin/pytest backend/tests/ -v
```
