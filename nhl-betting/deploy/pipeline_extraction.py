#!/usr/bin/env python3
"""Data extraction: NHL API schedule, goalies, odds."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import requests

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "api_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

import yaml

DEPLOY_DIR = Path(__file__).parent
with open(DEPLOY_DIR / "config.yaml") as f:
    CONFIG = yaml.safe_load(f)

from dotenv import load_dotenv

load_dotenv(DEPLOY_DIR / ".env")

ODDS_API_KEY = os.getenv("ODDS_API_KEY", CONFIG["apis"].get("odds_api_key", ""))
NHL_API_BASE = CONFIG["apis"]["nhl_api_base"]
DB_CONN = os.environ.get("DATABASE_URL", "postgresql://nhc_agent@localhost:5432/nhl_betting")

logger = logging.getLogger("data_pipeline")


def get_today_schedule(date: str = None) -> list[dict]:
    """Get today's NHL schedule from the NHL API."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    url = f"{NHL_API_BASE}/schedule/{date}"
    logger.info(f"Fetching schedule for {date}")

    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    cache_file = CACHE_DIR / f"schedule_{date}.json"
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)

    games = []
    for week in data.get("gameWeek", []):
        if week.get("date") != date:
            continue
        for game in week.get("games", []):
            if game.get("gameType") not in (2, 3):
                continue
            games.append({
                "game_id": game["id"],
                "date": date,
                "home_team": game["homeTeam"]["abbrev"],
                "away_team": game["awayTeam"]["abbrev"],
                "home_team_id": game["homeTeam"].get("id"),
                "away_team_id": game["awayTeam"].get("id"),
                "game_time": game.get("startTimeUTC"),
                "game_state": game.get("gameState", "FUT"),
            })

    logger.info(f"  Found {len(games)} games on {date}")
    return games


def get_probable_goalies(game_id: int) -> dict:
    """Get probable/confirmed starting goalies for a game."""
    url = f"{NHL_API_BASE}/gamecenter/{game_id}/landing"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result = {"home_goalie": None, "away_goalie": None, "confirmed": False}

        matchup = data.get("matchup", {})
        goalies = matchup.get("goalieComparison", {})

        if goalies:
            home_g = goalies.get("homeTeam", {}).get("leaders", [])
            away_g = goalies.get("awayTeam", {}).get("leaders", [])
            if home_g:
                g = home_g[0]
                result["home_goalie"] = {
                    "name": f"{g.get('firstName', {}).get('default', '')} {g.get('lastName', {}).get('default', '')}".strip(),
                    "player_id": g.get("playerId"),
                }
            if away_g:
                g = away_g[0]
                result["away_goalie"] = {
                    "name": f"{g.get('firstName', {}).get('default', '')} {g.get('lastName', {}).get('default', '')}".strip(),
                    "player_id": g.get("playerId"),
                }

        summary = data.get("summary", {})
        if summary:
            result["confirmed"] = True

        return result

    except Exception as e:
        logger.warning(f"  Could not get goalies for game {game_id}: {e}")
        return {"home_goalie": None, "away_goalie": None, "confirmed": False}


def get_team_recent_stats(team_id: int, n_games: int = 10) -> dict:
    """Get team's last N games from our database for Corsi calculation."""
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    cur.execute("""
        SELECT gts.shots_attempted AS own_sa,
               opp.shots_attempted AS opp_sa,
               gts.takeaways, gts.giveaways,
               gts.shots_on_goal, gts.power_play_opportunities,
               g.game_date
        FROM game_team_stats gts
        JOIN games g ON gts.game_id = g.game_id
        JOIN game_team_stats opp ON gts.game_id = opp.game_id AND gts.team_id != opp.team_id
        WHERE gts.team_id = %s
          AND g.game_type IN (2, 3)
          AND g.home_score IS NOT NULL
        ORDER BY g.game_date DESC
        LIMIT %s
    """, (team_id, n_games))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=["own_sa", "opp_sa", "takeaways", "giveaways",
                                      "shots_on_goal", "pp_opps", "game_date"])

    total_corsi = df["own_sa"] + df["opp_sa"]
    corsi_pct = np.where(total_corsi > 0, df["own_sa"] / total_corsi, 0.5)
    corsi_diff = df["own_sa"] - df["opp_sa"]
    puck_control = df["takeaways"] - df["giveaways"]

    return {
        "corsi_pct_avg_10": float(corsi_pct.mean()),
        "corsi_diff_avg_10": float(corsi_diff.mean()),
        "puck_control_avg_10": float(puck_control.mean()),
        "sog_avg_10": float(df["shots_on_goal"].mean()),
        "sa_avg_10": float(df["own_sa"].mean()),
        "pp_opps_avg_10": float(df["pp_opps"].mean()),
        "hits_avg_10": float((df["takeaways"] + df["giveaways"]).mean()),
        "n_games": len(df),
    }


def get_goalie_recent_stats(player_id: int, n_games: int = 20) -> dict:
    """Get goalie's recent stats from our database."""
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    cur.execute("""
        SELECT gs.saves, gs.shots_against, gs.goals_against, gs.save_pct,
               g.game_date,
               ga.games_started, ga.incomplete_games
        FROM goalie_stats gs
        JOIN games g ON gs.game_id = g.game_id
        LEFT JOIN goalie_advanced ga ON gs.game_id = ga.game_id AND gs.player_id = ga.player_id
        WHERE gs.player_id = %s
          AND g.game_type IN (2, 3)
          AND gs.shots_against > 0
        ORDER BY g.game_date DESC
        LIMIT %s
    """, (player_id, n_games))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=["saves", "shots_against", "goals_against",
                                      "save_pct", "game_date", "games_started",
                                      "incomplete_games"])

    last_date = pd.to_datetime(df["game_date"].iloc[0])

    pulls = ((df["games_started"] == 1) & (df["incomplete_games"] == 1)).astype(int) if "games_started" in df.columns else pd.Series(0, index=df.index)

    result = {
        "sa_avg_10": float(df["shots_against"].head(10).mean()) if len(df) >= 3 else None,
        "sa_avg_20": float(df["shots_against"].head(20).mean()) if len(df) >= 3 else None,
        "saves_avg_10": float(df["saves"].head(10).mean()) if len(df) >= 3 else None,
        "svpct_avg_10": float(df["save_pct"].head(10).mean()) if len(df) >= 3 else None,
        "svpct_avg_20": float(df["save_pct"].head(20).mean()) if len(df) >= 3 else None,
        "pull_rate_10": float(pulls.head(10).mean()) if len(df) >= 3 else None,
        "days_rest": (datetime.now().date() - last_date.date()).days,
        "last_game_date": str(last_date.date()),
        "starts_last_7d": int(((last_date - pd.to_datetime(df["game_date"])).dt.days < 7).sum()),
        "n_games": len(df),
    }

    return result


def get_goalie_saves_odds(date: str = None) -> list[dict]:
    """Pull goalie saves over/under lines from The Odds API."""
    if not ODDS_API_KEY or ODDS_API_KEY.startswith("$"):
        logger.error("ODDS_API_KEY not set! Sign up at https://the-odds-api.com/")
        return []

    url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/events"
    params = {"apiKey": ODDS_API_KEY, "regions": "us", "oddsFormat": "american"}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json()

        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        logger.info(f"  Odds API: {remaining} requests remaining ({used} used)")

        cache_file = CACHE_DIR / f"odds_events_{date or 'today'}.json"
        with open(cache_file, "w") as f:
            json.dump(events, f, indent=2)

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            logger.error("ODDS_API_KEY invalid! Check your key.")
        elif e.response.status_code == 429:
            logger.error("ODDS_API rate limit hit! 500 req/month max.")
        else:
            logger.error(f"Odds API error: {e}")
        return []

    all_odds = []
    for event in events:
        event_id = event["id"]
        home = event.get("home_team", "")
        away = event.get("away_team", "")

        props_url = f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events/{event_id}/odds"
        props_params = {
            "apiKey": ODDS_API_KEY, "regions": "us",
            "markets": "player_saves", "oddsFormat": "american",
        }

        try:
            resp = requests.get(props_url, params=props_params, timeout=15)
            resp.raise_for_status()
            props_data = resp.json()

            remaining = resp.headers.get("x-requests-remaining", "?")
            logger.info(f"    {away} @ {home}: {remaining} API calls left")

            cache_file = CACHE_DIR / f"odds_props_{event_id}.json"
            with open(cache_file, "w") as f:
                json.dump(props_data, f, indent=2)

            for bookmaker in props_data.get("bookmakers", []):
                book_name = bookmaker["key"]
                for market in bookmaker.get("markets", []):
                    if market["key"] != "player_saves":
                        continue
                    for outcome in market.get("outcomes", []):
                        player_name = outcome.get("description", "")
                        point = outcome.get("point")
                        price = outcome.get("price")
                        side = outcome.get("name", "").lower()

                        if player_name and point is not None and price is not None:
                            all_odds.append({
                                "event_id": event_id,
                                "home_team": home,
                                "away_team": away,
                                "player_name": player_name,
                                "line": float(point),
                                "odds": int(price),
                                "side": side,
                                "book": book_name,
                            })

        except Exception as e:
            logger.warning(f"    Could not get props for {event_id}: {e}")
            continue

    logger.info(f"  Total odds rows: {len(all_odds)}")
    return all_odds
