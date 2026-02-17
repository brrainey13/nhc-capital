"""
Scrape player Shots on Goal (SOG) O/U odds from BettingPros.
Market ID 321 = Player SOG.
Stores in sog_odds table.
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

PSQL = '/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql'
DB = 'nhl_betting'
API_KEY = 'CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh'
MARKET_ID = 321  # Player SOG
HEADERS = {'x-api-key': API_KEY}
BASE_URL = 'https://api.bettingpros.com/v3'

BOOK_MAP = {
    0: 'consensus', 3: 'fanduel', 10: 'caesars', 13: 'betmgm',
    19: 'espnbet', 22: 'hardrock', 12: 'book_12', 24: 'book_24',
    25: 'draftkings', 28: 'novig'
}


def run_sql(sql):
    r = subprocess.run([PSQL, '-d', DB, '-c', sql], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"SQL error: {r.stderr}")
    return r

def create_table():
    run_sql("""
    CREATE TABLE IF NOT EXISTS sog_odds (
        id SERIAL PRIMARY KEY,
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
        fair_probability REAL,
        market_ev REAL,
        updated_at TEXT,
        scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(event_id, bp_player_id, book_id)
    );
    """)

def get_events(date_str):
    r = requests.get(f'{BASE_URL}/events?sport=NHL&date={date_str}', headers=HEADERS)
    r.raise_for_status()
    return r.json().get('events', [])

def get_offers(event_id):
    r = requests.get(f'{BASE_URL}/offers?sport=NHL&market_id={MARKET_ID}&event_id={event_id}', headers=HEADERS)
    r.raise_for_status()
    return r.json().get('offers', [])

def parse_and_insert(offers, event, date_str):
    home = event.get('home', '')
    away = event.get('visitor', '')
    event_id = event['id']
    count = 0

    for offer in offers:
        player_id = offer.get('player_id')
        if not offer.get('participants'):
            continue
        p = offer['participants'][0]
        pname = p.get('name', '')
        pteam = p.get('player', {}).get('team', '')
        ppos = p.get('player', {}).get('position', '')

        sels = offer.get('selections', [])
        over_sel = next((s for s in sels if s.get('selection') == 'over'), None)
        under_sel = next((s for s in sels if s.get('selection') == 'under'), None)
        if not over_sel:
            continue

        opening = over_sel.get('opening_line', {})
        opening_line = opening.get('line')
        opening_cost = opening.get('cost')
        opening_created = opening.get('created')

        for book in over_sel.get('books', []):
            book_id = book.get('id')
            book_name = BOOK_MAP.get(book_id, f'book_{book_id}')

            for line_data in book.get('lines', []):
                line = line_data.get('line')
                over_cost = line_data.get('cost')
                is_best = line_data.get('best', False)
                updated = line_data.get('updated')

                # Find matching under odds
                under_cost = None
                if under_sel:
                    for ubook in under_sel.get('books', []):
                        if ubook.get('id') == book_id:
                            for uline in ubook.get('lines', []):
                                if uline.get('line') == line:
                                    under_cost = uline.get('cost')
                                    break
                            break

                pname_esc = pname.replace("'", "''")
                sql = f"""
                INSERT INTO sog_odds (event_id, event_date, home_team, away_team,
                    bp_player_id, player_name, player_team, player_position,
                    book_id, book_name, line, over_odds, under_odds,
                    opening_line, opening_over_odds, opening_created, is_best, updated_at)
                VALUES ({event_id}, '{date_str}', '{home}', '{away}',
                    {player_id or 'NULL'}, '{pname_esc}', '{pteam}', '{ppos}',
                    {book_id}, '{book_name}', {line or 'NULL'},
                    {over_cost or 'NULL'}, {under_cost or 'NULL'},
                    {opening_line or 'NULL'}, {opening_cost or 'NULL'},
                    {f"'{opening_created}'" if opening_created else 'NULL'},
                    {'TRUE' if is_best else 'FALSE'},
                    {f"'{updated}'" if updated else 'NULL'})
                ON CONFLICT (event_id, bp_player_id, book_id) DO UPDATE SET
                    line = EXCLUDED.line, over_odds = EXCLUDED.over_odds,
                    under_odds = EXCLUDED.under_odds, updated_at = EXCLUDED.updated_at,
                    scraped_at = CURRENT_TIMESTAMP;
                """
                run_sql(sql)
                count += 1
    return count

def scrape_range(start_date, end_date):
    create_table()
    current = start_date
    total = 0
    while current <= end_date:
        date_str = current.strftime('%Y-%m-%d')
        events = get_events(date_str)
        day_count = 0
        for event in events:
            offers = get_offers(event['id'])
            if offers:
                n = parse_and_insert(offers, event, date_str)
                day_count += n
            time.sleep(0.3)
        total += day_count
        if day_count > 0:
            print(f"{date_str}: {day_count} lines ({len(events)} games) | Total: {total}")
        current += timedelta(days=1)
        time.sleep(0.2)
    return total

if __name__ == '__main__':
    # Default: scrape from Oct 2022 to Feb 2026
    start = datetime(2022, 10, 1)
    end = datetime(2026, 2, 6)

    if len(sys.argv) >= 3:
        start = datetime.strptime(sys.argv[1], '%Y-%m-%d')
        end = datetime.strptime(sys.argv[2], '%Y-%m-%d')

    print(f"Scraping SOG odds from {start.date()} to {end.date()}")
    total = scrape_range(start, end)
    print(f"\nDone! Total lines scraped: {total}")
