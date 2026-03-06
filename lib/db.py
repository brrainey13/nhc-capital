"""
Shared DB connection layer for all NHC projects.

Usage:
    from lib.db import query, query_one, query_df, get_connection, get_conn_string

Respects env vars: DB_HOST, DB_PORT, DB_USER (default: nhc_agent), DB_NAME.
Also respects PGUSER/PGPASSWORD for compatibility with scripts/db-etl.
"""

import os
from contextlib import contextmanager


def get_conn_params(db: str = "nhl_betting") -> dict:
    """Return connection params in dict form for legacy callers and tests."""
    return {
        "host": os.environ.get("DB_HOST") or os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("DB_PORT") or os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER") or os.environ.get("DB_USER", "nhc_agent"),
        "password": os.environ.get("PGPASSWORD") or os.environ.get("DB_PASS", ""),
        "dbname": db,
    }


def get_conn_string(db: str = "nhl_betting") -> str:
    """Build a PostgreSQL connection string."""
    params = get_conn_params(db)
    user = params["user"]
    password = params["password"]
    host = params["host"]
    port = params["port"]
    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return f"postgresql://{user}@{host}:{port}/{db}"


@contextmanager
def get_connection(db: str = "nhl_betting"):
    """Context manager yielding a psycopg2 connection. Auto-commits on success."""
    import psycopg2
    conn = psycopg2.connect(get_conn_string(db))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_conn(db: str = "nhl_betting"):
    """Return a raw psycopg2 connection (caller must close). Prefer get_connection()."""
    import psycopg2
    return psycopg2.connect(get_conn_string(db))


class _SingleConnPool:
    """Minimal pool-like wrapper used by tests and simple scripts."""

    def __init__(self, db: str):
        self.db = db

    def getconn(self):
        return get_conn(self.db)

    def putconn(self, conn):
        conn.close()


def _get_pool(db: str = "nhl_betting"):
    """Return a lightweight pool wrapper for compatibility with older helpers."""
    return _SingleConnPool(db)


def query(sql: str, params=None, db: str = "nhl_betting") -> list:
    """Execute SQL and return list of dicts."""
    import psycopg2.extras
    pool = _get_pool(db)
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


def query_one(sql: str, params=None, db: str = "nhl_betting"):
    """Execute SQL and return one dict or None."""
    rows = query(sql, params, db)
    return rows[0] if rows else None


def query_df(sql: str, params=None, db: str = "nhl_betting"):
    """Execute SQL and return a pandas DataFrame."""
    import pandas as pd
    return pd.read_sql(sql, get_conn_string(db), params=params)
