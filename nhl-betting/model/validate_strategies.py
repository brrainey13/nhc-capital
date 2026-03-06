#!/usr/bin/env python3
"""
Validation diagnostics for the 5 winning goalie saves strategies.
Tests: overlap, fold stability, CLV proxy, juice sensitivity, confidence intervals.

Re-exports from validate_config and validate_reporting for backwards compatibility.
"""

import pandas as pd
from validate_config import (  # noqa: F401
    calc_payout,
    derive_corsi_features,
    get_strategy_bets,
    load_matrix,
    simulate_bets_detailed,
    walk_forward_split,
)
from validate_reporting import (  # noqa: F401
    diag_clv_proxy,
    diag_confidence_intervals,
    diag_fold_stability,
    diag_juice_sensitivity,
    diag_overlap,
    write_report,
)


def main():
    print("Loading data...")
    matrix = load_matrix()
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    matrix = derive_corsi_features(matrix)
    splits = walk_forward_split(matrix)
    print(f"Matrix: {len(matrix)} rows, {len(splits)} splits")

    print("\nGenerating strategy bets...")
    strategies = get_strategy_bets(matrix, splits)
    for sname, sdata in strategies.items():
        total = sum(len(df) for df in sdata.values())
        print(f"  {sname}: {total} bets across {len(sdata)} splits")

    overlap_data = diag_overlap(strategies, splits)
    fold_results = diag_fold_stability(strategies, splits)
    diag_clv_proxy(strategies, splits)
    diag_juice_sensitivity(strategies, splits)
    diag_confidence_intervals(strategies, splits)
    write_report(overlap_data, fold_results, strategies, splits)


if __name__ == '__main__':
    main()
