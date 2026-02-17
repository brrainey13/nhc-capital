"""
Phase 4b: Calibrated EV Analysis for Goalie Saves Model.

Uses isotonic regression to convert model predictions into
properly calibrated probabilities, then computes EV.
"""

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
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


def american_to_prob(odds):
    """Convert American odds to implied probability."""
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, -odds / (-odds + 100), 100 / (odds + 100))


def american_to_decimal(odds):
    """Convert American odds to decimal payout (profit per $1 risked)."""
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, 100 / (-odds), odds / 100)


def run_calibrated_ev():
    """Run EV analysis with proper probability calibration."""
    print("=" * 60)
    print("  CALIBRATED EV ANALYSIS (Phase 4b)")
    print("=" * 60)

    matrix = load_matrix()
    shot_features = [c for c in get_shot_features_by_iteration(5) if c in matrix.columns]
    svpct_features = [c for c in get_svpct_features_by_iteration(5) if c in matrix.columns]

    splits = walk_forward_split(matrix)
    all_results = []

    for split in splits:
        train_df = split["train"].dropna(subset=["shots_against", "save_pct"])
        val_df = split["val"].dropna(subset=["shots_against", "save_pct"])

        # Further split train into train/calibration sets (80/20)
        cal_cutoff = int(len(train_df) * 0.8)
        cal_df = train_df.iloc[cal_cutoff:]
        train_df_inner = train_df.iloc[:cal_cutoff]

        if len(val_df) < 20 or len(cal_df) < 50:
            continue

        # --- Train Model A: shots ---
        sp = get_shot_params(5)
        sp.pop("n_estimators", None)
        sp.pop("verbose", None)
        model_a = lgb.LGBMRegressor(**sp, n_estimators=500, verbose=-1)
        model_a.fit(
            train_df_inner[shot_features].fillna(-999),
            train_df_inner["shots_against"],
        )

        # --- Train Model B: save% ---
        svp = get_svpct_params(5)
        svp.pop("n_estimators", None)
        svp.pop("verbose", None)
        model_b = lgb.LGBMRegressor(**svp, n_estimators=500, verbose=-1)
        model_b.fit(
            train_df_inner[svpct_features].fillna(-999),
            train_df_inner["save_pct"],
        )

        # --- Calibration set predictions ---
        cal_pred_shots = model_a.predict(cal_df[shot_features].fillna(-999))
        cal_pred_svpct = model_b.predict(cal_df[svpct_features].fillna(-999))
        cal_pred_saves = cal_pred_shots * cal_pred_svpct
        cal_edge = cal_pred_saves - cal_df["line"].values
        cal_actual_over = cal_df["went_over"].values.astype(float)

        # --- Isotonic regression: edge → P(over) ---
        iso_reg = IsotonicRegression(y_min=0.05, y_max=0.95, out_of_bounds="clip")
        iso_reg.fit(cal_edge, cal_actual_over)

        # --- Validation predictions ---
        val_pred_shots = model_a.predict(val_df[shot_features].fillna(-999))
        val_pred_svpct = model_b.predict(val_df[svpct_features].fillna(-999))
        val_pred_saves = val_pred_shots * val_pred_svpct
        val_edge = val_pred_saves - val_df["line"].values

        # Calibrated probabilities
        val_p_over = iso_reg.predict(val_edge)
        val_p_under = 1 - val_p_over

        # --- Build result frame ---
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
        res["pred_saves"] = val_pred_saves
        res["pred_edge"] = val_edge
        res["p_over"] = val_p_over
        res["p_under"] = val_p_under

        # Implied probs from market
        res["mkt_p_over"] = american_to_prob(res["over_odds"])
        res["mkt_p_under"] = american_to_prob(res["under_odds"])

        # Payouts
        over_payout = american_to_decimal(res["over_odds"])
        under_payout = american_to_decimal(res["under_odds"])

        # EV = p_win * payout - p_lose
        res["ev_over"] = val_p_over * over_payout - (1 - val_p_over)
        res["ev_under"] = val_p_under * under_payout - (1 - val_p_under)

        # Best bet
        res["best_side"] = np.where(res["ev_over"] > res["ev_under"], "OVER", "UNDER")
        res["best_ev"] = np.maximum(res["ev_over"], res["ev_under"])

        # Our edge over market
        res["edge_over"] = val_p_over - res["mkt_p_over"]
        res["edge_under"] = val_p_under - res["mkt_p_under"]

        res["split"] = split["name"]
        all_results.append(res)

    if not all_results:
        print("  No valid results")
        return None

    results = pd.concat(all_results, ignore_index=True)

    print(f"\n  Total predictions: {len(results)}")
    print(
        f"  Pred saves MAE: {mean_absolute_error(results['saves'], results['pred_saves']):.2f}"
    )

    # --- Calibration check ---
    print("\n  --- Calibration Check ---")
    bins = [0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 1.0]
    results["p_over_bin"] = pd.cut(results["p_over"], bins=bins)
    cal_check = (
        results.groupby("p_over_bin", observed=True)
        .agg(count=("went_over", "count"), actual_over=("went_over", "mean"), avg_pred=("p_over", "mean"))
        .reset_index()
    )
    print(cal_check.to_string(index=False))

    # --- EV thresholds ---
    print("\n  --- EV Analysis (Calibrated) ---")
    for ev_thresh in [0.0, 0.02, 0.05, 0.08, 0.10, 0.15]:
        bets = results[results["best_ev"] > ev_thresh]
        if len(bets) < 10:
            print(f"  EV > {ev_thresh:.0%}: <10 bets, skipping")
            continue

        # Simulate flat $100 bets
        pnl = []
        for _, b in bets.iterrows():
            if b["best_side"] == "OVER":
                payout = american_to_decimal(np.array([b["over_odds"]]))[0]
                won = b["went_over"] == 1
            else:
                payout = american_to_decimal(np.array([b["under_odds"]]))[0]
                won = b["went_under"] == 1
            pnl.append(payout if won else -1)

        total_pnl = sum(pnl)
        roi = (total_pnl / len(bets)) * 100
        win_rate = sum(1 for p in pnl if p > 0) / len(pnl) * 100

        print(
            f"  EV > {ev_thresh:.0%}: {len(bets)} bets, "
            f"win {win_rate:.1f}%, ROI: {roi:+.1f}%, "
            f"P&L: {total_pnl:+.1f} units"
        )

    # --- Edge-based filtering (our prob vs market prob) ---
    print("\n  --- Edge Over Market ---")
    for edge_thresh in [0.02, 0.05, 0.08, 0.10, 0.15]:
        # Take bets where our edge over market is significant
        over_bets = results[(results["edge_over"] > edge_thresh)]
        under_bets = results[(results["edge_under"] > edge_thresh)]

        over_pnl = []
        for _, b in over_bets.iterrows():
            payout = american_to_decimal(np.array([b["over_odds"]]))[0]
            over_pnl.append(payout if b["went_over"] == 1 else -1)

        under_pnl = []
        for _, b in under_bets.iterrows():
            payout = american_to_decimal(np.array([b["under_odds"]]))[0]
            under_pnl.append(payout if b["went_under"] == 1 else -1)

        all_pnl = over_pnl + under_pnl
        n = len(all_pnl)
        if n < 10:
            continue
        roi = (sum(all_pnl) / n) * 100
        wr = sum(1 for p in all_pnl if p > 0) / n * 100
        print(
            f"  Edge > {edge_thresh:.0%}: {n} bets "
            f"(O:{len(over_bets)} U:{len(under_bets)}), "
            f"win {wr:.1f}%, ROI: {roi:+.1f}%, "
            f"P&L: {sum(all_pnl):+.1f}u"
        )

    # --- Monthly breakdown ---
    print("\n  --- Monthly P&L (EV > 5%) ---")
    bets = results[results["best_ev"] > 0.05].copy()
    if len(bets) > 0:
        bets["month"] = pd.to_datetime(bets["event_date"]).dt.to_period("M")
        for month, grp in bets.groupby("month"):
            pnl = []
            for _, b in grp.iterrows():
                if b["best_side"] == "OVER":
                    payout = american_to_decimal(np.array([b["over_odds"]]))[0]
                    won = b["went_over"] == 1
                else:
                    payout = american_to_decimal(np.array([b["under_odds"]]))[0]
                    won = b["went_under"] == 1
                pnl.append(payout if won else -1)
            roi = (sum(pnl) / len(pnl)) * 100
            print(f"  {month}: {len(pnl)} bets, ROI: {roi:+.1f}%, P&L: {sum(pnl):+.1f}u")

    # Save
    results.to_csv("calibrated_ev_results.csv", index=False)
    print(f"\n  Saved {len(results)} results to calibrated_ev_results.csv")
    return results


if __name__ == "__main__":
    run_calibrated_ev()
