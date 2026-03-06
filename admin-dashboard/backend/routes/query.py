"""SQL query route — raw SQL execution with read-only enforcement."""

from db import pools
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from query import is_read_only_query

router = APIRouter(prefix="/api", tags=["query"])


class QueryRequest(BaseModel):
    sql: str
    db: str = "nhl_betting"


@router.get("/databases")
async def list_databases():
    return [{"name": name} for name in pools]


@router.post("/query")
async def run_query(req: QueryRequest):
    sql = req.sql.strip()
    if not sql:
        raise HTTPException(400, "Empty query")
    if req.db not in pools:
        raise HTTPException(400, f"Unknown database: '{req.db}'")
    if not is_read_only_query(sql):
        raise HTTPException(
            403, "Only read-only queries are allowed (SELECT, WITH, etc.)"
        )
    try:
        rows = await pools[req.db].fetch(sql)
    except Exception as e:
        raise HTTPException(400, str(e))
    columns = [str(k) for k in rows[0].keys()] if rows else []
    return {
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "row_count": len(rows),
    }
