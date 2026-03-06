#!/usr/bin/env python3
"""Data loading: model predictions and pipeline orchestration."""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pipeline_extraction import get_goalie_saves_odds, get_today_schedule
from pipeline_transformation import aggregate_odds, build_daily_features

ROOT = Path(__file__).parent.parent
MODEL_DIR = ROOT / "model"
DATA_DIR = ROOT / "data"

logger = logging.getLogger("data_pipeline")


def run_predictions(features_df: pd.DataFrame) -> pd.DataFrame:
    """Run the LightGBM model on today's features."""
    import joblib

    if features_df.empty:
        return features_df

    model = joblib.load(MODEL_DIR / "lightgbm_model.pkl")
    with open(MODEL_DIR / "model_metadata.json") as f:
        metadata = json.load(f)

    feature_cols = metadata["features"]
    available = [c for c in feature_cols if c in features_df.columns]

    X = features_df[available].fillna(-999)
    predictions = model.predict(X)

    features_df = features_df.copy()
    features_df["pred_saves"] = predictions
    features_df["gap"] = features_df["pred_saves"] - features_df["line"]
    features_df["abs_gap"] = features_df["gap"].abs()
    features_df["model_side"] = np.where(features_df["pred_saves"] < features_df["line"], "under", "over")

    logger.info(f"  Predictions complete: {len(features_df)} goalies")
    for _, row in features_df.iterrows():
        logger.info(f"    {row['player_name']}: pred={row['pred_saves']:.1f}, line={row['line']}, gap={row['gap']:+.1f} → {row['model_side'].upper()}")

    return features_df


def run_pipeline(date: str = None, skip_odds: bool = False) -> pd.DataFrame:
    """Run the full daily data pipeline."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"{'='*60}")
    logger.info(f"DAILY PIPELINE — {date}")
    logger.info(f"{'='*60}")

    # 1. Get today's schedule
    games = get_today_schedule(date)
    if not games:
        logger.info("No NHL games today. Done.")
        return pd.DataFrame()

    # 2. Get odds
    if skip_odds:
        logger.info("Skipping odds fetch (skip_odds=True)")
        odds_df = pd.DataFrame()
    else:
        raw_odds = get_goalie_saves_odds(date)
        odds_df = aggregate_odds(raw_odds)

    # 3. Build features
    features_df = build_daily_features(games, odds_df)
    if features_df.empty:
        logger.warning("No features built — no goalies matched to odds")
        return pd.DataFrame()

    # 4. Run model predictions
    result = run_predictions(features_df)

    # 5. Save daily slate
    slate_path = DATA_DIR / f"daily_slate_{date}.csv"
    result.to_csv(slate_path, index=False)
    logger.info(f"  Saved slate to {slate_path}")

    return result
