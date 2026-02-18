#!/usr/bin/env python3
"""
Serialize the production LightGBM model for the deploy pipeline.
Trains on ALL available data (through current season) and saves to model/lightgbm_model.pkl.
Also saves the feature list and Corsi quantile thresholds needed by strategy filters.
"""

import json
import warnings
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

MODEL_DIR = Path(__file__).parent
DEPLOY_DIR = MODEL_DIR.parent / "deploy"


# These are the features from PROVENSTRATEGIES.md — the actual model features
MODEL_FEATURES = [
    "sa_avg_10", "sa_avg_20", "svpct_avg_10", "svpct_avg_20", "is_home",
    "opp_team_sog_avg_10", "days_rest", "own_def_missing_toi",
    "opp_corsi_pct_avg_10", "opp_corsi_diff_avg_10",
    "own_corsi_pct_avg_10", "pull_rate_10", "starts_last_7d",
    "opp_team_pp_opps_avg_10", "line",
]

MODEL_PARAMS = {
    "objective": "regression",
    "metric": "mae",
    "num_leaves": 10,
    "max_depth": 4,
    "min_child_samples": 50,
    "learning_rate": 0.05,
    "n_estimators": 300,
    "reg_alpha": 0.5,
    "reg_lambda": 0.5,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.7,
    "bagging_freq": 5,
    "verbose": -1,
}


def main():
    print("Loading feature matrix...")
    matrix = pd.read_pickle(MODEL_DIR / "feature_matrix.pkl")
    matrix["event_date"] = pd.to_datetime(matrix["event_date"])
    print(f"  {len(matrix)} rows, {matrix['event_date'].min()} to {matrix['event_date'].max()}")

    # Check features exist
    available = [f for f in MODEL_FEATURES if f in matrix.columns]
    missing = [f for f in MODEL_FEATURES if f not in matrix.columns]
    if missing:
        print(f"  WARNING: Missing features: {missing}")
    print(f"  Using {len(available)} / {len(MODEL_FEATURES)} features")

    # Target: saves (we predict saves directly, not shots*svpct)
    target = "saves"
    train = matrix.dropna(subset=[target])
    train = train[train[available].notna().any(axis=1)]
    print(f"  Training rows (after dropping NaN): {len(train)}")

    X = train[available].fillna(-999)
    y = train[target]

    # Train
    params = {k: v for k, v in MODEL_PARAMS.items() if k != "n_estimators"}
    model = lgb.LGBMRegressor(**params, n_estimators=MODEL_PARAMS["n_estimators"])
    model.fit(X, y)

    # Compute Corsi quantile thresholds from training data (for strategy filters)
    corsi_col = "opp_corsi_pct_avg_10"
    corsi_diff_col = "opp_corsi_diff_avg_10"
    puck_col = "opp_puck_control_avg_10"
    own_corsi_col = "own_corsi_pct_avg_10"

    corsi_data = train.dropna(subset=[corsi_col])
    thresholds = {
        "corsi_q25": float(corsi_data[corsi_col].quantile(0.25)),
        "corsi_q30": float(corsi_data[corsi_col].quantile(0.30)),
        "corsi_q75": float(corsi_data[corsi_col].quantile(0.75)),
        "corsi_diff_q75": float(corsi_data[corsi_diff_col].quantile(0.75)) if corsi_diff_col in corsi_data.columns else None,
        "puck_control_q75": float(corsi_data[puck_col].quantile(0.75)) if puck_col in corsi_data.columns else None,
    }

    print(f"\n  Corsi thresholds:")
    for k, v in thresholds.items():
        print(f"    {k}: {v}")

    # Feature importances
    importances = dict(zip(available, model.feature_importances_))
    sorted_imp = sorted(importances.items(), key=lambda x: -x[1])
    print(f"\n  Feature importances:")
    for feat, imp in sorted_imp:
        print(f"    {feat}: {imp}")

    # Quick validation: predict on training data for sanity
    preds = model.predict(X)
    mae = np.mean(np.abs(y - preds))
    print(f"\n  Training MAE: {mae:.2f}")
    print(f"  Mean actual: {y.mean():.2f}, Mean predicted: {preds.mean():.2f}")

    # Save model
    model_path = MODEL_DIR / "lightgbm_model.pkl"
    joblib.dump(model, model_path)
    print(f"\n  Saved model to {model_path}")

    # Save metadata
    metadata = {
        "features": available,
        "params": MODEL_PARAMS,
        "thresholds": thresholds,
        "training_rows": len(train),
        "training_date_range": [str(train["event_date"].min()), str(train["event_date"].max())],
        "training_mae": float(mae),
        "feature_importances": {k: int(v) for k, v in sorted_imp},
    }
    meta_path = MODEL_DIR / "model_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"  Saved metadata to {meta_path}")


if __name__ == "__main__":
    main()
