"""
Diagnose and fix model degradation from league-wide saves/shots decline.

Key finding: saves_avg dropped from 16.4 (2022-23) to 13.6 (2025-26).
Lines dropped from 27.9 to 24.0. Model trained on old data has stale baselines.

Fix: recency-weighted training + seasonal normalization.
"""
import pickle

import lightgbm as lgb
import numpy as np
from sklearn.metrics import mean_absolute_error

# Load feature matrix
fm = pickle.load(open("model/feature_matrix.pkl", "rb"))
fm["season"] = fm["event_date"].apply(
    lambda d: f"{d.year-1}-{str(d.year)[-2:]}" if d.month < 7 else f"{d.year}-{str(d.year+1)[-2:]}"
)

# Target
TARGET = "save_diff"  # saves - line

# Features used in model
FEATURES = [
    "line",
    "saves_avg_5",
    "saves_avg_10",
    "saves_avg_20",
    "saves_season_avg",
    "save_pct",
    "ev_svpct_avg_10",
    "ev_shots_avg_10",
    "ev_svpct_avg_20",
    "ev_shots_avg_20",
]
FEATURES = [f for f in FEATURES if f in fm.columns]

# Drop rows with NaN in features or target
subset = fm.dropna(subset=FEATURES + [TARGET]).copy()
print(f"Total rows: {len(subset)}")
print(f"Features: {FEATURES}")
print()

# ========= APPROACH 1: Baseline (no weighting) =========
print("=" * 60)
print("APPROACH 1: Baseline (no recency weighting)")
print("=" * 60)

# Train on seasons before 2025-26, test on 2025-26
train = subset[subset["season"] != "2025-26"]
test = subset[subset["season"] == "2025-26"]
print(f"Train: {len(train)}, Test: {len(test)}")

model_base = lgb.LGBMRegressor(n_estimators=200, max_depth=6, learning_rate=0.05, verbose=-1)
model_base.fit(train[FEATURES], train[TARGET])
pred_base = model_base.predict(test[FEATURES])
mae_base = mean_absolute_error(test[TARGET], pred_base)
print(f"MAE on 2025-26: {mae_base:.3f}")

# Directional accuracy (predicting over/under correctly)
test_base = test.copy()
test_base["pred_diff"] = pred_base
test_base["pred_over"] = test_base["pred_diff"] > 0
test_base["actual_over"] = test_base[TARGET] > 0
acc_base = (test_base["pred_over"] == test_base["actual_over"]).mean()
print(f"Directional accuracy: {acc_base:.1%}")
print()

# ========= APPROACH 2: Recency-weighted =========
print("=" * 60)
print("APPROACH 2: Recency-weighted (exponential decay)")
print("=" * 60)

# Weight by recency: more recent games get higher weight
max_date = train["event_date"].max()
days_ago = (max_date - train["event_date"]).dt.days
# Half-life of 365 days
weights = np.exp(-days_ago * np.log(2) / 365)
print(f"Weight range: {weights.min():.3f} to {weights.max():.3f}")
print("Mean weight by season:")
for s in sorted(train["season"].unique()):
    mask = train["season"] == s
    print(f"  {s}: {weights[mask].mean():.3f}")

model_rw = lgb.LGBMRegressor(n_estimators=200, max_depth=6, learning_rate=0.05, verbose=-1)
model_rw.fit(train[FEATURES], train[TARGET], sample_weight=weights)
pred_rw = model_rw.predict(test[FEATURES])
mae_rw = mean_absolute_error(test[TARGET], pred_rw)
print(f"MAE on 2025-26: {mae_rw:.3f}")

test_rw = test.copy()
test_rw["pred_diff"] = pred_rw
test_rw["pred_over"] = test_rw["pred_diff"] > 0
test_rw["actual_over"] = test_rw[TARGET] > 0
acc_rw = (test_rw["pred_over"] == test_rw["actual_over"]).mean()
print(f"Directional accuracy: {acc_rw:.1%}")
print()

# ========= APPROACH 3: Recent-only (last 2 seasons) =========
print("=" * 60)
print("APPROACH 3: Recent-only (2024-25 train, 2025-26 test)")
print("=" * 60)

train_recent = subset[subset["season"] == "2024-25"]
print(f"Train: {len(train_recent)}, Test: {len(test)}")

model_rec = lgb.LGBMRegressor(n_estimators=200, max_depth=6, learning_rate=0.05, verbose=-1)
model_rec.fit(train_recent[FEATURES], train_recent[TARGET])
pred_rec = model_rec.predict(test[FEATURES])
mae_rec = mean_absolute_error(test[TARGET], pred_rec)
print(f"MAE on 2025-26: {mae_rec:.3f}")

test_rec = test.copy()
test_rec["pred_diff"] = pred_rec
test_rec["pred_over"] = test_rec["pred_diff"] > 0
test_rec["actual_over"] = test_rec[TARGET] > 0
acc_rec = (test_rec["pred_over"] == test_rec["actual_over"]).mean()
print(f"Directional accuracy: {acc_rec:.1%}")
print()

# ========= APPROACH 4: Normalized features (z-score within rolling window) =========
print("=" * 60)
print("APPROACH 4: Season-normalized features")
print("=" * 60)

# Normalize features within each season
norm_features = []
for feat in FEATURES:
    new_col = f"{feat}_norm"
    subset[new_col] = subset.groupby("season")[feat].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-8)
    )
    norm_features.append(new_col)

train_norm = subset[subset["season"] != "2025-26"]
test_norm = subset[subset["season"] == "2025-26"]

model_norm = lgb.LGBMRegressor(n_estimators=200, max_depth=6, learning_rate=0.05, verbose=-1)
model_norm.fit(train_norm[norm_features], train_norm[TARGET])
pred_norm = model_norm.predict(test_norm[norm_features])
mae_norm = mean_absolute_error(test_norm[TARGET], pred_norm)
print(f"MAE on 2025-26: {mae_norm:.3f}")

test_n = test_norm.copy()
test_n["pred_diff"] = pred_norm
test_n["pred_over"] = test_n["pred_diff"] > 0
test_n["actual_over"] = test_n[TARGET] > 0
acc_norm = (test_n["pred_over"] == test_n["actual_over"]).mean()
print(f"Directional accuracy: {acc_norm:.1%}")
print()

# ========= SUMMARY =========
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"{'Approach':<30} {'MAE':>6} {'Dir Acc':>8}")
print("-" * 46)
print(f"{'1. Baseline':<30} {mae_base:>6.3f} {acc_base:>7.1%}")
print(f"{'2. Recency-weighted':<30} {mae_rw:>6.3f} {acc_rw:>7.1%}")
print(f"{'3. Recent-only (24-25)':<30} {mae_rec:>6.3f} {acc_rec:>7.1%}")
print(f"{'4. Season-normalized':<30} {mae_norm:>6.3f} {acc_norm:>7.1%}")

# ========= BEST MODEL: Simulate betting P&L =========
print()
print("=" * 60)
print("BETTING SIMULATION (best approach on 2025-26)")
print("=" * 60)

# Use the best model for EV calculation
approaches = {
    "Baseline": (pred_base, test_base),
    "Recency-weighted": (pred_rw, test_rw),
    "Recent-only": (pred_rec, test_rec),
    "Season-normalized": (pred_norm, test_n),
}

for name, (preds, tdf) in approaches.items():
    tdf = tdf.copy()
    tdf["pred_diff"] = preds
    # Simple strategy: bet over when pred_diff > threshold
    for thresh in [0.5, 1.0, 1.5]:
        over_bets = tdf[tdf["pred_diff"] > thresh]
        if len(over_bets) == 0:
            continue
        wins = over_bets["went_over"].sum()
        total = len(over_bets)
        # Flat unit betting, approximate -110 odds
        pl = wins * (100 / 110) - (total - wins)
        roi = pl / total * 100 if total > 0 else 0
        print(f"  {name} (over, thresh={thresh}): {total} bets, {wins}/{total} wins ({wins/total:.1%}), ROI: {roi:+.1f}%, P&L: {pl:+.1f}u")
