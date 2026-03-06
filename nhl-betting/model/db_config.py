"""Shared Postgres connection helpers for NHL betting model and pipeline code."""

import getpass
import os


def get_db_user() -> str:
    """Resolve the Postgres user from env, falling back to the local account."""
    return (
        os.environ.get("PGUSER")
        or os.environ.get("DB_USER")
        or getpass.getuser()
    )


def get_database_url(db: str = "nhl_betting") -> str:
    """Build a DATABASE_URL-style connection string."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = get_db_user()
    host = os.environ.get("PGHOST") or os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("PGPORT") or os.environ.get("DB_PORT", "5432")
    password = os.environ.get("PGPASSWORD") or os.environ.get("DB_PASS", "")

    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return f"postgresql://{user}@{host}:{port}/{db}"


def get_dsn(db: str = "nhl_betting") -> str:
    """Build a psycopg2-compatible DSN."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = get_db_user()
    host = os.environ.get("PGHOST") or os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("PGPORT") or os.environ.get("DB_PORT", "5432")
    password = os.environ.get("PGPASSWORD") or os.environ.get("DB_PASS", "")

    parts = [f"dbname={db}", f"user={user}", f"host={host}", f"port={port}"]
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)
