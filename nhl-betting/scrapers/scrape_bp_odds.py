#!/usr/bin/env python3
"""
Scrape NHL player prop odds from BettingPros API — all markets.

Markets: Points (319), Goals (318), Assists (320), Shots (321), Saves (322)
Books: DraftKings, FanDuel, Hard Rock (filtered)
Data: Opening lines, current lines, fair probability, market EV

Usage:
    python scrape_bp_odds.py --season 2025       # Full 2025-26 season
    python scrape_bp_odds.py --date 2026-03-09    # Single date
    python scrape_bp_odds.py --resume              # From last scraped date
    python scrape_bp_odds.py --start 2025-10-04   # From specific date
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# --- Config ---
API_BASE = "https://api.bettingpros.com/v3"
API_KEY = os.environ.get("BETTINGPROS_API_KEY", "")
SPORT = "NHL"
LOCATION = "OH"
HEADERS = {"x-api-key": API_KEY, "User-Agent": "Mozilla/5.0"}

# Markets we care about
MARKETS = {
    318: "goals",
    319: "points",
    320: "assists",
    321: "shots",
    322: "saves",
}

# Sportsbook ID mapping — ONLY the books we have access to
BOOK_FILTER = {
    10: "fanduel",
    39: "draftkings",
    49: "hardrock",
}

# Season date ranges
SEASONS = {
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
            log.warning(f"API error (attempt {attempt + 1}): {e}, retrying in {wait}s")
            time.sleep(wait)
    return {}


def get_events_for_date(date_str: str) -> list:
    """Get all NHL events for a given date."""
    data = api_get("events", {"sport": SPORT, "date": date_str})
    return data.get("events", [])


def get_offers(event_id: int, market_id: int) -> list:
    """Get player prop offers for an event and market."""
    data = api_get(
        "offers",
        {
            "sport": SPORT,
            "market_id": market_id,
            "event_id": event_id,
            "location": LOCATION,
        },
    )
    return data.get("offers", [])


def parse_offer(offer: dict, event: dict, market_name: str) -> list:
    """Parse a single offer into rows — filtered to our books only."""
    rows = []

    player_info = offer.get("participants", [{}])[0]
    player = player_info.get("player", {})
    player_name = player_info.get("name", "")
    player_team = player.get("team", "")
    bp_player_id = int(player_info.get("id", 0))
    player_position = player.get("position", "")

    event_date = event.get("scheduled", "")[:10]
    home_team = event.get("home", "")
    away_team = event.get("visitor", "")
    event_id = event.get("id")

    selections = offer.get("selections", [])
    over_sel = next((s for s in selections if s.get("selection") == "over"), None)
    under_sel = next((s for s in selections if s.get("selection") == "under"), None)

    if not over_sel:
        return rows

    # Opening line
    opening = over_sel.get("opening_line", {})
    opening_line = opening.get("line")
    opening_over_odds = opening.get("cost")
    opening_created = opening.get("created", "")

    # Get lines from each sportsbook — FILTERED to our books
    for book in over_sel.get("books", []):
        book_id = book.get("id")
        if book_id not in BOOK_FILTER:
            continue

        book_name = BOOK_FILTER[book_id]

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
                        break

            # Metrics
            metrics = line_data.get("metrics") or {}

            rows.append(
                {
                    "market": market_name,
                    "event_id": event_id,
                    "event_date": event_date,
                    "home_team": home_team,
                    "away_team": away_team,
                    "bp_player_id": bp_player_id,
                    "player_name": player_name,
                    "player_team": player_team,
                    "player_position": player_position,
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


def verify_table(conn):
    """Verify bp_player_odds table exists."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name='bp_player_odds'"
        )
        if not cur.fetchone():
            log.error(
                "Table bp_player_odds does not exist. "
                "Create it with scripts/db-etl or as superuser."
            )
            sys.exit(1)
    log.info("Table bp_player_odds ready")


def upsert_rows(conn, rows: list):
    """Upsert rows into bp_player_odds."""
    if not rows:
        return 0

    sql = """
        INSERT INTO bp_player_odds (
            market, event_id, event_date, home_team, away_team,
            bp_player_id, player_name, player_team, player_position,
            book_id, book_name, line, over_odds, under_odds,
            opening_line, opening_over_odds, opening_created,
            is_best, fair_probability, market_ev, updated_at
        ) VALUES (
            %(market)s, %(event_id)s, %(event_date)s, %(home_team)s, %(away_team)s,
            %(bp_player_id)s, %(player_name)s, %(player_team)s, %(player_position)s,
            %(book_id)s, %(book_name)s, %(line)s, %(over_odds)s, %(under_odds)s,
            %(opening_line)s, %(opening_over_odds)s, %(opening_created)s,
            %(is_best)s, %(fair_probability)s, %(market_ev)s, %(updated_at)s
        )
        ON CONFLICT (market, event_id, bp_player_id, book_id)
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


def scrape_date(conn, date_str: str) -> dict:
    """Scrape all markets for all events on a given date.

    Returns dict with counts per market.
    """
    events = get_events_for_date(date_str)
    time.sleep(RATE_LIMIT_DELAY)

    if not events:
        return {}

    counts = {}
    for market_id, market_name in MARKETS.items():
        market_rows = []
        for event in events:
            offers = get_offers(event["id"], market_id)
            time.sleep(RATE_LIMIT_DELAY)

            for offer in offers:
                rows = parse_offer(offer, event, market_name)
                market_rows.extend(rows)

        if market_rows:
            inserted = upsert_rows(conn, market_rows)
            counts[market_name] = inserted

    return counts


def scrape_date_range(conn, start_date: str, end_date: str):
    """Scrape all markets for a date range."""
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    today = datetime.now()

    total_rows = 0
    days_processed = 0
    days_with_data = 0

    while current <= min(end, today):
        date_str = current.strftime("%Y-%m-%d")
        counts = scrape_date(conn, date_str)

        if counts:
            day_total = sum(counts.values())
            total_rows += day_total
            days_with_data += 1
            market_str = " | ".join(f"{m}:{n}" for m, n in sorted(counts.items()))
            log.info(f"{date_str}: {day_total} lines ({market_str})")

        days_processed += 1
        if days_processed % 10 == 0:
            log.info(
                f"  Progress: {days_processed} days, "
                f"{days_with_data} with data, {total_rows} total lines"
            )

        current += timedelta(days=1)

    return total_rows, days_with_data


def get_last_scraped_date(conn):
    """Get the most recent event_date in the database."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(event_date) FROM bp_player_odds")
        result = cur.fetchone()
        return result[0] if result and result[0] else None


def main():
    parser = argparse.ArgumentParser(
        description="Scrape NHL player prop odds from BettingPros"
    )
    parser.add_argument("--season", type=int, help="Scrape specific season (e.g. 2025)")
    parser.add_argument("--date", type=str, help="Scrape single date (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--resume", action="store_true", help="Resume from last scraped")
    args = parser.parse_args()

    conn = psycopg2.connect("dbname=nhl_betting user=nhc_etl")
    verify_table(conn)

    if args.date:
        log.info(f"Scraping {args.date}")
        counts = scrape_date(conn, args.date)
        if counts:
            total = sum(counts.values())
            market_str = " | ".join(f"{m}:{n}" for m, n in sorted(counts.items()))
            log.info(f"Done: {total} lines ({market_str})")
        else:
            log.info("No data found for this date")
    elif args.resume:
        last_date = get_last_scraped_date(conn)
        if last_date:
            log.info(f"Resuming from {last_date}")
            end = args.end or datetime.now().strftime("%Y-%m-%d")
            total, days = scrape_date_range(conn, last_date, end)
            log.info(f"Done: {total} lines from {days} game days")
        else:
            log.info("No existing data — scraping current season")
            start, end = SEASONS[2025]
            total, days = scrape_date_range(conn, start, end)
            log.info(f"Done: {total} lines from {days} game days")
    elif args.season:
        if args.season not in SEASONS:
            log.error(f"Unknown season {args.season}. Available: {list(SEASONS.keys())}")
            sys.exit(1)
        start, end = SEASONS[args.season]
        log.info(f"Scraping {args.season}-{args.season + 1}: {start} to {end}")
        total, days = scrape_date_range(conn, start, end)
        log.info(f"Done: {total} lines from {days} game days")
    elif args.start:
        start = args.start
        end = args.end or datetime.now().strftime("%Y-%m-%d")
        log.info(f"Scraping {start} to {end}")
        total, days = scrape_date_range(conn, start, end)
        log.info(f"Done: {total} lines from {days} game days")
    else:
        # Default: scrape today
        today = datetime.now().strftime("%Y-%m-%d")
        log.info(f"Scraping today ({today})")
        counts = scrape_date(conn, today)
        if counts:
            total = sum(counts.values())
            market_str = " | ".join(f"{m}:{n}" for m, n in sorted(counts.items()))
            log.info(f"Done: {total} lines ({market_str})")
        else:
            log.info("No data found for today")

    # Print summary
    with conn.cursor() as cur:
        cur.execute("""
            SELECT market, COUNT(DISTINCT event_date) as days,
                   COUNT(DISTINCT bp_player_id) as players,
                   COUNT(*) as lines
            FROM bp_player_odds
            GROUP BY market ORDER BY market
        """)
        rows = cur.fetchall()
        if rows:
            log.info("\nSummary by market:")
            log.info(f"{'Market':>10} {'Days':>6} {'Players':>8} {'Lines':>8}")
            for market, days, players, lines in rows:
                log.info(f"{market:>10} {days:>6} {players:>8} {lines:>8}")

    conn.close()


if __name__ == "__main__":
    main()
