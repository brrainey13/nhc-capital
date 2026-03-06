#!/usr/bin/env bash
# Daily NHL odds scraper — runs saves_odds + player_odds scrapers
# Designed for launchd (daily at 10 AM ET, before games)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/../.venv/bin/python"
LOG="$DIR/scrape_log.txt"
PSQL="${PSQL_PATH:-psql}"

echo "=== $(date) — Daily odds scrape ===" >> "$LOG"

# Check Postgres is up
if ! $PSQL -U "${PGUSER:-nhc_agent}" -d nhl_betting -c "SELECT 1" &>/dev/null; then
    echo "ERROR: Postgres not reachable" >> "$LOG"
    exit 1
fi

# Saves odds (goalie props — primary strategy)
echo "Running saves odds scraper (--resume)..." >> "$LOG"
$VENV "$DIR/scrape_saves_odds.py" --resume >> "$LOG" 2>&1 || echo "WARN: saves scraper failed" >> "$LOG"

# Player odds (points, assists, SOG props — Strategy #2)
# These scrapers take start end as positional args (YYYY-MM-DD)
YESTERDAY=$(date -v-1d +%Y-%m-%d)
TODAY=$(date +%Y-%m-%d)

if [ -f "$DIR/scrape_player_odds.py" ]; then
    echo "Running player odds scraper ($YESTERDAY to $TODAY)..." >> "$LOG"
    $VENV "$DIR/scrape_player_odds.py" "$YESTERDAY" "$TODAY" >> "$LOG" 2>&1 || echo "WARN: player odds scraper failed" >> "$LOG"
fi

# SOG odds
if [ -f "$DIR/scrape_sog_odds.py" ]; then
    echo "Running SOG odds scraper ($YESTERDAY to $TODAY)..." >> "$LOG"
    $VENV "$DIR/scrape_sog_odds.py" "$YESTERDAY" "$TODAY" >> "$LOG" 2>&1 || echo "WARN: SOG odds scraper failed" >> "$LOG"
fi

echo "=== Done ===" >> "$LOG"
