"""
Multi-point (2+) game prediction model for OVER 1.5 points props.
Walk-forward: train on pre-2025-10, test on 2025-26 season.
"""
import subprocess
import sys
from io import StringIO

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

PSQL = '/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql'
DB = 'nhl_betting'

def query(sql):
    r = subprocess.run([PSQL, '-d', DB, '-c', f"COPY ({sql}) TO STDOUT WITH CSV HEADER"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"SQL Error: {r.stderr}", file=sys.stderr)
        return pd.DataFrame()
    return pd.read_csv(StringIO(r.stdout))

# === LOAD DATA ===
print("Loading player stats...")
df = query("""
    SELECT ps.game_id, ps.player_id, ps.team_id, ps.is_home, ps.position_code,
           ps.toi_minutes, ps.goals, ps.assists, ps.points, ps.shots, ps.power_play_goals,
           s.game_date, s.away_team_id, s.home_team_id
    FROM player_stats ps
    JOIN schedules s ON ps.game_id = s.game_id
    WHERE ps.toi_minutes > 0 AND ps.position_code IN ('C','L','R','D')
    ORDER BY ps.player_id, s.game_date
""")
df['game_date'] = pd.to_datetime(df['game_date'])
df['multi_point'] = (df['points'] >= 2).astype(int)
df['opp_team_id'] = np.where(df['team_id'] == df['home_team_id'], df['away_team_id'], df['home_team_id'])
print(f"  {len(df)} rows, {df['player_id'].nunique()} players, MP rate: {df['multi_point'].mean()*100:.1f}%")

# === ROLLING FEATURES (manual loop to avoid groupby column drop) ===
print("Computing rolling features...")
parts = []
for pid, grp in df.groupby('player_id'):
    g = grp.sort_values('game_date').copy()
    for w in [5, 10, 20]:
        g[f'pts_avg_{w}'] = g['points'].shift(1).rolling(w, min_periods=3).mean()
        g[f'shots_avg_{w}'] = g['shots'].shift(1).rolling(w, min_periods=3).mean()
        g[f'toi_avg_{w}'] = g['toi_minutes'].shift(1).rolling(w, min_periods=3).mean()
        g[f'mp_pct_{w}'] = g['multi_point'].shift(1).rolling(w, min_periods=3).mean()
        g[f'ppg_avg_{w}'] = g['power_play_goals'].shift(1).rolling(w, min_periods=3).mean()
    g['goals_avg_10'] = g['goals'].shift(1).rolling(10, min_periods=3).mean()
    g['assists_avg_10'] = g['assists'].shift(1).rolling(10, min_periods=3).mean()
    g['season_pts_avg'] = g['points'].shift(1).expanding(min_periods=5).mean()
    g['season_mp_pct'] = g['multi_point'].shift(1).expanding(min_periods=5).mean()
    g['pts_last_3'] = g['points'].shift(1).rolling(3, min_periods=1).sum()
    g['pts_last_1'] = g['points'].shift(1)
    g['blanks_last_5'] = (g['points'].shift(1) == 0).rolling(5, min_periods=1).sum()
    g['days_rest'] = g['game_date'].diff().dt.days.clip(0, 10)
    parts.append(g)
df = pd.concat(parts)
print(f"  Rolling done. Columns: {len(df.columns)}")

# === OPPONENT FEATURES ===
print("Computing opponent features...")
opp_raw = query("""
    SELECT gts.game_id, gts.team_id as opp_tid,
           (SELECT gts2.score FROM game_team_stats gts2
            WHERE gts2.game_id = gts.game_id AND gts2.team_id != gts.team_id LIMIT 1) as goals_against
    FROM game_team_stats gts
""")
gdates = df[['game_id','game_date']].drop_duplicates(subset='game_id')
opp_raw = opp_raw.merge(gdates, on='game_id', how='inner').sort_values(['opp_tid','game_date'])

opp_parts = []
for tid, grp in opp_raw.groupby('opp_tid'):
    g = grp.sort_values('game_date').copy()
    g['opp_ga_avg_10'] = g['goals_against'].shift(1).rolling(10, min_periods=3).mean()
    opp_parts.append(g[['opp_tid','game_date','opp_ga_avg_10']])
opp_agg = pd.concat(opp_parts).drop_duplicates(subset=['opp_tid','game_date'], keep='last')
df = df.merge(opp_agg, left_on=['opp_team_id','game_date'], right_on=['opp_tid','game_date'], how='left')

# === PP FEATURES ===
print("Computing PP features...")
pp = query("SELECT player_id as pp_pid, game_id as pp_gid, pp_toi_seconds, pp_points FROM player_pp_stats")
pp['pp_toi_min'] = pp['pp_toi_seconds'] / 60.0
pgd = df[['player_id','game_id','game_date']].drop_duplicates(subset=['player_id','game_id'])
pp = pp.merge(pgd, left_on=['pp_pid','pp_gid'], right_on=['player_id','game_id'], how='inner')
pp = pp.sort_values(['pp_pid','game_date'])

pp_parts = []
for pid, grp in pp.groupby('pp_pid'):
    g = grp.sort_values('game_date').copy()
    g['pp_toi_avg_10'] = g['pp_toi_min'].shift(1).rolling(10, min_periods=3).mean()
    g['pp_pts_avg_10'] = g['pp_points'].shift(1).rolling(10, min_periods=3).mean()
    pp_parts.append(g[['player_id','game_id','pp_toi_avg_10','pp_pts_avg_10']])
pp_agg = pd.concat(pp_parts)
df = df.merge(pp_agg, on=['player_id','game_id'], how='left')

df['is_forward'] = df['position_code'].isin(['C','L','R']).astype(int)

# === FEATURES ===
FEATURES = [
    'pts_avg_5', 'pts_avg_10', 'pts_avg_20',
    'goals_avg_10', 'assists_avg_10', 'shots_avg_10', 'toi_avg_10',
    'mp_pct_5', 'mp_pct_10', 'mp_pct_20',
    'ppg_avg_10', 'season_pts_avg', 'season_mp_pct',
    'pts_last_3', 'pts_last_1', 'blanks_last_5',
    'is_home', 'is_forward', 'days_rest',
    'opp_ga_avg_10', 'pp_toi_avg_10', 'pp_pts_avg_10',
]

valid = df.dropna(subset=FEATURES + ['multi_point'])
print(f"Valid rows: {len(valid)}, Features: {len(FEATURES)}")

# === SPLIT ===
train = valid[valid['game_date'] < '2025-10-01']
test = valid[valid['game_date'] >= '2025-10-01']
print(f"Train: {len(train)} ({train['game_date'].min().date()} to {train['game_date'].max().date()})")
print(f"Test:  {len(test)} ({test['game_date'].min().date()} to {test['game_date'].max().date()})")
print(f"Train MP: {train['multi_point'].mean()*100:.1f}%, Test MP: {test['multi_point'].mean()*100:.1f}%")

# === TRAIN ===
print("\nTraining LightGBM classifier...")
model = lgb.LGBMClassifier(
    objective='binary', num_leaves=15, max_depth=5,
    min_child_samples=100, learning_rate=0.05, n_estimators=300,
    reg_alpha=0.5, reg_lambda=0.5, feature_fraction=0.7,
    bagging_fraction=0.7, bagging_freq=5, verbose=-1, is_unbalance=True
)
model.fit(train[FEATURES], train['multi_point'])

test_probs = model.predict_proba(test[FEATURES])[:, 1]
auc = roc_auc_score(test['multi_point'], test_probs)
print(f"Test AUC: {auc:.4f}")

# === FEATURE IMPORTANCE ===
imp = pd.Series(model.feature_importances_, index=FEATURES).sort_values(ascending=False)
print("\n=== TOP FEATURES ===")
for f, v in imp.head(15).items():
    print(f"  {f}: {v}")

# === ROI SIMULATION ===
print("\n=== ROI SIMULATION ===")
print("Assuming +225 average odds (breakeven = 30.8%)")
for thresh in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
    mask = test_probs >= thresh
    if mask.sum() < 5:
        continue
    bets = int(mask.sum())
    wins = int(test['multi_point'][mask].sum())
    win_rate = wins / bets
    profit = wins * 2.25 - (bets - wins) * 1.0
    roi = profit / bets * 100
    print(f"  P >= {thresh:.0%}: {bets:>5} bets, {wins:>4} wins, {win_rate:.1%} WR, ROI: {roi:+.1f}%")

# === CALIBRATION ===
print("\n=== CALIBRATION ===")
for lo, hi in [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 1.0)]:
    mask = (test_probs >= lo) & (test_probs < hi)
    if mask.sum() < 10:
        continue
    actual = test['multi_point'][mask].mean()
    predicted = test_probs[mask].mean()
    n = int(mask.sum())
    print(f"  Pred {lo:.0%}-{hi:.0%}: n={n:>5}, actual={actual:.1%}, predicted={predicted:.1%}")

# === SAVE ===
imp.to_csv('model/points_15_feature_importance.csv')
test_out = test[['player_id','game_id','game_date','team_id','points','multi_point']].copy()
test_out['model_prob'] = test_probs
test_out.to_csv('model/points_15_test_predictions.csv', index=False)
print("\nSaved to model/points_15_*.csv")

print("\n=== DATA ENHANCEMENT RECOMMENDATIONS (for V2) ===")
print("1. Vegas game total (O/U) — high-total games = more multi-point performances")
print("2. PP1 vs PP2 unit assignment — PP1 players get 2x opportunity")
print("3. Opponent PK% (rolling 10g) — weak PKs boost PP point upside")
print("4. Player-level xG/xA (NaturalStatTrick) — quality-adjusted production")
print("5. Line combination stability — consistent linemates = chemistry")
print("6. Score state / game script — trailing teams generate more offense")
