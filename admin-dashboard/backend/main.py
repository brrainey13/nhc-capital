"""NHC Admin Dashboard API — thin entrypoint.

Modules:
  db.py          — connection pools, table discovery
  auth.py        — authentication middleware
  query.py       — SQL validation helpers
  routes/tables  — table browsing endpoints
  routes/query   — raw SQL query execution
  routes/usage   — session telemetry and token usage
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from auth import AuthMiddleware
from db import close_pools, init_pools
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from routes.claude_limits import router as claude_limits_router
from routes.comps import router as comps_router
from routes.ingest import router as ingest_router
from routes.nhl_bankroll import router as nhl_bankroll_router
from routes.nhl_model import router as nhl_model_router
from routes.query import router as query_router
from routes.real_estate import router as real_estate_router
from routes.tables import router as tables_router
from routes.usage import router as usage_router

load_dotenv(Path(__file__).parent.parent / ".env")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"
PUBLIC_DIR = Path(__file__).parent.parent / "frontend" / "public"

_default_origins = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000"
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pools()
    yield
    await close_pools()


app = FastAPI(title="NHC Admin Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.include_router(tables_router)
app.include_router(query_router)
app.include_router(real_estate_router)
app.include_router(comps_router)
app.include_router(usage_router)
app.include_router(claude_limits_router)
app.include_router(ingest_router)
app.include_router(nhl_bankroll_router)
app.include_router(nhl_model_router)

# Serve frontend
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path in ("manifest.json", "sw.js", "icon-192.png", "icon-512.png"):
            public_file = PUBLIC_DIR / full_path
            if public_file.exists():
                return FileResponse(public_file)
        # no-cache on index.html so deploys take effect immediately
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
