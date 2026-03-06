"""Migration 002 — Create bankroll ledger table and seed the opening balance."""

from __future__ import annotations

import sys

import psycopg2

DSN = "dbname=nhl_betting user=connorrainey"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS bankroll (
    id SERIAL PRIMARY KEY,
    event_date DATE NOT NULL DEFAULT CURRENT_DATE,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'deposit', 'withdrawal', 'bet_placed', 'bet_graded', 'adjustment', 'initial'
    )),
    amount NUMERIC(10,2) NOT NULL,
    balance NUMERIC(10,2) NOT NULL,
    pick_id INTEGER REFERENCES nhl_picks(pick_id),
    sportsbook TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

CREATE_IDX_DATE = """
CREATE INDEX IF NOT EXISTS idx_bankroll_event_date
    ON bankroll (event_date DESC, id DESC);
"""

CREATE_IDX_PICK = """
CREATE INDEX IF NOT EXISTS idx_bankroll_pick_id
    ON bankroll (pick_id);
"""

SEED_ROW = """
INSERT INTO bankroll (event_date, event_type, amount, balance, notes)
SELECT '2026-01-01', 'initial', 2500.00, 2500.00, 'Initial bankroll - DraftKings'
WHERE NOT EXISTS (
    SELECT 1
    FROM bankroll
    WHERE event_date = '2026-01-01'
      AND event_type = 'initial'
      AND amount = 2500.00
      AND balance = 2500.00
);
"""

GRANTS = [
    "GRANT SELECT ON bankroll TO nhc_agent;",
    "GRANT SELECT ON bankroll TO dashboard_readonly;",
    "GRANT INSERT, SELECT ON bankroll TO nhc_etl;",
    "GRANT USAGE, SELECT ON SEQUENCE bankroll_id_seq TO nhc_agent;",
    "GRANT USAGE, SELECT ON SEQUENCE bankroll_id_seq TO dashboard_readonly;",
    "GRANT USAGE, SELECT ON SEQUENCE bankroll_id_seq TO nhc_etl;",
]


def run() -> None:
    print("Migration 002: creating bankroll table...")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(CREATE_TABLE)
    print("  [OK] bankroll table")

    cur.execute(CREATE_IDX_DATE)
    print("  [OK] index on event_date")

    cur.execute(CREATE_IDX_PICK)
    print("  [OK] index on pick_id")

    cur.execute(SEED_ROW)
    print("  [OK] seed bankroll row")

    for grant in GRANTS:
        cur.execute(grant)
    print("  [OK] grants applied")

    cur.close()
    conn.close()
    print("Migration 002 complete.")


if __name__ == "__main__":
    run()
    sys.exit(0)
