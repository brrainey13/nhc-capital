"""
Scrape player prop odds from BettingPros for all major markets:
  318 = Player Goals
  319 = Player Assists
  320 = Player Points
  321 = Player SOG

Also scrapes team-level markets:
  317 = Team Goals O/U
  194 = Total Goals O/U

Stores in player_odds and team_odds tables.
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import requests

PSQL = '/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql'
DB = 'nhl_betting'
API_KEY = 'CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh'
HEADERS = {'x-api-key': API_KEY}
BASE_URL = 'https://api.bettingpros.com/v3'

PLAYER_MARKETS = {
    318: 'goals',
    319: 'assists',
    320: 'points',
    321: 'sog',
}

TEAM_MARKETS = {
    317: 'team_goals',
    194: 'total_goals',
}

BOOK_MAP = {
    0: 'consensus', 3: 'fanduel', 10: 'caesars', 13: 'betmgm',
    19: 'espnbet', 22: 'hardrock', 25: 'draftkings', 28: 'novig',
}


def run_sql(sql):
    r = subprocess.run([PSQL, '-d', DB, '-c', sql], capture_output=True, text=True)
    if r.returncode != 0 and 'already exists' not in r.stderr:
        print(f"SQL error: {r.stderr[:200]}")
    return r


def create_tables():
    run_sql("""
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
    """)
    run_sql("""
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
    # Indexes for fast lookups
    run_sql("CREATE INDEX IF NOT EXISTS idx_player_odds_date ON player_odds(event_date);")
    run_sql("CREATE INDEX IF NOT EXISTS idx_player_odds_market ON player_odds(market);")
    run_sql("CREATE INDEX IF NOT EXISTS idx_player_odds_player ON player_odds(player_name);")
    run_sql("CREATE INDEX IF NOT EXISTS idx_team_odds_date ON team_odds(event_date);")
    run_sql("CREATE INDEX IF NOT EXISTS idx_team_odds_market ON team_odds(market);")


def get_events(date_str):
    r = requests.get(f'{BASE_URL}/events?sport=NHL&date={date_str}', headers=HEADERS)
    r.raise_for_status()
    return r.json().get('events', [])


def get_offers(market_id, event_id):
    r = requests.get(
        f'{BASE_URL}/offers?sport=NHL&market_id={market_id}&event_id={event_id}',
        headers=HEADERS)
    r.raise_for_status()
    return r.json().get('offers', [])


def esc(s):
    if s is None:
        return ''
    return str(s).replace("'", "''")


def insert_player_offer(market_name, offer, event, date_str):
    """Parse one player offer and insert all book lines."""
    event_id = event['id']
    home = esc(event.get('home', ''))
    away = esc(event.get('visitor', ''))
    player_id = offer.get('player_id')

    parts = offer.get('participants', [])
    if not parts:
        return 0
    p = parts[0]
    pname = esc(p.get('name', ''))
    pteam = esc(p.get('player', {}).get('team', ''))
    ppos = esc(p.get('player', {}).get('position', ''))

    sels = offer.get('selections', [])
    over_sel = next((s for s in sels if s.get('selection') == 'over'), None)
    under_sel = next((s for s in sels if s.get('selection') == 'under'), None)
    if not over_sel:
        return 0

    opening = over_sel.get('opening_line', {})
    opening_line = opening.get('line')
    opening_cost = opening.get('cost')
    opening_created = opening.get('created')

    count = 0
    for book in over_sel.get('books', []):
        book_id = book.get('id')
        if book_id not in BOOK_MAP:
            continue
        book_name = BOOK_MAP[book_id]

        for line_data in book.get('lines', []):
            line = line_data.get('line')
            over_cost = line_data.get('cost')
            is_best = line_data.get('best', False)
            updated = line_data.get('updated')

            under_cost = None
            if under_sel:
                for ubook in under_sel.get('books', []):
                    if ubook.get('id') == book_id:
                        for uline in ubook.get('lines', []):
                            if uline.get('line') == line:
                                under_cost = uline.get('cost')
                                break
                        break

            sql = f"""
            INSERT INTO player_odds (market, event_id, event_date, home_team, away_team,
                bp_player_id, player_name, player_team, player_position,
                book_id, book_name, line, over_odds, under_odds,
                opening_line, opening_over_odds, opening_created, is_best, updated_at)
            VALUES ('{market_name}', {event_id}, '{date_str}', '{home}', '{away}',
                {player_id or 'NULL'}, '{pname}', '{pteam}', '{ppos}',
                {book_id}, '{book_name}', {line if line is not None else 'NULL'},
                {over_cost or 'NULL'}, {under_cost or 'NULL'},
                {opening_line if opening_line is not None else 'NULL'},
                {opening_cost or 'NULL'},
                {f"'{esc(opening_created)}'" if opening_created else 'NULL'},
                {'TRUE' if is_best else 'FALSE'},
                {f"'{esc(updated)}'" if updated else 'NULL'})
            ON CONFLICT (market, event_id, bp_player_id, book_id) DO UPDATE SET
                line = EXCLUDED.line, over_odds = EXCLUDED.over_odds,
                under_odds = EXCLUDED.under_odds, updated_at = EXCLUDED.updated_at,
                scraped_at = CURRENT_TIMESTAMP;
            """
            run_sql(sql)
            count += 1
    return count


def insert_team_offer(market_name, offer, event, date_str):
    """Parse one team-level offer and insert all book lines."""
    event_id = event['id']
    home = esc(event.get('home', ''))
    away = esc(event.get('visitor', ''))

    parts = offer.get('participants', [])
    team_name = esc(parts[0].get('name', '')) if parts else ''

    sels = offer.get('selections', [])
    over_sel = next((s for s in sels if s.get('selection') == 'over'), None)
    under_sel = next((s for s in sels if s.get('selection') == 'under'), None)
    if not over_sel:
        return 0

    opening = over_sel.get('opening_line', {})
    opening_line = opening.get('line')
    opening_cost = opening.get('cost')
    opening_created = opening.get('created')

    count = 0
    for book in over_sel.get('books', []):
        book_id = book.get('id')
        if book_id not in BOOK_MAP:
            continue
        book_name = BOOK_MAP[book_id]

        for line_data in book.get('lines', []):
            line = line_data.get('line')
            over_cost = line_data.get('cost')
            is_best = line_data.get('best', False)
            updated = line_data.get('updated')

            under_cost = None
            if under_sel:
                for ubook in under_sel.get('books', []):
                    if ubook.get('id') == book_id:
                        for uline in ubook.get('lines', []):
                            if uline.get('line') == line:
                                under_cost = uline.get('cost')
                                break
                        break

            sql = f"""
            INSERT INTO team_odds (market, event_id, event_date, home_team, away_team,
                team_name, book_id, book_name, line, over_odds, under_odds,
                opening_line, opening_over_odds, opening_created, is_best, updated_at)
            VALUES ('{market_name}', {event_id}, '{date_str}', '{home}', '{away}',
                '{team_name}', {book_id}, '{book_name}',
                {line if line is not None else 'NULL'},
                {over_cost or 'NULL'}, {under_cost or 'NULL'},
                {opening_line if opening_line is not None else 'NULL'},
                {opening_cost or 'NULL'},
                {f"'{esc(opening_created)}'" if opening_created else 'NULL'},
                {'TRUE' if is_best else 'FALSE'},
                {f"'{esc(updated)}'" if updated else 'NULL'})
            ON CONFLICT (market, event_id, team_name, book_id) DO UPDATE SET
                line = EXCLUDED.line, over_odds = EXCLUDED.over_odds,
                under_odds = EXCLUDED.under_odds, updated_at = EXCLUDED.updated_at,
                scraped_at = CURRENT_TIMESTAMP;
            """
            run_sql(sql)
            count += 1
    return count


def scrape_date(date_str):
    """Scrape all markets for one date."""
    events = get_events(date_str)
    if not events:
        return 0

    day_total = 0
    for event in events:
        eid = event['id']

        # Player props
        for mid, mname in PLAYER_MARKETS.items():
            offers = get_offers(mid, eid)
            for offer in offers:
                day_total += insert_player_offer(mname, offer, event, date_str)
            time.sleep(0.2)

        # Team props
        for mid, mname in TEAM_MARKETS.items():
            offers = get_offers(mid, eid)
            for offer in offers:
                day_total += insert_team_offer(mname, offer, event, date_str)
            time.sleep(0.2)

    return day_total


def scrape_range(start_date, end_date):
    """Scrape all markets across a date range."""
    create_tables()
    current = start_date
    total = 0

    while current <= end_date:
        date_str = current.strftime('%Y-%m-%d')
        day_count = scrape_date(date_str)
        total += day_count
        if day_count > 0:
            print(f"{date_str}: {day_count} lines | Running total: {total}")
        current += timedelta(days=1)
        time.sleep(0.15)

    return total


if __name__ == '__main__':
    start = datetime(2022, 10, 1)
    end = datetime(2026, 2, 17)

    if len(sys.argv) >= 3:
        start = datetime.strptime(sys.argv[1], '%Y-%m-%d')
        end = datetime.strptime(sys.argv[2], '%Y-%m-%d')

    print(f"Scraping player + team odds from {start.date()} to {end.date()}")
    print(f"Player markets: {list(PLAYER_MARKETS.values())}")
    print(f"Team markets: {list(TEAM_MARKETS.values())}")
    total = scrape_range(start, end)
    print(f"\nDone! Total lines scraped: {total}")
