#!/usr/bin/env python3
"""
Daily data pipeline for NHL goalie saves betting system.
Pulls today's schedule, starting goalies, odds, and team stats.
Builds feature vectors for each goalie and runs model predictions.

This module re-exports from pipeline_extraction, pipeline_transformation,
and pipeline_loading for backwards compatibility.
"""

import logging
import sys

# Re-export all public API
from pipeline_extraction import (  # noqa: F401
    get_goalie_recent_stats,
    get_goalie_saves_odds,
    get_probable_goalies,
    get_team_recent_stats,
    get_today_schedule,
)
from pipeline_loading import run_pipeline, run_predictions  # noqa: F401
from pipeline_transformation import aggregate_odds, build_daily_features  # noqa: F401

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    date = sys.argv[1] if len(sys.argv) > 1 else None
    skip_odds = "--skip-odds" in sys.argv

    run_pipeline(date=date, skip_odds=skip_odds)
