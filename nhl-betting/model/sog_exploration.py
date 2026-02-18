#!/usr/bin/env python3
"""SOG Exploratory Analysis — Steps 1-7"""

import warnings

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402
from scipy import stats as scipy_stats  # noqa: E402

warnings.filterwarnings('ignore')

DB = "postgresql://connorrainey@localhost:5432/nhl_betting"

def load():
    conn = psycopg2.connect(DB)
    ps = pd.read_sql("SELECT * FROM player_stats", conn)
    gts = pd.read_sql("SELECT * FROM game_team_stats", conn)
    games = pd.read_sql("""SELECT game_id, game_date, home_team_id, away_team_id, season
        FROM games WHERE home_score IS NOT NULL AND game_type IN (2,3) AND game_state='OFF'""", conn)
    sog_odds = pd.read_sql("SELECT * FROM sog_odds WHERE book_name='consensus'", conn)
    la = pd.read_sql("SELECT * FROM lineup_absences", conn)
    standings = pd.read_sql("SELECT * FROM standings", conn)
    players = pd.read_sql("SELECT player_id, first_name, last_name, position_code FROM players", conn)
    teams = pd.read_sql("SELECT team_id, tri_code FROM teams", conn)
    conn.close()
    return ps, gts, games, sog_odds, la, standings, players, teams

print("Loading data...")
ps, gts, games, sog_odds, la, standings, players, teams = load()
teams_map = teams.set_index('team_id')['tri_code'].to_dict()
players['full_name'] = players['first_name'] + ' ' + players['last_name']

# Filter to skaters only (exclude goalies)
ps = ps[ps['position_code'].isin(['C','L','R','D'])]
ps = ps.merge(games[['game_id','game_date','home_team_id','away_team_id']], on='game_id', how='inner')
print(f"Player stats: {len(ps)} rows, {ps['game_id'].nunique()} games, {ps['player_id'].nunique()} players\n")

# ============================================================
# STEP 1: BASELINE DISTRIBUTION
# ============================================================
print("=" * 70)
print("  STEP 1: BASELINE SOG DISTRIBUTION")
print("=" * 70)

shots = ps['shots']
print("\nOverall SOG per game:")
print(f"  Mean:   {shots.mean():.2f}")
print(f"  Median: {shots.median():.1f}")
print(f"  Std:    {shots.std():.2f}")
print(f"  Min:    {shots.min()}")
print(f"  Max:    {shots.max()}")
for p in [10, 25, 50, 75, 90, 95]:
    print(f"  P{p}:    {np.percentile(shots, p):.1f}")

print("\nBy position:")
print(f"  {'Pos':>4s} {'Mean':>6s} {'Median':>7s} {'Std':>6s} {'N':>8s}")
for pos in ['C','L','R','D']:
    sub = ps[ps['position_code']==pos]['shots']
    print(f"  {pos:>4s} {sub.mean():6.2f} {sub.median():7.1f} {sub.std():6.2f} {len(sub):8d}")

print("\nHome vs Away:")
home = ps[ps['is_home']==1]['shots']
away = ps[ps['is_home']==0]['shots']
print(f"  Home: {home.mean():.3f} avg ({len(home)} games)")
print(f"  Away: {away.mean():.3f} avg ({len(away)} games)")
print(f"  Diff: {home.mean()-away.mean():+.3f} (p={scipy_stats.ttest_ind(home, away).pvalue:.4f})")

# Histogram data (text-based)
print("\nSOG Histogram:")
bins = range(0, 15)
for b in bins:
    count = ((shots >= b) & (shots < b+1)).sum()
    pct = count / len(shots) * 100
    bar = '█' * int(pct)
    print(f"  {b:2d} shots: {count:6d} ({pct:5.1f}%) {bar}")

# ============================================================
# STEP 2: CORRELATION ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("  STEP 2: CORRELATION ANALYSIS")
print("=" * 70)

numeric_cols = [c for c in ps.columns if ps[c].dtype in ('float64','int64','int32','float32')
                and c not in ('game_id','player_id','team_id','home_team_id','away_team_id')]

print(f"\n  {'Feature':>25s} {'Pearson':>9s} {'Spearman':>9s} {'Signal':>8s}")
print(f"  {'-'*55}")

corr_results = []
for col in numeric_cols:
    if col == 'shots':
        continue
    valid = ps[['shots', col]].dropna()
    if len(valid) < 100:
        continue
    pearson = valid['shots'].corr(valid[col])
    spearman = valid['shots'].corr(valid[col], method='spearman')
    corr_results.append({'feature': col, 'pearson': pearson, 'spearman': spearman,
                         'abs_pearson': abs(pearson)})

corr_df = pd.DataFrame(corr_results).sort_values('abs_pearson', ascending=False)
for _, r in corr_df.iterrows():
    signal = "✅" if r['abs_pearson'] > 0.15 else "  "
    print(f"  {r['feature']:>25s} {r['pearson']:+9.4f} {r['spearman']:+9.4f} {signal:>8s}")

print(f"\n  Features with |r| > 0.15: {(corr_df['abs_pearson']>0.15).sum()}")

# ============================================================
# STEP 3: ROLLING WINDOW ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("  STEP 3: ROLLING WINDOW ANALYSIS")
print("=" * 70)

ps_sorted = ps.sort_values(['player_id','game_date'])

rolling_results = []
for window in [3, 5, 10, 20]:
    col_name = f'sog_avg_{window}'
    ps_sorted[col_name] = ps_sorted.groupby('player_id')['shots'].transform(
        lambda x: x.rolling(window, min_periods=max(3, window//2)).mean().shift(1)
    )
    valid = ps_sorted[['shots', col_name]].dropna()
    pearson = valid['shots'].corr(valid[col_name])
    spearman = valid['shots'].corr(valid[col_name], method='spearman')
    rolling_results.append({'window': window, 'pearson': pearson, 'spearman': spearman, 'n': len(valid)})

print(f"\n  {'Window':>8s} {'Pearson':>9s} {'Spearman':>9s} {'N':>8s}")
print(f"  {'-'*38}")
for r in rolling_results:
    print(f"  {r['window']:>8d} {r['pearson']:+9.4f} {r['spearman']:+9.4f} {r['n']:8d}")

best = max(rolling_results, key=lambda x: abs(x['pearson']))
print(f"\n  Best window: {best['window']}-game (r={best['pearson']:+.4f})")

# Also compute rolling TOI
for window in [5, 10]:
    col_name = f'toi_avg_{window}'
    ps_sorted[col_name] = ps_sorted.groupby('player_id')['toi_minutes'].transform(
        lambda x: x.rolling(window, min_periods=3).mean().shift(1)
    )

# ============================================================
# STEP 4: OPPONENT DEFENSIVE IMPACT
# ============================================================
print("\n" + "=" * 70)
print("  STEP 4: OPPONENT DEFENSIVE IMPACT")
print("=" * 70)

# For each player-game, find the opponent team and their defensive stats
ps_sorted['opponent_team_id'] = np.where(
    ps_sorted['team_id'] == ps_sorted['home_team_id'],
    ps_sorted['away_team_id'], ps_sorted['home_team_id']
)

# Opponent's average shots allowed (shots_on_goal from game_team_stats = shots their goalie faced)
# We need the OTHER team's shots_on_goal as "shots allowed by defense"
# Actually: for opponent defense, we want how many SOG the opponent ALLOWS = our team's SOG in games vs them
# Better: use game_team_stats to get each team's shots_on_goal allowed (= opponent's SOG)
gts_def = gts[['game_id','team_id','shots_on_goal','shots_attempted']].copy()
gts_def = gts_def.merge(games[['game_id','game_date']], on='game_id', how='inner')
gts_def = gts_def.sort_values(['team_id','game_date'])

# Rolling shots allowed by opponent (the opponent's SOG in games = what they allow)
# Join: for each game, get opponent's team_id, then get what teams score against that opponent
# Simpler: merge game_team_stats twice — once for each side
gts_merged = gts[['game_id','team_id','shots_on_goal']].copy()
gts_merged = gts_merged.merge(games[['game_id','game_date','home_team_id','away_team_id']], on='game_id')
gts_merged['opp_team_id'] = np.where(gts_merged['team_id']==gts_merged['home_team_id'],
                                      gts_merged['away_team_id'], gts_merged['home_team_id'])

# Get opponent's SOG in same game = shots allowed by this team's defense
opp_sog = gts[['game_id','team_id','shots_on_goal']].rename(columns={'team_id':'opp_team_id','shots_on_goal':'opp_sog_in_game'})
gts_merged = gts_merged.merge(opp_sog, on=['game_id','opp_team_id'], how='left')

# Now gts_merged has: team_id, opp_team_id, opp_sog_in_game = SOG allowed by team_id's defense
# We want: for each opponent, their rolling avg SOG allowed (= how many shots they give up)
# "shots allowed" by opp = what the other team shoots against them
# opp_sog_in_game is the opponent's SOG, which is what this team's defense allowed
# We want the OPPONENT's defensive quality = how many SOG they allow to OTHER teams
# = when team X is on defense, how many SOG does the offense get?
# = gts_merged where team_id = opp, the opp_sog_in_game column

# Let me redo: for opponent team O, their "SOG allowed" = in games where O plays, the other team's SOG
opp_def = gts_merged[['game_id','game_date','team_id','opp_sog_in_game']].copy()
# opp_sog_in_game here = SOG by the opponent AGAINST team_id = shots team_id's defense allowed
# So for team_id = T, opp_sog_in_game = how many SOG T allowed
opp_def = opp_def.rename(columns={'team_id':'def_team_id', 'opp_sog_in_game':'sog_allowed'})
opp_def = opp_def.sort_values(['def_team_id','game_date'])

# Rolling avg SOG allowed per team
opp_def_rolling = []
for tid, g in opp_def.groupby('def_team_id'):
    g = g.copy().sort_values('game_date')
    g['sog_allowed_avg_10'] = g['sog_allowed'].rolling(10, min_periods=5).mean().shift(1)
    g['sog_allowed_avg_20'] = g['sog_allowed'].rolling(20, min_periods=10).mean().shift(1)
    opp_def_rolling.append(g)
opp_def_rolling = pd.concat(opp_def_rolling, ignore_index=True)

# Merge back: for each player-game, get the opponent's rolling SOG allowed
ps_sorted = ps_sorted.merge(
    opp_def_rolling[['game_id','def_team_id','sog_allowed_avg_10','sog_allowed_avg_20']],
    left_on=['game_id','opponent_team_id'], right_on=['game_id','def_team_id'],
    how='left', suffixes=('','_opp_def')
)

valid = ps_sorted[['shots','sog_allowed_avg_10']].dropna()
corr = valid['shots'].corr(valid['sog_allowed_avg_10'])
print(f"\n  Correlation: player SOG vs opponent SOG allowed (10g avg): r={corr:+.4f} (n={len(valid)})")

valid20 = ps_sorted[['shots','sog_allowed_avg_20']].dropna()
corr20 = valid20['shots'].corr(valid20['sog_allowed_avg_20'])
print(f"  Correlation: player SOG vs opponent SOG allowed (20g avg): r={corr20:+.4f} (n={len(valid20)})")

# Top/bottom 5 teams by avg SOG allowed (season-level)
team_def = opp_def.groupby('def_team_id')['sog_allowed'].mean().sort_values()
print("\n  Top 5 defensive teams (fewest SOG allowed):")
for tid, val in team_def.head(5).items():
    print(f"    {teams_map.get(tid, tid):>4s}: {val:.1f} SOG/game allowed")
print("\n  Bottom 5 defensive teams (most SOG allowed):")
for tid, val in team_def.tail(5).items():
    print(f"    {teams_map.get(tid, tid):>4s}: {val:.1f} SOG/game allowed")

# Effect size: player SOG vs weak (top quartile allowed) vs strong (bottom quartile) defense
q25 = ps_sorted['sog_allowed_avg_10'].quantile(0.25)
q75 = ps_sorted['sog_allowed_avg_10'].quantile(0.75)
strong_def = ps_sorted[ps_sorted['sog_allowed_avg_10'] <= q25]['shots']
weak_def = ps_sorted[ps_sorted['sog_allowed_avg_10'] >= q75]['shots']
print(f"\n  Player SOG vs strong defense (bottom 25%): {strong_def.mean():.3f} avg")
print(f"  Player SOG vs weak defense (top 25%):     {weak_def.mean():.3f} avg")
print(f"  Difference: {weak_def.mean()-strong_def.mean():+.3f} SOG/game")

# ============================================================
# STEP 5: LINEUP ABSENCES IMPACT
# ============================================================
print("\n" + "=" * 70)
print("  STEP 5: LINEUP ABSENCES IMPACT")
print("=" * 70)

ps_la = ps_sorted.merge(la[['game_id','team_id','fwd_missing','fwd_missing_toi','def_missing',
                              'def_missing_toi','total_missing','total_missing_toi']],
                          on=['game_id','team_id'], how='left')

print(f"\n  {'Feature':>25s} {'Corr w/ SOG':>12s} {'N':>8s}")
print(f"  {'-'*48}")
for col in ['fwd_missing','fwd_missing_toi','def_missing','def_missing_toi','total_missing','total_missing_toi']:
    valid = ps_la[['shots', col]].dropna()
    if len(valid) > 100:
        r = valid['shots'].corr(valid[col])
        print(f"  {col:>25s} {r:+12.4f} {len(valid):8d}")

# Effect size by fwd_missing buckets
print("\n  Effect by # forwards missing on own team:")
for bucket, label in [(0, '0 missing'), (1, '1 missing'), (2, '2 missing'), (3, '3+ missing')]:
    if bucket < 3:
        sub = ps_la[ps_la['fwd_missing']==bucket]['shots']
    else:
        sub = ps_la[ps_la['fwd_missing']>=3]['shots']
    if len(sub) > 50:
        print(f"    {label:>12s}: {sub.mean():.3f} avg SOG ({len(sub)} games)")

# ============================================================
# STEP 6: LINE EFFICIENCY ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("  STEP 6: LINE EFFICIENCY (sog_odds vs actual)")
print("=" * 70)

# Match sog_odds to player_stats
sog_odds['event_date'] = pd.to_datetime(sog_odds['event_date'])
players_name_map = players.set_index('full_name')['player_id'].to_dict()
sog_odds['player_id'] = sog_odds['player_name'].map(players_name_map)
sog_odds = sog_odds.dropna(subset=['player_id'])
sog_odds['player_id'] = sog_odds['player_id'].astype(int)

# Join to actual stats
ps_for_odds = ps_sorted[['game_id','player_id','shots','position_code','team_id','is_home','game_date']].copy()
ps_for_odds['game_date_str'] = ps_for_odds['game_date'].astype(str)
sog_odds['event_date_str'] = sog_odds['event_date'].dt.strftime('%Y-%m-%d')

odds_matched = sog_odds.merge(
    ps_for_odds, left_on=['player_id','event_date_str'], right_on=['player_id','game_date_str'], how='inner'
)
print(f"\n  Matched odds to actual stats: {len(odds_matched)} rows")

if len(odds_matched) > 0:
    odds_matched['error'] = odds_matched['shots'] - odds_matched['line']
    odds_matched['abs_error'] = odds_matched['error'].abs()
    odds_matched['went_over'] = (odds_matched['shots'] > odds_matched['line']).astype(int)
    odds_matched['went_under'] = (odds_matched['shots'] < odds_matched['line']).astype(int)

    mae = odds_matched['abs_error'].mean()
    mean_error = odds_matched['error'].mean()
    over_rate = odds_matched['went_over'].mean()
    under_rate = odds_matched['went_under'].mean()
    push_rate = 1 - over_rate - under_rate

    print("\n  Book accuracy:")
    print(f"    MAE:        {mae:.2f} shots")
    print(f"    Mean error: {mean_error:+.3f} (positive = actual > line)")
    print(f"    Over rate:  {over_rate:.1%}")
    print(f"    Under rate: {under_rate:.1%}")
    print(f"    Push rate:  {push_rate:.1%}")

    # By position
    print("\n  By position:")
    print(f"    {'Pos':>4s} {'MAE':>6s} {'Bias':>7s} {'Over%':>7s} {'N':>6s}")
    for pos in ['C','L','R','D']:
        sub = odds_matched[odds_matched['position_code']==pos]
        if len(sub) > 50:
            print(f"    {pos:>4s} {sub['abs_error'].mean():6.2f} {sub['error'].mean():+7.3f} {sub['went_over'].mean():7.1%} {len(sub):6d}")

    # By line value bucket
    print("\n  By line bucket:")
    print(f"    {'Bucket':>12s} {'MAE':>6s} {'Bias':>7s} {'Over%':>7s} {'N':>6s}")
    for lo, hi, label in [(0,2,'0-2'), (2,3,'2-3'), (3,4,'3-4'), (4,5,'4-5'), (5,99,'5+')]:
        sub = odds_matched[(odds_matched['line']>=lo) & (odds_matched['line']<hi)]
        if len(sub) > 50:
            print(f"    {label:>12s} {sub['abs_error'].mean():6.2f} {sub['error'].mean():+7.3f} {sub['went_over'].mean():7.1%} {len(sub):6d}")

    # By team — find where books are most wrong
    print("\n  Biggest book errors by team (where model has most room):")
    team_errors = odds_matched.groupby('team_id').agg(
        mean_error=('error','mean'), mae=('abs_error','mean'), n=('error','count')
    ).sort_values('mean_error')
    team_errors = team_errors[team_errors['n'] >= 50]
    print("    Books OVER-set (actual < line, bet UNDER):")
    for tid, r in team_errors.head(5).iterrows():
        print(f"      {teams_map.get(tid,'?'):>4s}: bias {r['mean_error']:+.3f}, MAE {r['mae']:.2f} ({int(r['n'])} bets)")
    print("    Books UNDER-set (actual > line, bet OVER):")
    for tid, r in team_errors.tail(5).iterrows():
        print(f"      {teams_map.get(tid,'?'):>4s}: bias {r['mean_error']:+.3f}, MAE {r['mae']:.2f} ({int(r['n'])} bets)")

# ============================================================
# STEP 7: QUICK MODEL + FEATURE IMPORTANCE
# ============================================================
print("\n" + "=" * 70)
print("  STEP 7: FEATURE IMPORTANCE (XGBoost)")
print("=" * 70)

try:
    import xgboost as xgb
    has_xgb = True
except ImportError:
    try:
        import lightgbm as lgb
        has_xgb = False
    except ImportError:
        print("  Neither XGBoost nor LightGBM available")
        has_xgb = None

if has_xgb is not None:
    # Build feature set
    feature_cols = ['is_home', 'toi_minutes', 'goals', 'assists', 'plus_minus', 'pim',
                    'hits', 'blocked_shots', 'power_play_goals', 'power_play_points',
                    'takeaways', 'giveaways', 'faceoff_win_pct']

    # Add rolling features
    for w in [5, 10, 20]:
        col = f'sog_avg_{w}'
        if col in ps_sorted.columns:
            feature_cols.append(col)

    for w in [5, 10]:
        col = f'toi_avg_{w}'
        if col in ps_sorted.columns:
            feature_cols.append(col)

    # Add opponent defense
    for col in ['sog_allowed_avg_10', 'sog_allowed_avg_20']:
        if col in ps_sorted.columns:
            feature_cols.append(col)

    # Add position as numeric
    ps_sorted['pos_is_D'] = (ps_sorted['position_code'] == 'D').astype(int)
    ps_sorted['pos_is_C'] = (ps_sorted['position_code'] == 'C').astype(int)
    feature_cols.extend(['pos_is_D', 'pos_is_C'])

    # Add lineup absences
    if 'fwd_missing_toi' in ps_la.columns:
        ps_sorted = ps_sorted.merge(
            la[['game_id','team_id','fwd_missing_toi','def_missing_toi','total_missing_toi']],
            on=['game_id','team_id'], how='left', suffixes=('','_la2')
        )
        for col in ['fwd_missing_toi','def_missing_toi','total_missing_toi']:
            if col in ps_sorted.columns:
                feature_cols.append(col)

    feature_cols = [c for c in feature_cols if c in ps_sorted.columns]
    feature_cols = list(dict.fromkeys(feature_cols))  # dedupe

    # Remove leakage: goals, assists, plus_minus, pim, hits, blocked_shots etc are SAME-GAME stats
    # For a betting model we'd only use pre-game features. But for feature importance discovery, include both.
    # Flag which are pre-game vs same-game
    pre_game = ['is_home', 'pos_is_D', 'pos_is_C', 'sog_avg_5', 'sog_avg_10', 'sog_avg_20',
                'toi_avg_5', 'toi_avg_10', 'sog_allowed_avg_10', 'sog_allowed_avg_20',
                'fwd_missing_toi', 'def_missing_toi', 'total_missing_toi']
    same_game = ['toi_minutes', 'goals', 'assists', 'plus_minus', 'pim', 'hits',
                 'blocked_shots', 'power_play_goals', 'power_play_points', 'takeaways',
                 'giveaways', 'faceoff_win_pct']

    # Train on all features first for discovery
    df = ps_sorted[feature_cols + ['shots']].dropna()
    X = df[feature_cols]
    y = df['shots']

    print(f"\n  Training on {len(X)} samples, {len(feature_cols)} features")

    if has_xgb:
        model = xgb.XGBRegressor(n_estimators=300, max_depth=5, learning_rate=0.05,
                                  subsample=0.8, colsample_bytree=0.8, verbosity=0)
        model.fit(X, y)
        importances = dict(zip(feature_cols, model.feature_importances_))
    else:
        model = lgb.LGBMRegressor(n_estimators=300, max_depth=5, learning_rate=0.05,
                                   verbose=-1, subsample=0.8, colsample_bytree=0.8)
        model.fit(X, y)
        importances = dict(zip(feature_cols, model.feature_importances_))

    sorted_imp = sorted(importances.items(), key=lambda x: -x[1])

    print("\n  Top 15 features by importance:")
    print(f"  {'Rank':>4s} {'Feature':>25s} {'Importance':>12s} {'Type':>12s}")
    print(f"  {'-'*58}")
    for i, (feat, imp) in enumerate(sorted_imp[:15], 1):
        ftype = "PRE-GAME" if feat in pre_game else "SAME-GAME"
        print(f"  {i:4d} {feat:>25s} {imp:12.4f} {ftype:>12s}")

    # Now train PRE-GAME ONLY model
    pre_game_avail = [c for c in pre_game if c in feature_cols]
    if pre_game_avail:
        df2 = ps_sorted[pre_game_avail + ['shots']].dropna()
        X2 = df2[pre_game_avail]
        y2 = df2['shots']

        print(f"\n  PRE-GAME ONLY model ({len(X2)} samples, {len(pre_game_avail)} features):")
        if has_xgb:
            model2 = xgb.XGBRegressor(n_estimators=300, max_depth=5, learning_rate=0.05,
                                        subsample=0.8, colsample_bytree=0.8, verbosity=0)
        else:
            model2 = lgb.LGBMRegressor(n_estimators=300, max_depth=5, learning_rate=0.05,
                                         verbose=-1, subsample=0.8, colsample_bytree=0.8)
        model2.fit(X2, y2)
        imp2 = sorted(zip(pre_game_avail, model2.feature_importances_), key=lambda x: -x[1])

        print(f"  {'Rank':>4s} {'Feature':>25s} {'Importance':>12s}")
        print(f"  {'-'*44}")
        for i, (feat, imp) in enumerate(imp2, 1):
            print(f"  {i:4d} {feat:>25s} {imp:12.4f}")

        from sklearn.metrics import mean_absolute_error
        preds = model2.predict(X2)
        mae = mean_absolute_error(y2, preds)
        print(f"\n  Pre-game model MAE: {mae:.3f} (vs book MAE: ~{odds_matched['abs_error'].mean():.2f} if available)")

    # SHAP if available
    try:
        import shap
        print("\n  SHAP values (pre-game model):")
        explainer = shap.TreeExplainer(model2)
        shap_values = explainer.shap_values(X2.sample(min(1000, len(X2)), random_state=42))
        shap_imp = np.abs(shap_values).mean(axis=0)
        shap_sorted = sorted(zip(pre_game_avail, shap_imp), key=lambda x: -x[1])
        print(f"  {'Rank':>4s} {'Feature':>25s} {'Mean |SHAP|':>12s}")
        print(f"  {'-'*44}")
        for i, (feat, val) in enumerate(shap_sorted, 1):
            print(f"  {i:4d} {feat:>25s} {val:12.4f}")
    except ImportError:
        print("\n  SHAP not available — skipping")

print("\n\n" + "=" * 70)
print("  ANALYSIS COMPLETE")
print("=" * 70)
