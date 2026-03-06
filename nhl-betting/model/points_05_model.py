"""
OVER 0.5 points prediction model.
Predicts probability of a player recording 1+ points in a game.
Uses same feature set as V2 1.5 model but different target.
"""
import json
import pickle
import subprocess
from io import StringIO

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

PSQL = "/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql"
DB = "nhl_betting"


def query(sql):
    r = subprocess.run(
        [PSQL, "-d", DB, "-c", f"COPY ({sql}) TO STDOUT WITH CSV HEADER"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return pd.DataFrame()
    return pd.read_csv(StringIO(r.stdout))


# === LOAD DATA ===
print("Loading player stats...")
df = query("""
    SELECT ps.game_id, ps.player_id, ps.team_id, ps.is_home, ps.position_code,
           ps.toi_minutes, ps.goals, ps.assists, ps.points, ps.shots,
           ps.power_play_goals, ps.power_play_points,
           g.game_date, g.away_team_id, g.home_team_id
    FROM player_stats ps
    JOIN games g ON ps.game_id = g.game_id
    WHERE ps.toi_minutes > 0 AND ps.position_code IN ('C','L','R','D')
    ORDER BY ps.player_id, g.game_date
""")
df["game_date"] = pd.to_datetime(df["game_date"])
df["has_point"] = (df["points"] >= 1).astype(int)
df["multi_point"] = (df["points"] >= 2).astype(int)
df["opp_team_id"] = np.where(
    df["team_id"] == df["home_team_id"], df["away_team_id"], df["home_team_id"]
)
print(f"  {len(df)} rows, {df['player_id'].nunique()} players")
print(f"  1+ point rate: {df['has_point'].mean()*100:.1f}%")

# === ROLLING FEATURES ===
print("Computing rolling features...")
parts = []
for pid, grp in df.groupby("player_id"):
    g = grp.sort_values("game_date").copy()
    for w in [5, 10, 20]:
        g[f"pts_avg_{w}"] = g["points"].shift(1).rolling(w, min_periods=3).mean()
        g[f"shots_avg_{w}"] = g["shots"].shift(1).rolling(w, min_periods=3).mean()
        g[f"toi_avg_{w}"] = g["toi_minutes"].shift(1).rolling(w, min_periods=3).mean()
        g[f"point_pct_{w}"] = g["has_point"].shift(1).rolling(w, min_periods=3).mean()
        g[f"ppg_avg_{w}"] = g["power_play_goals"].shift(1).rolling(w, min_periods=3).mean()
        g[f"ppp_avg_{w}"] = g["power_play_points"].shift(1).rolling(w, min_periods=3).mean()
    g["goals_avg_10"] = g["goals"].shift(1).rolling(10, min_periods=3).mean()
    g["assists_avg_10"] = g["assists"].shift(1).rolling(10, min_periods=3).mean()
    g["season_pts_avg"] = g["points"].shift(1).expanding(min_periods=5).mean()
    g["season_point_pct"] = g["has_point"].shift(1).expanding(min_periods=5).mean()
    g["prev_game_score"] = g["points"].shift(1)
    parts.append(g)
df = pd.concat(parts)

# === OPPONENT FEATURES ===
print("Computing opponent features...")
opp_ga = []
for tid, grp in df.groupby("opp_team_id"):
    g = grp.sort_values("game_date").drop_duplicates("game_id").copy()
    g["opp_ga_avg_10"] = g["points"].shift(1).rolling(10, min_periods=3).mean()
    opp_ga.append(g[["game_id", "opp_team_id", "opp_ga_avg_10"]])
opp_df = pd.concat(opp_ga).drop_duplicates(["game_id", "opp_team_id"])
df = df.merge(opp_df, on=["game_id", "opp_team_id"], how="left", suffixes=("", "_opp"))

# Opponent PK%
print("Computing opponent PK%...")
pk = query("""
    SELECT game_id, team_id,
           CASE WHEN power_play_opportunities > 0
                THEN 1.0 - (power_play_goals::float / power_play_opportunities)
                ELSE NULL END as pk_pct
    FROM game_team_stats
    WHERE power_play_opportunities IS NOT NULL
""")
if not pk.empty:
    pk_rolling = []
    for tid, grp in pk.groupby("team_id"):
        g = grp.sort_values("game_id").copy()
        g["opp_pk_pct_10"] = g["pk_pct"].shift(1).rolling(10, min_periods=3).mean()
        pk_rolling.append(g[["game_id", "team_id", "opp_pk_pct_10"]])
    pk_df = pd.concat(pk_rolling)
    df = df.merge(
        pk_df, left_on=["game_id", "opp_team_id"],
        right_on=["game_id", "team_id"], how="left", suffixes=("", "_pk")
    )

# Days rest
df = df.sort_values(["player_id", "game_date"])
df["days_rest"] = df.groupby("player_id")["game_date"].diff().dt.days.clip(1, 7)

# === FEATURES ===
FEATURES = [
    "toi_avg_10", "toi_avg_20", "pts_avg_5", "pts_avg_10", "pts_avg_20",
    "shots_avg_10", "shots_avg_20", "point_pct_5", "point_pct_10", "point_pct_20",
    "ppg_avg_10", "ppp_avg_10", "goals_avg_10", "assists_avg_10",
    "season_pts_avg", "season_point_pct", "prev_game_score",
    "opp_ga_avg_10", "is_home", "days_rest",
]
if "opp_pk_pct_10" in df.columns and df["opp_pk_pct_10"].notna().mean() > 0.5:
    FEATURES.append("opp_pk_pct_10")

# Fill NaN features with median instead of dropping
for f in FEATURES:
    if f in df.columns:
        df[f] = df[f].fillna(df[f].median())
df_valid = df.dropna(subset=["has_point"])
print(f"Valid rows: {len(df_valid)}")

# Time-based split
split_date = df_valid["game_date"].quantile(0.8)
train = df_valid[df_valid["game_date"] < split_date]
test = df_valid[df_valid["game_date"] >= split_date]
print(f"Train: {len(train)}, Test: {len(test)}")

# === TRAIN ===
print("\nTraining OVER 0.5 model...")
params = dict(
    objective="binary", num_leaves=20, max_depth=5,
    min_child_samples=100, learning_rate=0.05, n_estimators=300,
    reg_alpha=0.5, reg_lambda=0.5, feature_fraction=0.7,
    bagging_fraction=0.7, bagging_freq=5, verbose=-1,
)
model = lgb.LGBMClassifier(**params)
model.fit(train[FEATURES], train["has_point"])

raw_probs = model.predict_proba(test[FEATURES])[:, 1]
auc = roc_auc_score(test["has_point"], raw_probs)
brier_raw = brier_score_loss(test["has_point"], raw_probs)
print(f"AUC: {auc:.4f}")
print(f"Raw Brier: {brier_raw:.5f}")
print(f"Raw mean pred: {raw_probs.mean():.3f} (actual: {test['has_point'].mean():.3f})")

# === CALIBRATE ===
print("\nCalibrating with isotonic regression...")
n_cal = int(len(test) * 0.5)
cal_true = test["has_point"].values[:n_cal]
cal_raw = raw_probs[:n_cal]
val_true = test["has_point"].values[n_cal:]
val_raw = raw_probs[n_cal:]

iso = IsotonicRegression(out_of_bounds="clip")
iso.fit(cal_raw, cal_true)
val_cal = iso.predict(val_raw)

brier_cal = brier_score_loss(val_true, val_cal)
print(f"Calibrated Brier: {brier_cal:.5f} (was {brier_raw:.5f})")
print(f"Cal mean pred: {val_cal.mean():.3f} (actual: {val_true.mean():.3f})")

# Calibration bins
print(f"\n{'Bin':>12} {'Predicted':>10} {'Actual':>10} {'Count':>8}")
bins = np.linspace(0, 1, 11)
for i in range(10):
    mask = (val_cal >= bins[i]) & (val_cal < bins[i + 1])
    if mask.sum() > 10:
        print(f"  {bins[i]:.1f}-{bins[i+1]:.1f} {val_cal[mask].mean():>10.3f} {val_true[mask].mean():>10.3f} {mask.sum():>8}")

# Feature importance
imp = pd.Series(model.feature_importances_, index=FEATURES).sort_values(ascending=False)
print("\nTOP FEATURES:")
for f, v in imp.head(15).items():
    print(f"  {f}: {v}")

# === SAVE ===
pickle.dump(model, open("model/points_05_lgbm.pkl", "wb"))
pickle.dump(iso, open("model/points_05_calibrator.pkl", "wb"))
json.dump(FEATURES, open("model/points_05_features.json", "w"))

test_out = test[["player_id", "game_id", "game_date", "team_id", "points", "has_point"]].copy()
test_out["model_prob"] = raw_probs
test_out["cal_prob"] = iso.predict(raw_probs)
test_out.to_csv("model/points_05_test_predictions.csv", index=False)
imp.to_csv("model/points_05_feature_importance.csv")

print("\nSaved model, calibrator, features, predictions.")
