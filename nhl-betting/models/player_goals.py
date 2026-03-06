"""
Player Goals Model — OVER 0.5 goals (anytime goalscorer).

Strategy E: Anytime Goalscorer
Plus-money bets on players with high goal rates vs implied odds.
"""
import subprocess
from collections import defaultdict
from io import StringIO

import pandas as pd

from models.player_points import calc_edge, kelly_size, get_player_team

PSQL = "/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql"
DB = "nhl_betting"
MASSIVE_EDGE = 0.15


def query(sql):
    r = subprocess.run(
        [PSQL, "-d", DB, "-c", f"COPY ({sql}) TO STDOUT WITH CSV HEADER"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return pd.DataFrame()
    return pd.read_csv(StringIO(r.stdout))


def confidence_score(edge, odds):
    """Confidence label for goalscorer picks."""
    if edge >= 0.12:
        return "🟢 HIGH"
    if edge >= 0.07:
        return "🟡 MEDIUM"
    return "⚪ LOW"


def run_anytime_goalscorer(best_odds, player_stats):
    """Generate OVER 0.5 goals (anytime goalscorer) picks.

    Args:
        best_odds: dict from odds_pull.get_best_odds
        player_stats: dict of player stats keyed by player_id
            Must include 'goal_rate' and 'gpg' fields.

    Returns:
        list of pick dicts sorted by edge, team-capped (max 2/team)
    """
    raw_picks = []

    for (player, market, side, line), prop in best_odds.items():
        if market != "player_goals" or side != "Over" or line != 0.5:
            continue

        stats = None
        for s in player_stats.values():
            if s["name"] == player:
                stats = s
                break
        if not stats or stats["gp"] < 10:
            continue

        goal_rate = stats.get("goal_rate", 0)
        odds = prop["odds"]
        edge, breakeven = calc_edge(goal_rate, odds)

        # Tightened filters (2026-03-01):
        # - Goal rate >= 35% (was 20%) — cuts low-volume scorers
        # - Avg SOG >= 2.5 — ensures high-shot players with more chances
        # - Edge >= 5% (was 3%) — higher conviction
        # Backtest: 6-3 (67%) vs old 6-11 (35%) over 2 nights
        avg_sog = stats.get("avg_sog", 0)
        if avg_sog == 0:
            # Estimate from goals per game if avg_sog not available
            avg_sog = stats.get("gpg", 0) * 8  # rough: ~8 SOG per goal
        if edge >= 0.05 and goal_rate >= 0.35 and avg_sog >= 2.5 and odds > 0:
            units, dollars = kelly_size(edge, odds)
            raw_picks.append({
                **prop,
                "goal_rate": goal_rate,
                "goal_games": stats.get("goal_games", 0),
                "gp": stats["gp"],
                "gpg": stats.get("gpg", 0),
                "breakeven": breakeven,
                "edge": edge,
                "confidence": confidence_score(edge, odds),
                "units": units,
                "dollars": dollars,
            })

    # Sort by edge, cap 2 per team
    raw_picks.sort(key=lambda x: -x["edge"])
    filtered = []
    team_count = defaultdict(int)
    for p in raw_picks:
        team = get_player_team(p["player"]) or p["game"]
        if team_count[team] >= 2 and p["edge"] < MASSIVE_EDGE:
            continue
        p["player_team"] = team
        filtered.append(p)
        team_count[team] += 1

    return filtered
