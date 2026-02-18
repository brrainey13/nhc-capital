#!/usr/bin/env python3
"""
Daily data pipeline for NHL goalie saves betting system.
Pulls today's schedule, starting goalies, odds, and team stats.
Builds feature vectors for each goalie and runs model predictions.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import requests
import yaml

# Paths
ROOT = Path(__file__).parent.parent
DEPLOY_DIR = Path(__file__).parent
MODEL_DIR = ROOT / "model"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "api_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Load config
with open(DEPLOY_DIR / "config.yaml") as f:
    CONFIG = yaml.safe_load(f)

# Load .env
from dotenv import load_dotenv
load_dotenv(DEPLOY_DIR / ".env")

ODDS_API_KEY = os.getenv("ODDS_API_KEY", CONFIG["apis"].get("odds_api_key", ""))
NHL_API_BASE = CONFIG["apis"]["nhl_api_base"]
DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"

logger = logging.getLogger("data_pipeline")


# ============================================================
# NHL API
# ============================================================

def get_today_schedule(date: str = None) -> list[dict]:
    """Get today's NHL schedule from the NHL API.
    Returns list of games with home/away teams and game IDs.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    url = f"{NHL_API_BASE}/schedule/{date}"
    logger.info(f"Fetching schedule for {date}")

    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # Cache raw response
    cache_file = CACHE_DIR / f"schedule_{date}.json"
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)

    games = []
    for week in data.get("gameWeek", []):
        if week.get("date") != date:
            continue
        for game in week.get("games", []):
            if game.get("gameType") not in (2, 3):  # Regular season + playoffs only
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

        # Check matchup section for goalies
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

        # Also try game summary for confirmed starters
        summary = data.get("summary", {})
        if summary:
            result["confirmed"] = True  # If summary exists, game has likely started or starters confirmed

        return result

    except Exception as e:
        logger.warning(f"  Could not get goalies for game {game_id}: {e}")
        return {"home_goalie": None, "away_goalie": None, "confirmed": False}


def get_team_recent_stats(team_id: int, n_games: int = 10) -> dict:
    """Get team's last N games from our database for Corsi calculation."""
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    cur.execute("""
        SELECT gts.shots_attempted, gts.shots_on_goal, gts.takeaways, gts.giveaways,
               gts.hits, gts.power_play_opportunities,
               g.game_date
        FROM game_team_stats gts
        JOIN games g ON gts.game_id = g.game_id
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

    # Also need opponent shots_attempted for Corsi
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
        "hits_avg_10": float((df["takeaways"] + df["giveaways"]).mean()),  # proxy
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

    # Rolling features matching the model
    last_date = pd.to_datetime(df["game_date"].iloc[0])
    second_date = pd.to_datetime(df["game_date"].iloc[1]) if len(df) > 1 else last_date - timedelta(days=7)

    # Was pulled in recent games
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


# ============================================================
# ODDS API
# ============================================================

def get_goalie_saves_odds(date: str = None) -> list[dict]:
    """
    Pull goalie saves over/under lines from The Odds API.
    Market: player_saves (or player_saves_over_under)
    """
    if not ODDS_API_KEY or ODDS_API_KEY.startswith("$"):
        logger.error("ODDS_API_KEY not set! Sign up at https://the-odds-api.com/")
        return []

    # The Odds API endpoint for player props
    url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/events"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json()

        # Log remaining requests
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        logger.info(f"  Odds API: {remaining} requests remaining ({used} used)")

        # Cache events
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

    # For each event, get player props (saves market)
    all_odds = []
    for event in events:
        event_id = event["id"]
        home = event.get("home_team", "")
        away = event.get("away_team", "")

        # Get player props for this event
        props_url = f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events/{event_id}/odds"
        props_params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "player_saves",  # goalie saves market
            "oddsFormat": "american",
        }

        try:
            resp = requests.get(props_url, params=props_params, timeout=15)
            resp.raise_for_status()
            props_data = resp.json()

            remaining = resp.headers.get("x-requests-remaining", "?")
            logger.info(f"    {away} @ {home}: {remaining} API calls left")

            # Cache
            cache_file = CACHE_DIR / f"odds_props_{event_id}.json"
            with open(cache_file, "w") as f:
                json.dump(props_data, f, indent=2)

            # Parse bookmaker odds
            for bookmaker in props_data.get("bookmakers", []):
                book_name = bookmaker["key"]
                for market in bookmaker.get("markets", []):
                    if market["key"] != "player_saves":
                        continue
                    for outcome in market.get("outcomes", []):
                        player_name = outcome.get("description", "")
                        point = outcome.get("point")
                        price = outcome.get("price")
                        side = outcome.get("name", "").lower()  # "Over" or "Under"

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


def aggregate_odds(raw_odds: list[dict]) -> pd.DataFrame:
    """
    Aggregate odds across books to get consensus line + best available juice.
    Returns one row per goalie with consensus line, over/under odds.
    """
    if not raw_odds:
        return pd.DataFrame()

    df = pd.DataFrame(raw_odds)

    # Split into over/under
    overs = df[df["side"] == "over"].copy()
    unders = df[df["side"] == "under"].copy()

    # Group by player to get consensus
    if overs.empty and unders.empty:
        return pd.DataFrame()

    # Use the most common line as consensus
    consensus = []
    for player_name in df["player_name"].unique():
        p_df = df[df["player_name"] == player_name]
        # Most common line
        line = p_df["line"].mode().iloc[0] if not p_df["line"].mode().empty else p_df["line"].median()

        # Best odds for over and under at that line
        p_overs = p_df[(p_df["side"] == "over") & (p_df["line"] == line)]
        p_unders = p_df[(p_df["side"] == "under") & (p_df["line"] == line)]

        over_odds = int(p_overs["odds"].max()) if not p_overs.empty else -110
        under_odds = int(p_unders["odds"].max()) if not p_unders.empty else -110

        # Get game info from first row
        first = p_df.iloc[0]

        consensus.append({
            "player_name": player_name,
            "line": float(line),
            "over_odds": over_odds,
            "under_odds": under_odds,
            "home_team": first["home_team"],
            "away_team": first["away_team"],
            "n_books": p_df["book"].nunique(),
        })

    return pd.DataFrame(consensus)


# ============================================================
# FEATURE BUILDER
# ============================================================

def build_daily_features(games: list[dict], odds_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build feature vectors for today's goalies matching the model's expected features.
    """
    import joblib

    # Load model metadata for feature list
    with open(MODEL_DIR / "model_metadata.json") as f:
        metadata = json.load(f)
    feature_list = metadata["features"]
    thresholds = metadata["thresholds"]

    rows = []

    for game in games:
        # Get goalies
        goalie_info = get_probable_goalies(game["game_id"])

        for side in ["home", "away"]:
            goalie = goalie_info.get(f"{side}_goalie")
            if not goalie or not goalie.get("name"):
                logger.warning(f"  No {side} goalie for {game['home_team']} vs {game['away_team']}")
                continue

            player_name = goalie["name"]
            player_id = goalie.get("player_id")

            # Check if this goalie has odds
            goalie_odds = odds_df[odds_df["player_name"].str.lower() == player_name.lower()] if not odds_df.empty else pd.DataFrame()
            if goalie_odds.empty:
                # Try partial match
                goalie_odds = odds_df[odds_df["player_name"].str.contains(player_name.split()[-1], case=False, na=False)] if not odds_df.empty else pd.DataFrame()

            if goalie_odds.empty:
                logger.info(f"  No odds for {player_name}, skipping")
                continue

            odds_row = goalie_odds.iloc[0]
            line = odds_row["line"]
            over_odds = odds_row["over_odds"]
            under_odds = odds_row["under_odds"]

            # Get goalie's recent stats
            goalie_stats = get_goalie_recent_stats(player_id) if player_id else {}

            # Determine opponent
            if side == "home":
                opp_team_id = game.get("away_team_id")
                own_team_id = game.get("home_team_id")
                is_home = 1
            else:
                opp_team_id = game.get("home_team_id")
                own_team_id = game.get("away_team_id")
                is_home = 0

            # Get team stats
            opp_stats = get_team_recent_stats(opp_team_id) if opp_team_id else {}
            own_stats = get_team_recent_stats(own_team_id) if own_team_id else {}

            # Build feature row matching model input
            feature_row = {
                "game_id": game["game_id"],
                "date": game["date"],
                "player_name": player_name,
                "player_id": player_id,
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "is_home": is_home,
                "line": line,
                "over_odds": over_odds,
                "under_odds": under_odds,
                "starter_confirmed": goalie_info.get("confirmed", False),
                # Goalie rolling stats
                "sa_avg_10": goalie_stats.get("sa_avg_10"),
                "sa_avg_20": goalie_stats.get("sa_avg_20"),
                "svpct_avg_10": goalie_stats.get("svpct_avg_10"),
                "svpct_avg_20": goalie_stats.get("svpct_avg_20"),
                "pull_rate_10": goalie_stats.get("pull_rate_10"),
                "days_rest": goalie_stats.get("days_rest", 7),
                "starts_last_7d": goalie_stats.get("starts_last_7d", 0),
                "last_game_date": goalie_stats.get("last_game_date"),
                # Opponent team stats
                "opp_team_sog_avg_10": opp_stats.get("sog_avg_10"),
                "opp_team_pp_opps_avg_10": opp_stats.get("pp_opps_avg_10"),
                "opp_corsi_pct_avg_10": opp_stats.get("corsi_pct_avg_10"),
                "opp_corsi_diff_avg_10": opp_stats.get("corsi_diff_avg_10"),
                "opp_puck_control_avg_10": opp_stats.get("puck_control_avg_10"),
                # Own team stats
                "own_corsi_pct_avg_10": own_stats.get("corsi_pct_avg_10"),
                "own_def_missing_toi": 0,  # Can't know lineup absences pre-game easily
                # Thresholds (for strategy engine)
                "corsi_q25": thresholds["corsi_q25"],
                "corsi_q30": thresholds["corsi_q30"],
                "corsi_q75": thresholds["corsi_q75"],
                "corsi_diff_q75": thresholds["corsi_diff_q75"],
                "puck_control_q75": thresholds["puck_control_q75"],
            }

            rows.append(feature_row)

    if not rows:
        logger.warning("  No goalie feature rows built")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    logger.info(f"  Built features for {len(df)} goalies")
    return df


def run_predictions(features_df: pd.DataFrame) -> pd.DataFrame:
    """Run the LightGBM model on today's features."""
    import joblib

    if features_df.empty:
        return features_df

    model = joblib.load(MODEL_DIR / "lightgbm_model.pkl")
    with open(MODEL_DIR / "model_metadata.json") as f:
        metadata = json.load(f)

    feature_cols = metadata["features"]
    available = [c for c in feature_cols if c in features_df.columns]

    X = features_df[available].fillna(-999)
    predictions = model.predict(X)

    features_df = features_df.copy()
    features_df["pred_saves"] = predictions
    features_df["gap"] = features_df["pred_saves"] - features_df["line"]
    features_df["abs_gap"] = features_df["gap"].abs()
    features_df["model_side"] = np.where(features_df["pred_saves"] < features_df["line"], "under", "over")

    logger.info(f"  Predictions complete: {len(features_df)} goalies")
    for _, row in features_df.iterrows():
        logger.info(f"    {row['player_name']}: pred={row['pred_saves']:.1f}, line={row['line']}, gap={row['gap']:+.1f} → {row['model_side'].upper()}")

    return features_df


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline(date: str = None, skip_odds: bool = False) -> pd.DataFrame:
    """Run the full daily data pipeline."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"{'='*60}")
    logger.info(f"DAILY PIPELINE — {date}")
    logger.info(f"{'='*60}")

    # 1. Get today's schedule
    games = get_today_schedule(date)
    if not games:
        logger.info("No NHL games today. Done.")
        return pd.DataFrame()

    # 2. Get odds
    if skip_odds:
        logger.info("Skipping odds fetch (skip_odds=True)")
        odds_df = pd.DataFrame()
    else:
        raw_odds = get_goalie_saves_odds(date)
        odds_df = aggregate_odds(raw_odds)

    # 3. Build features
    features_df = build_daily_features(games, odds_df)
    if features_df.empty:
        logger.warning("No features built — no goalies matched to odds")
        return pd.DataFrame()

    # 4. Run model predictions
    result = run_predictions(features_df)

    # 5. Save daily slate
    slate_path = DATA_DIR / f"daily_slate_{date}.csv"
    result.to_csv(slate_path, index=False)
    logger.info(f"  Saved slate to {slate_path}")

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    date = sys.argv[1] if len(sys.argv) > 1 else None
    skip_odds = "--skip-odds" in sys.argv

    run_pipeline(date=date, skip_odds=skip_odds)
