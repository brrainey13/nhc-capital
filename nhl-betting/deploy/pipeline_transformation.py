#!/usr/bin/env python3
"""Data transformation: odds aggregation and feature building."""

import json
import logging
from pathlib import Path

import pandas as pd
from pipeline_extraction import get_goalie_recent_stats, get_probable_goalies, get_team_recent_stats

ROOT = Path(__file__).parent.parent
MODEL_DIR = ROOT / "model"

logger = logging.getLogger("data_pipeline")


def aggregate_odds(raw_odds: list[dict]) -> pd.DataFrame:
    """Aggregate odds across books to get consensus line + best available juice."""
    if not raw_odds:
        return pd.DataFrame()

    df = pd.DataFrame(raw_odds)

    if df.empty:
        return pd.DataFrame()

    consensus = []
    for player_name in df["player_name"].unique():
        p_df = df[df["player_name"] == player_name]
        line = p_df["line"].mode().iloc[0] if not p_df["line"].mode().empty else p_df["line"].median()

        p_overs = p_df[(p_df["side"] == "over") & (p_df["line"] == line)]
        p_unders = p_df[(p_df["side"] == "under") & (p_df["line"] == line)]

        over_odds = int(p_overs["odds"].max()) if not p_overs.empty else -110
        under_odds = int(p_unders["odds"].max()) if not p_unders.empty else -110

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


def build_daily_features(games: list[dict], odds_df: pd.DataFrame) -> pd.DataFrame:
    """Build feature vectors for today's goalies matching the model's expected features."""
    with open(MODEL_DIR / "model_metadata.json") as f:
        metadata = json.load(f)
    feature_list = metadata["features"]
    thresholds = metadata["thresholds"]

    rows = []

    for game in games:
        goalie_info = get_probable_goalies(game["game_id"])

        for side in ["home", "away"]:
            goalie = goalie_info.get(f"{side}_goalie")
            if not goalie or not goalie.get("name"):
                logger.warning(f"  No {side} goalie for {game['home_team']} vs {game['away_team']}")
                continue

            player_name = goalie["name"]
            player_id = goalie.get("player_id")

            goalie_odds = odds_df[odds_df["player_name"].str.lower() == player_name.lower()] if not odds_df.empty else pd.DataFrame()
            if goalie_odds.empty:
                goalie_odds = odds_df[odds_df["player_name"].str.contains(player_name.split()[-1], case=False, na=False)] if not odds_df.empty else pd.DataFrame()

            if goalie_odds.empty:
                logger.info(f"  No odds for {player_name}, skipping")
                continue

            odds_row = goalie_odds.iloc[0]
            line = odds_row["line"]
            over_odds = odds_row["over_odds"]
            under_odds = odds_row["under_odds"]

            goalie_stats = get_goalie_recent_stats(player_id) if player_id else {}

            if side == "home":
                opp_team_id = game.get("away_team_id")
                own_team_id = game.get("home_team_id")
                is_home = 1
            else:
                opp_team_id = game.get("home_team_id")
                own_team_id = game.get("away_team_id")
                is_home = 0

            opp_stats = get_team_recent_stats(opp_team_id) if opp_team_id else {}
            own_stats = get_team_recent_stats(own_team_id) if own_team_id else {}

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
                "sa_avg_10": goalie_stats.get("sa_avg_10"),
                "sa_avg_20": goalie_stats.get("sa_avg_20"),
                "svpct_avg_10": goalie_stats.get("svpct_avg_10"),
                "svpct_avg_20": goalie_stats.get("svpct_avg_20"),
                "pull_rate_10": goalie_stats.get("pull_rate_10"),
                "days_rest": goalie_stats.get("days_rest", 7),
                "starts_last_7d": goalie_stats.get("starts_last_7d", 0),
                "last_game_date": goalie_stats.get("last_game_date"),
                "opp_team_sog_avg_10": opp_stats.get("sog_avg_10"),
                "opp_team_pp_opps_avg_10": opp_stats.get("pp_opps_avg_10"),
                "opp_corsi_pct_avg_10": opp_stats.get("corsi_pct_avg_10"),
                "opp_corsi_diff_avg_10": opp_stats.get("corsi_diff_avg_10"),
                "opp_puck_control_avg_10": opp_stats.get("puck_control_avg_10"),
                "own_corsi_pct_avg_10": own_stats.get("corsi_pct_avg_10"),
                "own_def_missing_toi": 0,
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
