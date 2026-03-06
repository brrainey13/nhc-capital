
#!/usr/bin/env python3
"""
Scrape advanced goalie stats from NHL Stats API.

Tables created:
  - goalie_saves_by_strength: EV/PP/SH saves & shots per game
  - goalie_advanced: quality starts, shots against/60, goals for/against avg
  - goalie_starts: started vs relieved with separate save stats

Source: api.nhle.com/stats/rest/en/goalie/{report}
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import requests

from lib.db import get_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

API_BASE = "https://api.nhle.com/stats/rest/en/goalie"
BATCH = 100
SLEEP = 0.5

SEASON_RANGES = [
    ("2022-10-07", "2023-06-30"),
    ("2023-10-10", "2024-06-30"),
    ("2024-10-04", "2025-06-30"),
    ("2025-10-07", "2026-06-30"),
]




def create_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS goalie_saves_by_strength (
            game_id       INTEGER NOT NULL,
            player_id     INTEGER NOT NULL,
            game_date     TEXT NOT NULL,
            team          TEXT,
            opponent      TEXT,
            home_road     TEXT,
            ev_saves      INTEGER,
            ev_shots      INTEGER,
            ev_goals_against INTEGER,
            ev_save_pct   DOUBLE PRECISION,
            pp_saves      INTEGER,
            pp_shots      INTEGER,
            pp_goals_against INTEGER,
            pp_save_pct   DOUBLE PRECISION,
            sh_saves      INTEGER,
            sh_shots      INTEGER,
            sh_goals_against INTEGER,
            sh_save_pct   DOUBLE PRECISION,
            total_saves   INTEGER,
            total_shots   INTEGER,
            total_save_pct DOUBLE PRECISION,
            PRIMARY KEY (game_id, player_id)
        );

        CREATE TABLE IF NOT EXISTS goalie_advanced (
            game_id           INTEGER NOT NULL,
            player_id         INTEGER NOT NULL,
            game_date         TEXT NOT NULL,
            team              TEXT,
            opponent          TEXT,
            home_road         TEXT,
            games_started     INTEGER,
            quality_start     INTEGER,
            goals_against     INTEGER,
            goals_against_avg DOUBLE PRECISION,
            goals_for         INTEGER,
            goals_for_avg     DOUBLE PRECISION,
            shots_against_per60 DOUBLE PRECISION,
            save_pct          DOUBLE PRECISION,
            complete_games    INTEGER,
            incomplete_games  INTEGER,
            time_on_ice       TEXT,
            PRIMARY KEY (game_id, player_id)
        );

        CREATE TABLE IF NOT EXISTS goalie_starts (
            game_id       INTEGER NOT NULL,
            player_id     INTEGER NOT NULL,
            game_date     TEXT NOT NULL,
            team          TEXT,
            opponent      TEXT,
            home_road     TEXT,
            games_started INTEGER,
            games_relieved INTEGER,
            started_saves INTEGER,
            started_shots INTEGER,
            started_save_pct DOUBLE PRECISION,
            started_goals_against INTEGER,
            relieved_saves INTEGER,
            relieved_shots INTEGER,
            relieved_save_pct DOUBLE PRECISION,
            relieved_goals_against INTEGER,
            total_save_pct DOUBLE PRECISION,
            PRIMARY KEY (game_id, player_id)
        );
        """)
    conn.commit()
    log.info("Tables created/verified")


def fetch_report(report, start_date, end_date, start=0):
    url = f"{API_BASE}/{report}"
    params = {
        "isAggregate": "false",
        "isGame": "true",
        "limit": BATCH,
        "start": start,
        "cayenneExp": f'gameDate>="{start_date}" and gameDate<="{end_date}" and gameTypeId=2',
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", []), data.get("total", 0)


def scrape_saves_by_strength(conn, start_date, end_date):
    log.info(f"Scraping savesByStrength {start_date} -> {end_date}")
    offset = 0
    total_inserted = 0
    while True:
        rows, total = fetch_report("savesByStrength", start_date, end_date, offset)
        if not rows:
            break
        with conn.cursor() as cur:
            for r in rows:
                cur.execute("""
                INSERT INTO goalie_saves_by_strength
                (game_id, player_id, game_date, team, opponent, home_road,
                 ev_saves, ev_shots, ev_goals_against, ev_save_pct,
                 pp_saves, pp_shots, pp_goals_against, pp_save_pct,
                 sh_saves, sh_shots, sh_goals_against, sh_save_pct,
                 total_saves, total_shots, total_save_pct)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (game_id, player_id) DO NOTHING
                """, (
                    r.get("gameId"), r.get("playerId"), r.get("gameDate"),
                    r.get("teamAbbrev"), r.get("opponentTeamAbbrev"), r.get("homeRoad"),
                    r.get("evSaves"), r.get("evShotsAgainst"), r.get("evGoalsAgainst"), r.get("evSavePct"),
                    r.get("ppSaves"), r.get("ppShotsAgainst"), r.get("ppGoalsAgainst"), r.get("ppSavePct"),
                    r.get("shSaves"), r.get("shShotsAgainst"), r.get("shGoalsAgainst"), r.get("shSavePct"),
                    r.get("saves"), r.get("shotsAgainst"), r.get("savePct"),
                ))
        conn.commit()
        total_inserted += len(rows)
        offset += BATCH
        if offset >= total:
            break
        time.sleep(SLEEP)
    log.info(f"  savesByStrength: {total_inserted} rows")
    return total_inserted


def scrape_advanced(conn, start_date, end_date):
    log.info(f"Scraping advanced {start_date} -> {end_date}")
    offset = 0
    total_inserted = 0
    while True:
        rows, total = fetch_report("advanced", start_date, end_date, offset)
        if not rows:
            break
        with conn.cursor() as cur:
            for r in rows:
                cur.execute("""
                INSERT INTO goalie_advanced
                (game_id, player_id, game_date, team, opponent, home_road,
                 games_started, quality_start, goals_against, goals_against_avg,
                 goals_for, goals_for_avg, shots_against_per60, save_pct,
                 complete_games, incomplete_games, time_on_ice)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (game_id, player_id) DO NOTHING
                """, (
                    r.get("gameId"), r.get("playerId"), r.get("gameDate"),
                    r.get("teamAbbrev"), r.get("opponentTeamAbbrev"), r.get("homeRoad"),
                    r.get("gamesStarted"), r.get("qualityStart"),
                    r.get("goalsAgainst"), r.get("goalsAgainstAverage"),
                    r.get("goalsFor"), r.get("goalsForAverage"),
                    r.get("shotsAgainstPer60"), r.get("savePct"),
                    r.get("completeGames"), r.get("incompleteGames"),
                    r.get("timeOnIce"),
                ))
        conn.commit()
        total_inserted += len(rows)
        offset += BATCH
        if offset >= total:
            break
        time.sleep(SLEEP)
    log.info(f"  advanced: {total_inserted} rows")
    return total_inserted


def scrape_starts(conn, start_date, end_date):
    log.info(f"Scraping startedVsRelieved {start_date} -> {end_date}")
    offset = 0
    total_inserted = 0
    while True:
        rows, total = fetch_report("startedVsRelieved", start_date, end_date, offset)
        if not rows:
            break
        with conn.cursor() as cur:
            for r in rows:
                cur.execute("""
                INSERT INTO goalie_starts
                (game_id, player_id, game_date, team, opponent, home_road,
                 games_started, games_relieved,
                 started_saves, started_shots, started_save_pct, started_goals_against,
                 relieved_saves, relieved_shots, relieved_save_pct, relieved_goals_against,
                 total_save_pct)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (game_id, player_id) DO NOTHING
                """, (
                    r.get("gameId"), r.get("playerId"), r.get("gameDate"),
                    r.get("teamAbbrev"), r.get("opponentTeamAbbrev"), r.get("homeRoad"),
                    r.get("gamesStarted"), r.get("gamesRelieved"),
                    r.get("gamesStartedSaves"), r.get("gamesStartedShotsAgainst"),
                    r.get("gamesStartedSavePct"), r.get("gamesStartedGoalsAgainst"),
                    r.get("gamesRelievedSaves"), r.get("gamesRelievedShotsAgainst"),
                    r.get("gamesRelievedSavePct"), r.get("gamesRelievedGoalsAgainst"),
                    r.get("savePct"),
                ))
        conn.commit()
        total_inserted += len(rows)
        offset += BATCH
        if offset >= total:
            break
        time.sleep(SLEEP)
    log.info(f"  startedVsRelieved: {total_inserted} rows")
    return total_inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    args = parser.parse_args()

    conn = get_conn(db="nhl_betting")
    create_tables(conn)

    today = datetime.now().strftime("%Y-%m-%d")
    grand_total = 0

    for season_start, season_end in SEASON_RANGES:
        # Skip future seasons
        if season_start > today:
            continue
        # Clamp end to today
        end = min(season_end, today)
        s = args.start if args.start and args.start > season_start else season_start
        e = args.end if args.end and args.end < end else end

        grand_total += scrape_saves_by_strength(conn, s, e)
        grand_total += scrape_advanced(conn, s, e)
        grand_total += scrape_starts(conn, s, e)

    conn.close()
    log.info(f"Done. Total rows inserted: {grand_total}")


if __name__ == "__main__":
    main()
