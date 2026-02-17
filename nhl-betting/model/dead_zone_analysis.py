#!/usr/bin/env python3
"""Dead zone investigation: MF3 gap [1.5-2.5) losing bets."""

import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2

warnings.filterwarnings('ignore')

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"
MODEL_DIR = Path('/Users/connorrainey/nhc-capital/nhl-betting/model')

FEATS = ['sa_avg_10','sa_avg_20','svpct_avg_10','svpct_avg_20','is_home',
         'opp_team_sog_avg_10','days_rest','own_def_missing_toi',
         'opp_corsi_pct_avg_10','opp_corsi_diff_avg_10',
         'own_corsi_pct_avg_10','pull_rate_10','starts_last_7d',
         'opp_team_pp_opps_avg_10','line']

def load_and_prepare():
    matrix = pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])

    conn = psycopg2.connect(DB_CONN)
    gts = pd.read_sql("SELECT * FROM game_team_stats", conn)
    games = pd.read_sql("""SELECT game_id, game_date, home_team_id, away_team_id
        FROM games WHERE home_score IS NOT NULL AND game_type IN (2,3) AND game_state='OFF'""", conn)
    teams = pd.read_sql("SELECT team_id, tri_code AS abbreviation FROM teams", conn)
    players = pd.read_sql("SELECT player_id, first_name, last_name FROM players", conn)
    goalie_adv = pd.read_sql("SELECT game_id, player_id, games_started FROM goalie_advanced", conn)
    conn.close()

    # Corsi features
    gts_m = gts.merge(games[['game_id','game_date','home_team_id','away_team_id']], on='game_id', how='inner')
    tg = gts_m[['game_id','team_id','shots_attempted','takeaways','giveaways','game_date']].copy()
    opp = gts_m[['game_id','team_id','shots_attempted']].copy()
    opp.columns = ['game_id','opp_team_id','opp_shots_attempted']
    mg = tg.merge(games[['game_id','home_team_id','away_team_id']], on='game_id')
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

    return matrix, teams, players, goalie_adv

def get_splits(matrix):
    splits = [
        {'name':'S1', 'train': matrix[matrix['event_date']<'2023-10-01'],
         'val': matrix[(matrix['event_date']>='2023-10-01')&(matrix['event_date']<'2024-10-01')]},
        {'name':'S2', 'train': matrix[matrix['event_date']<'2024-10-01'],
         'val': matrix[(matrix['event_date']>='2024-10-01')&(matrix['event_date']<'2025-10-01')]},
        {'name':'S3', 'train': matrix[matrix['event_date']<'2025-10-01'],
         'val': matrix[matrix['event_date']>='2025-10-01']},
    ]
    return [s for s in splits if len(s['train'])>100 and len(s['val'])>50]

def main():
    matrix, teams, players, goalie_adv = load_and_prepare()
    feats = [f for f in FEATS if f in matrix.columns]
    splits = get_splits(matrix)

    # Merge team/player names
    teams_map = teams.set_index('team_id')['abbreviation'].to_dict()
    players['full_name'] = players['first_name'] + ' ' + players['last_name']
    players_map = players.set_index('player_id')['full_name'].to_dict()

    # Merge starter info
    starter_map = goalie_adv.set_index(['game_id','player_id'])['games_started'].to_dict()

    all_dead_zone = []

    for split in splits:
        model = lgb.LGBMRegressor(objective='regression', num_leaves=10, max_depth=4,
                                   min_child_samples=50, learning_rate=0.05, n_estimators=300,
                                   verbose=-1, reg_alpha=0.5, reg_lambda=0.5,
                                   feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=5)
        train = split['train'].dropna(subset=['saves'])
        tv = train[feats].notna().any(axis=1)
        model.fit(train[tv][feats].fillna(-999), train[tv]['saves'])

        val = split['val'].dropna(subset=['saves','line','over_odds','under_odds']).copy()
        vf = val[val[feats].notna().any(axis=1)]
        val.loc[vf.index, 'pred'] = model.predict(vf[feats].fillna(-999))
        val = val.dropna(subset=['pred'])
        val['gap'] = np.abs(val['pred'] - val['line'])
        val['model_side'] = np.where(val['pred'] > val['line'], 'over', 'under')

        if 'opp_corsi_pct_avg_10' not in val.columns:
            continue
        v = val.dropna(subset=['opp_corsi_pct_avg_10'])
        q25 = v['opp_corsi_pct_avg_10'].quantile(0.25)

        dead = v[(v['model_side']=='under') & (v['opp_corsi_pct_avg_10']<q25) &
                 (v['gap']>=1.5) & (v['gap']<2.5)]
        dead = dead.copy()
        dead['split'] = split['name']
        all_dead_zone.append(dead)

    dz = pd.concat(all_dead_zone, ignore_index=True)
    dz['goalie'] = dz['player_id'].map(players_map)
    dz['team_abbr'] = dz['team_id'].map(teams_map)
    dz['opp_abbr'] = dz['opponent_team_id'].map(teams_map)
    dz['is_starter'] = dz.apply(lambda r: starter_map.get((r['game_id'], r['player_id']), 0), axis=1)
    dz['won_under'] = dz['saves'] < dz['line']
    dz['day_of_week'] = dz['event_date'].dt.day_name()

    print(f"Dead zone bets: {len(dz)}")
    print(f"Under wins: {dz['won_under'].sum()} ({dz['won_under'].mean()*100:.1f}%)")
    print(f"Losses: {(~dz['won_under']).sum()}")

    # Detailed bet table
    print(f"\n{'Date':12s} {'Goalie':22s} {'Team':>5s} {'Opp':>5s} {'H/A':>4s} {'Line':>5s} {'Saves':>6s} {'Pred':>6s} {'Gap':>5s} {'OppCorsi':>9s} {'B2B':>4s} {'DayRest':>7s} {'Result':>7s}")
    print("-" * 115)
    for _, r in dz.sort_values('event_date').iterrows():
        ha = 'H' if r['is_home'] == 1 else 'A'
        b2b = 'Y' if r['days_rest'] <= 1 else 'N'
        result = '✅ W' if r['won_under'] else '❌ L'
        print(f"{str(r['event_date'].date()):12s} {str(r['goalie'])[:22]:22s} {str(r['team_abbr']):>5s} {str(r['opp_abbr']):>5s} {ha:>4s} {r['line']:5.1f} {r['saves']:6.0f} {r['pred']:6.1f} {r['gap']:5.1f} {r['opp_corsi_pct_avg_10']:9.3f} {b2b:>4s} {r['days_rest']:7.0f} {result:>7s}")

    # Pattern analysis
    print("\n\n=== PATTERN ANALYSIS ===")

    # Home vs away
    home = dz[dz['is_home']==1]
    away = dz[dz['is_home']==0]
    print(f"\nHome: {len(home)} bets, {home['won_under'].mean()*100:.1f}% under win")
    print(f"Away: {len(away)} bets, {away['won_under'].mean()*100:.1f}% under win")

    # B2B
    b2b = dz[dz['days_rest']<=1]
    rested = dz[dz['days_rest']>1]
    print(f"\nB2B: {len(b2b)} bets, {b2b['won_under'].mean()*100:.1f}% under win" if len(b2b)>0 else "\nB2B: 0 bets")
    print(f"Rested: {len(rested)} bets, {rested['won_under'].mean()*100:.1f}% under win")

    # Starter vs backup
    starters = dz[dz['is_starter']==1]
    backups = dz[dz['is_starter']!=1]
    print(f"\nStarters: {len(starters)} bets, {starters['won_under'].mean()*100:.1f}% under win" if len(starters)>0 else "")
    print(f"Backups: {len(backups)} bets, {backups['won_under'].mean()*100:.1f}% under win" if len(backups)>0 else "")

    # Day of week
    print("\nDay of week:")
    for day, group in dz.groupby('day_of_week'):
        print(f"  {day}: {len(group)} bets, {group['won_under'].mean()*100:.1f}% under win")

    # Goalie frequency
    print("\nMost frequent goalies in dead zone:")
    for goalie, group in dz.groupby('goalie'):
        if len(group) >= 2:
            print(f"  {goalie}: {len(group)} bets, {group['won_under'].mean()*100:.1f}% under win, avg saves {group['saves'].mean():.1f} vs line {group['line'].mean():.1f}")

    # Opponent frequency
    print("\nMost frequent opponents in dead zone:")
    for opp, group in dz.groupby('opp_abbr'):
        if len(group) >= 2:
            print(f"  vs {opp}: {len(group)} bets, {group['won_under'].mean()*100:.1f}% under win")

    # Line movement
    print(f"\nLine movement: avg {dz['line_movement'].mean():+.2f}")
    print(f"  Dropped (≤-0.5): {len(dz[dz['line_movement']<=-0.5])} bets, {dz[dz['line_movement']<=-0.5]['won_under'].mean()*100:.1f}% win" if len(dz[dz['line_movement']<=-0.5])>0 else "")
    print(f"  Stable: {len(dz[dz['line_movement'].between(-0.5,0.5)])} bets, {dz[dz['line_movement'].between(-0.5,0.5)]['won_under'].mean()*100:.1f}% win")
    print(f"  Rose (≥0.5): {len(dz[dz['line_movement']>=0.5])} bets, {dz[dz['line_movement']>=0.5]['won_under'].mean()*100:.1f}% win" if len(dz[dz['line_movement']>=0.5])>0 else "")

    # Actual saves distribution in dead zone
    print("\nSaves distribution in dead zone:")
    print(f"  Mean saves: {dz['saves'].mean():.1f}, Mean line: {dz['line'].mean():.1f}, Mean pred: {dz['pred'].mean():.1f}")
    print(f"  Saves > line (over): {(dz['saves']>dz['line']).sum()} ({(dz['saves']>dz['line']).mean()*100:.1f}%)")
    print(f"  Saves = line (push): {(dz['saves']==dz['line']).sum()}")
    print(f"  Saves < line (under): {(dz['saves']<dz['line']).sum()} ({(dz['saves']<dz['line']).mean()*100:.1f}%)")

    # Compare dead zone to adjacent good buckets
    print("\n\n=== COMPARISON WITH GOOD BUCKETS ===")
    for split in splits:
        model = lgb.LGBMRegressor(objective='regression', num_leaves=10, max_depth=4,
                                   min_child_samples=50, learning_rate=0.05, n_estimators=300,
                                   verbose=-1, reg_alpha=0.5, reg_lambda=0.5,
                                   feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=5)
        train = split['train'].dropna(subset=['saves'])
        tv = train[feats].notna().any(axis=1)
        model.fit(train[tv][feats].fillna(-999), train[tv]['saves'])

        val = split['val'].dropna(subset=['saves','line','over_odds','under_odds']).copy()
        vf = val[val[feats].notna().any(axis=1)]
        val.loc[vf.index, 'pred'] = model.predict(vf[feats].fillna(-999))
        val = val.dropna(subset=['pred','opp_corsi_pct_avg_10'])
        val['gap'] = np.abs(val['pred'] - val['line'])
        val['model_side'] = np.where(val['pred'] > val['line'], 'over', 'under')
        q25 = val['opp_corsi_pct_avg_10'].quantile(0.25)
        base = val[(val['model_side']=='under') & (val['opp_corsi_pct_avg_10']<q25)]

        good_low = base[(base['gap']>=1.0)&(base['gap']<1.5)]
        dead = base[(base['gap']>=1.5)&(base['gap']<2.5)]
        good_high = base[base['gap']>=2.5]

        print(f"\n  {split['name']}:")
        for label, subset in [('Good [1.0-1.5)', good_low), ('Dead [1.5-2.5)', dead), ('Good [2.5+]', good_high)]:
            if len(subset) > 0:
                avg_corsi = subset['opp_corsi_pct_avg_10'].mean()
                avg_rest = subset['days_rest'].mean()
                avg_svpct = subset['svpct_avg_10'].mean() if 'svpct_avg_10' in subset.columns else 0
                pct_home = subset['is_home'].mean() * 100
                wr = (subset['saves'] < subset['line']).mean() * 100
                print(f"    {label:20s}: {len(subset):3d} bets, {wr:.0f}% under, avgCorsi {avg_corsi:.3f}, avgRest {avg_rest:.1f}d, home {pct_home:.0f}%, svpct {avg_svpct:.3f}")

    # Write dead_zone_analysis.md
    dz[~dz['won_under']]
    dz[dz['won_under']]

    lines = ["# Dead Zone Analysis — MF3 Gap [1.5-2.5)\n"]
    lines.append(f"**{len(dz)} bets, {dz['won_under'].mean()*100:.1f}% under win rate (vs 66%+ in adjacent buckets)**\n")

    lines.append("## Summary")
    # Build summary based on findings
    home_wr = home['won_under'].mean()*100 if len(home)>0 else 0
    away_wr = away['won_under'].mean()*100 if len(away)>0 else 0
    lines.append(f"- Home/Away split: Home {home_wr:.0f}% ({len(home)}) vs Away {away_wr:.0f}% ({len(away)}) under win rate")

    if len(b2b) > 0:
        lines.append(f"- B2B goalies: {len(b2b)} bets at {b2b['won_under'].mean()*100:.0f}% vs rested {rested['won_under'].mean()*100:.0f}%")

    lines.append(f"- Avg saves: {dz['saves'].mean():.1f} vs avg line: {dz['line'].mean():.1f} vs avg prediction: {dz['pred'].mean():.1f}")
    lines.append("- The model predicts correctly (pred < line) but actual saves cluster right around the line, leading to over-hits")
    lines.append("")

    lines.append("## Bet Details")
    lines.append("| Date | Goalie | Team | Opp | H/A | Line | Saves | Pred | Gap | Corsi | Rest | Result |")
    lines.append("|------|--------|------|-----|-----|------|-------|------|-----|-------|------|--------|")
    for _, r in dz.sort_values('event_date').iterrows():
        ha = 'H' if r['is_home']==1 else 'A'
        res = '✅' if r['won_under'] else '❌'
        lines.append(f"| {str(r['event_date'].date())} | {str(r['goalie'])[:18]} | {r['team_abbr']} | {r['opp_abbr']} | {ha} | {r['line']:.1f} | {r['saves']:.0f} | {r['pred']:.1f} | {r['gap']:.1f} | {r['opp_corsi_pct_avg_10']:.3f} | {r['days_rest']:.0f}d | {res} |")
    lines.append("")

    with open(MODEL_DIR / 'dead_zone_analysis.md', 'w') as f:
        f.write('\n'.join(lines))
    print(f"\n\nSaved to {MODEL_DIR / 'dead_zone_analysis.md'}")

if __name__ == '__main__':
    main()
