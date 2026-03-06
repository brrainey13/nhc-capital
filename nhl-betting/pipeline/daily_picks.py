"""
NHC Daily Picks Pipeline — Orchestrator.

1. Refresh rosters (pre-flight)
2. Pull live odds (DK, FD, BetMGM, Hard Rock)
3. Pull player season stats from NHL API
4. Run each model
5. Output consolidated picks with Kelly sizing
6. Persist picks to nhl_picks table (skip with --no-db)

Usage:
    cd ~/nhc-capital/nhl-betting
    .venv/bin/python -m pipeline.daily_picks [--date YYYY-MM-DD] [--no-db]
"""
import sys
import time
import uuid
from datetime import date
from decimal import Decimal

import requests
from model.bankroll import append_bankroll_event, get_unit_size
from model.db_config import get_dsn
from models.game_totals import run_game_total_over
from models.goalie_saves import run_goalie_saves
from models.player_assists import run_assists_under
from models.player_goals import run_anytime_goalscorer
from models.player_points import (
    get_games_with_multiple_15_edges,
    run_over_05,
    run_over_15,
)
from pipeline.odds_pull import (
    check_quota,
    get_best_odds,
    get_todays_events,
    pull_all_odds,
)
from pipeline.roster_refresh import refresh_rosters

WRITE_DSN = get_dsn()

# market tag by strategy source list name
_MARKET_MAP = {
    "goalie_picks": "goalie_saves",
    "over_15": "over_15_pts",
    "over_05": "over_05_pts",
    "assists_under": "assists_under",
    "goalscorer_deduped": "atg",
    "total_picks": "game_total",
}

MAX_RISK = None  # Set to cap total deployment (e.g., 500)


def sort_picks_by_edge(picks):
    """Return picks sorted by edge descending."""
    return sorted(picks, key=lambda pick: pick.get("edge", 0), reverse=True)


def apply_max_risk_cap(picks, max_risk):
    """Scale pick sizing down to the configured max risk cap."""
    total_risk = sum(p.get("dollars", 0) for p in picks)
    if not max_risk or total_risk <= max_risk:
        return picks, total_risk, None

    scale = max_risk / total_risk
    for pick in picks:
        pick["dollars_raw"] = pick.get("dollars", 0)
        pick["units_raw"] = pick.get("units", 0)
        pick["dollars"] = round(pick["dollars_raw"] * scale, 2)
        pick["units"] = round(pick["units_raw"] * scale, 1)
    return picks, sum(p.get("dollars", 0) for p in picks), scale


def get_current_bankroll() -> Decimal:
    """Read the latest bankroll balance from Postgres."""
    import psycopg2

    conn = psycopg2.connect(WRITE_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM bankroll ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return Decimal(str(row[0])) if row and row[0] is not None else Decimal("0.00")
    finally:
        conn.close()


def fetch_player_season_stats(player_names):
    """Fetch season stats from NHL API for a set of player names.

    Returns dict keyed by player_id with stats.
    """
    player_stats = {}
    player_ids_checked = set()

    for name in player_names:
        last_name = name.split()[-1]
        try:
            search_r = requests.get(
                f"https://search.d3.nhle.com/api/v1/search/player"
                f"?culture=en-us&limit=5&q={last_name}",
                timeout=10,
            )
            results = search_r.json()
        except Exception:
            continue

        for p in results:
            if p["name"] == name and p.get("active"):
                pid = p["playerId"]
                if pid in player_ids_checked:
                    break
                player_ids_checked.add(pid)

                try:
                    stats_r = requests.get(
                        f"https://api-web.nhle.com/v1/player/{pid}"
                        f"/game-log/20252026/2",
                        timeout=10,
                    )
                    games = stats_r.json().get("gameLog", [])
                except Exception:
                    break

                if not games:
                    break

                gp = len(games)
                total_pts = sum(
                    g.get("goals", 0) + g.get("assists", 0) for g in games
                )
                total_goals = sum(g.get("goals", 0) for g in games)
                total_assists = sum(g.get("assists", 0) for g in games)
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
                games_with_goal = sum(
                    1 for g in games if g.get("goals", 0) >= 1
                )
                total_sog = sum(g.get("shots", 0) for g in games)

                player_stats[pid] = {
                    "player_id": pid,
                    "name": name,
                    "gp": gp,
                    "pts": total_pts,
                    "ppg": round(total_pts / gp, 3),
                    "goals": total_goals,
                    "gpg": round(total_goals / gp, 3),
                    "goal_rate": round(games_with_goal / gp, 3),
                    "goal_games": games_with_goal,
                    "assists": total_assists,
                    "apg": round(total_assists / gp, 3),
                    "mp_rate": round(games_2plus / gp, 3),
                    "point_rate": round(games_1plus / gp, 3),
                    "mp_games": games_2plus,
                    "point_games": games_1plus,
                    "avg_sog": round(total_sog / gp, 1),
                    "total_sog": total_sog,
                }
                break
        time.sleep(0.1)

    return player_stats


def print_pick(p, strategy_label):
    """Print a formatted pick line."""
    odds = p["odds"]
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    book = p.get("book_title", p.get("book", ""))
    units = p.get("units", 0)
    dollars = p.get("dollars", 0)
    team = p.get("player_team", "")
    team_str = f" ({team})" if team else ""
    player = p.get("player", p.get("game", ""))
    print(
        f"  {p['confidence']} | {player}{team_str} "
        f"| {odds_str} @ {book} | Edge: {p['edge']*100:+.1f}% "
        f"| {units}u (${dollars:.0f})"
    )


def persist_picks(picks_by_market, pick_date_str, pipeline_run_id):
    """Insert all picks into nhl_picks via nhc_etl.

    Args:
        picks_by_market: dict of market_name -> list of pick dicts
        pick_date_str: YYYY-MM-DD string for pick_date
        pipeline_run_id: UUID string identifying this pipeline run

    Returns:
        Number of rows inserted.
    """
    import psycopg2

    INSERT_PICK = """
        INSERT INTO nhl_picks (
            pick_date, pipeline_run_id, player, player_team, market,
            bet, book, odds, line, edge, model_prediction,
            units, dollars, confidence, sub_strategy
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        RETURNING pick_id
    """

    conn = psycopg2.connect(WRITE_DSN)
    inserted = 0
    try:
        with conn:
            with conn.cursor() as cur:
                for market, picks in picks_by_market.items():
                    for p in picks:
                        cur.execute(INSERT_PICK, (
                            pick_date_str,
                            pipeline_run_id,
                            p.get("player") or p.get("game"),
                            p.get("player_team"),
                            market,
                            p.get("bet"),
                            p.get("book_title") or p.get("book"),
                            p.get("odds"),
                            p.get("line"),
                            p.get("edge"),
                            p.get("pred") or p.get("model_prediction"),
                            p.get("units"),
                            p.get("dollars"),
                            p.get("confidence"),
                            p.get("sub_strategy"),
                        ))
                        pick_id = cur.fetchone()[0]
                        sportsbook = p.get("book_title") or p.get("book")
                        dollars = Decimal(str(p.get("dollars") or 0))
                        append_bankroll_event(
                            cur,
                            event_date=pick_date_str,
                            event_type="bet_placed",
                            amount=-dollars,
                            pick_id=pick_id,
                            sportsbook=sportsbook,
                            notes=f"{market}: {p.get('bet')}",
                        )
                        inserted += 1
    finally:
        conn.close()
    return inserted


def run_pipeline(date_str=None, max_risk=MAX_RISK, no_db=False):
    """Run the daily picks pipeline and return the picks."""
    pipeline_run_id = str(uuid.uuid4())
    pick_date_str = date_str if date_str else date.today().isoformat()
    bankroll = get_current_bankroll()
    unit = get_unit_size(bankroll)

    # === PRE-FLIGHT ===
    print("=" * 70)
    print("PRE-FLIGHT: ROSTER REFRESH")
    print("=" * 70)
    print(f"Current bankroll: ${bankroll:.2f} | Unit (1%): ${unit:.2f}")
    roster_result = refresh_rosters(verbose=False)
    print(
        f"Rosters: {roster_result['updates']} updates, "
        f"{len(roster_result['errors'])} errors"
    )

    # === PULL ODDS ===
    print("\n" + "=" * 70)
    print("PULLING LIVE ODDS")
    print("=" * 70)
    events = get_todays_events(date_str)
    print(f"Games: {len(events)}")

    if not events:
        print("No games found. Exiting.")
        return

    # Build set of teams playing tonight for validation
    tonight_teams = set()
    for ev in events:
        tonight_teams.add(ev.get("away_team", ""))
        tonight_teams.add(ev.get("home_team", ""))
    print(f"Teams playing: {len(tonight_teams)}")
    for ev in events:
        print(f"  {ev['away_team']} @ {ev['home_team']}")

    # Single optimized pull: all player props + totals + saves in one call per game
    all_props, all_game_totals, pull_id = pull_all_odds(
        events,
        markets=["player_points", "player_assists", "player_goals",
                 "player_shots_on_goal", "player_total_saves", "totals"],
    )
    # Filter to the markets we need for scoring
    props = [p for p in all_props if p["market"] in
             ("player_points", "player_assists", "player_goals",
              "player_shots_on_goal")]
    print(f"Player prop lines: {len(props)}")

    best_odds = get_best_odds(props)

    # === PLAYER STATS ===
    print("\n" + "=" * 70)
    print("FETCHING PLAYER SEASON STATS")
    print("=" * 70)
    unique_players = set(p["player"] for p in props if p["player"])
    print(f"Looking up {len(unique_players)} players...")
    player_stats = fetch_player_season_stats(unique_players)
    print(f"Found stats for {len(player_stats)} players")

    # === RUN MODELS ===
    print("\n" + "=" * 70)
    print("RUNNING MODELS")
    print("=" * 70)

    # Strategy C: OVER 1.5 pts
    over_15 = run_over_15(best_odds, player_stats, bankroll=bankroll)
    print(f"\nStrategy C — OVER 1.5 pts: {len(over_15)} picks")
    for p in over_15:
        print_pick(p, "C")

    # Strategy B2: OVER 0.5 pts
    over_05 = run_over_05(best_odds, player_stats, bankroll=bankroll)
    print(f"\nStrategy B2 — OVER 0.5 pts: {len(over_05)} picks")
    for p in over_05[:15]:
        print_pick(p, "B2")

    # Strategy B1: Assists UNDER
    assists_under = run_assists_under(best_odds, player_stats, bankroll=bankroll)
    print(f"\nStrategy B1 — Assists UNDER 0.5: {len(assists_under)} picks")
    for p in assists_under[:5]:
        print_pick(p, "B1")

    # Strategy E: Anytime Goalscorer
    goalscorer = run_anytime_goalscorer(best_odds, player_stats, bankroll=bankroll)
    print(f"\nStrategy E — Anytime Goalscorer: {len(goalscorer)} picks")
    for p in goalscorer[:10]:
        print_pick(p, "E")

    # Strategy A: Goalie Saves (MF3, MF2, PF1)
    goalie_picks = run_goalie_saves(best_odds, events, bankroll=bankroll)
    print(f"\nStrategy A — Goalie Saves: {len(goalie_picks)} picks")
    for p in goalie_picks:
        odds = p["odds"]
        odds_str = f"+{odds}" if odds > 0 else str(odds)
        print(
            f"  {p['confidence']} | {p['player']} ({p['player_team']}) "
            f"| {p['bet']} | {odds_str} @ {p['book_title']} "
            f"| Edge: {p['edge']*100:+.1f}% | {p['units']}u (${p['dollars']:.0f}) "
            f"| [{p['sub_strategy']}] pred={p['pred']} line={p['line']}"
        )

    # Strategy D: Game Total OVER
    flagged_games = get_games_with_multiple_15_edges(
        over_15, best_odds, player_stats
    )
    if flagged_games:
        print(f"\nFlagged {len(flagged_games)} games for total OVER check")
        game_totals = all_game_totals  # already fetched in the single pull
        total_picks = run_game_total_over(
            flagged_games,
            game_totals,
            bankroll=bankroll,
        )
        print(f"Strategy D — Game Total OVER: {len(total_picks)} picks")
        for p in total_picks:
            odds_str = (
                f"+{p['odds']}" if p["odds"] > 0 else str(p["odds"])
            )
            print(
                f"  {p['confidence']} | {p['game']} | "
                f"O {p['total']} {odds_str} @ {p['book_title']} | "
                f"Edge: {p['edge']*100:+.1f}% | "
                f"{p['units']}u (${p['dollars']:.0f})"
            )
    else:
        total_picks = []

    # === DEDUP: No double-dipping same player across O0.5 and ATG ===
    # If a player qualifies for both O0.5 pts and ATG, keep O0.5 (higher
    # hit rate, lower variance) and drop ATG. Minimizes correlated exposure.
    pts_players = set()
    for p in list(over_15) + list(over_05[:15]):
        pts_players.add(p.get("player", ""))
    goalscorer_deduped = [
        p for p in goalscorer[:10]
        if p.get("player", "") not in pts_players
    ]
    dropped = len(goalscorer[:10]) - len(goalscorer_deduped)
    if dropped:
        dropped_names = [
            p["player"] for p in goalscorer[:10]
            if p.get("player", "") in pts_players
        ]
        print(f"\n⚠️  DEDUP: Dropped {dropped} ATG picks (already in pts): "
              f"{', '.join(dropped_names)}")

    # === COLLECT ALL PICKS ===
    all_picks = []
    all_picks.extend(goalie_picks)
    all_picks.extend(over_15)
    all_picks.extend(over_05[:15])
    all_picks.extend(assists_under[:5])
    all_picks.extend(goalscorer_deduped)
    all_picks.extend(total_picks)
    all_picks = sort_picks_by_edge(all_picks)

    raw_total_risk = sum(p.get("dollars", 0) for p in all_picks)

    # === SCALE TO MAX RISK CAP ===
    all_picks, total_risk, scale = apply_max_risk_cap(all_picks, max_risk)
    if scale is not None:
        print(f"\n⚠️  SCALING: Raw risk ${raw_total_risk:.0f} → capped at ${max_risk:.0f} "
              f"(scale factor: {scale:.3f})")

        # Reprint scaled picks
        print("\n" + "=" * 70)
        print(f"SCALED PICKS (max risk: ${max_risk:.0f})")
        print("=" * 70)
        for p in all_picks:
            odds = p["odds"]
            odds_str = f"+{odds}" if odds > 0 else str(odds)
            book = p.get("book_title", p.get("book", ""))
            label = p.get("player", p.get("game", ""))
            team = p.get("player_team", "")
            team_str = f" ({team})" if team else ""
            strat = p.get("strategy", p.get("bet", ""))
            print(
                f"  {p.get('confidence', '')} | {label}{team_str} | {strat} "
                f"| {odds_str} @ {book} | Edge: {p['edge']*100:+.1f}% "
                f"| {p['units']}u (${p['dollars']:.0f})"
            )

    # === PERSIST TO DB ===
    if not no_db:
        picks_by_market = {
            "goalie_saves": goalie_picks,
            "over_15_pts": list(over_15),
            "over_05_pts": list(over_05[:15]),
            "assists_under": list(assists_under[:5]),
            "atg": list(goalscorer_deduped),
            "game_total": list(total_picks),
        }
        try:
            inserted = persist_picks(picks_by_market, pick_date_str, pipeline_run_id)
            print(f"\nDB: Inserted {inserted} picks (run_id={pipeline_run_id})")
        except Exception as exc:
            print(f"\nDB ERROR (picks NOT saved): {exc}")
    else:
        print("\nDB: skipped (--no-db)")

    # === SUMMARY ===
    print("\n" + "=" * 70)
    print(f"TOTAL PICKS: {len(all_picks)}")
    print(f"TOTAL RISK: ${total_risk:.0f}")
    if max_risk:
        print(f"MAX RISK CAP: ${max_risk:.0f}")
    print(f"API QUOTA: {check_quota()} remaining")
    if not no_db:
        print(f"PIPELINE RUN ID: {pipeline_run_id}")
    print("=" * 70)
    return all_picks


def main():
    date_str = None
    max_risk = MAX_RISK
    no_db = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            date_str = args[i + 1]
            i += 2
        elif args[i] == "--max-risk" and i + 1 < len(args):
            max_risk = float(args[i + 1])
            i += 2
        elif args[i] == "--no-db":
            no_db = True
            i += 1
        else:
            i += 1

    run_pipeline(date_str=date_str, max_risk=max_risk, no_db=no_db)


if __name__ == "__main__":
    main()
