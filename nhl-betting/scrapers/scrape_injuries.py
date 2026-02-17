#!/usr/bin/env python3
"""
NHL Injury Data - Two approaches:

1. HISTORICAL (derived): Reconstruct player absences from player_stats.
   For each game, compute which regular players were missing from the lineup
   and their combined TOI impact. This captures injuries, suspensions,
   healthy scratches — any absence that affects team strength.

2. LIVE (ESPN API): Scrape current injury reports for pre-game predictions.
   Source: site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries

Tables:
  - lineup_absences: derived historical absences per team per game
  - injuries_live: current ESPN injury data (daily snapshot)
"""

import logging
from datetime import datetime

import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"

# Map ESPN team names to our tri_codes
ESPN_TEAM_MAP = {
    "Anaheim Ducks": "ANA", "Arizona Coyotes": "ARI", "Boston Bruins": "BOS",
    "Buffalo Sabres": "BUF", "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR",
    "Chicago Blackhawks": "CHI", "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ",
    "Dallas Stars": "DAL", "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM",
    "Florida Panthers": "FLA", "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN",
    "Montréal Canadiens": "MTL", "Montreal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD",
    "New York Islanders": "NYI", "New York Rangers": "NYR", "Ottawa Senators": "OTT",
    "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA", "St. Louis Blues": "STL", "Tampa Bay Lightning": "TBL",
    "Toronto Maple Leafs": "TOR", "Utah Hockey Club": "UTA",
    "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}


def get_conn():
    return psycopg2.connect(DB_CONN)


def create_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lineup_absences (
            game_id          INTEGER NOT NULL,
            team_id          INTEGER NOT NULL,
            game_date        TEXT NOT NULL,
            -- Forwards
            fwd_regulars     INTEGER,
            fwd_missing      INTEGER,
            fwd_missing_toi  DOUBLE PRECISION,
            -- Defensemen
            def_regulars     INTEGER,
            def_missing      INTEGER,
            def_missing_toi  DOUBLE PRECISION,
            -- Combined
            total_missing    INTEGER,
            total_missing_toi DOUBLE PRECISION,
            -- Top player missing (by avg TOI)
            top_missing_player_id INTEGER,
            top_missing_avg_toi   DOUBLE PRECISION,
            PRIMARY KEY (game_id, team_id)
        );

        CREATE TABLE IF NOT EXISTS injuries_live (
            id               SERIAL PRIMARY KEY,
            scraped_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            scraped_date     TEXT NOT NULL,
            team_name        TEXT,
            team_abbrev      TEXT,
            player_name      TEXT NOT NULL,
            player_espn_id   TEXT,
            position         TEXT,
            status           TEXT,
            injury_date      TEXT,
            detail           TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_injuries_live_date ON injuries_live(scraped_date);
        CREATE INDEX IF NOT EXISTS idx_injuries_live_player ON injuries_live(player_name);
        """)
    conn.commit()
    log.info("Tables created/verified")


def build_historical_absences(conn):
    """Derive lineup absences from player_stats for all completed games."""
    log.info("Building historical lineup absences...")

    with conn.cursor() as cur:
        # Build regulars: players who played 25%+ of their team's games in a season window
        # Then for each game, find who's missing
        cur.execute("""
        WITH season_bounds AS (
            SELECT '2022-10-01'::date as s, '2023-06-30'::date as e, '2022' as season
            UNION ALL SELECT '2023-10-01', '2024-06-30', '2023'
            UNION ALL SELECT '2024-10-01', '2025-06-30', '2024'
            UNION ALL SELECT '2025-10-01', '2026-06-30', '2025'
        ),
        team_game_counts AS (
            SELECT ps.team_id, sb.season, count(DISTINCT ps.game_id) as team_games
            FROM player_stats ps
            JOIN games g ON ps.game_id = g.game_id
            JOIN season_bounds sb ON g.game_date::date >= sb.s AND g.game_date::date <= sb.e
            GROUP BY ps.team_id, sb.season
        ),
        regulars AS (
            SELECT ps.team_id, ps.player_id, p.position_code, sb.season,
                   count(DISTINCT ps.game_id) as gp,
                   avg(ps.toi_minutes) as avg_toi
            FROM player_stats ps
            JOIN players p ON ps.player_id = p.player_id
            JOIN games g ON ps.game_id = g.game_id
            JOIN season_bounds sb ON g.game_date::date >= sb.s AND g.game_date::date <= sb.e
            JOIN team_game_counts tgc ON ps.team_id = tgc.team_id AND sb.season = tgc.season
            WHERE p.position_code IN ('D', 'L', 'R', 'C')
            GROUP BY ps.team_id, ps.player_id, p.position_code, sb.season, tgc.team_games
            HAVING count(DISTINCT ps.game_id) >= GREATEST(15, tgc.team_games * 0.25)
        ),
        game_teams AS (
            SELECT g.game_id, g.game_date::text as game_date, g.home_team_id as team_id,
                   CASE WHEN g.game_date::date >= '2025-10-01' THEN '2025'
                        WHEN g.game_date::date >= '2024-10-01' THEN '2024'
                        WHEN g.game_date::date >= '2023-10-01' THEN '2023'
                        ELSE '2022' END as season
            FROM games g WHERE g.home_score IS NOT NULL AND g.game_type IN (2, 3) AND g.game_state = 'OFF'
            UNION ALL
            SELECT g.game_id, g.game_date::text, g.away_team_id,
                   CASE WHEN g.game_date::date >= '2025-10-01' THEN '2025'
                        WHEN g.game_date::date >= '2024-10-01' THEN '2024'
                        WHEN g.game_date::date >= '2023-10-01' THEN '2023'
                        ELSE '2022' END
            FROM games g WHERE g.home_score IS NOT NULL AND g.game_type IN (2, 3) AND g.game_state = 'OFF'
        ),
        absences AS (
            SELECT gt.game_id, gt.team_id, gt.game_date,
                   r.player_id, r.position_code, r.avg_toi,
                   CASE WHEN ps.player_id IS NULL THEN 1 ELSE 0 END as is_missing
            FROM game_teams gt
            JOIN regulars r ON r.team_id = gt.team_id AND r.season = gt.season
            LEFT JOIN player_stats ps ON ps.game_id = gt.game_id AND ps.player_id = r.player_id
        )
        INSERT INTO lineup_absences
        (game_id, team_id, game_date,
         fwd_regulars, fwd_missing, fwd_missing_toi,
         def_regulars, def_missing, def_missing_toi,
         total_missing, total_missing_toi,
         top_missing_player_id, top_missing_avg_toi)
        SELECT
            game_id, team_id, game_date,
            count(*) FILTER (WHERE position_code IN ('L','R','C')),
            count(*) FILTER (WHERE position_code IN ('L','R','C') AND is_missing = 1),
            coalesce(sum(avg_toi) FILTER (WHERE position_code IN ('L','R','C') AND is_missing = 1), 0),
            count(*) FILTER (WHERE position_code = 'D'),
            count(*) FILTER (WHERE position_code = 'D' AND is_missing = 1),
            coalesce(sum(avg_toi) FILTER (WHERE position_code = 'D' AND is_missing = 1), 0),
            count(*) FILTER (WHERE is_missing = 1),
            coalesce(sum(avg_toi) FILTER (WHERE is_missing = 1), 0),
            (SELECT a2.player_id FROM absences a2
             WHERE a2.game_id = absences.game_id AND a2.team_id = absences.team_id AND a2.is_missing = 1
             ORDER BY a2.avg_toi DESC LIMIT 1),
            (SELECT a2.avg_toi FROM absences a2
             WHERE a2.game_id = absences.game_id AND a2.team_id = absences.team_id AND a2.is_missing = 1
             ORDER BY a2.avg_toi DESC LIMIT 1)
        FROM absences
        GROUP BY game_id, team_id, game_date
        ON CONFLICT (game_id, team_id) DO UPDATE SET
            fwd_missing = EXCLUDED.fwd_missing,
            fwd_missing_toi = EXCLUDED.fwd_missing_toi,
            def_missing = EXCLUDED.def_missing,
            def_missing_toi = EXCLUDED.def_missing_toi,
            total_missing = EXCLUDED.total_missing,
            total_missing_toi = EXCLUDED.total_missing_toi,
            top_missing_player_id = EXCLUDED.top_missing_player_id,
            top_missing_avg_toi = EXCLUDED.top_missing_avg_toi;
        """)
        count = cur.rowcount
    conn.commit()
    log.info(f"Historical absences: {count} rows upserted")
    return count


def scrape_espn_injuries(conn):
    """Scrape current injuries from ESPN API."""
    log.info("Scraping ESPN injuries...")
    today = datetime.now().strftime("%Y-%m-%d")

    resp = requests.get(ESPN_URL, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for team in data.get("injuries", []):
        team_name = team.get("displayName", "")
        team_abbrev = ESPN_TEAM_MAP.get(team_name, "")

        for inj in team.get("injuries", []):
            athlete = inj.get("athlete", {})
            rows.append((
                today,
                team_name,
                team_abbrev,
                athlete.get("displayName", ""),
                str(athlete.get("id", "")),
                (athlete.get("position", {}).get("abbreviation", "")
                 if isinstance(athlete.get("position"), dict) else ""),
                inj.get("status", ""),
                inj.get("date", ""),
                inj.get("longComment", inj.get("shortComment", "")),
            ))

    with conn.cursor() as cur:
        # Clear today's existing data (idempotent)
        cur.execute("DELETE FROM injuries_live WHERE scraped_date = %s", (today,))
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO injuries_live
            (scraped_date, team_name, team_abbrev, player_name, player_espn_id,
             position, status, injury_date, detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, rows)
    conn.commit()
    log.info(f"ESPN injuries: {len(rows)} entries for {today}")
    return len(rows)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical", action="store_true", help="Build historical absence data")
    parser.add_argument("--live", action="store_true", help="Scrape current ESPN injuries")
    parser.add_argument("--all", action="store_true", help="Run both")
    args = parser.parse_args()

    if not any([args.historical, args.live, args.all]):
        args.all = True

    conn = get_conn()
    create_tables(conn)

    if args.historical or args.all:
        build_historical_absences(conn)

    if args.live or args.all:
        scrape_espn_injuries(conn)

    conn.close()
    log.info("Done")


if __name__ == "__main__":
    main()
