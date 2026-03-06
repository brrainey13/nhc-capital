"""
Shared data ingestion helpers for NHC Capital.

All writes use the nhc_etl role. Validation happens BEFORE any insert.

Usage:
    from lib.ingest import ingest_rows, ingest_df, validate_schema, log_ingestion

    ingest_rows("my_table", [{"col1": "val1"}], db="nhl_betting")
    ingest_df("my_table", df, db="nhl_betting")
"""

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


# ---------------------------------------------------------------------------
# ETL connection (nhc_etl role — INSERT/UPDATE only)
# ---------------------------------------------------------------------------

def _etl_conn_params(db: str = "nhl_betting") -> dict[str, Any]:
    """Connection params for the nhc_etl write role."""
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "user": os.environ.get("DB_ETL_USER", "nhc_etl"),
        "password": os.environ.get("DB_ETL_PASSWORD", ""),
        "dbname": db,
    }


@contextmanager
def get_etl_connection(db: str = "nhl_betting"):
    """Context manager yielding a psycopg2 connection as nhc_etl."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required: pip install psycopg2-binary")
    conn = psycopg2.connect(**_etl_conn_params(db))
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def get_table_columns(table: str, db: str = "nhl_betting") -> list[str]:
    """Fetch column names for a table from information_schema."""
    from lib.db import query
    rows = query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %s ORDER BY ordinal_position",
        [table], db=db,
    )
    return [r["column_name"] for r in rows]


def validate_schema(table: str, rows: list[dict], db: str = "nhl_betting") -> dict:
    """
    Check that row keys match table columns.
    Returns {"valid": bool, "errors": list[str], "extra_cols": list, "missing_cols": list}.
    """
    if not rows:
        return {"valid": True, "errors": [], "extra_cols": [], "missing_cols": []}

    table_cols = set(get_table_columns(table, db))
    if not table_cols:
        return {
            "valid": False,
            "errors": [f"Table '{table}' not found or has no columns"],
            "extra_cols": [],
            "missing_cols": [],
        }

    row_cols = set(rows[0].keys())
    extra = sorted(row_cols - table_cols)
    # missing_cols = table cols not in rows (non-nullable ones would fail on insert)
    errors = []
    if extra:
        errors.append(f"Extra columns not in table: {extra}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "extra_cols": extra,
        "missing_cols": sorted(table_cols - row_cols),
    }


# ---------------------------------------------------------------------------
# Ingestion log table
# ---------------------------------------------------------------------------

_LOG_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS ingestion_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    table_name TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    source TEXT,
    status TEXT NOT NULL,
    error_msg TEXT
);
"""


def _ensure_log_table(db: str = "nhl_betting"):
    """Create ingestion_log if it doesn't exist."""
    with get_etl_connection(db) as conn:
        with conn.cursor() as cur:
            cur.execute(_LOG_TABLE_DDL)
        conn.commit()


def log_ingestion(
    table: str,
    row_count: int,
    source: str | None = None,
    status: str = "success",
    error_msg: str | None = None,
    db: str = "nhl_betting",
):
    """Record an ingestion event in ingestion_log."""
    _ensure_log_table(db)
    with get_etl_connection(db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_log (timestamp, table_name, row_count, source, status, error_msg) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [datetime.now(timezone.utc), table, row_count, source, status, error_msg],
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Bulk insert helpers
# ---------------------------------------------------------------------------

def ingest_rows(
    table: str,
    rows: list[dict],
    db: str = "nhl_betting",
    source: str | None = None,
    validate: bool = True,
) -> int:
    """
    Bulk insert rows into a table using nhc_etl role.
    Returns number of rows inserted.
    """
    if not rows:
        return 0

    # Validate before insert
    if validate:
        result = validate_schema(table, rows, db)
        if not result["valid"]:
            error = "; ".join(result["errors"])
            log_ingestion(table, 0, source, "failed", error, db)
            raise ValueError(f"Schema validation failed: {error}")

    columns = list(rows[0].keys())
    col_str = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    with get_etl_connection(db) as conn:
        with conn.cursor() as cur:
            values = [[row.get(c) for c in columns] for row in rows]
            psycopg2.extras.execute_batch(
                cur,
                f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})",
                values,
            )
        conn.commit()

    log_ingestion(table, len(rows), source, "success", db=db)
    return len(rows)


def ingest_df(
    table: str,
    df: "Any",  # pandas DataFrame
    db: str = "nhl_betting",
    source: str | None = None,
    validate: bool = True,
) -> int:
    """
    Insert a pandas DataFrame into a table.
    Returns number of rows inserted.
    """
    rows = df.to_dict(orient="records")
    return ingest_rows(table, rows, db=db, source=source, validate=validate)
