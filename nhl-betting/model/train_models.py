#!/usr/bin/env python3
"""
Phases 2-5: Model Training, Pull Model, and Stress Testing.

Runs 5 iterations each for:
- Model A: Shot volume prediction
- Model B: Save percentage prediction
- Model C: Pull prediction (binary)

Then combines A*B for saves prediction, finds +EV bets, and stress tests.

This module re-exports all public API from sub-modules for backwards compatibility.
"""

import json
from datetime import datetime

# Re-export all public API for backwards compatibility
from train_core import train_and_evaluate  # noqa: F401
from train_data_prep import (  # noqa: F401
    get_pull_features_by_iteration,
    get_pull_params,
    get_shot_features_by_iteration,
    get_shot_params,
    get_svpct_features_by_iteration,
    get_svpct_params,
)
from train_evaluation import combined_prediction_and_ev, stress_tests  # noqa: F401
from train_utils import MODEL_DIR, load_matrix, walk_forward_split  # noqa: F401


def main():
    print("Loading feature matrix...")
    matrix = load_matrix()
    print(f"Matrix: {len(matrix)} rows, {len(matrix.columns)} cols")
    print(f"Date range: {matrix['event_date'].min()} to {matrix['event_date'].max()}")

    shot_results, shot_imp = train_and_evaluate(
        matrix, "MODEL A: Shot Volume", "shots_against",
        get_shot_features_by_iteration, get_shot_params
    )

    svpct_results, svpct_imp = train_and_evaluate(
        matrix, "MODEL B: Save Percentage", "save_pct",
        get_svpct_features_by_iteration, get_svpct_params
    )

    pull_results, pull_imp = train_and_evaluate(
        matrix, "MODEL C: Pull Prediction", "was_pulled",
        get_pull_features_by_iteration, get_pull_params, is_classifier=True
    )

    combined_prediction_and_ev(matrix)
    stress_tests(matrix)

    summary = {
        'timestamp': datetime.now().isoformat(),
        'matrix_size': len(matrix),
        'shot_iterations': len(shot_results) if shot_results else 0,
        'svpct_iterations': len(svpct_results) if svpct_results else 0,
        'pull_iterations': len(pull_results) if pull_results else 0,
    }

    if shot_imp:
        summary['top_shot_features'] = sorted(shot_imp.items(), key=lambda x: -x[1])[:10]
    if svpct_imp:
        summary['top_svpct_features'] = sorted(svpct_imp.items(), key=lambda x: -x[1])[:10]
    if pull_imp:
        summary['top_pull_features'] = sorted(pull_imp.items(), key=lambda x: -x[1])[:10]

    with open(MODEL_DIR / 'results_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n\nResults saved to {MODEL_DIR / 'results_summary.json'}")


if __name__ == '__main__':
    main()
