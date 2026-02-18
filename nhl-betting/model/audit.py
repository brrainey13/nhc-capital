"""
Full audit of goalie saves strategies — all 14 checks.
"""

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

warnings.filterwarnings("ignore")

DB = "postgresql://connorrainey@localhost:5432/nhl_betting"
MODEL_DIR = "/Users/connorrainey/nhc-capital/nhl-betting/model"


def load_matrix():
    df = pd.read_pickle(f"{MODEL_DIR}/feature_matrix.pkl")
    df["event_date"] = pd.to_datetime(df["event_date"])
    return df


# ── CHECK 1: Matrix stats ──
def check1(df):
    print("=" * 70)
    print("CHECK 1: FEATURE MATRIX STATS")
    print("=" * 70)
    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print(f"Date range: {df['event_date'].min().date()} to {df['event_date'].max().date()}")

    goalie_col = None
    for c in ["player_name", "goalie_name", "player_id", "goalie_id"]:
        if c in df.columns:
            goalie_col = c
            break
    if goalie_col:
        print(f"Unique goalies ({goalie_col}): {df[goalie_col].nunique()}")
    else:
        print("No obvious goalie ID column found. Columns containing 'player' or 'goalie':")
        print([c for c in df.columns if "player" in c.lower() or "goalie" in c.lower()])

    print("\nNull % per column (showing >0% only):")
    null_pct = (df.isnull().sum() / len(df) * 100).round(2)
    non_zero = null_pct[null_pct > 0].sort_values(ascending=False)
    if len(non_zero) == 0:
        print("  No nulls in any column")
    else:
        for col, pct in non_zero.items():
            print(f"  {col}: {pct}%")
    print()


# ── CHECK 2: Cross-reference 5 random rows ──
def check2(df):
    print("=" * 70)
    print("CHECK 2: CROSS-REFERENCE 5 RANDOM ROWS VS SOURCE TABLES")
    print("=" * 70)
    conn = psycopg2.connect(DB)

    sample = df.sample(5, random_state=42)

    for i, (idx, row) in enumerate(sample.iterrows()):
        print(f"\n--- Row {i+1} ---")
        date = row["event_date"]
        player = row.get("player_name", "unknown")
        line = row.get("line", None)
        saves = row.get("saves", None)
        sa = row.get("shots_against", None)

        print(f"  Matrix: date={date.date()}, player={player}, line={line}, saves={saves}, shots_against={sa}")

        # Check saves_odds table
        cur = conn.cursor()
        cur.execute(
            "SELECT player_name, line, event_date FROM saves_odds WHERE player_name ILIKE %s AND event_date::date = %s::date LIMIT 3",
            (f"%{player.split()[-1]}%", str(date.date())),
        )
        odds_rows = cur.fetchall()
        if odds_rows:
            for r in odds_rows:
                print(f"  saves_odds: player={r[0]}, line={r[1]}, date={r[2]}")
                if line is not None and r[1] is not None:
                    match = "✅" if abs(float(line) - float(r[1])) < 0.01 else "⚠️ MISMATCH"
                    print(f"    Line check: matrix={line}, source={r[1]} {match}")
        else:
            print(f"  saves_odds: NO MATCH found for {player} on {date.date()}")

        # Check goalie_stats for saves/shots_against (join via games for date)
        cur.execute(
            "SELECT gs.saves, gs.shots_against, g.game_date "
            "FROM goalie_stats gs "
            "JOIN games g ON gs.game_id = g.game_id "
            "JOIN players p ON gs.player_id = p.player_id "
            "WHERE p.last_name ILIKE %s AND g.game_date::date = %s::date LIMIT 3",
            (f"%{player.split()[-1]}%", str(date.date())),
        )
        gs_rows = cur.fetchall()
        if gs_rows:
            for r in gs_rows:
                sa_match = "✅" if sa is not None and r[1] is not None and int(sa) == int(r[1]) else "⚠️"
                sv_match = "✅" if saves is not None and r[0] is not None and int(saves) == int(r[0]) else "⚠️"
                print(f"  goalie_stats: saves={r[0]}{sv_match}, shots_against={r[1]}{sa_match}, date={r[2]}")
        else:
            print(f"  goalie_stats: NO MATCH for {player} on {date.date()}")

    conn.close()
    print()


# ── CHECK 3: Duplicate rows ──
def check3(df):
    print("=" * 70)
    print("CHECK 3: DUPLICATE GOALIE + DATE ROWS")
    print("=" * 70)
    id_cols = []
    for c in ["player_name", "player_id", "goalie_id"]:
        if c in df.columns:
            id_cols.append(c)
            break
    id_cols.append("event_date")

    dupes = df.duplicated(subset=id_cols, keep=False)
    n_dupes = dupes.sum()
    print(f"Duplicate rows on {id_cols}: {n_dupes}")
    if n_dupes > 0:
        dupe_df = df[dupes].sort_values(id_cols)
        print("Sample duplicates:")
        print(dupe_df[id_cols + ["line", "saves"]].head(10).to_string())
    else:
        print("✅ No duplicates")
    print()


# ── CHECK 4: Pulled goalies ──
def check4(df):
    print("=" * 70)
    print("CHECK 4: PULLED GOALIES / SHORTENED STARTS")
    print("=" * 70)
    if "was_pulled" in df.columns:
        pulled = df["was_pulled"].sum()
        pct = pulled / len(df) * 100
        print(f"Pulled games: {int(pulled)} / {len(df)} ({pct:.1f}%)")

        # Stats for pulled vs not
        pulled_df = df[df["was_pulled"] == 1]
        normal_df = df[df["was_pulled"] != 1]
        print(f"  Pulled: avg saves={pulled_df['saves'].mean():.1f}, avg SA={pulled_df['shots_against'].mean():.1f}")
        print(f"  Normal: avg saves={normal_df['saves'].mean():.1f}, avg SA={normal_df['shots_against'].mean():.1f}")

        # Are pulled games included in backtest?
        if "line" in df.columns:
            pulled_with_line = pulled_df["line"].notna().sum()
            print(f"  Pulled games with odds lines: {pulled_with_line}")
            print("  → Pulled games ARE included in backtest (realistic — books don't know in advance)")
    else:
        print("No 'was_pulled' column. Checking for proxies...")
        if "saves" in df.columns and "shots_against" in df.columns:
            low_sa = df[df["shots_against"] < 15]
            print(f"  Games with <15 shots against (likely pulled/shortened): {len(low_sa)} ({len(low_sa)/len(df)*100:.1f}%)")
    print()


# ── CHECK 5: Train/test splits — no leakage ──
def check5(df):
    print("=" * 70)
    print("CHECK 5: EXACT TRAIN/TEST DATE SPLITS")
    print("=" * 70)
    splits = [
        {
            "name": "Fold 1: Train 22-23, Val 23-24",
            "train": df[df["event_date"] < "2023-10-01"],
            "val": df[(df["event_date"] >= "2023-10-01") & (df["event_date"] < "2024-10-01")],
        },
        {
            "name": "Fold 2: Train 22-24, Val 24-25",
            "train": df[df["event_date"] < "2024-10-01"],
            "val": df[(df["event_date"] >= "2024-10-01") & (df["event_date"] < "2025-10-01")],
        },
        {
            "name": "Fold 3: Train 22-25, Val 25-26",
            "train": df[df["event_date"] < "2025-10-01"],
            "val": df[df["event_date"] >= "2025-10-01"],
        },
    ]

    for s in splits:
        tr, va = s["train"], s["val"]
        if len(tr) == 0 or len(va) == 0:
            print(f"\n{s['name']}: SKIPPED (empty)")
            continue
        tr_max = tr["event_date"].max()
        va_min = va["event_date"].min()
        gap_days = (va_min - tr_max).days
        leak = "⚠️ LEAK!" if tr_max >= va_min else "✅ No leak"
        print(f"\n{s['name']}:")
        print(f"  Train: {tr['event_date'].min().date()} → {tr_max.date()} ({len(tr)} rows)")
        print(f"  Val:   {va_min.date()} → {va['event_date'].max().date()} ({len(va)} rows)")
        print(f"  Gap: {gap_days} days {leak}")
    print()
    return splits


# ── CHECK 6 + 7 + 8 + 9: Per-fold strategy results ──
def check6789(df):
    print("=" * 70)
    print("CHECK 6-9: PER-FOLD STRATEGY RESULTS (MF3 + MF2)")
    print("=" * 70)

    # Model features (from PROVENSTRATEGIES.md)
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
        "objective": "regression",
        "num_leaves": 10,
        "max_depth": 4,
        "min_child_samples": 50,
        "learning_rate": 0.05,
        "feature_fraction": 0.6,
        "bagging_fraction": 0.7,
        "bagging_freq": 5,
        "reg_alpha": 0.5,
        "reg_lambda": 0.5,
        "verbose": -1,
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

        # Compute Corsi quantile from TRAINING data only
        if "opp_corsi_pct_avg_10" in val_clean.columns:
            corsi_q25 = train_clean["opp_corsi_pct_avg_10"].quantile(0.25)
        else:
            corsi_q25 = None

        # MF3: under, gap >= 1.0, opp_corsi < q25
        if corsi_q25 is not None:
            mf3 = val_clean[
                (val_clean["model_side"] == "under")
                & (val_clean["gap"] >= 1.0)
                & (val_clean["opp_corsi_pct_avg_10"] < corsi_q25)
            ].copy()
        else:
            mf3 = pd.DataFrame()

        # MF2: under, gap >= 2.0, B2B (days_rest <= 1)
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

            # Determine win/loss: UNDER wins if saves < line
            strat_df = strat_df.copy()
            strat_df["won"] = strat_df["saves"] < strat_df["line"]
            strat_df["push"] = strat_df["saves"] == strat_df["line"]
            non_push = strat_df[~strat_df["push"]]

            n = len(non_push)
            wins = non_push["won"].sum()
            wr = wins / n * 100 if n > 0 else 0

            # ROI at -110
            pnl = non_push["won"].apply(lambda w: 100 / 110 if w else -1).sum()
            roi = pnl / n * 100 if n > 0 else 0

            # Losing streak
            results_seq = non_push["won"].astype(int).values
            max_losing = 0
            current_losing = 0
            for r in results_seq:
                if r == 0:
                    current_losing += 1
                    max_losing = max(max_losing, current_losing)
                else:
                    current_losing = 0

            # Max drawdown (in units)
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

        # CHECK 7: Sample size
        flag = " ⚠️ <100 BETS" if n < 100 else ""
        print(f"\n{strat_name}: {n} total bets{flag}")
        print(f"  Win rate: {wr:.1f}% ({int(wins)}/{n})")

        # CHECK 8: p-value vs naive 50% baseline
        # Binomial test: is win rate significantly > 52.38% (breakeven at -110)?
        breakeven = 110 / 210  # = 0.5238
        p_val = 1 - stats.binom.cdf(int(wins) - 1, n, breakeven)
        print(f"  Breakeven at -110: {breakeven*100:.2f}%")
        print(f"  P-value (vs breakeven): {p_val:.6f} {'✅ p<0.05' if p_val < 0.05 else '⚠️ NOT significant'}")

        # Also vs 50%
        p_val_50 = 1 - stats.binom.cdf(int(wins) - 1, n, 0.5)
        print(f"  P-value (vs 50%): {p_val_50:.6f}")

        # CHECK 9: Max losing streak + drawdown across all folds
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

    # We need to re-run the strategy with shifted thresholds
    # Use the full pipeline but vary key params

    model_features = [
        "sa_avg_10", "sa_avg_20", "svpct_avg_10", "svpct_avg_20", "is_home",
        "opp_team_sog_avg_10", "days_rest", "own_def_missing_toi",
        "opp_corsi_pct_avg_10", "opp_corsi_diff_avg_10",
        "own_corsi_pct_avg_10", "pull_rate_10", "starts_last_7d",
        "opp_team_pp_opps_avg_10", "line",
    ]
    available_feats = [c for c in model_features if c in df.columns]

    lgb_params = {
        "objective": "regression",
        "num_leaves": 10,
        "max_depth": 4,
        "min_child_samples": 50,
        "learning_rate": 0.05,
        "feature_fraction": 0.6,
        "bagging_fraction": 0.7,
        "bagging_freq": 5,
        "reg_alpha": 0.5,
        "reg_lambda": 0.5,
        "verbose": -1,
    }

    # Use fold 2 (biggest validation set) for sensitivity
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

    # MF3 sensitivity: Corsi features missing from feature_matrix.pkl
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
        print("   Corsi features were derived at strategy-research time but NOT persisted.")
        print("   MF3 strategy is NOT reproducible from the current pkl file.")
        print("   Impact: MF3 results from PROVENSTRATEGIES.md cannot be independently verified")
        print("   without re-deriving Corsi from game_team_stats and re-joining.")

    # MF2 sensitivity: vary gap threshold and days_rest
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

        # Average implied vig
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


def main():
    print("Loading feature matrix...")
    df = load_matrix()

    check1(df)
    check2(df)
    check3(df)
    check4(df)
    check5(df)
    mf3_bets, mf2_bets = check6789(df)
    check10_11(df, mf3_bets, mf2_bets)
    check12_13_14(df, mf3_bets, mf2_bets)

    print("=" * 70)
    print("AUDIT COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
