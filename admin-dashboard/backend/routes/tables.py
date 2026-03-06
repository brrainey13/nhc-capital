"""Table browsing routes — list, schema, data, grouped, distinct, examples."""

import json

from db import (
    ALLOWED_TABLES,
    TABLE_DB_MAP,
    get_column_types,
    get_pool,
    get_table_columns,
    pools,
)
from fastapi import APIRouter, HTTPException, Query
from query import (
    DATE_PG_TYPES,
    NUMERIC_PG_TYPES,
    build_operator_filter,
    validate_column,
    validate_table_name,
)

router = APIRouter(prefix="/api/tables", tags=["tables"])


@router.get("")
async def list_tables():
    results = []
    for tbl in sorted(ALLOWED_TABLES):
        db_name = TABLE_DB_MAP.get(tbl, "nhl_betting")
        tbl_pool = pools[db_name]
        # Use pg_class estimate for speed; fall back to COUNT(*) for small/new tables
        count = await tbl_pool.fetchval(
            "SELECT GREATEST(c.reltuples::bigint, 0) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = $1", tbl
        )
        if count is None or count < 0:
            count = await tbl_pool.fetchval(f'SELECT COUNT(*) FROM "{tbl}"')
        results.append({"name": tbl, "row_count": count, "database": db_name})
    return results


@router.get("/{name}/schema")
async def table_schema(name: str):
    validate_table_name(name, ALLOWED_TABLES)
    p = get_pool(name)
    rows = await p.fetch(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 "
        "ORDER BY ordinal_position",
        name,
    )
    return {"table": name, "columns": [dict(r) for r in rows]}


@router.get("/{name}/data")
async def table_data(
    name: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    filters: str | None = Query(None),
):
    validate_table_name(name, ALLOWED_TABLES)
    valid_cols = await get_table_columns(name)
    col_types = await get_column_types(name)

    where_parts: list[str] = []
    params: list[object] = []
    param_idx = 1

    if filters:
        try:
            parsed = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid filters JSON")

        if isinstance(parsed, list):
            for f in parsed:
                if not isinstance(f, dict) or "column" not in f or "operator" not in f:
                    raise HTTPException(400, "Each filter must have 'column' and 'operator'")
                col = f["column"]
                validate_column(col, valid_cols, "filter column")
                col_type = col_types.get(col, "text")
                clauses, param_idx = build_operator_filter(
                    col, f["operator"], f.get("value", ""), col_type, params, param_idx
                )
                where_parts.extend(clauses)

        elif isinstance(parsed, dict):
            for col, val in parsed.items():
                validate_column(col, valid_cols, "filter column")
                if isinstance(val, dict) and ("min" in val or "max" in val):
                    if "min" in val:
                        where_parts.append(f'"{col}" >= ${param_idx}')
                        params.append(val["min"])
                        param_idx += 1
                    if "max" in val:
                        where_parts.append(f'"{col}" <= ${param_idx}')
                        params.append(val["max"])
                        param_idx += 1
                else:
                    where_parts.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
                    params.append(f"%{val}%")
                    param_idx += 1
        else:
            raise HTTPException(400, "Filters must be a JSON array or object")

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    order_sql = ""
    if sort_by:
        validate_column(sort_by, valid_cols, "sort_by column")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        order_sql = f' ORDER BY "{sort_by}" {direction} NULLS LAST'

    p = get_pool(name)
    # Use pg_class estimate for unfiltered total on large tables (avoids full scan)
    total = await p.fetchval(
        "SELECT GREATEST(c.reltuples::bigint, 0) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = $1", name
    )
    if total is None or total < 1:
        total = await p.fetchval(f'SELECT COUNT(*) FROM "{name}"')
    if where_sql:
        filtered_total = await p.fetchval(f'SELECT COUNT(*) FROM "{name}"{where_sql}', *list(params))
    else:
        filtered_total = total

    data_sql = (
        f'SELECT * FROM "{name}"{where_sql}{order_sql}'
        f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
    )
    params.append(limit)
    params.append(offset)

    rows = await p.fetch(data_sql, *params)
    columns = [str(k) for k in rows[0].keys()] if rows else []
    return {
        "table": name,
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "total": total,
        "filtered_total": filtered_total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{name}/grouped")
async def table_grouped(name: str, group_by: str = Query(...)):
    validate_table_name(name, ALLOWED_TABLES)
    valid_cols = await get_table_columns(name)
    validate_column(group_by, valid_cols, "group_by column")
    p = get_pool(name)
    rows = await p.fetch(
        f'SELECT "{group_by}" AS value, COUNT(*) AS count'
        f' FROM "{name}" GROUP BY "{group_by}" ORDER BY count DESC'
    )
    return [{"value": r["value"], "count": r["count"]} for r in rows]


@router.get("/{name}/distinct")
async def table_distinct(
    name: str,
    column: str = Query(...),
    limit: int = Query(200, ge=1, le=1000),
    q: str = Query("", description="Optional prefix/substring filter"),
):
    validate_table_name(name, ALLOWED_TABLES)
    valid_cols = await get_table_columns(name)
    validate_column(column, valid_cols, "column")
    p = get_pool(name)
    if q.strip():
        rows = await p.fetch(
            f'SELECT DISTINCT "{column}" AS value FROM "{name}"'
            f' WHERE CAST("{column}" AS TEXT) ILIKE $1'
            f' ORDER BY "{column}" LIMIT $2',
            f"%{q}%", limit,
        )
    else:
        rows = await p.fetch(
            f'SELECT DISTINCT "{column}" AS value FROM "{name}"'
            f' ORDER BY "{column}" LIMIT $1',
            limit,
        )
    return [r["value"] for r in rows]


@router.get("/{name}/examples")
async def table_examples(name: str):
    """Generate example SQL queries for a table based on its schema."""
    validate_table_name(name, ALLOWED_TABLES)
    p = get_pool(name)

    schema_rows = await p.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 ORDER BY ordinal_position",
        name,
    )
    if not schema_rows:
        return []

    columns = [(r["column_name"], r["data_type"]) for r in schema_rows]
    examples: list[dict[str, str]] = []

    # 1. Basic preview
    examples.append({
        "label": "Preview first 10 rows",
        "sql": f'SELECT * FROM "{name}" LIMIT 10',
    })

    # 2. Row count
    examples.append({
        "label": "Total row count",
        "sql": f'SELECT COUNT(*) AS total FROM "{name}"',
    })

    # 3. Numeric aggregations
    numeric_cols = [c for c, dt in columns if dt in NUMERIC_PG_TYPES]
    if numeric_cols:
        col = numeric_cols[0]
        examples.append({
            "label": f"Stats on {col}",
            "sql": (
                f'SELECT MIN("{col}"), MAX("{col}"), '
                f'AVG("{col}")::numeric(12,2), COUNT(*) '
                f'FROM "{name}"'
            ),
        })

    # 4. Date range
    date_cols = [c for c, dt in columns if dt in DATE_PG_TYPES]
    if date_cols:
        col = date_cols[0]
        examples.append({
            "label": f"Date range on {col}",
            "sql": f'SELECT MIN("{col}"), MAX("{col}") FROM "{name}"',
        })

    # 5. Group by first text column
    text_cols = [
        c for c, dt in columns
        if dt not in NUMERIC_PG_TYPES and dt not in DATE_PG_TYPES
        and dt in ("text", "character varying", "varchar")
    ]
    if text_cols:
        col = text_cols[0]
        examples.append({
            "label": f"Top values in {col}",
            "sql": (
                f'SELECT "{col}", COUNT(*) AS cnt '
                f'FROM "{name}" GROUP BY "{col}" '
                f'ORDER BY cnt DESC LIMIT 20'
            ),
        })

    # 6. Recent rows if date column exists
    if date_cols:
        col = date_cols[0]
        examples.append({
            "label": f"Most recent rows by {col}",
            "sql": (
                f'SELECT * FROM "{name}" '
                f'ORDER BY "{col}" DESC LIMIT 20'
            ),
        })

    return examples


@router.get("/{name}/preview")
async def table_preview(name: str, rows: int = Query(5, ge=1, le=50)):
    """Quick preview of a table — first N rows + schema summary."""
    validate_table_name(name, ALLOWED_TABLES)
    db_name = TABLE_DB_MAP.get(name, "nhl_betting")
    p = get_pool(name)

    count = await p.fetchval(
        "SELECT GREATEST(c.reltuples::bigint, 0) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = $1", name
    )
    if count is None or count < 1:
        count = await p.fetchval(f'SELECT COUNT(*) FROM "{name}"')
    schema_rows = await p.fetch(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 "
        "ORDER BY ordinal_position",
        name,
    )
    data_rows = await p.fetch(f'SELECT * FROM "{name}" LIMIT $1', rows)
    columns = [str(k) for k in data_rows[0].keys()] if data_rows else []

    return {
        "table": name,
        "database": db_name,
        "row_count": count,
        "column_count": len(schema_rows),
        "schema": [dict(r) for r in schema_rows],
        "columns": columns,
        "sample_rows": [dict(r) for r in data_rows],
    }
