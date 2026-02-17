"""
Strategy V2: Direct threshold betting (no isotonic calibration).

Finding: Raw model predictions with simple thresholds outperform
the isotonic-calibrated EV approach. The calibration layer was
actually degrading signal quality.

Approach:
- Recency-weighted LightGBM (half-life 365 days)
- Bet OVER when pred_saves - line > threshold
- Bet UNDER when line - pred_saves > threshold
- No probability conversion needed — just use the raw edge
"""
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error
from train_models import (
    get_shot_features_by_iteration,
    get_shot_params,
    get_svpct_features_by_iteration,
    get_svpct_params,
    load_matrix,
    walk_forward_split,
)

warnings.filterwarnings("ignore", category=UserWarning)


def american_to_decimal(odds):
    """Convert American odds to decimal payout (profit per $1 risked)."""
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, 100 / (-odds), odds / 100)


def run_strategy_v2():
    """Direct threshold strategy with recency weighting."""
    print("=" * 60)
    print("  STRATEGY V2: Direct Threshold (Recency-Weighted)")
    print("=" * 60)

    matrix = load_matrix()
    shot_features = [c for c in get_shot_features_by_iteration(5) if c in matrix.columns]
    svpct_features = [c for c in get_svpct_features_by_iteration(5) if c in matrix.columns]

    splits = walk_forward_split(matrix)
    all_results = []

    for split in splits:
        train_df = split["train"].dropna(subset=["shots_against", "save_pct"])
        val_df = split["val"].dropna(subset=["shots_against", "save_pct"])

        if len(val_df) < 20:
            continue

        # --- Recency weights (half-life 365 days) ---
        max_date = train_df["event_date"].max()
        days_ago = (max_date - train_df["event_date"]).dt.days
        weights = np.exp(-days_ago * np.log(2) / 365)

        # --- Train shots model ---
        sp = get_shot_params(5)
        sp.pop("n_estimators", None)
        sp.pop("verbose", None)
        model_a = lgb.LGBMRegressor(**sp, n_estimators=500, verbose=-1)
        model_a.fit(
            train_df[shot_features].fillna(-999),
            train_df["shots_against"],
            sample_weight=weights,
        )

        # --- Train save% model ---
        svp = get_svpct_params(5)
        svp.pop("n_estimators", None)
        svp.pop("verbose", None)
        model_b = lgb.LGBMRegressor(**svp, n_estimators=500, verbose=-1)
        model_b.fit(
            train_df[svpct_features].fillna(-999),
            train_df["save_pct"],
            sample_weight=weights,
        )

        # --- Predict ---
        pred_shots = model_a.predict(val_df[shot_features].fillna(-999))
        pred_svpct = model_b.predict(val_df[svpct_features].fillna(-999))
        pred_saves = pred_shots * pred_svpct
        pred_edge = pred_saves - val_df["line"].values

        res = val_df[
            [
                "event_date",
                "player_name",
                "line",
                "over_odds",
                "under_odds",
                "saves",
                "shots_against",
                "went_over",
                "went_under",
                "was_pulled",
            ]
        ].copy()
        res["pred_saves"] = pred_saves
        res["pred_edge"] = pred_edge
        res["split"] = split["name"]
        all_results.append(res)

    results = pd.concat(all_results, ignore_index=True)
    print(f"\n  Total predictions: {len(results)}")
    print(f"  Pred saves MAE: {mean_absolute_error(results['saves'], results['pred_saves']):.2f}")

    # --- Directional accuracy ---
    dir_acc = ((results["pred_edge"] > 0) == (results["went_over"] == 1)).mean()
    print(f"  Directional accuracy: {dir_acc:.1%}")

    # --- Threshold analysis ---
    print("\n  --- OVER Bets (pred_edge > threshold) ---")
    print(f"  {'Thresh':>6} {'Bets':>5} {'Win%':>6} {'ROI':>7} {'P&L':>8}")
    print(f"  {'-'*36}")
    for thresh in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        bets = results[results["pred_edge"] > thresh]
        if len(bets) < 10:
            continue
        payouts = american_to_decimal(bets["over_odds"].values)
        pnl = np.where(bets["went_over"] == 1, payouts, -1)
        roi = pnl.sum() / len(pnl) * 100
        wr = (pnl > 0).mean() * 100
        print(f"  {thresh:>6.1f} {len(bets):>5} {wr:>5.1f}% {roi:>+6.1f}% {pnl.sum():>+7.1f}u")

    print("\n  --- UNDER Bets (pred_edge < -threshold) ---")
    print(f"  {'Thresh':>6} {'Bets':>5} {'Win%':>6} {'ROI':>7} {'P&L':>8}")
    print(f"  {'-'*36}")
    for thresh in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        bets = results[results["pred_edge"] < -thresh]
        if len(bets) < 10:
            continue
        payouts = american_to_decimal(bets["under_odds"].values)
        pnl = np.where(bets["went_under"] == 1, payouts, -1)
        roi = pnl.sum() / len(pnl) * 100
        wr = (pnl > 0).mean() * 100
        print(f"  {thresh:>6.1f} {len(bets):>5} {wr:>5.1f}% {roi:>+6.1f}% {pnl.sum():>+7.1f}u")

    # --- Combined (both sides) ---
    print("\n  --- Combined (OVER + UNDER, |edge| > threshold) ---")
    print(f"  {'Thresh':>6} {'Bets':>5} {'Win%':>6} {'ROI':>7} {'P&L':>8}")
    print(f"  {'-'*36}")
    for thresh in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        over = results[results["pred_edge"] > thresh]
        under = results[results["pred_edge"] < -thresh]

        over_payouts = american_to_decimal(over["over_odds"].values)
        over_pnl = np.where(over["went_over"] == 1, over_payouts, -1)

        under_payouts = american_to_decimal(under["under_odds"].values)
        under_pnl = np.where(under["went_under"] == 1, under_payouts, -1)

        all_pnl = np.concatenate([over_pnl, under_pnl])
        if len(all_pnl) < 10:
            continue
        roi = all_pnl.sum() / len(all_pnl) * 100
        wr = (all_pnl > 0).mean() * 100
        print(f"  {thresh:>6.1f} {len(all_pnl):>5} {wr:>5.1f}% {roi:>+6.1f}% {all_pnl.sum():>+7.1f}u")

    # --- Monthly P&L for best threshold ---
    best_thresh = 1.5
    print(f"\n  --- Monthly P&L (|edge| > {best_thresh}) ---")
    over = results[results["pred_edge"] > best_thresh].copy()
    under = results[results["pred_edge"] < -best_thresh].copy()

    over["pnl"] = np.where(
        over["went_over"] == 1,
        american_to_decimal(over["over_odds"].values),
        -1,
    )
    over["side"] = "OVER"
    under["pnl"] = np.where(
        under["went_under"] == 1,
        american_to_decimal(under["under_odds"].values),
        -1,
    )
    under["side"] = "UNDER"

    combined = pd.concat([over, under])
    combined["month"] = pd.to_datetime(combined["event_date"]).dt.to_period("M")

    for month, grp in combined.groupby("month"):
        roi = grp["pnl"].sum() / len(grp) * 100
        wr = (grp["pnl"] > 0).mean() * 100
        print(f"  {month}: {len(grp)} bets, win {wr:.0f}%, ROI: {roi:+.1f}%, P&L: {grp['pnl'].sum():+.1f}u")

    # --- 2025-26 specific ---
    print(f"\n  --- 2025-26 Season Only (|edge| > {best_thresh}) ---")
    s2526 = combined[pd.to_datetime(combined["event_date"]) >= "2025-10-01"]
    if len(s2526) > 0:
        roi = s2526["pnl"].sum() / len(s2526) * 100
        wr = (s2526["pnl"] > 0).mean() * 100
        print(f"  {len(s2526)} bets, win {wr:.1f}%, ROI: {roi:+.1f}%, P&L: {s2526['pnl'].sum():+.1f}u")
        for month, grp in s2526.groupby("month"):
            roi = grp["pnl"].sum() / len(grp) * 100
            print(f"    {month}: {len(grp)} bets, ROI: {roi:+.1f}%, P&L: {grp['pnl'].sum():+.1f}u")
    else:
        print("  No 2025-26 data in this split")

    # Save
    results.to_csv("strategy_v2_results.csv", index=False)
    print(f"\n  Saved to strategy_v2_results.csv")
    return results


if __name__ == "__main__":
    run_strategy_v2()
