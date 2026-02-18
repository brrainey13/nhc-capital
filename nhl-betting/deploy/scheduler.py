#!/usr/bin/env python3
"""
Scheduler for the NHL goalie saves betting pipeline.
Runs daily at configured times to pull data, generate picks, and track results.

Can run as:
1. Long-running daemon (python scheduler.py --daemon)
2. One-shot for specific phase (python scheduler.py --phase morning|starters|picks|results)
3. Cron-triggered (set up cron jobs for each phase)
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
DEPLOY_DIR = Path(__file__).parent
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

with open(DEPLOY_DIR / "config.yaml") as f:
    CONFIG = yaml.safe_load(f)

# Set up logging
today = datetime.now().strftime("%Y-%m-%d")
log_file = LOGS_DIR / f"scheduler_{today}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("scheduler")


def run_morning():
    """8:00 AM ET: Pull today's schedule + initial lines."""
    logger.info("=" * 60)
    logger.info("PHASE: MORNING PULL (8:00 AM)")
    logger.info("=" * 60)

    from data_pipeline import run_pipeline

    today = datetime.now().strftime("%Y-%m-%d")

    try:
        result = run_pipeline(date=today)
        if result is None or (hasattr(result, "empty") and result.empty):
            logger.info("No NHL games today")
            return False
        logger.info(f"Morning pull complete: {len(result)} goalies")
        return True
    except Exception as e:
        logger.error(f"Morning pull failed: {e}", exc_info=True)
        _log_error("morning_pull", str(e))
        return False


def run_starter_check():
    """11:00 AM ET: Re-check starter confirmations."""
    logger.info("=" * 60)
    logger.info("PHASE: STARTER CHECK (11:00 AM)")
    logger.info("=" * 60)

    from data_pipeline import run_pipeline

    today = datetime.now().strftime("%Y-%m-%d")

    try:
        # Re-run pipeline to update starter confirmations
        result = run_pipeline(date=today)
        if result is None or (hasattr(result, "empty") and result.empty):
            logger.info("No games or no updates")
            return False

        confirmed = result["starter_confirmed"].sum() if "starter_confirmed" in result.columns else 0
        total = len(result)
        logger.info(f"Starter check: {confirmed}/{total} confirmed")
        return True
    except Exception as e:
        logger.error(f"Starter check failed: {e}", exc_info=True)
        _log_error("starter_check", str(e))
        return False


def run_picks():
    """2:00 PM ET: Final starter check + generate picks + notify."""
    logger.info("=" * 60)
    logger.info("PHASE: FINAL PICKS (2:00 PM)")
    logger.info("=" * 60)

    from data_pipeline import run_pipeline
    from strategy_engine import run_strategies
    from notify import send_notification

    today = datetime.now().strftime("%Y-%m-%d")

    try:
        # Final data pull
        result = run_pipeline(date=today)
        if result is None or (hasattr(result, "empty") and result.empty):
            logger.info("No games today")
            return False

        # Run strategies
        picks = run_strategies(date=today)

        # Notify
        if picks.get("picks"):
            send_notification(picks_data=picks)
            logger.info(f"Picks generated and notification sent: {picks['n_picks']} picks")
        else:
            logger.info("No qualifying picks today")

        return True
    except Exception as e:
        logger.error(f"Picks generation failed: {e}", exc_info=True)
        _log_error("picks", str(e))
        return False


def run_results():
    """9:00 AM next day: Track yesterday's results."""
    logger.info("=" * 60)
    logger.info("PHASE: RESULTS TRACKING (9:00 AM)")
    logger.info("=" * 60)

    from track_results import track_date, get_rolling_stats
    from notify import send_notification

    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        summary = track_date(yesterday)
        if not summary.get("tracked"):
            logger.info(f"No results to track for {yesterday}")
            return False

        # Get rolling stats
        rolling = get_rolling_stats(7)
        summary.update(rolling)

        # Notify
        send_notification(results_data=summary)
        logger.info(f"Results tracked: {summary.get('record', 'N/A')}")
        return True
    except Exception as e:
        logger.error(f"Results tracking failed: {e}", exc_info=True)
        _log_error("results", str(e))
        return False


def run_daemon():
    """Run as a long-running daemon using schedule library."""
    try:
        import schedule
        import time
    except ImportError:
        logger.error("'schedule' package not installed. pip install schedule")
        sys.exit(1)

    times = CONFIG["schedule"]

    schedule.every().day.at(times["initial_pull"]).do(run_morning)
    schedule.every().day.at(times["starter_check"]).do(run_starter_check)
    schedule.every().day.at(times["final_picks"]).do(run_picks)
    schedule.every().day.at(times["results_summary"]).do(run_results)

    logger.info("Scheduler daemon started")
    logger.info(f"  Morning pull: {times['initial_pull']} ET")
    logger.info(f"  Starter check: {times['starter_check']} ET")
    logger.info(f"  Final picks: {times['final_picks']} ET")
    logger.info(f"  Results summary: {times['results_summary']} ET")

    while True:
        schedule.run_pending()
        time.sleep(60)


def _log_error(phase: str, error: str):
    """Log error to daily error file."""
    error_file = LOGS_DIR / f"errors_{datetime.now().strftime('%Y-%m-%d')}.log"
    with open(error_file, "a") as f:
        f.write(f"{datetime.now().isoformat()} | {phase} | {error}\n")


def main():
    parser = argparse.ArgumentParser(description="NHL Betting Pipeline Scheduler")
    parser.add_argument("--daemon", action="store_true", help="Run as long-running daemon")
    parser.add_argument("--phase", choices=["morning", "starters", "picks", "results"],
                        help="Run a specific phase once")
    parser.add_argument("--date", help="Override date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    elif args.phase:
        phases = {
            "morning": run_morning,
            "starters": run_starter_check,
            "picks": run_picks,
            "results": run_results,
        }
        phases[args.phase]()
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python scheduler.py --daemon          # Run as daemon")
        print("  python scheduler.py --phase morning   # Run morning pull once")
        print("  python scheduler.py --phase picks     # Generate today's picks")


if __name__ == "__main__":
    main()
