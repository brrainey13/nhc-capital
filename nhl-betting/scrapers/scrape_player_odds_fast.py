"""
Fast bulk scraper — uses psycopg2 for batch inserts, only hits dates with known games.
"""
import subprocess
import sys
import time
from datetime import datetime

import psycopg2
import psycopg2.extras
import requests

PSQL = '/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql'
DB = 'nhl_betting'
API_KEY = 'CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh'
HEADERS = {'x-api-key': API_KEY}
BASE_URL = 'https://api.bettingpros.com/v3'

PLAYER_MARKETS = {318: 'goals', 319: 'assists', 320: 'points', 321: 'sog'}
TEAM_MARKETS = {317: 'team_goals', 194: 'total_goals'}
BOOK_MAP = {0: 'consensus', 3: 'fanduel', 10: 'caesars', 13: 'betmgm',
            19: 'espnbet', 22: 'hardrock', 25: 'draftkings', 28: 'novig'}

conn = psycopg2.connect(dbname=DB)
conn.autocommit = True


def create_tables():
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS player_odds (
            id SERIAL PRIMARY KEY,
            market TEXT NOT NULL,
            event_id INTEGER,
            event_date TEXT,
            home_team TEXT,
            away_team TEXT,
            bp_player_id INTEGER,
            player_name TEXT,
            player_team TEXT,
            player_position TEXT,
            book_id INTEGER,
            book_name TEXT,
            line REAL,
            over_odds INTEGER,
            under_odds INTEGER,
            opening_line REAL,
            opening_over_odds INTEGER,
            opening_created TEXT,
            is_best BOOLEAN DEFAULT FALSE,
            updated_at TEXT,
            scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(market, event_id, bp_player_id, book_id)
        );
        CREATE TABLE IF NOT EXISTS team_odds (
            id SERIAL PRIMARY KEY,
            market TEXT NOT NULL,
            event_id INTEGER,
            event_date TEXT,
            home_team TEXT,
            away_team TEXT,
            team_name TEXT,
            book_id INTEGER,
            book_name TEXT,
            line REAL,
            over_odds INTEGER,
            under_odds INTEGER,
            opening_line REAL,
            opening_over_odds INTEGER,
            opening_created TEXT,
            is_best BOOLEAN DEFAULT FALSE,
            updated_at TEXT,
            scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(market, event_id, team_name, book_id)
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_player_odds_date ON player_odds(event_date);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_player_odds_market ON player_odds(market);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_team_odds_date ON team_odds(event_date);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_team_odds_market ON team_odds(market);")


def get_events(date_str):
    r = requests.get(f'{BASE_URL}/events?sport=NHL&date={date_str}', headers=HEADERS)
    r.raise_for_status()
    return r.json().get('events', [])


def get_offers(market_id, event_id):
    r = requests.get(f'{BASE_URL}/offers?sport=NHL&market_id={market_id}&event_id={event_id}', headers=HEADERS)
    r.raise_for_status()
    return r.json().get('offers', [])


def parse_player_offers(market_name, offers, event, date_str):
    """Parse all player offers into rows for batch insert."""
    rows = []
    event_id = event['id']
    home = event.get('home', '')
    away = event.get('visitor', '')

    for offer in offers:
        player_id = offer.get('player_id')
        parts = offer.get('participants', [])
        if not parts:
            continue
        p = parts[0]
        pname = p.get('name', '')
        pteam = p.get('player', {}).get('team', '')
        ppos = p.get('player', {}).get('position', '')

        sels = offer.get('selections', [])
        over_sel = next((s for s in sels if s.get('selection') == 'over'), None)
        under_sel = next((s for s in sels if s.get('selection') == 'under'), None)
        if not over_sel:
            continue

        opening = over_sel.get('opening_line', {})

        for book in over_sel.get('books', []):
            book_id = book.get('id')
            if book_id not in BOOK_MAP:
                continue

            for line_data in book.get('lines', []):
                under_cost = None
                if under_sel:
                    for ubook in under_sel.get('books', []):
                        if ubook.get('id') == book_id:
                            for uline in ubook.get('lines', []):
                                if uline.get('line') == line_data.get('line'):
                                    under_cost = uline.get('cost')
                                    break
                            break

                rows.append((
                    market_name, event_id, date_str, home, away,
                    player_id, pname, pteam, ppos,
                    book_id, BOOK_MAP[book_id],
                    line_data.get('line'), line_data.get('cost'), under_cost,
                    opening.get('line'), opening.get('cost'), opening.get('created'),
                    line_data.get('best', False), line_data.get('updated')
                ))
    return rows


def parse_team_offers(market_name, offers, event, date_str):
    """Parse team offers into rows."""
    rows = []
    event_id = event['id']
    home = event.get('home', '')
    away = event.get('visitor', '')

    for offer in offers:
        parts = offer.get('participants', [])
        team_name = parts[0].get('name', '') if parts else ''

        sels = offer.get('selections', [])
        over_sel = next((s for s in sels if s.get('selection') == 'over'), None)
        under_sel = next((s for s in sels if s.get('selection') == 'under'), None)
        if not over_sel:
            continue

        opening = over_sel.get('opening_line', {})

        for book in over_sel.get('books', []):
            book_id = book.get('id')
            if book_id not in BOOK_MAP:
                continue

            for line_data in book.get('lines', []):
                under_cost = None
                if under_sel:
                    for ubook in under_sel.get('books', []):
                        if ubook.get('id') == book_id:
                            for uline in ubook.get('lines', []):
                                if uline.get('line') == line_data.get('line'):
                                    under_cost = uline.get('cost')
                                    break
                            break

                rows.append((
                    market_name, event_id, date_str, home, away,
                    team_name, book_id, BOOK_MAP[book_id],
                    line_data.get('line'), line_data.get('cost'), under_cost,
                    opening.get('line'), opening.get('cost'), opening.get('created'),
                    line_data.get('best', False), line_data.get('updated')
                ))
    return rows


def bulk_insert_players(rows):
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO player_odds (market, event_id, event_date, home_team, away_team,
                bp_player_id, player_name, player_team, player_position,
                book_id, book_name, line, over_odds, under_odds,
                opening_line, opening_over_odds, opening_created, is_best, updated_at)
            VALUES %s
            ON CONFLICT (market, event_id, bp_player_id, book_id) DO UPDATE SET
                line = EXCLUDED.line, over_odds = EXCLUDED.over_odds,
                under_odds = EXCLUDED.under_odds, updated_at = EXCLUDED.updated_at,
                scraped_at = CURRENT_TIMESTAMP
        """, rows, page_size=500)


def bulk_insert_teams(rows):
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO team_odds (market, event_id, event_date, home_team, away_team,
                team_name, book_id, book_name, line, over_odds, under_odds,
                opening_line, opening_over_odds, opening_created, is_best, updated_at)
            VALUES %s
            ON CONFLICT (market, event_id, team_name, book_id) DO UPDATE SET
                line = EXCLUDED.line, over_odds = EXCLUDED.over_odds,
                under_odds = EXCLUDED.under_odds, updated_at = EXCLUDED.updated_at,
                scraped_at = CURRENT_TIMESTAMP
        """, rows, page_size=500)


def get_game_dates():
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT game_date::date FROM games WHERE game_type IN (2,3) AND game_state='OFF' ORDER BY game_date")
        return [str(r[0]) for r in cur.fetchall()]


def get_scraped_dates():
    with conn.cursor() as cur:
        cur.execute("SELECT event_date FROM player_odds GROUP BY event_date HAVING COUNT(DISTINCT market) >= 4")
        return set(str(r[0]) for r in cur.fetchall())


def main():
    create_tables()
    all_dates = get_game_dates()
    done_dates = get_scraped_dates()
    remaining = [d for d in all_dates if d not in done_dates]
    print(f"Game dates: {len(all_dates)}, done: {len(done_dates)}, remaining: {len(remaining)}", flush=True)

    total = 0
    errors = 0
    for i, date_str in enumerate(remaining):
        try:
            events = get_events(date_str)
        except Exception as e:
            print(f"  {date_str}: event fetch error: {e}", flush=True)
            errors += 1
            if errors > 10:
                print("Too many errors, stopping.", flush=True)
                break
            time.sleep(2)
            continue

        if not events:
            continue

        player_rows = []
        team_rows = []

        for event in events:
            eid = event['id']
            for mid, mname in PLAYER_MARKETS.items():
                try:
                    offers = get_offers(mid, eid)
                    player_rows.extend(parse_player_offers(mname, offers, event, date_str))
                except Exception:
                    pass
                time.sleep(0.08)

            for mid, mname in TEAM_MARKETS.items():
                try:
                    offers = get_offers(mid, eid)
                    team_rows.extend(parse_team_offers(mname, offers, event, date_str))
                except Exception:
                    pass
                time.sleep(0.08)

        bulk_insert_players(player_rows)
        bulk_insert_teams(team_rows)

        day_count = len(player_rows) + len(team_rows)
        total += day_count
        pct = (i + 1) / len(remaining) * 100
        print(f"[{pct:5.1f}%] {date_str}: {day_count} lines ({len(events)} games) | Total: {total}", flush=True)

    print(f"\nDone! {total} lines across {len(remaining)} dates", flush=True)


if __name__ == '__main__':
    main()
