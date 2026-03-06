"""Audit checks 6-9: per-fold strategy results with statistical significance."""

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import stats


def check6789(df):
    print("=" * 70)
    print("CHECK 6-9: PER-FOLD STRATEGY RESULTS (MF3 + MF2)")
    print("=" * 70)

    model_features = [
        "sa_avg_10", "sa_avg_20", "svpct_avg_10", "svpct_avg_20", "is_home",
        "opp_team_sog_avg_10", "days_rest", "own_def_missing_toi",
        "opp_corsi_pct_avg_10", "opp_corsi_diff_avg_10",
        "own_corsi_pct_avg_10", "pull_rate_10", "starts_last_7d",
        "opp_team_pp_opps_avg_10", "line",
    ]
    available_feats = [c for c in model_features if c in df.columns]
    print(f"Model features available: {len(available_feats)}/{len(model_features)}")
    missing = [c for c in model_features if c not in df.columns]
    if missing:
        print(f"Missing: {missing}")

    lgb_params = {
        "objective": "regression", "num_leaves": 10, "max_depth": 4,
        "min_child_samples": 50, "learning_rate": 0.05, "feature_fraction": 0.6,
        "bagging_fraction": 0.7, "bagging_freq": 5, "reg_alpha": 0.5,
        "reg_lambda": 0.5, "verbose": -1,
    }

    splits = [
        ("Fold 1 (val 23-24)", df[df["event_date"] < "2023-10-01"],
         df[(df["event_date"] >= "2023-10-01") & (df["event_date"] < "2024-10-01")]),
        ("Fold 2 (val 24-25)", df[df["event_date"] < "2024-10-01"],
         df[(df["event_date"] >= "2024-10-01") & (df["event_date"] < "2025-10-01")]),
        ("Fold 3 (val 25-26)", df[df["event_date"] < "2025-10-01"],
         df[df["event_date"] >= "2025-10-01"]),
    ]

    all_mf3_bets = []
    all_mf2_bets = []

    for fold_name, train, val in splits:
        if len(train) < 50 or len(val) < 20:
            print(f"\n{fold_name}: SKIPPED (train={len(train)}, val={len(val)})")
            continue

        train_clean = train.dropna(subset=["saves"] + available_feats)
        val_clean = val.dropna(subset=["saves"] + available_feats)

        if len(train_clean) < 50 or len(val_clean) < 20:
            print(f"\n{fold_name}: SKIPPED after dropna (train={len(train_clean)}, val={len(val_clean)})")
            continue

        X_train = train_clean[available_feats].fillna(-999)
        y_train = train_clean["saves"]
        X_val = val_clean[available_feats].fillna(-999)

        model = lgb.LGBMRegressor(**lgb_params, n_estimators=300)
        model.fit(X_train, y_train)
        preds = model.predict(X_val)

        val_clean = val_clean.copy()
        val_clean["pred"] = preds
        val_clean["gap"] = abs(val_clean["pred"] - val_clean["line"])
        val_clean["model_side"] = np.where(val_clean["pred"] < val_clean["line"], "under", "over")

        corsi_q25 = train_clean["opp_corsi_pct_avg_10"].quantile(0.25) if "opp_corsi_pct_avg_10" in val_clean.columns else None

        if corsi_q25 is not None:
            mf3 = val_clean[
                (val_clean["model_side"] == "under")
                & (val_clean["gap"] >= 1.0)
                & (val_clean["opp_corsi_pct_avg_10"] < corsi_q25)
            ].copy()
        else:
            mf3 = pd.DataFrame()

        if "days_rest" in val_clean.columns:
            mf2 = val_clean[
                (val_clean["model_side"] == "under")
                & (val_clean["gap"] >= 2.0)
                & (val_clean["days_rest"] <= 1)
            ].copy()
        else:
            mf2 = pd.DataFrame()

        print(f"\n{fold_name}:")
        print(f"  Train: {len(train_clean)}, Val: {len(val_clean)}")
        if corsi_q25 is not None:
            print(f"  Corsi Q25 (from training): {corsi_q25:.4f}")

        for strat_name, strat_df in [("MF3", mf3), ("MF2", mf2)]:
            if len(strat_df) == 0:
                print(f"  {strat_name}: 0 bets")
                continue

            strat_df = strat_df.copy()
            strat_df["won"] = strat_df["saves"] < strat_df["line"]
            strat_df["push"] = strat_df["saves"] == strat_df["line"]
            non_push = strat_df[~strat_df["push"]]

            n = len(non_push)
            wins = non_push["won"].sum()
            wr = wins / n * 100 if n > 0 else 0

            pnl = non_push["won"].apply(lambda w: 100 / 110 if w else -1).sum()
            roi = pnl / n * 100 if n > 0 else 0

            results_seq = non_push["won"].astype(int).values
            max_losing = 0
            current_losing = 0
            for r in results_seq:
                if r == 0:
                    current_losing += 1
                    max_losing = max(max_losing, current_losing)
                else:
                    current_losing = 0

            cum_pnl = non_push["won"].apply(lambda w: 100 / 110 if w else -1).cumsum()
            running_max = cum_pnl.cummax()
            drawdown = (running_max - cum_pnl).max()

            print(f"  {strat_name}: {n} bets ({int(strat_df['push'].sum())} pushes), "
                  f"Wins={int(wins)}, WR={wr:.1f}%, ROI={roi:+.1f}%, "
                  f"MaxLoseStreak={max_losing}, MaxDD={drawdown:.2f}u")

            if strat_name == "MF3":
                all_mf3_bets.append(non_push)
            else:
                all_mf2_bets.append(non_push)

    # Aggregate totals + p-values
    print(f"\n{'='*70}")
    print("AGGREGATE TOTALS + STATISTICAL SIGNIFICANCE")
    print(f"{'='*70}")

    for strat_name, all_bets in [("MF3", all_mf3_bets), ("MF2", all_mf2_bets)]:
        if not all_bets:
            print(f"\n{strat_name}: No bets across any fold")
            continue
        combined = pd.concat(all_bets, ignore_index=True)
        n = len(combined)
        wins = combined["won"].sum()
        wr = wins / n * 100

        flag = " ⚠️ <100 BETS" if n < 100 else ""
        print(f"\n{strat_name}: {n} total bets{flag}")
        print(f"  Win rate: {wr:.1f}% ({int(wins)}/{n})")

        breakeven = 110 / 210
        p_val = 1 - stats.binom.cdf(int(wins) - 1, n, breakeven)
        print(f"  Breakeven at -110: {breakeven*100:.2f}%")
        print(f"  P-value (vs breakeven): {p_val:.6f} {'✅ p<0.05' if p_val < 0.05 else '⚠️ NOT significant'}")

        p_val_50 = 1 - stats.binom.cdf(int(wins) - 1, n, 0.5)
        print(f"  P-value (vs 50%): {p_val_50:.6f}")

        results_seq = combined["won"].astype(int).values
        max_losing = 0
        current_losing = 0
        for r in results_seq:
            if r == 0:
                current_losing += 1
                max_losing = max(max_losing, current_losing)
            else:
                current_losing = 0

        cum_pnl = combined["won"].apply(lambda w: 100 / 110 if w else -1).cumsum()
        max_dd = (cum_pnl.cummax() - cum_pnl).max()
        total_pnl = cum_pnl.iloc[-1]

        print(f"  Total P&L: {total_pnl:+.2f}u")
        print(f"  Max losing streak: {max_losing}")
        print(f"  Max drawdown: {max_dd:.2f}u")

    return all_mf3_bets, all_mf2_bets
