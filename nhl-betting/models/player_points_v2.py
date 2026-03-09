"""
Player Points V2 Model — Enhanced OVER 0.5 and OVER 1.5 strategies.

Improvements over V1:
  - Home/away point rate splits
  - Exponential decay recent form weighting
  - Opponent defensive quality adjustment
"""

import subprocess
from collections import defaultdict
from io import StringIO

import pandas as pd
from model.bankroll import kelly_size

PSQL = "/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql"
DB = "nhl_betting"
MASSIVE_EDGE = 0.15

# V2 blending weights (must sum to 1.0)
SPLIT_WEIGHT = 0.25
FORM_WEIGHT = 0.35
SEASON_WEIGHT = 0.40

# Exponential decay factor per game for recent form
DECAY_FACTOR = 0.97

# Minimum home or away games before using split-specific rate
MIN_SPLIT_GAMES = 5


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
    """Look up player's current team tri_code from DB."""
    safe_name = name.replace("'", "''")
    result = query(
        f"SELECT t.tri_code FROM players p JOIN teams t "
        f"ON p.current_team_id = t.team_id "
        f"WHERE p.first_name || ' ' || p.last_name = '{safe_name}' "
        f"LIMIT 1"
    )
    if not result.empty:
        return result.iloc[0]["tri_code"]
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


# ---------------------------------------------------------------------------
# Opponent adjustment cache (loaded once per run)
# ---------------------------------------------------------------------------
_opponent_cache = None


def _load_opponent_adjustments():
    """Load opponent defensive quality multipliers for current season.

    Returns dict: tri_code -> multiplier (>1.0 means weaker defense).
    """
    global _opponent_cache
    if _opponent_cache is not None:
        return _opponent_cache

    # Get the latest season
    season_df = query(
        "SELECT MAX(season) AS season FROM games WHERE game_state = 'OFF'"
    )
    if season_df.empty:
        _opponent_cache = {}
        return _opponent_cache
    season = int(season_df.iloc[0]["season"])

    # Goals against per team this season
    df = query(
        f"SELECT t.tri_code, "
        f"AVG(CASE WHEN gts.is_home = 1 THEN g.away_score ELSE g.home_score END) "
        f"AS ga_per_game "
        f"FROM game_team_stats gts "
        f"JOIN games g ON gts.game_id = g.game_id "
        f"JOIN teams t ON gts.team_id = t.team_id "
        f"WHERE g.season = {season} AND g.game_state = 'OFF' "
        f"GROUP BY t.tri_code"
    )
    if df.empty:
        _opponent_cache = {}
        return _opponent_cache

    league_avg = df["ga_per_game"].mean()
    if league_avg == 0:
        _opponent_cache = {}
        return _opponent_cache

    _opponent_cache = {
        row["tri_code"]: row["ga_per_game"] / league_avg
        for _, row in df.iterrows()
    }
    return _opponent_cache


def get_opponent_multiplier(opponent_tri_code):
    """Return defensive quality multiplier for an opponent.

    >1.0 = opponent allows more goals than average (good for points).
    <1.0 = opponent allows fewer goals than average (bad for points).
    Returns 1.0 if opponent not found.
    """
    adjustments = _load_opponent_adjustments()
    return adjustments.get(opponent_tri_code, 1.0)


# ---------------------------------------------------------------------------
# Game log analysis helpers
# ---------------------------------------------------------------------------

def _parse_game_log(stats, line):
    """Extract game log from player_stats dict and compute V2 rates.

    Args:
        stats: player_stats dict entry (has 'game_log' list if available)
        line: point line (0.5 or 1.5)

    Returns:
        dict with season_rate, home_rate, away_rate, form_rate,
        home_games, away_games, or None if insufficient data.
    """
    game_log = stats.get("game_log")
    if not game_log or len(game_log) < 10:
        return None

    threshold = line  # 0.5 or 1.5

    total_hits = 0
    home_hits = 0
    home_games = 0
    away_hits = 0
    away_games = 0

    # Weighted form calculation (game_log should be newest-first)
    weighted_sum = 0.0
    weight_total = 0.0

    for i, game in enumerate(game_log):
        points = game.get("points", 0)
        hit = 1 if points > threshold else 0
        total_hits += hit

        flag = game.get("homeRoadFlag", "")
        if flag == "H":
            home_games += 1
            home_hits += hit
        elif flag == "R":
            away_games += 1
            away_hits += hit

        # Exponential decay: newest game (i=0) gets weight 1.0
        weight = DECAY_FACTOR ** i
        weighted_sum += hit * weight
        weight_total += weight

    gp = len(game_log)
    season_rate = total_hits / gp
    home_rate = (home_hits / home_games) if home_games >= MIN_SPLIT_GAMES else season_rate
    away_rate = (away_hits / away_games) if away_games >= MIN_SPLIT_GAMES else season_rate
    form_rate = weighted_sum / weight_total if weight_total > 0 else season_rate

    return {
        "season_rate": season_rate,
        "home_rate": home_rate,
        "away_rate": away_rate,
        "form_rate": form_rate,
        "home_games": home_games,
        "away_games": away_games,
    }


def _get_adjusted_rate(stats, line, is_home, opponent_tri_code):
    """Compute the V2 adjusted rate for a player.

    Returns (adjusted_rate, v2_details_dict) or (None, None) if no data.
    """
    rates = _parse_game_log(stats, line)
    if rates is None:
        return None, None

    split_rate = rates["home_rate"] if is_home else rates["away_rate"]

    blended = (
        SPLIT_WEIGHT * split_rate
        + FORM_WEIGHT * rates["form_rate"]
        + SEASON_WEIGHT * rates["season_rate"]
    )

    opp_mult = get_opponent_multiplier(opponent_tri_code) if opponent_tri_code else 1.0
    adjusted = blended * opp_mult

    details = {
        "season_rate": round(rates["season_rate"], 4),
        "home_rate": round(rates["home_rate"], 4),
        "away_rate": round(rates["away_rate"], 4),
        "form_rate": round(rates["form_rate"], 4),
        "split_used": "home" if is_home else "away",
        "opp_multiplier": round(opp_mult, 4),
        "blended_pre_opp": round(blended, 4),
        "adjusted_rate": round(adjusted, 4),
    }
    return adjusted, details


def _resolve_home_away(prop):
    """Determine if the player's team is home and the opponent tri_code.

    Returns (is_home, opponent_tri_code) using the prop's game field
    and player team lookup.
    """
    player_team = get_player_team(prop.get("player", ""))
    game_str = prop.get("game", "")

    # game field is typically "TEAM1 @ TEAM2" or "TEAM1 vs TEAM2"
    # or sometimes just team codes separated by delimiter
    is_home = None
    opponent = None

    if player_team and game_str:
        # Try parsing "AAA @ BBB" format (AAA=away, BBB=home)
        if " @ " in game_str:
            parts = game_str.split(" @ ")
            away_code = parts[0].strip()
            home_code = parts[1].strip()
            if player_team == home_code:
                is_home = True
                opponent = away_code
            elif player_team == away_code:
                is_home = False
                opponent = home_code
        elif " vs " in game_str or " vs. " in game_str:
            sep = " vs. " if " vs. " in game_str else " vs "
            parts = game_str.split(sep)
            team_a = parts[0].strip()
            team_b = parts[1].strip()
            if player_team == team_a:
                is_home = True
                opponent = team_b
            elif player_team == team_b:
                is_home = False
                opponent = team_a

    return is_home, opponent


# ---------------------------------------------------------------------------
# Public API — same interface as V1
# ---------------------------------------------------------------------------

def run_over_15_v2(best_odds, player_stats, bankroll=None):
    """Generate OVER 1.5 point picks using V2 model.

    Same interface and return format as V1's run_over_15.
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

        odds = prop["odds"]
        is_home, opponent = _resolve_home_away(prop)

        # Try V2 adjusted rate
        adjusted_rate, v2_details = _get_adjusted_rate(
            stats, 1.5, is_home, opponent
        )

        if adjusted_rate is not None:
            est_prob = adjusted_rate
        else:
            # Fallback to V1 behavior
            est_prob = stats["mp_rate"]
            v2_details = {"fallback": "v1_rate"}

        edge, breakeven = calc_edge(est_prob, odds)

        if stats["mp_rate"] >= 0.30 and edge > 0:
            units, dollars = kelly_size(edge=edge, odds=odds, bankroll=bankroll)
            raw_picks.append({
                **prop,
                "mp_rate": stats["mp_rate"],
                "est_prob": round(est_prob, 4),
                "mp_games": stats["mp_games"],
                "gp": stats["gp"],
                "breakeven": breakeven,
                "edge": edge,
                "confidence": confidence_score_15(stats["mp_rate"], edge),
                "ppg": stats["ppg"],
                "units": units,
                "dollars": dollars,
                "model_version": "v2",
                "v2_details": v2_details,
            })

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


def run_over_05_v2(best_odds, player_stats, bankroll=None):
    """Generate OVER 0.5 point picks using V2 model.

    Same interface and return format as V1's run_over_05.
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

        odds = prop["odds"]
        is_home, opponent = _resolve_home_away(prop)

        adjusted_rate, v2_details = _get_adjusted_rate(
            stats, 0.5, is_home, opponent
        )

        if adjusted_rate is not None:
            point_rate = adjusted_rate
        else:
            point_rate = stats["point_rate"]
            v2_details = {"fallback": "v1_rate"}

        edge, breakeven = calc_edge(point_rate, odds)

        if edge >= 0.03 and stats["point_rate"] >= 0.55:
            units, dollars = kelly_size(edge=edge, odds=odds, bankroll=bankroll)
            raw_picks.append({
                **prop,
                "point_rate": round(point_rate, 4),
                "season_point_rate": stats["point_rate"],
                "point_games": stats["point_games"],
                "gp": stats["gp"],
                "breakeven": breakeven,
                "edge": edge,
                "confidence": confidence_score_05(edge, odds),
                "ppg": stats["ppg"],
                "units": units,
                "dollars": dollars,
                "model_version": "v2",
                "v2_details": v2_details,
            })

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
