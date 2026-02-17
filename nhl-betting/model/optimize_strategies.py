#!/usr/bin/env python3
"""
Final optimization: gap distribution + Corsi threshold sweep for MF2/MF3.
"""

import warnings
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2

warnings.filterwarnings('ignore')

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"
MODEL_DIR = Path('/Users/connorrainey/nhc-capital/nhl-betting/model')

def load_and_prepare():
    matrix = pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])

    conn = psycopg2.connect(DB_CONN)
    gts = pd.read_sql("SELECT * FROM game_team_stats", conn)
    games = pd.read_sql("""SELECT game_id, game_date, home_team_id, away_team_id
        FROM games WHERE home_score IS NOT NULL AND game_type IN (2,3) AND game_state='OFF'""", conn)
    conn.close()

    gts_m = gts.merge(games[['game_id','game_date','home_team_id','away_team_id']], on='game_id', how='inner')
    team_g = gts_m[['game_id','team_id','shots_attempted','takeaways','giveaways','game_date']].copy()
    opp = gts_m[['game_id','team_id','shots_attempted']].copy()
    opp.columns = ['game_id','opp_team_id','opp_shots_attempted']

    mg = team_g.merge(games[['game_id','home_team_id','away_team_id']], on='game_id')
    mg['opp_team_id'] = np.where(mg['team_id']==mg['home_team_id'], mg['away_team_id'], mg['home_team_id'])
    mg = mg.merge(opp, on=['game_id','opp_team_id'], how='left')
    mg['corsi_pct'] = mg['shots_attempted'] / (mg['shots_attempted'] + mg['opp_shots_attempted'])
    mg['corsi_diff'] = mg['shots_attempted'] - mg['opp_shots_attempted']
    mg['puck_control'] = mg['takeaways'] - mg['giveaways']
    mg = mg.sort_values(['team_id','game_date'])

    feats = []
    for tid, g in mg.groupby('team_id'):
        g = g.copy().sort_values('game_date')
        for w in [5,10,20]:
            g[f'corsi_pct_avg_{w}'] = g['corsi_pct'].rolling(w, min_periods=3).mean().shift(1)
            g[f'corsi_diff_avg_{w}'] = g['corsi_diff'].rolling(w, min_periods=3).mean().shift(1)
            g[f'puck_control_avg_{w}'] = g['puck_control'].rolling(w, min_periods=3).mean().shift(1)
        feats.append(g)
    corsi_df = pd.concat(feats, ignore_index=True)

    cols = [c for c in corsi_df.columns if c.endswith(('_5','_10','_20')) and any(c.startswith(p) for p in ['corsi_pct','corsi_diff','puck_control'])]
    for prefix, on_col in [('opp_', 'opponent_team_id'), ('own_', 'team_id')]:
        tmp = corsi_df[['game_id','team_id'] + cols].copy()
        tmp = tmp.rename(columns={c: f'{prefix}{c}' for c in cols})
        matrix = matrix.merge(tmp, left_on=['game_id', on_col], right_on=['game_id','team_id'], how='left', suffixes=('', f'_{prefix}drop'))
        drop_cols = [c for c in matrix.columns if c.endswith(f'_{prefix}drop')]
        matrix = matrix.drop(columns=drop_cols, errors='ignore')

    return matrix

def get_splits(matrix):
    splits = [
        {'name':'S1 (23-24)', 'train': matrix[matrix['event_date']<'2023-10-01'],
         'val': matrix[(matrix['event_date']>='2023-10-01')&(matrix['event_date']<'2024-10-01')]},
        {'name':'S2 (24-25)', 'train': matrix[matrix['event_date']<'2024-10-01'],
         'val': matrix[(matrix['event_date']>='2024-10-01')&(matrix['event_date']<'2025-10-01')]},
        {'name':'S3 (25-26)', 'train': matrix[matrix['event_date']<'2025-10-01'],
         'val': matrix[matrix['event_date']>='2025-10-01']},
    ]
    return [s for s in splits if len(s['train'])>100 and len(s['val'])>50]

def calc_payout(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds<0, 100/(-odds), odds/100)

def train_model(train_df, feats):
    model = lgb.LGBMRegressor(objective='regression', num_leaves=10, max_depth=4,
                               min_child_samples=50, learning_rate=0.05, n_estimators=300,
                               verbose=-1, reg_alpha=0.5, reg_lambda=0.5,
                               feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=5)
    t = train_df.dropna(subset=['saves'])
    tv = t[feats].notna().any(axis=1)
    t = t[tv]
    model.fit(t[feats].fillna(-999), t['saves'])
    return model

def eval_bucket(df, side='under'):
    if len(df) == 0:
        return None
    profits = []
    for _, r in df.iterrows():
        if side == 'under':
            won = r['saves'] < r['line']
            payout = calc_payout(np.array([r['under_odds']]))[0]
        else:
            won = r['saves'] > r['line']
            payout = calc_payout(np.array([r['over_odds']]))[0]
        push = r['saves'] == r['line']
        profits.append(0 if push else (payout if won else -1))
    n = len(profits)
    wins = sum(1 for p in profits if p > 0)
    return {'bets': n, 'win_rate': round(wins/n*100,1), 'roi': round(sum(profits)/n*100,1)}

FEATS = ['sa_avg_10','sa_avg_20','svpct_avg_10','svpct_avg_20','is_home',
         'opp_team_sog_avg_10','days_rest','own_def_missing_toi',
         'opp_corsi_pct_avg_10','opp_corsi_diff_avg_10',
         'own_corsi_pct_avg_10','pull_rate_10','starts_last_7d',
         'opp_team_pp_opps_avg_10','line']

def main():
    print("Loading data...")
    matrix = load_and_prepare()
    feats = [f for f in FEATS if f in matrix.columns]
    splits = get_splits(matrix)
    print(f"{len(matrix)} rows, {len(splits)} splits, {len(feats)} features\n")

    # ============================================================
    # 1. GAP DISTRIBUTION ANALYSIS
    # ============================================================
    print("=" * 70)
    print("  1. MODEL GAP DISTRIBUTION ANALYSIS")
    print("=" * 70)

    mf3_buckets = {'[1.0-1.5)': (1.0, 1.5), '[1.5-2.0)': (1.5, 2.0), '[2.0-2.5)': (2.0, 2.5), '[2.5+]': (2.5, 99)}
    mf2_buckets = {'[2.0-2.5)': (2.0, 2.5), '[2.5-3.0)': (2.5, 3.0), '[3.0+]': (3.0, 99)}

    mf3_all = {b: [] for b in mf3_buckets}
    mf2_all = {b: [] for b in mf2_buckets}

    for split in splits:
        model = train_model(split['train'], feats)
        val = split['val'].dropna(subset=['saves','line','over_odds','under_odds']).copy()
        val_f = val[val[feats].notna().any(axis=1)]
        val.loc[val_f.index, 'pred'] = model.predict(val_f[feats].fillna(-999))
        val = val.dropna(subset=['pred'])
        val['gap'] = np.abs(val['pred'] - val['line'])
        val['model_side'] = np.where(val['pred'] > val['line'], 'over', 'under')

        # MF3: under + low corsi + gap>=1
        if 'opp_corsi_pct_avg_10' in val.columns:
            v3 = val.dropna(subset=['opp_corsi_pct_avg_10'])
            q25 = v3['opp_corsi_pct_avg_10'].quantile(0.25)
            mf3_base = v3[(v3['model_side']=='under') & (v3['opp_corsi_pct_avg_10']<q25)]

            for bname, (lo, hi) in mf3_buckets.items():
                bucket = mf3_base[(mf3_base['gap']>=lo) & (mf3_base['gap']<hi)]
                mf3_all[bname].append(bucket)

        # MF2: under + b2b + gap>=2
        mf2_base = val[(val['model_side']=='under') & (val['days_rest']<=1)]
        for bname, (lo, hi) in mf2_buckets.items():
            bucket = mf2_base[(mf2_base['gap']>=lo) & (mf2_base['gap']<hi)]
            mf2_all[bname].append(bucket)

    print("\n  MF3 (UNDER: model + low Corsi) — Gap Breakdown:")
    print(f"  {'Bucket':15s} {'Bets':>6s} {'Win%':>8s} {'ROI':>8s}")
    print(f"  {'-'*40}")
    for bname, dfs in mf3_all.items():
        combined = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        res = eval_bucket(combined, 'under')
        if res:
            emoji = "🟢" if res['roi'] > 0 else "🔴"
            print(f"  {bname:15s} {res['bets']:6d} {res['win_rate']:7.1f}% {emoji}{res['roi']:+6.1f}%")
        else:
            print(f"  {bname:15s}      0       —       —")

    print("\n  MF2 (UNDER: model + B2B) — Gap Breakdown:")
    print(f"  {'Bucket':15s} {'Bets':>6s} {'Win%':>8s} {'ROI':>8s}")
    print(f"  {'-'*40}")
    for bname, dfs in mf2_all.items():
        combined = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        res = eval_bucket(combined, 'under')
        if res:
            emoji = "🟢" if res['roi'] > 0 else "🔴"
            print(f"  {bname:15s} {res['bets']:6d} {res['win_rate']:7.1f}% {emoji}{res['roi']:+6.1f}%")
        else:
            print(f"  {bname:15s}      0       —       —")

    # ============================================================
    # 2. CORSI THRESHOLD OPTIMIZATION
    # ============================================================
    print("\n" + "=" * 70)
    print("  2. OPPONENT CORSI THRESHOLD OPTIMIZATION (MF3)")
    print("=" * 70)

    thresholds = [0.20, 0.25, 0.30, 0.35]
    gap_levels = [1.0, 1.5, 2.0]

    print(f"\n  {'Corsi%ile':>10s} {'Gap≥':>6s} {'Bets':>6s} {'Win%':>8s} {'ROI':>8s} {'Edge×Vol':>10s}")
    print(f"  {'-'*55}")

    best_score = -999
    best_config = None

    for thresh in thresholds:
        for gap in gap_levels:
            all_bets = []
            for split in splits:
                model = train_model(split['train'], feats)
                val = split['val'].dropna(subset=['saves','line','over_odds','under_odds']).copy()
                val_f = val[val[feats].notna().any(axis=1)]
                val.loc[val_f.index, 'pred'] = model.predict(val_f[feats].fillna(-999))
                val = val.dropna(subset=['pred'])
                val['gap'] = np.abs(val['pred'] - val['line'])
                val['model_side'] = np.where(val['pred'] > val['line'], 'over', 'under')

                if 'opp_corsi_pct_avg_10' not in val.columns:
                    continue
                v = val.dropna(subset=['opp_corsi_pct_avg_10'])
                q = v['opp_corsi_pct_avg_10'].quantile(thresh)
                mask = (v['model_side']=='under') & (v['gap']>=gap) & (v['opp_corsi_pct_avg_10']<q)
                all_bets.append(v[mask])

            combined = pd.concat(all_bets, ignore_index=True) if all_bets else pd.DataFrame()
            res = eval_bucket(combined, 'under')
            if res and res['bets'] >= 10:
                edge = res['win_rate']/100 - 0.524
                score = edge * res['bets']
                emoji = "🟢" if res['roi'] > 0 else "🔴"
                marker = ""
                if score > best_score:
                    best_score = score
                    best_config = {'thresh': thresh, 'gap': gap, 'res': res, 'score': score}
                    marker = " ⭐"
                print(f"  {thresh*100:8.0f}%  {gap:5.1f} {res['bets']:6d} {res['win_rate']:7.1f}% {emoji}{res['roi']:+6.1f}% {score:9.1f}{marker}")

    if best_config:
        print(f"\n  ⭐ OPTIMAL: Bottom {best_config['thresh']*100:.0f}% Corsi, gap≥{best_config['gap']}")
        print(f"     {best_config['res']['bets']} bets, {best_config['res']['win_rate']}% win, {best_config['res']['roi']:+.1f}% ROI")
        print(f"     Edge×Volume score: {best_config['score']:.1f}")

    # ============================================================
    # RECOMMENDATIONS
    # ============================================================
    print("\n" + "=" * 70)
    print("  RECOMMENDATIONS")
    print("=" * 70)

    # Check if higher gap is better for MF3
    mf3_high = pd.concat(mf3_all.get('[2.5+]', []), ignore_index=True) if mf3_all.get('[2.5+]') else pd.DataFrame()
    mf3_high_res = eval_bucket(mf3_high, 'under') if len(mf3_high) > 0 else None

    if mf3_high_res and mf3_high_res['bets'] >= 15 and mf3_high_res['roi'] > 20:
        print(f"\n  ✅ CREATE MF4: MF3 with gap≥2.5 — {mf3_high_res['bets']} bets, {mf3_high_res['win_rate']}% win, {mf3_high_res['roi']:+.1f}% ROI")
        print("     Higher conviction subset, use for larger unit sizing")
    else:
        print("\n  ❌ No MF4 recommended — high gap buckets don't have enough volume or edge concentration")

    if best_config and (best_config['thresh'] != 0.25 or best_config['gap'] != 1.0):
        print(f"\n  ✅ CREATE MF5: Optimized MF3 — bottom {best_config['thresh']*100:.0f}% Corsi, gap≥{best_config['gap']}")
        print(f"     {best_config['res']['bets']} bets, {best_config['res']['win_rate']}% win, {best_config['res']['roi']:+.1f}% ROI")
    else:
        print("\n  ❌ No MF5 needed — current MF3 thresholds (25%, gap≥1) are already optimal")

    # Write summary
    lines = [f"\n## Optimization Results — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    lines.append("### Gap Distribution")
    for bname, dfs in mf3_all.items():
        c = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        r = eval_bucket(c, 'under')
        if r:
            lines.append(f"- MF3 {bname}: {r['bets']} bets, {r['win_rate']}% win, {r['roi']:+.1f}% ROI")
    for bname, dfs in mf2_all.items():
        c = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        r = eval_bucket(c, 'under')
        if r:
            lines.append(f"- MF2 {bname}: {r['bets']} bets, {r['win_rate']}% win, {r['roi']:+.1f}% ROI")
    if best_config:
        lines.append("\n### Optimal Corsi Threshold")
        lines.append(f"- Best: bottom {best_config['thresh']*100:.0f}%, gap≥{best_config['gap']} → {best_config['res']['bets']} bets, {best_config['res']['roi']:+.1f}% ROI")
    lines.append("")

    with open(MODEL_DIR / 'strategy.md', 'a') as f:
        f.write('\n'.join(lines))

    print("\nLogged to strategy.md")

if __name__ == '__main__':
    main()
