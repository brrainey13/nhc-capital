#!/usr/bin/env python3
"""Model inference and strategy filters for daily picks."""

import logging
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parent.parent / "model"
sys.path.insert(0, str(MODEL_DIR))

from train_models import (  # noqa: E402
    get_shot_features_by_iteration,
    get_shot_params,
    get_svpct_features_by_iteration,
    get_svpct_params,
)

log = logging.getLogger(__name__)


def get_goalie_features_for_prediction(
    matrix: pd.DataFrame, player_name: str, target_date: str
) -> dict | None:
    """Extract the most recent rolling features for a goalie."""
    target_dt = pd.to_datetime(target_date)
    goalie_data = matrix[
        (matrix["player_name"] == player_name)
        & (matrix["event_date"] < target_dt)
    ].sort_values("event_date")

    if len(goalie_data) == 0:
        return None

    latest = goalie_data.iloc[-1]
    return latest.to_dict()


def train_production_model(matrix: pd.DataFrame, target_date: str):
    """Train shot and save% models on all data before target_date."""
    target_dt = pd.to_datetime(target_date)
    train_df = matrix[matrix["event_date"] < target_dt].dropna(
        subset=["shots_against", "save_pct"]
    )

    if len(train_df) < 100:
        log.error(f"Not enough training data: {len(train_df)} rows")
        return None, None, None, None

    log.info(f"Training on {len(train_df)} games (up to {target_date})")

    max_date = train_df["event_date"].max()
    days_ago = (max_date - train_df["event_date"]).dt.days
    weights = np.exp(-days_ago * np.log(2) / 365)

    shot_features = [c for c in get_shot_features_by_iteration(5) if c in train_df.columns]
    svpct_features = [c for c in get_svpct_features_by_iteration(5) if c in train_df.columns]

    sp = get_shot_params(5)
    sp.pop("n_estimators", None)
    sp.pop("verbose", None)
    model_shots = lgb.LGBMRegressor(**sp, n_estimators=500, verbose=-1)
    model_shots.fit(train_df[shot_features].fillna(-999), train_df["shots_against"], sample_weight=weights)

    svp = get_svpct_params(5)
    svp.pop("n_estimators", None)
    svp.pop("verbose", None)
    model_svpct = lgb.LGBMRegressor(**svp, n_estimators=500, verbose=-1)
    model_svpct.fit(train_df[svpct_features].fillna(-999), train_df["save_pct"], sample_weight=weights)

    recent = train_df[train_df["event_date"] >= target_dt - pd.Timedelta(days=730)]
    corsi_q25 = recent["opp_corsi_pct_avg_10"].quantile(0.25) if "opp_corsi_pct_avg_10" in recent.columns else 48.0
    corsi_q75 = recent["opp_corsi_pct_avg_10"].quantile(0.75) if "opp_corsi_pct_avg_10" in recent.columns else 52.0

    log.info(f"Corsi Q25={corsi_q25:.1f}, Q75={corsi_q75:.1f}")

    return model_shots, model_svpct, shot_features, svpct_features


def predict_saves(model_shots, model_svpct, shot_features, svpct_features, features_dict: dict) -> float:
    """Predict saves for a single goalie game."""
    shot_vals = pd.DataFrame([{f: features_dict.get(f, -999) for f in shot_features}])
    svpct_vals = pd.DataFrame([{f: features_dict.get(f, -999) for f in svpct_features}])

    pred_shots = model_shots.predict(shot_vals)[0]
    pred_svpct = model_svpct.predict(svpct_vals)[0]
    return pred_shots * pred_svpct


def apply_strategy_filters(picks: list[dict], matrix: pd.DataFrame, target_date: str) -> list[dict]:
    """Apply proven strategy filters (MF3a, MF3b, MF2, PF1) to picks."""
    target_dt = pd.to_datetime(target_date)
    recent = matrix[matrix["event_date"] >= target_dt - pd.Timedelta(days=730)]

    corsi_q25 = recent["opp_corsi_pct_avg_10"].quantile(0.25) if "opp_corsi_pct_avg_10" in recent.columns else 48.0
    corsi_q75 = recent["opp_corsi_pct_avg_10"].quantile(0.75) if "opp_corsi_pct_avg_10" in recent.columns else 52.0

    for pick in picks:
        strategies = []
        feat = pick.get("features", {})
        edge = pick["pred_saves"] - pick["line"]
        gap = abs(edge)
        opp_corsi = feat.get("opp_corsi_pct_avg_10")
        days_rest = feat.get("days_rest")
        opp_corsi_diff = feat.get("opp_corsi_diff_avg_10")

        if edge < 0:
            if 1.0 <= gap < 1.5 and opp_corsi is not None and opp_corsi < corsi_q25:
                strategies.append("MF3a")
            if gap >= 2.5 and opp_corsi is not None and opp_corsi < corsi_q25:
                strategies.append("MF3b")
            if gap >= 2.0 and days_rest is not None and days_rest <= 1:
                strategies.append("MF2")

        if edge > 0:
            opp_puck = feat.get("opp_puck_control_avg_10")
            corsi_diff_q75 = (
                recent["opp_corsi_diff_avg_10"].quantile(0.75)
                if "opp_corsi_diff_avg_10" in recent.columns else 3.0
            )
            puck_q75 = (
                recent["opp_puck_control_avg_10"].quantile(0.75)
                if "opp_puck_control_avg_10" in recent.columns else -1.0
            )
            if (
                opp_corsi is not None and opp_corsi > corsi_q75
                and opp_corsi_diff is not None and opp_corsi_diff > corsi_diff_q75
                and opp_puck is not None and opp_puck > puck_q75
            ):
                strategies.append("PF1")

        pick["strategies"] = strategies
        pick["side"] = "UNDER" if edge < 0 else "OVER"
        pick["edge"] = edge
        pick["gap"] = gap
        pick["has_signal"] = len(strategies) > 0
        pick["confidence"] = len(strategies)

    return picks
