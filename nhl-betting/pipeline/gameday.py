#!/usr/bin/env python3
"""
Game Day Automation — Full pipeline from odds scrape to formatted picks.

Runs the complete workflow:
  1. Scrape today's saves odds (+ optional SOG/player odds)
  2. Run daily_picks pipeline (features → model → strategy filters)
  3. Format output for Discord posting
  4. Optionally write picks to a JSON file for external consumers

Usage:
    .venv/bin/python pipeline/gameday.py                    # Today
    .venv/bin/python pipeline/gameday.py --date 2025-12-15  # Historical
    .venv/bin/python pipeline/gameday.py --skip-scrape      # Skip odds fetch
    .venv/bin/python pipeline/gameday.py --json-out picks.json
"""
import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"


def run_scraper(script_name: str, target_date: str) -> bool:
    """Run a scraper script, return True on success."""
    script = SCRAPERS_DIR / script_name
    if not script.exists():
        log.warning(f"Scraper not found: {script}")
        return False

    log.info(f"Running {script_name}...")
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            log.error(f"{script_name} failed: {result.stderr[:500]}")
            return False
        log.info(f"{script_name} completed OK")
        return True
    except subprocess.TimeoutExpired:
        log.error(f"{script_name} timed out after 120s")
        return False


def run_daily_picks(target_date: str, dry_run: bool = False) -> list:
    """Run the daily picks pipeline and capture output."""
    # Import directly to get structured data back
    sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
    from daily_picks import run_pipeline
    return run_pipeline(target_date, dry_run=dry_run)


def format_discord_message(picks: list, target_date: str) -> str:
    """Format picks into a Discord-ready message."""
    if not picks:
        return (
            f"⚡ **NHL Picks — {target_date}**\n\n"
            "No qualifying picks today. Either no games or no edges found."
        )

    # Filter to picks with strategy signals
    signaled = [p for p in picks if p.get("has_signal")]
    if not signaled:
        return (
            f"⚡ **NHL Picks — {target_date}**\n\n"
            f"Model ran on {len(picks)} goalies but no qualifying strategy edges found."
        )

    # Separate by strategy
    strat_groups: dict[str, list] = {}
    for p in signaled:
        for strat in p.get("strategies", ["Unknown"]):
            strat_groups.setdefault(strat, []).append(p)

    lines = [f"⚡ **NHL Picks — {target_date}**\n"]

    for strat, group in sorted(strat_groups.items()):
        lines.append(f"**{strat}**")
        for p in group:
            side = p.get("side", "?").upper()
            line = p.get("line", "?")
            odds = p.get("best_odds") or p.get("over_odds" if side == "OVER" else "under_odds", "?")
            pred = p.get("pred_saves", 0)
            gap = abs(pred - (line or 0))
            player = p.get("player_name", "Unknown")
            team = p.get("player_team", "")

            odds_str = f"{odds:+d}" if isinstance(odds, (int, float)) and odds != 0 else str(odds)
            lines.append(
                f"- **{player}** ({team}) — {side} {line} saves "
                f"[{odds_str}] | Model: {pred:.1f} (gap {gap:.1f})"
            )
        lines.append("")

    total = len(signaled)
    lines.append(f"**{total} pick{'s' if total != 1 else ''}** | Strategies: MF3, MF2, PF1")
    lines.append("NHL resumes Feb 25 🏒" if target_date < "2026-02-25" else "")

    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser(description="NHL Game Day Automation")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--skip-scrape", action="store_true", help="Skip odds scraping")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--json-out", type=str, help="Write picks to JSON file")
    parser.add_argument("--discord-only", action="store_true", help="Only output Discord message")
    args = parser.parse_args()

    target_date = args.date
    log.info(f"=== Game Day Pipeline: {target_date} ===")

    # Step 1: Scrape odds
    if not args.skip_scrape:
        run_scraper("scrape_saves_odds.py", target_date)
        run_scraper("scrape_sog_odds.py", target_date)

    # Step 2: Run picks pipeline
    picks = run_daily_picks(target_date, dry_run=args.dry_run)

    # Step 3: Format for Discord
    discord_msg = format_discord_message(picks, target_date)
    print("\n" + "=" * 60)
    print("DISCORD OUTPUT:")
    print("=" * 60)
    print(discord_msg)

    # Step 4: Optional JSON output
    if args.json_out:
        # Serialize picks (drop non-serializable features dict)
        clean = []
        for p in picks:
            cp = {k: v for k, v in p.items() if k != "features"}
            clean.append(cp)
        Path(args.json_out).write_text(json.dumps(clean, indent=2, default=str))
        log.info(f"Wrote {len(clean)} picks to {args.json_out}")

    return discord_msg, picks


if __name__ == "__main__":
    main()
