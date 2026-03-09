#!/usr/bin/env python3
"""
Compare Player Points V1 vs V2 models side-by-side.

Usage:
    cd nhl-betting
    .venv/bin/python scripts/compare_models.py [DATE]

DATE defaults to today. Format: YYYY-MM-DD

Requires ODDS_API_KEY in environment (or admin-dashboard/.env).
"""

import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from models.player_points import run_over_05, run_over_15
from models.player_points_v2 import run_over_05_v2, run_over_15_v2

# Load env from admin-dashboard/.env if ODDS_API_KEY not already set
if not os.environ.get("ODDS_API_KEY"):
    env_path = Path(__file__).resolve().parents[2] / "admin-dashboard" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("ODDS_API_KEY", "")
if not API_KEY:
    print("ERROR: ODDS_API_KEY not set. Add to env or admin-dashboard/.env")
    sys.exit(1)

# Determine target date
if len(sys.argv) > 1:
    target_date = sys.argv[1]
else:
    from datetime import date
    target_date = date.today().isoformat()

print(f"Comparing models for date: {target_date}")
print("=" * 70)

# -------------------------------------------------------------------
# 1. Pull live odds
# -------------------------------------------------------------------
print("Pulling live odds...")
events_r = requests.get(
    "https://api.the-odds-api.com/v4/sports/icehockey_nhl/events",
    params={"apiKey": API_KEY},
    timeout=30,
)
events = events_r.json()
tonight = [e for e in events if target_date in e.get("commence_time", "")]
print(f"Games found: {len(tonight)}")

if not tonight:
    print("No games found for this date. Exiting.")
    sys.exit(0)

all_props = []
for ev in tonight:
    eid = ev["id"]
    game = f"{ev['away_team']} @ {ev['home_team']}"
    r = requests.get(
        f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events/{eid}/odds",
        params={
            "apiKey": API_KEY,
            "regions": "us,us2",
            "markets": "player_points",
            "oddsFormat": "american",
            "bookmakers": "draftkings,fanduel,betmgm,hardrockbet",
        },
        timeout=30,
    )
    d = r.json()
    for bk in d.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            for o in mkt.get("outcomes", []):
                all_props.append({
                    "game": game,
                    "book": bk["key"],
                    "market": mkt["key"],
                    "player": o.get("description", ""),
                    "side": o["name"],
                    "line": o.get("point", 0),
                    "odds": o["price"],
                    "event_id": eid,
                })
    time.sleep(0.3)

print(f"Total prop lines: {len(all_props)}")

# Best odds per key
best_odds = defaultdict(lambda: None)
for p in all_props:
    key = (p["player"], p["market"], p["side"], p["line"])
    if best_odds[key] is None or p["odds"] > best_odds[key]["odds"]:
        best_odds[key] = p

# -------------------------------------------------------------------
# 2. Pull player stats with game logs (needed for V2)
# -------------------------------------------------------------------
print("\nPulling player season stats from NHL API...")

unique_players = set(
    p["player"]
    for p in all_props
    if p["player"] and p["market"] == "player_points" and p["side"] == "Over"
)

player_stats = {}
player_ids_checked = set()


def get_player_stats_with_log(name):
    """Get player stats including full game log for V2."""
    last_name = name.split()[-1]
    search_r = requests.get(
        f"https://search.d3.nhle.com/api/v1/search/player"
        f"?culture=en-us&limit=5&q={last_name}",
        timeout=15,
    )
    results = search_r.json()

    for p in results:
        if p["name"] == name and p.get("active"):
            pid = p["playerId"]
            if pid in player_ids_checked:
                return player_stats.get(pid)
            player_ids_checked.add(pid)

            stats_r = requests.get(
                f"https://api-web.nhle.com/v1/player/{pid}/game-log/20252026/2",
                timeout=15,
            )
            games = stats_r.json().get("gameLog", [])
            if not games:
                return None

            gp = len(games)
            total_pts = sum(
                g.get("goals", 0) + g.get("assists", 0) for g in games
            )
            games_2plus = sum(
                1
                for g in games
                if (g.get("goals", 0) + g.get("assists", 0)) >= 2
            )
            games_1plus = sum(
                1
                for g in games
                if (g.get("goals", 0) + g.get("assists", 0)) >= 1
            )

            # Build game_log with points and homeRoadFlag for V2
            game_log = []
            for g in games:
                pts = g.get("goals", 0) + g.get("assists", 0)
                game_log.append({
                    "points": pts,
                    "homeRoadFlag": g.get("homeRoadFlag", ""),
                    "gameDate": g.get("gameDate", ""),
                })

            stats = {
                "player_id": pid,
                "name": name,
                "gp": gp,
                "pts": total_pts,
                "ppg": round(total_pts / gp, 3),
                "mp_rate": round(games_2plus / gp, 3),
                "point_rate": round(games_1plus / gp, 3),
                "mp_games": games_2plus,
                "point_games": games_1plus,
                "game_log": game_log,
            }
            player_stats[pid] = stats
            return stats
    return None


for i, name in enumerate(unique_players):
    get_player_stats_with_log(name)
    if i % 20 == 0 and i > 0:
        print(f"  ...{i}/{len(unique_players)}")
        time.sleep(0.3)

print(f"Found stats for {len(player_stats)} players")

# -------------------------------------------------------------------
# 3. Run both models
# -------------------------------------------------------------------
print("\n" + "=" * 70)
print("RUNNING MODELS")
print("=" * 70)

v1_05 = run_over_05(dict(best_odds), player_stats)
v1_15 = run_over_15(dict(best_odds), player_stats)
v2_05 = run_over_05_v2(dict(best_odds), player_stats)
v2_15 = run_over_15_v2(dict(best_odds), player_stats)

# -------------------------------------------------------------------
# 4. Compare
# -------------------------------------------------------------------


def print_comparison(label, v1_picks, v2_picks):
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")

    v1_map = {p["player"]: p for p in v1_picks}
    v2_map = {p["player"]: p for p in v2_picks}
    all_players = sorted(set(v1_map) | set(v2_map))

    overlap = set(v1_map) & set(v2_map)
    v1_only = set(v1_map) - set(v2_map)
    v2_only = set(v2_map) - set(v1_map)

    print(f"\n  V1 picks: {len(v1_picks)}  |  V2 picks: {len(v2_picks)}")
    print(f"  Overlap: {len(overlap)}  |  V1-only: {len(v1_only)}  |  V2-only: {len(v2_only)}")

    if all_players:
        hdr = f"  {'Player':<25} {'V1 Edge':>8} {'V2 Edge':>8} {'V1 Rate':>8} {'V2 Rate':>8} {'Opp Adj':>8} {'Status'}"
        print(f"\n{hdr}")
        print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")

        for player in all_players:
            v1 = v1_map.get(player)
            v2 = v2_map.get(player)

            v1_edge = f"{v1['edge']:+.1%}" if v1 else "   —"
            v2_edge = f"{v2['edge']:+.1%}" if v2 else "   —"

            # Get the rate field (different for 0.5 vs 1.5)
            if v1:
                v1_rate = f"{v1.get('point_rate', v1.get('mp_rate', 0)):.1%}"
            else:
                v1_rate = "   —"

            if v2:
                v2_rate = f"{v2.get('est_prob', v2.get('point_rate', 0)):.1%}"
                details = v2.get("v2_details", {})
                opp_adj = details.get("opp_multiplier")
                opp_str = f"{opp_adj:.3f}" if opp_adj else "   —"
            else:
                v2_rate = "   —"
                opp_str = "   —"

            if v1 and v2:
                status = "BOTH"
            elif v1:
                status = "V1 ONLY"
            else:
                status = "V2 ONLY"

            print(f"  {player:<25} {v1_edge:>8} {v2_edge:>8} {v1_rate:>8} {v2_rate:>8} {opp_str:>8} {status}")

    if not all_players:
        print("\n  No picks from either model.")


print_comparison("OVER 0.5 POINTS", v1_05, v2_05)
print_comparison("OVER 1.5 POINTS", v1_15, v2_15)

print(f"\n{'=' * 70}")
print("COMPARISON COMPLETE")
print(f"{'=' * 70}")
