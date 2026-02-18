#!/usr/bin/env python3
"""
Results tracking for NHL goalie saves bets.
After games complete, pull actual stats and match to picks.
"""

import csv
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent
DEPLOY_DIR = Path(__file__).parent
PICKS_DIR = ROOT / "picks"
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"

logger = logging.getLogger("track_results")

PAPER_TRADES_FILE = LOGS_DIR / "paper_trades.csv"
PAPER_TRADES_HEADERS = [
    "Date", "Game", "Goalie", "Strategy", "Line", "Juice", "Bet",
    "BetSize", "Result", "ActualSaves", "PnL", "ConfirmedStarter", "LineMovement",
]


def ensure_csv():
    """Create paper_trades.csv with headers if it doesn't exist."""
    if not PAPER_TRADES_FILE.exists():
        with open(PAPER_TRADES_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(PAPER_TRADES_HEADERS)


def get_actual_saves(date: str) -> dict:
    """
    Pull actual game results from our database.
    Returns dict of {player_name: {"saves": N, "shots_against": N, "game_id": N}}
    """
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    cur.execute("""
        SELECT p.first_name || ' ' || p.last_name AS player_name,
               gs.saves, gs.shots_against, gs.goals_against,
               g.game_id
        FROM goalie_stats gs
        JOIN games g ON gs.game_id = g.game_id
        JOIN players p ON gs.player_id = p.player_id
        WHERE g.game_date = %s
          AND gs.shots_against > 0
    """, (date,))

    rows = cur.fetchall()
    conn.close()

    result = {}
    for name, saves, sa, ga, gid in rows:
        result[name.lower()] = {
            "saves": int(saves),
            "shots_against": int(sa),
            "goals_against": int(ga),
            "game_id": int(gid),
        }

    return result


def track_date(date: str) -> dict:
    """Track results for a specific date's picks."""
    picks_file = PICKS_DIR / f"picks_{date}.json"
    if not picks_file.exists():
        logger.info(f"No picks file for {date}")
        return {"date": date, "tracked": False}

    with open(picks_file) as f:
        picks_data = json.load(f)

    picks = picks_data.get("picks", [])
    if not picks:
        return {"date": date, "tracked": True, "n_picks": 0}

    # Get actual results
    actuals = get_actual_saves(date)
    if not actuals:
        logger.warning(f"No actual game data for {date} yet — games may not have completed")
        return {"date": date, "tracked": False, "reason": "no_actuals"}

    ensure_csv()

    results = []
    for pick in picks:
        goalie_name = pick["goalie"]
        actual = actuals.get(goalie_name.lower())

        if not actual:
            logger.warning(f"  No actual data for {goalie_name} on {date}")
            continue

        actual_saves = actual["saves"]
        line = pick["line"]
        bet_side = pick["bet"].upper()
        juice = pick["juice"]
        bet_size = float(pick["bet_size_025kelly"].replace("$", ""))

        # Determine result
        if bet_side == "UNDER":
            won = actual_saves < line
            push = actual_saves == line
        else:
            won = actual_saves > line
            push = actual_saves == line

        if push:
            result_str = "PUSH"
            pnl = 0
        elif won:
            result_str = "WIN"
            pnl = bet_size * (100 / abs(juice)) if juice < 0 else bet_size * (juice / 100)
        else:
            result_str = "LOSS"
            pnl = -bet_size

        result = {
            "date": date,
            "game": pick["game"],
            "goalie": goalie_name,
            "strategy": pick["strategy"],
            "line": line,
            "juice": juice,
            "bet": bet_side,
            "bet_size": f"${bet_size:.0f}",
            "result": result_str,
            "actual_saves": actual_saves,
            "pnl": round(pnl, 2),
            "confirmed_starter": pick.get("starter_confirmed", "N/A"),
            "line_movement": "+0.0",  # TODO: track line movement
        }

        results.append(result)

        # Append to CSV
        with open(PAPER_TRADES_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                result["date"], result["game"], result["goalie"],
                result["strategy"], result["line"], result["juice"],
                result["bet"], result["bet_size"], result["result"],
                result["actual_saves"], result["pnl"],
                result["confirmed_starter"], result["line_movement"],
            ])

    # Summary
    wins = sum(1 for r in results if r["result"] == "WIN")
    losses = sum(1 for r in results if r["result"] == "LOSS")
    pushes = sum(1 for r in results if r["result"] == "PUSH")
    total_pnl = sum(r["pnl"] for r in results)
    total_risked = sum(float(r["bet_size"].replace("$", "")) for r in results)
    roi = (total_pnl / total_risked * 100) if total_risked > 0 else 0

    summary = {
        "date": date,
        "tracked": True,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "pnl": round(total_pnl, 2),
        "roi": round(roi, 1),
        "results": results,
    }

    logger.info(f"  {date}: {summary['record']} | PnL: ${total_pnl:+.2f} | ROI: {roi:+.1f}%")
    return summary


def get_rolling_stats(days: int = 7) -> dict:
    """Calculate rolling stats from paper_trades.csv."""
    if not PAPER_TRADES_FILE.exists():
        return {}

    df = pd.read_csv(PAPER_TRADES_FILE)
    if df.empty:
        return {}

    df["Date"] = pd.to_datetime(df["Date"])
    cutoff = datetime.now() - timedelta(days=days)
    recent = df[df["Date"] >= cutoff]

    if recent.empty:
        return {}

    # By strategy
    by_strategy = {}
    for strat, grp in recent.groupby("Strategy"):
        wins = (grp["Result"] == "WIN").sum()
        losses = (grp["Result"] == "LOSS").sum()
        total = wins + losses
        by_strategy[strat] = {
            "record": f"{wins}-{losses}",
            "win_pct": (wins / total * 100) if total > 0 else 0,
            "pnl": float(grp["PnL"].sum()),
        }

    # Overall
    wins = (recent["Result"] == "WIN").sum()
    losses = (recent["Result"] == "LOSS").sum()
    total = wins + losses
    total_pnl = float(recent["PnL"].sum())
    total_risked = recent["BetSize"].apply(lambda x: float(str(x).replace("$", ""))).sum()

    overall = {
        "record": f"{wins}-{losses}",
        "win_pct": (wins / total * 100) if total > 0 else 0,
        "pnl": total_pnl,
        "roi": (total_pnl / total_risked * 100) if total_risked > 0 else 0,
    }

    return {
        "by_strategy": by_strategy,
        "overall_7d": overall,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Track yesterday's results by default
    if len(sys.argv) > 1:
        date = sys.argv[1]
    else:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    summary = track_date(date)
    print(json.dumps(summary, indent=2))

    # Show rolling stats
    rolling = get_rolling_stats(7)
    if rolling:
        print("\n7-day rolling stats:")
        print(json.dumps(rolling, indent=2))
