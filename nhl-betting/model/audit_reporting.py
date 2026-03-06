"""Audit checks 10-14: overfitting checks and reality checks."""

import lightgbm as lgb
import numpy as np
import pandas as pd


# ── CHECK 10 + 11: Overfitting checks ──
def check10_11(df, all_mf3_bets, all_mf2_bets):
    print(f"\n{'='*70}")
    print("CHECK 10: FILTER COMBINATIONS TESTED")
    print(f"{'='*70}")
    print("""
From the research log (40+ strategies across 8 rounds):
- Round 1: 8 solo filters (B2B, home/away, division, Corsi, etc.)
- Round 2: 8 more (pull risk, SV%, rest days, etc.)
- Round 3-8: Stacked filter combinations
- Final: MF3 (model+Corsi) and MF2 (model+B2B) selected

Total unique filter combos tested: ~40-50
This is moderate researcher degrees of freedom. The walk-forward design
mitigates this (filters chosen on fold 1 data, validated on folds 2-3),
but the risk of overfitting to the specific Corsi/B2B thresholds is real.
""")

    print(f"{'='*70}")
    print("CHECK 11: THRESHOLD SENSITIVITY (±10%)")
    print(f"{'='*70}")

    model_features = [
        "sa_avg_10", "sa_avg_20", "svpct_avg_10", "svpct_avg_20", "is_home",
        "opp_team_sog_avg_10", "days_rest", "own_def_missing_toi",
        "opp_corsi_pct_avg_10", "opp_corsi_diff_avg_10",
        "own_corsi_pct_avg_10", "pull_rate_10", "starts_last_7d",
        "opp_team_pp_opps_avg_10", "line",
    ]
    available_feats = [c for c in model_features if c in df.columns]

    lgb_params = {
        "objective": "regression", "num_leaves": 10, "max_depth": 4,
        "min_child_samples": 50, "learning_rate": 0.05, "feature_fraction": 0.6,
        "bagging_fraction": 0.7, "bagging_freq": 5, "reg_alpha": 0.5,
        "reg_lambda": 0.5, "verbose": -1,
    }

    train = df[df["event_date"] < "2024-10-01"].dropna(subset=["saves"] + available_feats)
    val = df[(df["event_date"] >= "2024-10-01") & (df["event_date"] < "2025-10-01")].dropna(
        subset=["saves"] + available_feats
    )

    if len(train) < 50 or len(val) < 20:
        print("Insufficient data for sensitivity analysis")
        return

    model = lgb.LGBMRegressor(**lgb_params, n_estimators=300)
    model.fit(train[available_feats].fillna(-999), train["saves"])
    preds = model.predict(val[available_feats].fillna(-999))

    val = val.copy()
    val["pred"] = preds
    val["gap"] = abs(val["pred"] - val["line"])
    val["model_side"] = np.where(val["pred"] < val["line"], "under", "over")

    has_corsi = "opp_corsi_pct_avg_10" in df.columns
    if has_corsi:
        print("\nMF3 Sensitivity (gap threshold × Corsi percentile):")
        print(f"{'Gap':<8} {'Corsi%':<10} {'Bets':>6} {'WR%':>7} {'ROI%':>8}")
        print("-" * 42)

        for gap in [0.9, 1.0, 1.1]:
            for corsi_pct in [0.225, 0.25, 0.275]:
                corsi_q = train["opp_corsi_pct_avg_10"].quantile(corsi_pct)
                mf3 = val[
                    (val["model_side"] == "under")
                    & (val["gap"] >= gap)
                    & (val["opp_corsi_pct_avg_10"] < corsi_q)
                ]
                non_push = mf3[mf3["saves"] != mf3["line"]]
                n = len(non_push)
                if n == 0:
                    print(f"{gap:<8} {corsi_pct:<10} {0:>6}   N/A      N/A")
                    continue
                wins = (non_push["saves"] < non_push["line"]).sum()
                wr = wins / n * 100
                pnl = sum(100 / 110 if w else -1 for w in (non_push["saves"] < non_push["line"]))
                roi = pnl / n * 100
                marker = " ← BASE" if gap == 1.0 and corsi_pct == 0.25 else ""
                print(f"{gap:<8} {corsi_pct:<10} {n:>6} {wr:>6.1f}% {roi:>+7.1f}%{marker}")
    else:
        print("\n⚠️ MF3 SENSITIVITY CANNOT BE RUN — opp_corsi_pct_avg_10 MISSING from feature_matrix.pkl")

    print("\nMF2 Sensitivity (gap threshold × rest threshold):")
    print(f"{'Gap':<8} {'Rest≤':<10} {'Bets':>6} {'WR%':>7} {'ROI%':>8}")
    print("-" * 42)

    for gap in [1.8, 2.0, 2.2]:
        for rest in [0, 1, 2]:
            mf2 = val[
                (val["model_side"] == "under")
                & (val["gap"] >= gap)
                & (val["days_rest"] <= rest)
            ]
            non_push = mf2[mf2["saves"] != mf2["line"]]
            n = len(non_push)
            if n == 0:
                print(f"{gap:<8} {rest:<10} {0:>6}   N/A      N/A")
                continue
            wins = (non_push["saves"] < non_push["line"]).sum()
            wr = wins / n * 100
            pnl = sum(100 / 110 if w else -1 for w in (non_push["saves"] < non_push["line"]))
            roi = pnl / n * 100
            marker = " ← BASE" if gap == 2.0 and rest == 1 else ""
            print(f"{gap:<8} {rest:<10} {n:>6} {wr:>6.1f}% {roi:>+7.1f}%{marker}")
    print()


# ── CHECK 12 + 13 + 14: Reality checks ──
def check12_13_14(df, all_mf3_bets, all_mf2_bets):
    print(f"{'='*70}")
    print("CHECK 12: LINE ASSUMPTION")
    print(f"{'='*70}")

    if "opening_line" in df.columns and "line" in df.columns:
        both = df.dropna(subset=["opening_line", "line"])
        same = (both["opening_line"] == both["line"]).sum()
        diff = (both["opening_line"] != both["line"]).sum()
        print(f"Rows with both opening_line and line: {len(both)}")
        print(f"  Same: {same} ({same/len(both)*100:.1f}%)")
        print(f"  Different: {diff} ({diff/len(both)*100:.1f}%)")
        if diff > 0:
            avg_move = (both["line"] - both["opening_line"]).mean()
            print(f"  Avg line movement: {avg_move:+.3f}")
        print("\nThe 'line' column appears to be the CLOSING/BEST AVAILABLE line from the scraper.")
        print("⚠️ This is optimistic — in live betting you'd get the line at time of bet,")
        print("   which is typically between opening and closing.")
    else:
        cols_with_line = [c for c in df.columns if "line" in c.lower() or "open" in c.lower()]
        print(f"Line-related columns: {cols_with_line}")
        if "line" in df.columns:
            print("Only 'line' column exists — likely closing/consensus line")
            print("⚠️ Cannot verify if opening vs closing. Assume best available.")

    print(f"\n{'='*70}")
    print("CHECK 13: VIG ACCOUNTING")
    print(f"{'='*70}")
    print("Standard -110/-110 vig:")
    print(f"  Breakeven win rate: {110/210*100:.2f}%")
    print(f"  Win payout: +{100/110:.4f} units per unit risked")
    print("  Loss payout: -1.0000 units")

    if "over_odds" in df.columns and "under_odds" in df.columns:
        sample_odds = df[["over_odds", "under_odds"]].dropna().head(20)
        print("\nActual odds from data (sample):")
        for _, r in sample_odds.head(5).iterrows():
            print(f"  Over: {r['over_odds']:+.0f}, Under: {r['under_odds']:+.0f}")

        all_odds = df[["over_odds", "under_odds"]].dropna()

        def implied_prob(odds):
            odds = float(odds)
            if odds < 0:
                return -odds / (-odds + 100)
            return 100 / (odds + 100)

        all_odds = all_odds.copy()
        all_odds["ip_over"] = all_odds["over_odds"].apply(implied_prob)
        all_odds["ip_under"] = all_odds["under_odds"].apply(implied_prob)
        all_odds["total_ip"] = all_odds["ip_over"] + all_odds["ip_under"]
        avg_vig = (all_odds["total_ip"].mean() - 1) * 100
        print(f"\n  Average total implied probability: {all_odds['total_ip'].mean():.4f}")
        print(f"  Average vig (overround): {avg_vig:.2f}%")
        print(f"  Effective breakeven: ~{all_odds['ip_under'].mean()*100:.1f}% for under bets")
    else:
        print("\nNo over_odds/under_odds columns — vig assumed at -110")

    print(f"\n{'='*70}")
    print("CHECK 14: MONTHLY CONSISTENCY")
    print(f"{'='*70}")

    for strat_name, all_bets in [("MF3", all_mf3_bets), ("MF2", all_mf2_bets)]:
        if not all_bets:
            print(f"\n{strat_name}: No data")
            continue
        combined = pd.concat(all_bets, ignore_index=True)
        combined["month"] = combined["event_date"].dt.to_period("M")

        print(f"\n{strat_name} by month:")
        print(f"{'Month':<12} {'Bets':>6} {'WR%':>7} {'ROI%':>8} {'P&L':>8}")
        print("-" * 44)

        months_positive = 0
        months_total = 0

        for month, grp in combined.groupby("month"):
            non_push = grp[grp["saves"] != grp["line"]]
            n = len(non_push)
            if n == 0:
                continue
            wins = (non_push["saves"] < non_push["line"]).sum()
            wr = wins / n * 100
            pnl = sum(100 / 110 if w else -1 for w in (non_push["saves"] < non_push["line"]))
            roi = pnl / n * 100
            months_total += 1
            if pnl > 0:
                months_positive += 1
            print(f"{str(month):<12} {n:>6} {wr:>6.1f}% {roi:>+7.1f}% {pnl:>+7.2f}u")

        print(f"\n  Positive months: {months_positive}/{months_total}")
        concentrated = months_positive < months_total * 0.4
        if concentrated:
            print("  ⚠️ Edge may be concentrated — fewer than 40% of months profitable")
        else:
            print("  ✅ Edge distributed across months")
    print()
