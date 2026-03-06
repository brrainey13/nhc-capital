-- Historical odds storage — every line we pull from The Odds API
-- One row per player/market/book/side/line per pull
-- Enables: line movement tracking, CLV analysis, sharp book detection

CREATE TABLE IF NOT EXISTS odds_history (
    id              SERIAL PRIMARY KEY,
    pull_id         TEXT NOT NULL,           -- UUID per pipeline run (groups all lines from one pull)
    pulled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_id        TEXT NOT NULL,           -- Odds API event ID
    event_date      DATE NOT NULL,           -- Game date (EST)
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    commence_time   TIMESTAMPTZ,             -- Game start time
    book            TEXT NOT NULL,            -- e.g. draftkings, fanduel
    market          TEXT NOT NULL,            -- e.g. player_points, totals, player_total_saves
    player          TEXT,                     -- NULL for game-level markets (totals)
    side            TEXT NOT NULL,            -- Over/Under/Yes for props, team name for moneyline
    line            REAL,                     -- e.g. 0.5, 5.5
    odds            INTEGER NOT NULL,         -- American odds (-110, +150, etc.)
    api_key_used    INTEGER DEFAULT 1         -- Which key (1 or 2) was used
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_odds_history_pull ON odds_history (pull_id);
CREATE INDEX IF NOT EXISTS idx_odds_history_event ON odds_history (event_id, market);
CREATE INDEX IF NOT EXISTS idx_odds_history_player ON odds_history (player, market, event_date);
CREATE INDEX IF NOT EXISTS idx_odds_history_date ON odds_history (event_date);

-- Example queries:
-- Line movement for a player: SELECT * FROM odds_history WHERE player = 'Nathan MacKinnon' AND market = 'player_points' ORDER BY pulled_at;
-- Best odds across books: SELECT DISTINCT ON (player, market, side, line) * FROM odds_history WHERE event_date = '2026-03-06' ORDER BY player, market, side, line, odds DESC;
-- CLV check: Compare odds at pick time vs closing odds for same line
