# Admin Dashboard

Internal ops dashboard for NH Capital. Browse database tables, inspect schemas, and run read-only SQL queries.

## Stack

- **Backend:** Python / FastAPI (port 8000)
- **Frontend:** React / Vite / TypeScript (port 3000)
- **Database:** PostgreSQL 17

## Quick Start

```bash
./run.sh
```

This installs dependencies and starts both servers. Open http://localhost:3000.

## Manual Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/tables` | List all tables with row counts |
| GET | `/api/tables/{name}/schema` | Column info for a table |
| GET | `/api/tables/{name}/data?limit=100&offset=0` | Paginated table data |
| GET | `/api/query?sql=SELECT...` | Run read-only SQL (SELECT only) |

## Tests

```bash
cd backend
pytest tests/ -v
```

## Features

- Sidebar listing all 22 database tables with row counts
- Table viewer with schema inspector and pagination
- SQL query editor with Cmd+Enter execution
- Write protection: only SELECT queries allowed
- Dark theme UI
