#!/usr/bin/env python3
"""
Notification system for NHL goalie saves picks.
Uses Discord via OpenClaw's message tool (primary) or webhook fallback.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
DEPLOY_DIR = Path(__file__).parent
PICKS_DIR = ROOT / "picks"

with open(DEPLOY_DIR / "config.yaml") as f:
    CONFIG = yaml.safe_load(f)

logger = logging.getLogger("notify")


def format_picks_message(picks_data: dict) -> str:
    """Format picks into a Discord-friendly message."""
    date = picks_data["date"]
    picks = picks_data.get("picks", [])
    paper = picks_data.get("paper_trading", True)
    total_action = picks_data.get("total_action", "$0")

    if not picks:
        return f"🏒 **NHL Picks for {date}**\n\nNo qualifying picks today."

    mode = "📝 PAPER TRADING" if paper else "💰 LIVE"

    # Group by confidence
    high = [p for p in picks if p["confidence"] == "HIGH" and not p.get("paper_only")]
    medium = [p for p in picks if p["confidence"] == "MEDIUM" and not p.get("paper_only")]
    paper_only = [p for p in picks if p.get("paper_only")]

    lines = [f"🏒 **NHL Picks for {date}** ({mode})"]
    lines.append("")

    if high:
        lines.append(f"✅ **HIGH CONFIDENCE** ({len(high)} picks):")
        for p in high:
            confirmed = "✅" if p["starter_confirmed"] else "⚠️ TBD"
            lines.append(
                f"• {p['goalie']} **{p['bet']} {p['line']}** @ {p['juice']} | "
                f"{p['strategy']} | Gap {p['model_gap']} | "
                f"Bet {p['bet_size_025kelly']} (0.25 Kelly) | "
                f"WP {p['estimated_win_prob']} | Starter: {confirmed}"
            )
        lines.append("")

    if medium:
        lines.append(f"⚠️ **MEDIUM CONFIDENCE** ({len(medium)} picks):")
        for p in medium:
            confirmed = "✅" if p["starter_confirmed"] else "⚠️ TBD"
            lines.append(
                f"• {p['goalie']} **{p['bet']} {p['line']}** @ {p['juice']} | "
                f"{p['strategy']} | Gap {p['model_gap']} | "
                f"Bet {p['bet_size_025kelly']} (0.25 Kelly) | "
                f"Starter: {confirmed}"
            )
        lines.append("")

    if paper_only:
        lines.append(f"📝 **PAPER ONLY** ({len(paper_only)} picks):")
        for p in paper_only:
            lines.append(
                f"• {p['goalie']} **{p['bet']} {p['line']}** @ {p['juice']} | "
                f"{p['strategy']} | {p['reasoning']}"
            )
        lines.append("")

    lines.append(f"📊 **Total action:** {total_action} across {len(picks)} games")
    lines.append(f"Full details: `picks/picks_{date}.json`")

    return "\n".join(lines)


def format_results_message(results: dict) -> str:
    """Format daily results summary."""
    date = results.get("date", "?")
    record = results.get("record", "0-0")
    pnl = results.get("pnl", 0)
    roi = results.get("roi", 0)

    lines = [f"📈 **Results for {date}:** {record} | {pnl:+.0f}u | {roi:+.1f}% ROI"]

    by_strategy = results.get("by_strategy", {})
    if by_strategy:
        lines.append("")
        lines.append("**By strategy (last 7 days):**")
        for strat, stats in by_strategy.items():
            lines.append(f"• {strat}: {stats['record']} ({stats['win_pct']:.1f}%) | {stats['pnl']:+.1f}u")

    overall = results.get("overall_7d", {})
    if overall:
        lines.append(f"\n**Overall (7d):** {overall['record']} ({overall['win_pct']:.1f}%) | {overall['pnl']:+.1f}u | {overall['roi']:+.1f}% ROI")

    return "\n".join(lines)


def send_discord_message(message: str):
    """
    Send message to Discord #nhl-betting channel.
    This is called from the scheduler which runs inside OpenClaw context,
    so it writes to a notification file that the scheduler picks up.
    """
    # Write notification to file for the scheduler/OpenClaw to send
    notif_path = DEPLOY_DIR / "pending_notification.json"
    with open(notif_path, "w") as f:
        json.dump({
            "channel": "nhl-betting",
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2)
    logger.info(f"  Notification queued to {notif_path}")
    logger.info(f"  Message preview:\n{message[:500]}")


def send_notification(picks_data: dict = None, results_data: dict = None):
    """Send picks or results notification."""
    if picks_data:
        message = format_picks_message(picks_data)
        logger.info("Sending picks notification")
        send_discord_message(message)

    if results_data:
        message = format_results_message(results_data)
        logger.info("Sending results notification")
        send_discord_message(message)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Test with most recent picks file
    picks_files = sorted(PICKS_DIR.glob("picks_*.json"), reverse=True)
    if picks_files:
        with open(picks_files[0]) as f:
            data = json.load(f)
        send_notification(picks_data=data)
    else:
        print("No picks files found to notify about")
