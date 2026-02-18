#!/usr/bin/env python3
"""Steps 6-7: Line efficiency + feature importance for SOG model."""
import warnings

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402
from sklearn.metrics import mean_absolute_error  # noqa: E402

warnings.filterwarnings('ignore')

DB = "postgresql://connorrainey@localhost:5432/nhl_betting"
conn = psycopg2.connect(DB)

# Load data
ps = pd.read_sql("SELECT * FROM player_stats WHERE position_code IN ('C','L','R','D')", conn)
games = pd.read_sql("""SELECT game_id, game_date, home_team_id, away_team_id, season
    FROM games WHERE home_score IS NOT NULL AND game_type IN (2,3) AND game_state='OFF'""", conn)
sog_odds = pd.read_sql("SELECT * FROM sog_odds WHERE book_name='consensus'", conn)
la = pd.read_sql("SELECT * FROM lineup_absences", conn)
teams = pd.read_sql("SELECT team_id, tri_code FROM teams", conn)
gts = pd.read_sql("SELECT * FROM game_team_stats", conn)
conn.close()

teams_map = teams.set_index('team_id')['tri_code'].to_dict()
# Reverse map: tri_code -> team_id (handle sog_odds team abbreviations)
tri_to_id = teams.set_index('tri_code')['team_id'].to_dict()

ps = ps.merge(games[['game_id','game_date','home_team_id','away_team_id']], on='game_id', how='inner')
ps = ps.sort_values(['player_id','game_date'])

# Build rolling features
for w in [5, 10, 20]:
    ps[f'sog_avg_{w}'] = ps.groupby('player_id')['shots'].transform(
        lambda x: x.rolling(w, min_periods=max(3,w//2)).mean().shift(1))
    ps[f'toi_avg_{w}'] = ps.groupby('player_id')['toi_minutes'].transform(
        lambda x: x.rolling(w, min_periods=max(3,w//2)).mean().shift(1))

# Opponent defense rolling
gts_m = gts.merge(games[['game_id','game_date','home_team_id','away_team_id']], on='game_id', how='inner')
gts_m['opp_team_id'] = np.where(gts_m['team_id']==gts_m['home_team_id'], gts_m['away_team_id'], gts_m['home_team_id'])
opp_sog = gts[['game_id','team_id','shots_on_goal']].rename(columns={'team_id':'opp_team_id','shots_on_goal':'opp_sog_in_game'})
gts_m = gts_m.merge(opp_sog, on=['game_id','opp_team_id'], how='left')
opp_def = gts_m[['game_id','game_date','team_id','opp_sog_in_game']].rename(columns={'team_id':'def_team_id','opp_sog_in_game':'sog_allowed'})
opp_def = opp_def.sort_values(['def_team_id','game_date'])
opp_def_r = []
for tid, g in opp_def.groupby('def_team_id'):
    g = g.copy().sort_values('game_date')
    g['sog_allowed_avg_10'] = g['sog_allowed'].rolling(10, min_periods=5).mean().shift(1)
    opp_def_r.append(g)
opp_def_r = pd.concat(opp_def_r, ignore_index=True)

ps['opponent_team_id'] = np.where(ps['team_id']==ps['home_team_id'], ps['away_team_id'], ps['home_team_id'])
ps = ps.merge(opp_def_r[['game_id','def_team_id','sog_allowed_avg_10']],
              left_on=['game_id','opponent_team_id'], right_on=['game_id','def_team_id'], how='left')
ps = ps.merge(la[['game_id','team_id','fwd_missing_toi','def_missing_toi','total_missing_toi']],
              on=['game_id','team_id'], how='left')

ps['pos_is_D'] = (ps['position_code']=='D').astype(int)
ps['pos_is_C'] = (ps['position_code']=='C').astype(int)

# ============================================================
# STEP 6: Match sog_odds to player_stats
# ============================================================
print("=" * 70)
print("  STEP 6: LINE EFFICIENCY (sog_odds vs actual)")
print("=" * 70)

# sog_odds uses different team abbreviations — normalize
team_alias = {'NJ':'NJD','TB':'TBL','LA':'LAK','SJ':'SJS','WAS':'WSH','LV':'VGK',
              'NY':'NYR','NYI':'NYI','NYR':'NYR','WSH':'WSH','VGK':'VGK','SJS':'SJS',
              'NJD':'NJD','TBL':'TBL','LAK':'LAK'}
# Map sog_odds player_team -> team_id
sog_odds['team_id_mapped'] = sog_odds['player_team'].map(lambda x: tri_to_id.get(x) or tri_to_id.get(team_alias.get(x, x)))

# Normalize position: sog_odds has C, LW, RW, D; player_stats has C, L, R, D
pos_map = {'C':'C', 'LW':'L', 'RW':'R', 'D':'D', 'L':'L', 'R':'R', 'W':'L'}
sog_odds['pos_norm'] = sog_odds['player_position'].map(pos_map)

# Strategy: match by (event_date, team_id, position) + pick closest line to actual
# First, get unique player-game combos from player_stats with shots
ps_unique = ps[['game_id','player_id','team_id','position_code','shots','game_date']].copy()
ps_unique = ps_unique[ps_unique['shots'] > 0]  # only players who actually played

# For each sog_odds row, find matching player_stats rows
sog_odds_clean = sog_odds.dropna(subset=['team_id_mapped']).copy()
sog_odds_clean['team_id_mapped'] = sog_odds_clean['team_id_mapped'].astype(int)

# Join on game_date + team_id + position
matched = sog_odds_clean.merge(
    ps_unique,
    left_on=['event_date', 'team_id_mapped', 'pos_norm'],
    right_on=['game_date', 'team_id', 'position_code'],
    how='inner'
)

# Multiple players can match (same team, same position, same game)
# Pick the one whose shots are closest to the line (most likely the right player)
# Actually, better: group by odds row and pick the player with most TOI (= starter)
# We have toi_minutes in ps, let's re-merge
ps_toi = ps[['game_id','player_id','toi_minutes']].copy()
matched = matched.merge(ps_toi, on=['game_id','player_id'], how='left')

# For each odds entry, keep the player with highest TOI at that position
matched['abs_diff'] = (matched['shots'] - matched['line']).abs()
# Sort by toi desc and drop duplicates on odds side
matched = matched.sort_values('toi_minutes', ascending=False)
matched_dedup = matched.drop_duplicates(subset=['id', 'event_date', 'player_name'], keep='first')

print(f"\n  Raw matches: {len(matched)}, Deduped: {len(matched_dedup)}")

if len(matched_dedup) > 100:
    df = matched_dedup.copy()
    df['error'] = df['shots'] - df['line']
    df['abs_error'] = df['error'].abs()
    df['went_over'] = (df['shots'] > df['line']).astype(int)
    df['went_under'] = (df['shots'] < df['line']).astype(int)

    mae = df['abs_error'].mean()
    mean_error = df['error'].mean()
    over_rate = df['went_over'].mean()
    under_rate = df['went_under'].mean()
    push_rate = 1 - over_rate - under_rate

    print("\n  Book accuracy:")
    print(f"    MAE:        {mae:.2f} shots")
    print(f"    Mean error: {mean_error:+.3f} (positive = actual > line)")
    print(f"    Over rate:  {over_rate:.1%}")
    print(f"    Under rate: {under_rate:.1%}")
    print(f"    Push rate:  {push_rate:.1%}")

    print("\n  By position:")
    print(f"    {'Pos':>4s} {'MAE':>6s} {'Bias':>7s} {'Over%':>7s} {'N':>6s}")
    for pos in ['C','L','R','D']:
        sub = df[df['position_code']==pos]
        if len(sub) > 50:
            print(f"    {pos:>4s} {sub['abs_error'].mean():6.2f} {sub['error'].mean():+7.3f} {sub['went_over'].mean():7.1%} {len(sub):6d}")

    print("\n  By line bucket:")
    print(f"    {'Bucket':>12s} {'MAE':>6s} {'Bias':>7s} {'Over%':>7s} {'N':>6s}")
    for lo, hi, label in [(0,2,'0-2'), (2,3,'2-3'), (3,4,'3-4'), (4,5,'4-5'), (5,99,'5+')]:
        sub = df[(df['line']>=lo) & (df['line']<hi)]
        if len(sub) > 50:
            print(f"    {label:>12s} {sub['abs_error'].mean():6.2f} {sub['error'].mean():+7.3f} {sub['went_over'].mean():7.1%} {len(sub):6d}")

    print("\n  Biggest book errors by team:")
    team_err = df.groupby('team_id').agg(
        mean_error=('error','mean'), mae=('abs_error','mean'), n=('error','count')
    ).sort_values('mean_error')
    team_err = team_err[team_err['n']>=50]
    print("    Books OVER-set (actual < line → bet UNDER):")
    for tid, r in team_err.head(5).iterrows():
        print(f"      {teams_map.get(tid,'?'):>4s}: bias {r['mean_error']:+.3f}, MAE {r['mae']:.2f} ({int(r['n'])} bets)")
    print("    Books UNDER-set (actual > line → bet OVER):")
    for tid, r in team_err.tail(5).iterrows():
        print(f"      {teams_map.get(tid,'?'):>4s}: bias {r['mean_error']:+.3f}, MAE {r['mae']:.2f} ({int(r['n'])} bets)")

    book_mae = mae  # save for step 7
else:
    print("  Not enough matched odds data")
    book_mae = None

# ============================================================
# STEP 7: FEATURE IMPORTANCE
# ============================================================
print("\n" + "=" * 70)
print("  STEP 7: FEATURE IMPORTANCE (LightGBM)")
print("=" * 70)

pre_game_feats = ['is_home', 'pos_is_D', 'pos_is_C',
                  'sog_avg_5', 'sog_avg_10', 'sog_avg_20',
                  'toi_avg_5', 'toi_avg_10',
                  'sog_allowed_avg_10',
                  'fwd_missing_toi', 'def_missing_toi', 'total_missing_toi']
pre_game_feats = [f for f in pre_game_feats if f in ps.columns]

df_model = ps[pre_game_feats + ['shots']].dropna()
X = df_model[pre_game_feats]
y = df_model['shots']
print(f"\n  Pre-game model: {len(X)} samples, {len(pre_game_feats)} features")

model = lgb.LGBMRegressor(n_estimators=300, max_depth=5, learning_rate=0.05,
                           verbose=-1, subsample=0.8, colsample_bytree=0.8,
                           reg_alpha=0.5, reg_lambda=0.5)
model.fit(X, y)
preds = model.predict(X)
mae = mean_absolute_error(y, preds)
print(f"  Pre-game model in-sample MAE: {mae:.3f}")
if book_mae:
    print(f"  Book line MAE: {book_mae:.3f}")
    print(f"  {'✅ Model beats the book' if mae < book_mae else '⚠️ Book is better (but this is in-sample, will degrade OOS)'}")

imp = sorted(zip(pre_game_feats, model.feature_importances_), key=lambda x: -x[1])
print("\n  Feature importances (pre-game only):")
print(f"  {'Rank':>4s} {'Feature':>25s} {'Importance':>12s}")
print(f"  {'-'*44}")
for i, (feat, v) in enumerate(imp, 1):
    print(f"  {i:4d} {feat:>25s} {v:12d}")

# Also train ALL features (including same-game) for discovery
all_feats = pre_game_feats + ['toi_minutes', 'goals', 'assists', 'hits', 'blocked_shots',
                                'takeaways', 'giveaways', 'power_play_points']
all_feats = [f for f in all_feats if f in ps.columns]
df_all = ps[all_feats + ['shots']].dropna()
X_all = df_all[all_feats]
y_all = df_all['shots']

model_all = lgb.LGBMRegressor(n_estimators=300, max_depth=5, learning_rate=0.05,
                                verbose=-1, subsample=0.8, colsample_bytree=0.8)
model_all.fit(X_all, y_all)
imp_all = sorted(zip(all_feats, model_all.feature_importances_), key=lambda x: -x[1])
print("\n  All features (including same-game, for discovery):")
print(f"  {'Rank':>4s} {'Feature':>25s} {'Importance':>12s} {'Type':>12s}")
print(f"  {'-'*58}")
for i, (feat, v) in enumerate(imp_all[:15], 1):
    ftype = "PRE-GAME" if feat in pre_game_feats else "SAME-GAME"
    print(f"  {i:4d} {feat:>25s} {v:12d} {ftype:>12s}")

# SHAP
try:
    import shap
    print("\n  SHAP values (pre-game model):")
    sample = X.sample(min(2000, len(X)), random_state=42)
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(sample)
    shap_imp = np.abs(shap_values).mean(axis=0)
    shap_sorted = sorted(zip(pre_game_feats, shap_imp), key=lambda x: -x[1])
    print(f"  {'Rank':>4s} {'Feature':>25s} {'Mean |SHAP|':>12s}")
    print(f"  {'-'*44}")
    for i, (feat, val) in enumerate(shap_sorted, 1):
        print(f"  {i:4d} {feat:>25s} {val:12.4f}")
except ImportError:
    print("\n  SHAP not available")

print("\n" + "=" * 70)
print("  STEPS 6-7 COMPLETE")
print("=" * 70)
