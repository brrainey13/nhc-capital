
#!/usr/bin/env python3
"""
Scrape historical NHL goalie saves O/U prop odds from BettingPros API.

Data source: https://www.bettingpros.com/nhl/odds/player-props/saves/
API endpoint: https://api.bettingpros.com/v3/

Coverage: 2022-23 season onward (Oct 2022 - present)
Market ID 322 = NHL Goalie Saves O/U

Usage:
    python scrape_saves_odds.py                    # Scrape all seasons
    python scrape_saves_odds.py --season 2025      # Scrape 2025-26 only
    python scrape_saves_odds.py --start 2024-10-01 # From specific date
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import psycopg2
import psycopg2.extras
import requests

from lib.db import get_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# --- Config ---
API_BASE = "https://api.bettingpros.com/v3"
API_KEY = "CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh"
MARKET_ID = 322  # Saves O/U
SPORT = "NHL"
LOCATION = "OH"
HEADERS = {"x-api-key": API_KEY, "User-Agent": "Mozilla/5.0"}

# Sportsbook ID mapping (from BettingPros)
BOOK_MAP = {
    0: "consensus",
    10: "fanduel",
    13: "caesars",
    19: "betmgm",
    33: "espnbet",
    39: "draftkings",
    45: "bet365",
    49: "hardrock",
    60: "novig",
}

# Season date ranges (regular season approximate)
SEASONS = {
    2022: ("2022-10-07", "2023-06-15"),
    2023: ("2023-10-07", "2024-06-15"),
    2024: ("2024-10-04", "2025-06-15"),
    2025: ("2025-10-04", "2026-06-15"),
}

RATE_LIMIT_DELAY = 0.3  # seconds between API calls


def api_get(endpoint: str, params: dict) -> dict:
    """Make API request with retry logic."""
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt == 2:
                log.error(f"API failed after 3 attempts: {e}")
                return {}
            wait = (attempt + 1) * 2
            log.warning(f"API error (attempt {attempt+1}): {e}, retrying in {wait}s")
            time.sleep(wait)
    return {}


def get_events_for_date(date_str: str) -> list:
    """Get all NHL events for a given date."""
    data = api_get("events", {"sport": SPORT, "date": date_str})
    return data.get("events", [])


def get_saves_offers(event_id: int) -> list:
    """Get goalie saves O/U offers for an event."""
    data = api_get(
        "offers",
        {
            "sport": SPORT,
            "market_id": MARKET_ID,
            "event_id": event_id,
            "location": LOCATION,
        },
    )
    return data.get("offers", [])


def parse_offer(offer: dict, event: dict) -> list:
    """Parse a single offer into rows for the database.

    Returns a list of dicts, one per sportsbook line found.
    """
    rows = []

    player_info = offer.get("participants", [{}])[0]
    player = player_info.get("player", {})
    player_name = player_info.get("name", "")
    player_team = player.get("team", "")
    bp_player_id = int(player_info.get("id", 0))

    event_date = event.get("scheduled", "")[:10]
    home_team = event.get("home", "")
    away_team = event.get("visitor", "")
    event_id = event.get("id")

    # Get opening line
    selections = offer.get("selections", [])
    over_sel = next((s for s in selections if s.get("selection") == "over"), None)
    under_sel = next((s for s in selections if s.get("selection") == "under"), None)

    if not over_sel:
        return rows

    opening = over_sel.get("opening_line", {})
    opening_line = opening.get("line")
    opening_over_odds = opening.get("cost")
    opening_created = opening.get("created", "")

    # Get lines from each sportsbook
    for book in over_sel.get("books", []):
        book_id = book.get("id")
        book_name = BOOK_MAP.get(book_id, f"book_{book_id}")

        for line_data in book.get("lines", []):
            over_odds = line_data.get("cost")
            over_line = line_data.get("line")
            updated = line_data.get("updated", "")
            is_best = line_data.get("best", False)

            # Find matching under line from same book
            under_odds = None
            if under_sel:
                for ubook in under_sel.get("books", []):
                    if ubook.get("id") == book_id:
                        ulines = ubook.get("lines", [])
                        if ulines:
                            under_odds = ulines[0].get("cost")
                            ulines[0].get("line")
                        break

            # Get metrics if available
            metrics = line_data.get("metrics") or {}

            rows.append(
                {
                    "event_id": event_id,
                    "event_date": event_date,
                    "home_team": home_team,
                    "away_team": away_team,
                    "bp_player_id": bp_player_id,
                    "player_name": player_name,
                    "player_team": player_team,
                    "book_id": book_id,
                    "book_name": book_name,
                    "line": over_line,
                    "over_odds": over_odds,
                    "under_odds": under_odds,
                    "opening_line": opening_line,
                    "opening_over_odds": opening_over_odds,
                    "opening_created": opening_created,
                    "is_best": is_best,
                    "fair_probability": metrics.get("fair_probability"),
                    "market_ev": metrics.get("market_ev"),
                    "updated_at": updated,
                }
            )

    return rows


def create_table(conn):
    """Create the saves_odds table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS saves_odds (
                id SERIAL PRIMARY KEY,
                event_id INTEGER NOT NULL,
                event_date TEXT NOT NULL,
                home_team TEXT,
                away_team TEXT,
                bp_player_id INTEGER,
                player_name TEXT NOT NULL,
                player_team TEXT,
                book_id INTEGER,
                book_name TEXT,
                line DOUBLE PRECISION,
                over_odds INTEGER,
                under_odds INTEGER,
                opening_line DOUBLE PRECISION,
                opening_over_odds INTEGER,
                opening_created TEXT,
                is_best BOOLEAN DEFAULT FALSE,
                fair_probability DOUBLE PRECISION,
                market_ev DOUBLE PRECISION,
                updated_at TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_id, bp_player_id, book_id)
            );

            CREATE INDEX IF NOT EXISTS idx_saves_odds_date ON saves_odds(event_date);
            CREATE INDEX IF NOT EXISTS idx_saves_odds_player ON saves_odds(bp_player_id);
            CREATE INDEX IF NOT EXISTS idx_saves_odds_event ON saves_odds(event_id);
        """)
        conn.commit()
    log.info("Table saves_odds ready")


def upsert_rows(conn, rows: list):
    """Upsert rows into saves_odds."""
    if not rows:
        return 0

    sql = """
        INSERT INTO saves_odds (
            event_id, event_date, home_team, away_team,
            bp_player_id, player_name, player_team,
            book_id, book_name, line, over_odds, under_odds,
            opening_line, opening_over_odds, opening_created,
            is_best, fair_probability, market_ev, updated_at
        ) VALUES (
            %(event_id)s, %(event_date)s, %(home_team)s, %(away_team)s,
            %(bp_player_id)s, %(player_name)s, %(player_team)s,
            %(book_id)s, %(book_name)s, %(line)s, %(over_odds)s, %(under_odds)s,
            %(opening_line)s, %(opening_over_odds)s, %(opening_created)s,
            %(is_best)s, %(fair_probability)s, %(market_ev)s, %(updated_at)s
        )
        ON CONFLICT (event_id, bp_player_id, book_id)
        DO UPDATE SET
            line = EXCLUDED.line,
            over_odds = EXCLUDED.over_odds,
            under_odds = EXCLUDED.under_odds,
            is_best = EXCLUDED.is_best,
            fair_probability = EXCLUDED.fair_probability,
            market_ev = EXCLUDED.market_ev,
            updated_at = EXCLUDED.updated_at,
            scraped_at = CURRENT_TIMESTAMP
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows)
    conn.commit()
    return len(rows)


def scrape_date_range(conn, start_date: str, end_date: str):
    """Scrape all saves odds for a date range."""
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    today = datetime.now()

    total_rows = 0
    total_events = 0
    days_processed = 0

    while current <= min(end, today):
        date_str = current.strftime("%Y-%m-%d")
        events = get_events_for_date(date_str)
        time.sleep(RATE_LIMIT_DELAY)

        if not events:
            current += timedelta(days=1)
            continue

        day_rows = 0
        for event in events:
            offers = get_saves_offers(event["id"])
            time.sleep(RATE_LIMIT_DELAY)

            for offer in offers:
                rows = parse_offer(offer, event)
                if rows:
                    inserted = upsert_rows(conn, rows)
                    day_rows += inserted

            total_events += 1

        if day_rows > 0:
            total_rows += day_rows
            log.info(
                f"{date_str}: {len(events)} events, {day_rows} lines "
                f"(total: {total_rows} lines, {total_events} events)"
            )

        days_processed += 1
        if days_processed % 30 == 0:
            log.info(f"Progress: {days_processed} days processed, {total_rows} total lines")

        current += timedelta(days=1)

    return total_rows, total_events


def get_last_scraped_date(conn):
    """Get the most recent event_date in the database."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(event_date) FROM saves_odds")
        result = cur.fetchone()
        return result[0] if result and result[0] else None


def main():
    parser = argparse.ArgumentParser(description="Scrape NHL goalie saves O/U odds")
    parser.add_argument("--season", type=int, help="Scrape specific season (e.g. 2025)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--resume", action="store_true", help="Resume from last scraped date")
    args = parser.parse_args()

    conn = get_conn(db="nhl_betting")
    create_table(conn)

    if args.resume:
        last_date = get_last_scraped_date(conn)
        if last_date:
            start = last_date  # Re-scrape last day to catch updates
            end = datetime.now().strftime("%Y-%m-%d")
            log.info(f"Resuming from {start}")
            total_rows, total_events = scrape_date_range(conn, start, end)
        else:
            log.info("No existing data, starting from scratch")
            args.season = None  # Fall through to scrape all

    if args.season:
        if args.season not in SEASONS:
            log.error(f"Unknown season {args.season}. Available: {list(SEASONS.keys())}")
            sys.exit(1)
        start, end = SEASONS[args.season]
        log.info(f"Scraping {args.season}-{args.season+1} season: {start} to {end}")
        total_rows, total_events = scrape_date_range(conn, start, end)
    elif args.start:
        start = args.start
        end = args.end or datetime.now().strftime("%Y-%m-%d")
        log.info(f"Scraping {start} to {end}")
        total_rows, total_events = scrape_date_range(conn, start, end)
    elif not args.resume:
        # Scrape all seasons
        grand_total_rows = 0
        grand_total_events = 0
        for season, (start, end) in sorted(SEASONS.items()):
            log.info(f"\n{'='*50}")
            log.info(f"Scraping {season}-{season+1} season: {start} to {end}")
            log.info(f"{'='*50}")
            rows, events = scrape_date_range(conn, start, end)
            grand_total_rows += rows
            grand_total_events += events
            log.info(f"Season {season}-{season+1}: {rows} lines from {events} events")

        total_rows = grand_total_rows
        total_events = grand_total_events

    log.info(f"\nDone! Total: {total_rows} lines from {total_events} events")

    # Print summary
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                substring(event_date, 1, 7) as month,
                count(DISTINCT event_id) as games,
                count(DISTINCT bp_player_id) as goalies,
                count(*) as lines
            FROM saves_odds
            GROUP BY 1
            ORDER BY 1
        """)
        rows = cur.fetchall()
        if rows:
            log.info("\nMonthly summary:")
            log.info(f"{'Month':>10} {'Games':>8} {'Goalies':>8} {'Lines':>8}")
            for month, games, goalies, lines in rows:
                log.info(f"{month:>10} {games:>8} {goalies:>8} {lines:>8}")

    conn.close()


if __name__ == "__main__":
    main()
