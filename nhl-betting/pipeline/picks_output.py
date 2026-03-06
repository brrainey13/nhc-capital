#!/usr/bin/env python3
"""Output formatting and database persistence for daily picks."""

import json
import logging
import os
from datetime import datetime

import psycopg2

DB_CONN = os.environ.get("DATABASE_URL", "postgresql://nhc_agent@localhost:5432/nhl_betting")
log = logging.getLogger(__name__)


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal payout."""
    if odds < 0:
        return 100 / (-odds)
    return odds / 100


def format_picks(picks: list[dict]) -> str:
    """Format picks as a readable table."""
    signaled = [p for p in picks if p.get("has_signal")]
    if not signaled:
        return "No strategy signals found for today's games."

    signaled.sort(key=lambda p: (-p["confidence"], -p["gap"]))

    lines = []
    lines.append("=" * 80)
    lines.append(f"  NHL GOALIE SAVES PICKS — {signaled[0].get('date', 'Today')}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(
        f"  {'Player':<22} {'Team':<5} {'Line':>5} {'Pred':>5} {'Edge':>6} "
        f"{'Side':<6} {'Odds':>6} {'Strategies':<20}"
    )
    lines.append(f"  {'-' * 76}")

    for p in signaled:
        odds = p.get("under_odds") if p["side"] == "UNDER" else p.get("over_odds")
        odds_str = f"{odds:+d}" if odds else "N/A"
        strats = ", ".join(p["strategies"])
        lines.append(
            f"  {p['player_name']:<22} {p.get('player_team', ''):<5} "
            f"{p['line']:>5.1f} {p['pred_saves']:>5.1f} {p['edge']:>+5.1f} "
            f"{p['side']:<6} {odds_str:>6} {strats:<20}"
        )

    lines.append("")
    lines.append(f"  Total signals: {len(signaled)} / {len(picks)} games")
    lines.append("=" * 80)
    return "\n".join(lines)


def save_predictions(picks: list[dict], dry_run: bool = False):
    """Save predictions and model run to database."""
    if dry_run:
        log.info("Dry run — skipping DB writes")
        return

    signaled = [p for p in picks if p.get("has_signal")]
    if not signaled:
        return

    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    cur.execute(
        """INSERT INTO model_runs (model_name, model_version, trained_at,
           train_start_date, train_end_date, row_count, metrics_json)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING run_id""",
        (
            "saves_strategy_v2",
            "1.0",
            datetime.now().isoformat(),
            "2022-10-01",
            signaled[0].get("date", datetime.now().strftime("%Y-%m-%d")),
            len(signaled),
            json.dumps({
                "strategies": [p["strategies"] for p in signaled],
                "picks": [
                    {
                        "player": p["player_name"],
                        "side": p["side"],
                        "edge": round(p["edge"], 2),
                        "line": p["line"],
                    }
                    for p in signaled
                ],
            }),
        ),
    )
    run_id = cur.fetchone()[0]
    log.info(f"Saved model run #{run_id}")

    conn.commit()
    cur.close()
    conn.close()
