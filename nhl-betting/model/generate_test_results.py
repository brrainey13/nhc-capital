#!/usr/bin/env python3
"""Generate TESTRESULTS.md with bet-by-bet results for all proven strategies."""

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
DOCS_DIR = Path('/Users/connorrainey/nhc-capital/nhl-betting/docs')

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
    teams = pd.read_sql("SELECT team_id, tri_code FROM teams", conn)
    players = pd.read_sql("SELECT player_id, first_name, last_name FROM players", conn)
    conn.close()

    teams_map = teams.set_index('team_id')['tri_code'].to_dict()
    players['full_name'] = players['first_name'] + ' ' + players['last_name']
    players_map = players.set_index('player_id')['full_name'].to_dict()

    # Corsi
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
        matrix = matrix.merge(tmp, left_on=['game_id', on_col], right_on=['game_id','team_id'],
                               how='left', suffixes=('', f'_{prefix}drop'))
        matrix = matrix.drop(columns=[c for c in matrix.columns if c.endswith(f'_{prefix}drop')], errors='ignore')

    return matrix, teams_map, players_map


def get_splits(matrix):
    return [
        {'name':'Season 1 (23-24)', 'train': matrix[matrix['event_date']<'2023-10-01'],
         'val': matrix[(matrix['event_date']>='2023-10-01')&(matrix['event_date']<'2024-10-01')]},
        {'name':'Season 2 (24-25)', 'train': matrix[matrix['event_date']<'2024-10-01'],
         'val': matrix[(matrix['event_date']>='2024-10-01')&(matrix['event_date']<'2025-10-01')]},
        {'name':'Season 3 (25-26)', 'train': matrix[matrix['event_date']<'2025-10-01'],
         'val': matrix[matrix['event_date']>='2025-10-01']},
    ]


def calc_payout(odds):
    odds = float(odds)
    return 100 / (-odds) if odds < 0 else odds / 100


def collect_bets(matrix, splits, teams_map, players_map):
    feats = [f for f in FEATS if f in matrix.columns]
    all_strat_bets = {s: [] for s in ['MF3a', 'MF3b', 'MF2', 'MF5', 'PF1']}

    for split in splits:
        if len(split['train']) < 100 or len(split['val']) < 50:
            continue

        # Train model
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
        val['goalie'] = val['player_id'].map(players_map)
        val['team_abbr'] = val['team_id'].map(teams_map)
        val['opp_abbr'] = val['opponent_team_id'].map(teams_map)
        val['season'] = split['name']

        # MF3a: under, gap [1.0-1.5), bottom 25% Corsi
        if 'opp_corsi_pct_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_pct_avg_10'])
            q25 = v['opp_corsi_pct_avg_10'].quantile(0.25)
            q30 = v['opp_corsi_pct_avg_10'].quantile(0.30)

            mf3a = v[(v['model_side']=='under') & (v['gap']>=1.0) & (v['gap']<1.5) & (v['opp_corsi_pct_avg_10']<q25)]
            for _, r in mf3a.iterrows():
                all_strat_bets['MF3a'].append(make_row(r, 'UNDER'))

            # MF3b: under, gap >=2.5, bottom 25% Corsi
            mf3b = v[(v['model_side']=='under') & (v['gap']>=2.5) & (v['opp_corsi_pct_avg_10']<q25)]
            for _, r in mf3b.iterrows():
                all_strat_bets['MF3b'].append(make_row(r, 'UNDER'))

            # MF5: under, gap >=1.0, bottom 30% Corsi (skip dead zone)
            mf5 = v[(v['model_side']=='under') & (v['gap']>=1.0) & (v['opp_corsi_pct_avg_10']<q30) &
                     ~((v['gap']>=1.5) & (v['gap']<2.5))]
            for _, r in mf5.iterrows():
                all_strat_bets['MF5'].append(make_row(r, 'UNDER'))

        # MF2: under, gap >=2.0, B2B
        mf2 = val[(val['model_side']=='under') & (val['gap']>=2.0) & (val['days_rest']<=1)]
        for _, r in mf2.iterrows():
            all_strat_bets['MF2'].append(make_row(r, 'UNDER'))

        # PF1: over, triple corsi top 25%
        if all(c in val.columns for c in ['opp_corsi_pct_avg_10','opp_corsi_diff_avg_10','opp_puck_control_avg_10']):
            v = val.dropna(subset=['opp_corsi_pct_avg_10','opp_corsi_diff_avg_10','opp_puck_control_avg_10'])
            pf1 = v[(v['opp_corsi_pct_avg_10'] > v['opp_corsi_pct_avg_10'].quantile(0.75)) &
                     (v['opp_corsi_diff_avg_10'] > v['opp_corsi_diff_avg_10'].quantile(0.75)) &
                     (v['opp_puck_control_avg_10'] > v['opp_puck_control_avg_10'].quantile(0.75))]
            for _, r in pf1.iterrows():
                all_strat_bets['PF1'].append(make_row(r, 'OVER'))

    return all_strat_bets


def make_row(r, side):
    ha = 'H' if r['is_home'] == 1 else 'A'
    if side == 'UNDER':
        won = r['saves'] < r['line']
        push = r['saves'] == r['line']
        payout = calc_payout(r['under_odds'])
    else:
        won = r['saves'] > r['line']
        push = r['saves'] == r['line']
        payout = calc_payout(r['over_odds'])

    profit = 0 if push else (payout if won else -1)
    result = '🔵 P' if push else ('✅' if won else '❌')

    return {
        'date': str(r['event_date'].date()),
        'goalie': str(r.get('goalie', r.get('player_name', '?')))[:20],
        'team': str(r.get('team_abbr', '?')),
        'opp': str(r.get('opp_abbr', '?')),
        'ha': ha,
        'line': r['line'],
        'saves': int(r['saves']),
        'pred': round(r['pred'], 1),
        'gap': round(r['gap'], 1),
        'corsi': round(r.get('opp_corsi_pct_avg_10', 0), 3),
        'rest': f"{int(r['days_rest'])}d",
        'result': result,
        'side': side,
        'profit': round(profit, 3),
        'won': won and not push,
        'season': r.get('season', ''),
    }


def write_results(all_strat_bets):
    lines = ["# Test Results — Proven Strategies\n"]
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} | **Data:** 2,795 games, 3-season walk-forward\n")

    for strat_name in ['MF3a', 'MF3b', 'MF2', 'MF5', 'PF1']:
        bets = all_strat_bets[strat_name]
        if not bets:
            continue

        bets_sorted = sorted(bets, key=lambda x: x['date'])
        wins = sum(1 for b in bets if b['won'])
        n = len(bets)
        total_profit = sum(b['profit'] for b in bets)
        roi = (total_profit / n) * 100 if n > 0 else 0
        wr = wins / n * 100 if n > 0 else 0

        side = bets[0]['side']
        lines.append(f"## {strat_name} — {side} ({n} bets, {wr:.1f}% win, {roi:+.1f}% ROI)\n")
        lines.append("| Date | Goalie | Team | Opp | H/A | Line | Saves | Pred | Gap | Corsi | Rest | Result |")
        lines.append("|------|--------|------|-----|-----|------|-------|------|-----|-------|------|--------|")

        season_stats = {}
        for b in bets_sorted:
            lines.append(f"| {b['date']} | {b['goalie']} | {b['team']} | {b['opp']} | {b['ha']} | {b['line']:.1f} | {b['saves']} | {b['pred']} | {b['gap']} | {b['corsi']} | {b['rest']} | {b['result']} |")
            s = b['season']
            if s not in season_stats:
                season_stats[s] = {'wins': 0, 'n': 0, 'profit': 0}
            season_stats[s]['n'] += 1
            season_stats[s]['wins'] += int(b['won'])
            season_stats[s]['profit'] += b['profit']

        lines.append("\n**Per-season breakdown:**")
        for s, st in season_stats.items():
            sr = (st['profit']/st['n'])*100 if st['n']>0 else 0
            sw = st['wins']/st['n']*100 if st['n']>0 else 0
            lines.append(f"- {s}: {st['n']} bets, {sw:.0f}% win, {sr:+.1f}% ROI")
        lines.append(f"- **Total: {n} bets, {wr:.1f}% win, {roi:+.1f}% ROI, {total_profit:+.1f} units**\n")
        lines.append("---\n")

    out_path = DOCS_DIR / 'TESTRESULTS.md'
    with open(out_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"Written to {out_path}")
    print(f"Strategies: {', '.join(s for s in all_strat_bets if all_strat_bets[s])}")
    for s, bets in all_strat_bets.items():
        if bets:
            wins = sum(1 for b in bets if b['won'])
            print(f"  {s}: {len(bets)} bets, {wins}/{len(bets)} wins ({wins/len(bets)*100:.1f}%)")


def main():
    print("Loading data...")
    matrix, teams_map, players_map = load_and_prepare()
    splits = get_splits(matrix)
    print(f"{len(matrix)} rows, {len(splits)} splits")

    print("Collecting bets...")
    all_bets = collect_bets(matrix, splits, teams_map, players_map)

    print("Writing results...")
    write_results(all_bets)


if __name__ == '__main__':
    main()
