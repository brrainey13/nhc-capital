"""
V2 Multi-point (2+) game prediction model for OVER 1.5 points props.
Adds: opponent PK%, game totals, player xG season stats.
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
        print(f"SQL Error: {r.stderr[:300]}", file=sys.stderr)
        return pd.DataFrame()
    return pd.read_csv(StringIO(r.stdout))

# === LOAD BASE DATA ===
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
print(f"  {len(df)} rows, {df['player_id'].nunique()} players, MP: {df['multi_point'].mean()*100:.1f}%")

# === V1 ROLLING FEATURES ===
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

# === V1 OPP DEFENSIVE QUALITY ===
print("Computing opponent GA...")
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

# === V1 PP FEATURES ===
print("Computing PP features...")
pp = query("SELECT player_id as pp_pid, game_id as pp_gid, pp_toi_seconds, pp_points FROM player_pp_stats")
pp['pp_toi_min'] = pp['pp_toi_seconds'] / 60.0
pgd = df[['player_id','game_id','game_date']].drop_duplicates(subset=['player_id','game_id'])
pp = pp.merge(pgd, left_on=['pp_pid','pp_gid'], right_on=['player_id','game_id'], how='inner')
pp_parts = []
for pid, grp in pp.groupby('pp_pid'):
    g = grp.sort_values('game_date').copy()
    g['pp_toi_avg_10'] = g['pp_toi_min'].shift(1).rolling(10, min_periods=3).mean()
    g['pp_pts_avg_10'] = g['pp_points'].shift(1).rolling(10, min_periods=3).mean()
    pp_parts.append(g[['player_id','game_id','pp_toi_avg_10','pp_pts_avg_10']])
pp_agg = pd.concat(pp_parts)
df = df.merge(pp_agg, on=['player_id','game_id'], how='left')

df['is_forward'] = df['position_code'].isin(['C','L','R']).astype(int)

# =========================================
# === V2 NEW FEATURES ===
# =========================================

# === V2.1: OPPONENT PK% (rolling 10-game) ===
print("V2: Computing opponent PK%...")
pk = query("SELECT team_id as pk_tid, game_date as pk_date, pk_pct, times_shorthanded, pk_goals_against FROM team_pk_stats")
pk['pk_date'] = pd.to_datetime(pk['pk_date'])
pk = pk.sort_values(['pk_tid','pk_date'])
pk_parts = []
for tid, grp in pk.groupby('pk_tid'):
    g = grp.sort_values('pk_date').copy()
    g['opp_pk_pct_10'] = g['pk_pct'].shift(1).rolling(10, min_periods=3).mean()
    g['opp_ppga_10'] = g['pk_goals_against'].shift(1).rolling(10, min_periods=3).mean()
    pk_parts.append(g[['pk_tid','pk_date','opp_pk_pct_10','opp_ppga_10']])
pk_agg = pd.concat(pk_parts).drop_duplicates(subset=['pk_tid','pk_date'], keep='last')
df = df.merge(pk_agg, left_on=['opp_team_id','game_date'], right_on=['pk_tid','pk_date'], how='left')
print(f"  opp_pk_pct_10 coverage: {df['opp_pk_pct_10'].notna().mean()*100:.1f}%")

# === V2.2: GAME TOTALS (proxy for Vegas O/U) ===
print("V2: Computing game total features...")
# MoneyPuck game_totals uses its own game IDs. Match via date + teams.
gt = query("""
    SELECT game_date, home_team, away_team, total_goals,
           xgoals_for_home + xgoals_for_away as expected_total
    FROM game_totals
""")
gt['game_date'] = pd.to_datetime(gt['game_date'])

# We need team tri_code mapping. Get from teams table.
teams_map = query("SELECT team_id, tri_code FROM teams")
tri_to_id = dict(zip(teams_map['tri_code'], teams_map['team_id']))

# For each team, compute rolling average game totals
# First, create a team-game view from game_totals
gt_team_rows = []
for _, row in gt.iterrows():
    ht = tri_to_id.get(row['home_team'])
    at = tri_to_id.get(row['away_team'])
    if ht:
        gt_team_rows.append({'team_id': ht, 'game_date': row['game_date'], 'game_total': row['total_goals'], 'xg_total': row['expected_total']})
    if at:
        gt_team_rows.append({'team_id': at, 'game_date': row['game_date'], 'game_total': row['total_goals'], 'xg_total': row['expected_total']})
gt_team = pd.DataFrame(gt_team_rows)
gt_team = gt_team.sort_values(['team_id','game_date'])

gt_parts = []
for tid, grp in gt_team.groupby('team_id'):
    g = grp.sort_values('game_date').copy()
    g['team_game_total_10'] = g['game_total'].shift(1).rolling(10, min_periods=3).mean()
    g['team_xg_total_10'] = g['xg_total'].shift(1).rolling(10, min_periods=3).mean()
    gt_parts.append(g[['team_id','game_date','team_game_total_10','team_xg_total_10']])
gt_agg = pd.concat(gt_parts).drop_duplicates(subset=['team_id','game_date'], keep='last')

# Merge for player's team game total tendency
df = df.merge(gt_agg, on=['team_id','game_date'], how='left')
# Also merge opponent's game total tendency
gt_agg_opp = gt_agg.rename(columns={'team_id':'opp_team_id','team_game_total_10':'opp_game_total_10','team_xg_total_10':'opp_xg_total_10'})
df = df.merge(gt_agg_opp, on=['opp_team_id','game_date'], how='left')
# Combined game environment
df['combined_game_total_10'] = (df['team_game_total_10'].fillna(0) + df['opp_game_total_10'].fillna(0)) / 2
print(f"  game_total coverage: {df['team_game_total_10'].notna().mean()*100:.1f}%")

# === V2.3: PLAYER XG SEASON STATS ===
print("V2: Merging player xG season data...")
xg = query("SELECT player_mp_id, season, xgoals, high_danger_xgoals, game_score, on_ice_xgoals_pct, on_ice_corsi_pct, games_played FROM player_xg_season")
# Need to map MoneyPuck player IDs to our player IDs
# MoneyPuck uses NHL API player IDs which should match our player_id
xg = xg.rename(columns={'player_mp_id': 'player_id'})

# Map season year to game_date range
# season 2023 = 2022-10 to 2023-06, season 2024 = 2023-10 to 2024-06, etc.
def season_to_date_range(season):
    return (f'{season-1}-10-01', f'{season}-06-30')

# Per-game rates
xg['xg_per_game'] = xg['xgoals'] / xg['games_played'].clip(lower=1)
xg['hdxg_per_game'] = xg['high_danger_xgoals'] / xg['games_played'].clip(lower=1)

# For each row in df, look up the PREVIOUS season's xG stats (to avoid leakage)
df['season_year'] = df['game_date'].dt.year
df.loc[df['game_date'].dt.month >= 10, 'season_year'] = df.loc[df['game_date'].dt.month >= 10, 'game_date'].dt.year + 1

# Previous season = season_year - 1 maps to MoneyPuck season = season_year - 1
xg_prev = xg.rename(columns={
    'xg_per_game': 'prev_xg_per_game',
    'hdxg_per_game': 'prev_hdxg_per_game',
    'game_score': 'prev_game_score',
    'on_ice_xgoals_pct': 'prev_oixg_pct',
    'on_ice_corsi_pct': 'prev_oicorsi_pct',
})
xg_prev['season_year'] = xg_prev['season'] + 1  # Match to next season's games
df = df.merge(xg_prev[['player_id','season_year','prev_xg_per_game','prev_hdxg_per_game',
                        'prev_game_score','prev_oixg_pct','prev_oicorsi_pct']],
              on=['player_id','season_year'], how='left')
print(f"  prev_xg coverage: {df['prev_xg_per_game'].notna().mean()*100:.1f}%")

# =========================================
# === FEATURE LISTS ===
# =========================================
V1_FEATURES = [
    'pts_avg_5', 'pts_avg_10', 'pts_avg_20',
    'goals_avg_10', 'assists_avg_10', 'shots_avg_10', 'toi_avg_10',
    'mp_pct_5', 'mp_pct_10', 'mp_pct_20',
    'ppg_avg_10', 'season_pts_avg', 'season_mp_pct',
    'pts_last_3', 'pts_last_1', 'blanks_last_5',
    'is_home', 'is_forward', 'days_rest',
    'opp_ga_avg_10', 'pp_toi_avg_10', 'pp_pts_avg_10',
]

V2_FEATURES = V1_FEATURES + [
    'opp_pk_pct_10', 'opp_ppga_10',          # Opponent PK weakness
    'team_game_total_10', 'opp_game_total_10', 'combined_game_total_10',  # Game environment
    'prev_xg_per_game', 'prev_hdxg_per_game', 'prev_game_score',         # Player quality (xG)
    'prev_oixg_pct', 'prev_oicorsi_pct',                                  # On-ice impact
]

# === TRAIN/TEST ===
valid_v1 = df.dropna(subset=V1_FEATURES + ['multi_point'])
valid_v2 = df.dropna(subset=V2_FEATURES + ['multi_point'])

print(f"\nV1 valid: {len(valid_v1)}, V2 valid: {len(valid_v2)}")

# Use same test set for fair comparison
train_v1 = valid_v1[valid_v1['game_date'] < '2025-10-01']
test_v1 = valid_v1[valid_v1['game_date'] >= '2025-10-01']
train_v2 = valid_v2[valid_v2['game_date'] < '2025-10-01']
test_v2 = valid_v2[valid_v2['game_date'] >= '2025-10-01']

print(f"V1 Train: {len(train_v1)}, Test: {len(test_v1)}")
print(f"V2 Train: {len(train_v2)}, Test: {len(test_v2)}")

# === TRAIN BOTH MODELS ===
params = dict(
    objective='binary', num_leaves=15, max_depth=5,
    min_child_samples=100, learning_rate=0.05, n_estimators=300,
    reg_alpha=0.5, reg_lambda=0.5, feature_fraction=0.7,
    bagging_fraction=0.7, bagging_freq=5, verbose=-1, is_unbalance=True
)

print("\nTraining V1...")
mdl_v1 = lgb.LGBMClassifier(**params)
mdl_v1.fit(train_v1[V1_FEATURES], train_v1['multi_point'])
v1_probs = mdl_v1.predict_proba(test_v1[V1_FEATURES])[:, 1]
v1_auc = roc_auc_score(test_v1['multi_point'], v1_probs)

print("Training V2...")
mdl_v2 = lgb.LGBMClassifier(**params)
mdl_v2.fit(train_v2[V2_FEATURES], train_v2['multi_point'])
v2_probs = mdl_v2.predict_proba(test_v2[V2_FEATURES])[:, 1]
v2_auc = roc_auc_score(test_v2['multi_point'], v2_probs)

print(f"\n{'='*60}")
print(f"V1 AUC: {v1_auc:.4f}")
print(f"V2 AUC: {v2_auc:.4f}")
print(f"Lift:   {(v2_auc - v1_auc)*100:+.2f} bps")
print(f"{'='*60}")

# === V2 FEATURE IMPORTANCE ===
imp = pd.Series(mdl_v2.feature_importances_, index=V2_FEATURES).sort_values(ascending=False)
print("\nV2 TOP FEATURES:")
for f, v in imp.head(20).items():
    new = " ← NEW" if f not in V1_FEATURES else ""
    print(f"  {f}: {v}{new}")

# === ROI COMPARISON ===
print(f"\n{'='*60}")
print("ROI SIMULATION (V1 vs V2 at +225 avg, BE=30.8%)")
print(f"{'='*60}")

for label, probs, test_data in [("V1", v1_probs, test_v1), ("V2", v2_probs, test_v2)]:
    print(f"\n--- {label} ---")
    for thresh in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        mask = probs >= thresh
        if mask.sum() < 10:
            continue
        b = int(mask.sum())
        w = int(test_data['multi_point'][mask].sum())
        roi = (w*2.25-(b-w))/b*100
        print(f"  P>={thresh:.0%}: {b:>5} bets, {w:>4} wins, {w/b:.1%} WR, ROI:{roi:+.1f}%")

# === HYBRID STRATEGY (V2) ===
print(f"\n{'='*60}")
print("V2 HYBRID STRATEGY (model + hit rate)")
print(f"{'='*60}")

# Compute per-player hit rate from test data
player_rates = test_v2.groupby('player_id').agg(
    games=('multi_point','count'),
    mp_rate=('multi_point','mean')
).reset_index()
test_v2_rated = test_v2.merge(player_rates[['player_id','mp_rate']], on='player_id', suffixes=('','_szn'))

for min_rate in [0.25, 0.30, 0.35, 0.40]:
    for min_prob in [0.25, 0.30, 0.40]:
        mask = (v2_probs >= min_prob) & (test_v2_rated['mp_rate'] >= min_rate)
        if mask.sum() < 20:
            continue
        b = int(mask.sum())
        w = int(test_v2_rated['multi_point'][mask].sum())
        roi = (w*2.25-(b-w))/b*100
        print(f"  P>={min_prob:.0%} + rate>={min_rate:.0%}: {b:>5} bets, {w:>4} wins, {w/b:.1%} WR, ROI:{roi:+.1f}%")

# === CALIBRATION V2 ===
print("\nV2 CALIBRATION:")
for lo, hi in [(0,0.1),(0.1,0.2),(0.2,0.3),(0.3,0.4),(0.4,0.5),(0.5,1.0)]:
    mask = (v2_probs >= lo) & (v2_probs < hi)
    if mask.sum() < 10:
            continue
    actual = test_v2['multi_point'][mask].mean()
    pred = v2_probs[mask].mean()
    print(f"  {lo:.0%}-{hi:.0%}: n={int(mask.sum()):>5}, actual={actual:.1%}, pred={pred:.1%}")

# === SAVE ===
imp.to_csv('model/points_15_v2_feature_importance.csv')
test_out = test_v2[['player_id','game_id','game_date','team_id','points','multi_point']].copy()
test_out['model_prob'] = v2_probs
test_out.to_csv('model/points_15_v2_test_predictions.csv', index=False)

# Save trained V2 model + feature list for live inference
import json
import pickle

pickle.dump(mdl_v2, open('model/points_15_v2_lgbm.pkl', 'wb'))
json.dump(V2_FEATURES, open('model/points_15_v2_features.json', 'w'))
print(f"\nSaved V2 model: model/points_15_v2_lgbm.pkl ({len(V2_FEATURES)} features)")
print("Saved V2 outputs.")
