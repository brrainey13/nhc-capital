"""
Player Points Model — OVER 0.5 and OVER 1.5 strategies.

Strategy C: OVER 1.5 pts — model-informed, high-value longshots
Strategy B2: OVER 0.5 pts — minus-odds singles with edge

Calibration: Uses isotonic regression to convert raw model probs
to true probabilities (fitted on 18K holdout rows, Brier 0.066).
"""
import os
import pickle
import subprocess
from collections import defaultdict
from io import StringIO

import pandas as pd

PSQL = "/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql"
DB = "nhl_betting"
MASSIVE_EDGE = 0.15  # override team cap if edge this high
MODEL_DIR = os.path.expanduser("~/nhc-capital/nhl-betting/model")

# Load isotonic calibrator (fitted in calibrate_model.py)
_iso_calibrator = None


def get_calibrator():
    """Lazy-load the isotonic regression calibrator."""
    global _iso_calibrator
    if _iso_calibrator is None:
        cal_path = os.path.join(MODEL_DIR, "isotonic_calibrator.pkl")
        if os.path.exists(cal_path):
            _iso_calibrator = pickle.load(open(cal_path, "rb"))
        else:
            print("WARNING: No calibrator found, using raw probabilities")
    return _iso_calibrator


def calibrate_prob(raw_prob):
    """Convert raw model probability to calibrated probability.

    Raw model is ~4x overconfident (predicts 35% avg when reality is 9%).
    Isotonic regression maps raw → true probability.
    """
    cal = get_calibrator()
    if cal is not None:
        return float(cal.predict([raw_prob])[0])
    return raw_prob


def query(sql):
    r = subprocess.run(
        [PSQL, "-d", DB, "-c", f"COPY ({sql}) TO STDOUT WITH CSV HEADER"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return pd.DataFrame()
    return pd.read_csv(StringIO(r.stdout))


def get_player_team(name):
    """Look up player's current team tri_code from DB.

    Handles both full names ('Josh Norris') and initial names ('J. Norris')
    stored in the players table.
    """
    safe_name = name.replace("'", "''")
    # Try exact match first (full name)
    result = query(
        f"SELECT t.tri_code FROM players p JOIN teams t "
        f"ON p.current_team_id = t.team_id "
        f"WHERE p.first_name || ' ' || p.last_name = '{safe_name}' "
        f"LIMIT 1"
    )
    if not result.empty:
        return result.iloc[0]["tri_code"]
    # Fallback: match last name + first initial
    parts = safe_name.split()
    if len(parts) >= 2:
        first_initial = parts[0][0]
        last_name = " ".join(parts[1:])
        result = query(
            f"SELECT t.tri_code FROM players p JOIN teams t "
            f"ON p.current_team_id = t.team_id "
            f"WHERE p.last_name = '{last_name}' "
            f"AND p.first_name LIKE '{first_initial}%' "
            f"LIMIT 1"
        )
        if not result.empty:
            return result.iloc[0]["tri_code"]
    return None


def calc_edge(hit_rate, odds):
    """Calculate edge = hit_rate - breakeven implied probability."""
    if odds > 0:
        breakeven = 100 / (odds + 100)
    else:
        breakeven = abs(odds) / (abs(odds) + 100)
    return hit_rate - breakeven, breakeven


def kelly_size(edge, odds, fraction=0.25, bankroll=2500):
    """Quarter-Kelly bet sizing.

    Args:
        edge: estimated edge (hit_rate - breakeven)
        odds: American odds
        fraction: Kelly fraction (default 0.25 = quarter Kelly)
        bankroll: current bankroll in dollars

    Returns:
        (units, dollars) tuple. Returns (0, 0) if negative edge.
    """
    if edge <= 0:
        return 0.0, 0.0
    if odds > 0:
        b = odds / 100
    else:
        b = 100 / abs(odds)
    p = edge + (1 / (b + 1))  # implied prob + edge
    q = 1 - p
    f_star = (b * p - q) / b
    f_kelly = max(0, f_star * fraction)
    dollars = round(f_kelly * bankroll, 2)
    units = round(dollars / 25, 1)  # 1u = $25
    return units, dollars


def confidence_score_15(mp_rate, edge):
    """Confidence label for OVER 1.5 picks."""
    if (mp_rate >= 0.40 and edge >= 0.10) or (
        mp_rate >= 0.35 and edge >= 0.05
    ):
        return "🟢 HIGH"
    if mp_rate >= 0.30 and edge >= 0.03:
        return "🟡 MEDIUM"
    return "🟡 MEDIUM"


def confidence_score_05(edge, odds):
    """Confidence label for OVER 0.5 picks."""
    if odds >= 150:
        return "🟢 HIGH" if edge >= 0.10 else "🟡 MEDIUM"
    if -200 <= odds < 0:
        return "🟢 HIGH" if edge >= 0.06 else "🟡 MEDIUM"
    if odds < -200:
        return "🟡 MEDIUM" if edge >= 0.05 else "⚪ LOW"
    return "🟡 MEDIUM"


def run_over_15(best_odds, player_stats):
    """Generate OVER 1.5 point picks.

    Args:
        best_odds: dict from odds_pull.get_best_odds
        player_stats: dict of player stats keyed by player_id

    Returns:
        list of pick dicts sorted by edge, team-capped (max 1/team)
    """
    raw_picks = []

    for (player, market, side, line), prop in best_odds.items():
        if market != "player_points" or side != "Over" or line != 1.5:
            continue

        stats = None
        for s in player_stats.values():
            if s["name"] == player:
                stats = s
                break
        if not stats or stats["gp"] < 10:
            continue

        mp_rate = stats["mp_rate"]
        odds = prop["odds"]

        # Hybrid probability: blend season hit rate with calibrated model
        # If model prob available, use calibrated version weighted 50/50
        # with season rate for robustness
        raw_model_prob = stats.get("model_prob")
        if raw_model_prob is not None:
            cal_prob = calibrate_prob(raw_model_prob)
            # Blend: 50% calibrated model, 50% season hit rate
            est_prob = 0.5 * cal_prob + 0.5 * mp_rate
        else:
            est_prob = mp_rate

        edge, breakeven = calc_edge(est_prob, odds)

        if mp_rate >= 0.30 and edge > 0:
            units, dollars = kelly_size(edge, odds)
            raw_picks.append({
                **prop,
                "mp_rate": mp_rate,
                "est_prob": round(est_prob, 4),
                "calibrated": raw_model_prob is not None,
                "mp_games": stats["mp_games"],
                "gp": stats["gp"],
                "breakeven": breakeven,
                "edge": edge,
                "confidence": confidence_score_15(mp_rate, edge),
                "ppg": stats["ppg"],
                "units": units,
                "dollars": dollars,
            })

    # Sort by edge, cap 1 per team
    raw_picks.sort(key=lambda x: -x["edge"])
    filtered = []
    team_count = defaultdict(int)
    for p in raw_picks:
        team = get_player_team(p["player"]) or p["game"]
        if team_count[team] >= 1 and p["edge"] < MASSIVE_EDGE:
            continue
        p["player_team"] = team
        filtered.append(p)
        team_count[team] += 1

    return filtered


def run_over_05(best_odds, player_stats):
    """Generate OVER 0.5 point picks.

    Args:
        best_odds: dict from odds_pull.get_best_odds
        player_stats: dict of player stats keyed by player_id

    Returns:
        list of pick dicts sorted by edge, team-capped (max 2/team)
    """
    raw_picks = []

    for (player, market, side, line), prop in best_odds.items():
        if market != "player_points" or side != "Over" or line != 0.5:
            continue

        stats = None
        for s in player_stats.values():
            if s["name"] == player:
                stats = s
                break
        if not stats or stats["gp"] < 10:
            continue

        point_rate = stats["point_rate"]
        odds = prop["odds"]
        edge, breakeven = calc_edge(point_rate, odds)

        if edge >= 0.03 and point_rate >= 0.55:
            units, dollars = kelly_size(edge, odds)
            raw_picks.append({
                **prop,
                "point_rate": point_rate,
                "point_games": stats["point_games"],
                "gp": stats["gp"],
                "breakeven": breakeven,
                "edge": edge,
                "confidence": confidence_score_05(edge, odds),
                "ppg": stats["ppg"],
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


def get_games_with_multiple_15_edges(over_15_raw, best_odds, player_stats):
    """Find games where 2+ players qualified for OVER 1.5.

    Used to flag games for game total OVER bets (Strategy D).
    Returns set of event_ids.
    """
    # Re-run without team cap to find all qualifiers
    game_players = defaultdict(list)
    for (player, market, side, line), prop in best_odds.items():
        if market != "player_points" or side != "Over" or line != 1.5:
            continue
        stats = None
        for s in player_stats.values():
            if s["name"] == player:
                stats = s
                break
        if not stats or stats["gp"] < 10:
            continue
        edge, _ = calc_edge(stats["mp_rate"], prop["odds"])
        if stats["mp_rate"] >= 0.30 and edge > 0:
            game_players[prop["event_id"]].append(player)

    return {
        eid for eid, players in game_players.items() if len(players) >= 2
    }
