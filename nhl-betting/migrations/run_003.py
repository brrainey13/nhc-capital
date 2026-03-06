"""Create odds_history table for storing all Odds API pulls."""
import psycopg2

conn = psycopg2.connect("postgresql://nhc_etl@localhost:5432/nhl_betting")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS odds_history (
    id              SERIAL PRIMARY KEY,
    pull_id         TEXT NOT NULL,
    pulled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_id        TEXT NOT NULL,
    event_date      DATE NOT NULL,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    commence_time   TIMESTAMPTZ,
    book            TEXT NOT NULL,
    market          TEXT NOT NULL,
    player          TEXT,
    side            TEXT NOT NULL,
    line            REAL,
    odds            INTEGER NOT NULL,
    api_key_used    INTEGER DEFAULT 1
)
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_odds_history_pull ON odds_history (pull_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_odds_history_event ON odds_history (event_id, market)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_odds_history_player ON odds_history (player, market, event_date)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_odds_history_date ON odds_history (event_date)")

conn.commit()
cur.close()
conn.close()
print("✅ odds_history table created with indexes")
