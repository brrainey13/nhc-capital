"""
Migration 001 — Create nhl_picks table.

Idempotent: safe to run multiple times.
Connects as nhc_etl (write user).

Usage:
    cd ~/nhc-capital/nhl-betting
    .venv/bin/python migrations/001_create_nhl_picks.py
"""
import sys

import psycopg2

DSN = "dbname=nhl_betting user=nhc_etl host=localhost port=5432"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS nhl_picks (
    pick_id         SERIAL PRIMARY KEY,
    pick_date       DATE NOT NULL,
    pipeline_run_id TEXT NOT NULL,
    player          TEXT,
    player_team     TEXT,
    market          TEXT,
    bet             TEXT,
    book            TEXT,
    odds            INTEGER,
    line            REAL,
    edge            REAL,
    model_prediction REAL,
    units           REAL,
    dollars         REAL,
    confidence      TEXT,
    sub_strategy    TEXT,
    result          TEXT,
    actual_value    REAL,
    pnl             REAL,
    graded_at       TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);
"""

CREATE_IDX_DATE = """
CREATE INDEX IF NOT EXISTS idx_nhl_picks_pick_date
    ON nhl_picks (pick_date);
"""

CREATE_IDX_RUN = """
CREATE INDEX IF NOT EXISTS idx_nhl_picks_pipeline_run_id
    ON nhl_picks (pipeline_run_id);
"""

GRANT_AGENT = """
GRANT SELECT ON nhl_picks TO nhc_agent;
"""

GRANT_SEQUENCE = """
GRANT USAGE, SELECT ON SEQUENCE nhl_picks_pick_id_seq TO nhc_agent;
"""


def run():
    print("Migration 001: creating nhl_picks table...")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(CREATE_TABLE)
    print("  [OK] nhl_picks table")

    cur.execute(CREATE_IDX_DATE)
    print("  [OK] index on pick_date")

    cur.execute(CREATE_IDX_RUN)
    print("  [OK] index on pipeline_run_id")

    cur.execute(GRANT_AGENT)
    print("  [OK] SELECT grant to nhc_agent")

    cur.execute(GRANT_SEQUENCE)
    print("  [OK] sequence grant to nhc_agent")

    cur.close()
    conn.close()
    print("Migration 001 complete.")


if __name__ == "__main__":
    run()
    sys.exit(0)
