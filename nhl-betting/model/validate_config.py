"""Strategy configurations and data preparation for validation diagnostics."""

import os
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2

warnings.filterwarnings('ignore')

DB_CONN = os.environ.get("DATABASE_URL", "postgresql://nhc_agent@localhost:5432/nhl_betting")
MODEL_DIR = Path(__file__).resolve().parent


def load_matrix():
    return pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')


def derive_corsi_features(matrix):
    conn = psycopg2.connect(DB_CONN)
    gts = pd.read_sql("SELECT * FROM game_team_stats", conn)
    games = pd.read_sql("""
        SELECT game_id, game_date, home_team_id, away_team_id
        FROM games WHERE home_score IS NOT NULL AND game_type IN (2,3) AND game_state='OFF'
    """, conn)
    conn.close()

    gts_merged = gts.merge(games[['game_id', 'game_date', 'home_team_id', 'away_team_id']], on='game_id', how='inner')
    team_games = gts_merged[['game_id', 'team_id', 'shots_attempted', 'shots_on_goal', 'blocked_shots',
                              'faceoff_win_pct', 'takeaways', 'giveaways', 'game_date']].copy()
    opp = gts_merged[['game_id', 'team_id', 'shots_attempted', 'shots_on_goal', 'blocked_shots',
                       'faceoff_win_pct', 'takeaways', 'giveaways']].copy()
    opp.columns = ['game_id', 'opp_team_id', 'opp_shots_attempted', 'opp_sog', 'opp_blocked',
                   'opp_faceoff_pct', 'opp_takeaways', 'opp_giveaways']

    merged = team_games.merge(games[['game_id', 'home_team_id', 'away_team_id']], on='game_id')
    merged['opp_team_id'] = np.where(merged['team_id'] == merged['home_team_id'],
                                      merged['away_team_id'], merged['home_team_id'])
    merged = merged.merge(opp, on=['game_id', 'opp_team_id'], how='left')

    merged['corsi_pct'] = merged['shots_attempted'] / (merged['shots_attempted'] + merged['opp_shots_attempted'])
    merged['corsi_diff'] = merged['shots_attempted'] - merged['opp_shots_attempted']
    merged['puck_control'] = merged['takeaways'] - merged['giveaways']
    merged = merged.sort_values(['team_id', 'game_date'])

    new_feats = []
    for tid, group in merged.groupby('team_id'):
        g = group.copy().sort_values('game_date')
        for w in [5, 10, 20]:
            g[f'corsi_pct_avg_{w}'] = g['corsi_pct'].rolling(w, min_periods=3).mean().shift(1)
            g[f'corsi_diff_avg_{w}'] = g['corsi_diff'].rolling(w, min_periods=3).mean().shift(1)
            g[f'puck_control_avg_{w}'] = g['puck_control'].rolling(w, min_periods=3).mean().shift(1)
        new_feats.append(g)

    corsi_df = pd.concat(new_feats, ignore_index=True)
    corsi_cols = [c for c in corsi_df.columns if c.endswith(('_5', '_10', '_20')) and
                  any(c.startswith(p) for p in ['corsi_pct', 'corsi_diff', 'puck_control'])]

    opp_corsi = corsi_df[['game_id', 'team_id'] + corsi_cols].copy()
    opp_corsi = opp_corsi.rename(columns={c: f'opp_{c}' for c in corsi_cols})
    matrix = matrix.merge(opp_corsi, left_on=['game_id', 'opponent_team_id'],
                           right_on=['game_id', 'team_id'], how='left', suffixes=('', '_corsi_opp'))

    own_corsi = corsi_df[['game_id', 'team_id'] + corsi_cols].copy()
    own_corsi = own_corsi.rename(columns={c: f'own_{c}' for c in corsi_cols})
    matrix = matrix.merge(own_corsi, left_on=['game_id', 'team_id'],
                           right_on=['game_id', 'team_id'], how='left', suffixes=('', '_corsi_own'))
    return matrix


def walk_forward_split(matrix):
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    splits = [
        {'name': '22-23→23-24', 'label': 'S1',
         'train': matrix[matrix['event_date'] < '2023-10-01'],
         'val': matrix[(matrix['event_date'] >= '2023-10-01') & (matrix['event_date'] < '2024-10-01')]},
        {'name': '22-24→24-25', 'label': 'S2',
         'train': matrix[matrix['event_date'] < '2024-10-01'],
         'val': matrix[(matrix['event_date'] >= '2024-10-01') & (matrix['event_date'] < '2025-10-01')]},
        {'name': '22-25→25-26', 'label': 'S3',
         'train': matrix[matrix['event_date'] < '2025-10-01'],
         'val': matrix[matrix['event_date'] >= '2025-10-01']},
    ]
    return [s for s in splits if len(s['train']) > 100 and len(s['val']) > 50]


def calc_payout(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, 100 / (-odds), odds / 100)


def simulate_bets_detailed(df, side):
    """Return per-bet results with game_id."""
    results = []
    for _, row in df.iterrows():
        if side == 'over':
            won = row['saves'] > row['line']
            push = row['saves'] == row['line']
            payout = calc_payout(np.array([row['over_odds']]))[0]
        else:
            won = row['saves'] < row['line']
            push = row['saves'] == row['line']
            payout = calc_payout(np.array([row['under_odds']]))[0]

        profit = 0 if push else (payout if won else -1)
        results.append({
            'game_id': row['game_id'],
            'player_id': row['player_id'],
            'event_date': row['event_date'],
            'line': row['line'],
            'saves': row['saves'],
            'over_odds': row['over_odds'],
            'under_odds': row['under_odds'],
            'line_movement': row.get('line_movement', 0),
            'opening_line': row.get('opening_line', row['line']),
            'side': side,
            'won': won and not push,
            'push': push,
            'profit': profit,
        })
    return pd.DataFrame(results)


def get_strategy_bets(matrix, splits):
    """Return dict of {strategy_name: DataFrame of bets per split}."""
    strategies = {}

    feats = ['sa_avg_10', 'sa_avg_20', 'svpct_avg_10', 'svpct_avg_20', 'is_home',
             'opp_team_sog_avg_10', 'days_rest', 'own_def_missing_toi',
             'opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10',
             'own_corsi_pct_avg_10', 'pull_rate_10', 'starts_last_7d',
             'opp_team_pp_opps_avg_10', 'line']
    feats = [f for f in feats if f in matrix.columns]

    for sname in ['PF1_over_corsi3', 'PF2_over_corsi_puck', 'MF1_under_model2_corsi_diff',
                    'MF2_under_model2_b2b', 'MF3_under_model1_corsi']:
        strategies[sname] = {}

    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['line', 'saves', 'over_odds', 'under_odds'])

        train = split['train'].dropna(subset=['saves'])
        t_valid = train[feats].notna().any(axis=1)
        v_valid = val[feats].notna().any(axis=1)
        train_f = train[t_valid]
        val_f = val[v_valid]

        model = lgb.LGBMRegressor(objective='regression', num_leaves=10, max_depth=4,
                                   min_child_samples=50, learning_rate=0.05, n_estimators=300,
                                   verbose=-1, reg_alpha=0.5, reg_lambda=0.5,
                                   feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=5)
        model.fit(train_f[feats].fillna(-999), train_f['saves'])
        val = val.copy()
        val['pred'] = np.nan
        pred_mask = val.index.isin(val_f.index)
        val.loc[pred_mask, 'pred'] = model.predict(val_f[feats].fillna(-999))
        val['model_gap'] = np.abs(val['pred'] - val['line'])
        val['model_side'] = np.where(val['pred'] > val['line'], 'over', 'under')

        sname = split['label']

        # PF1
        if 'opp_corsi_pct_avg_10' in val.columns and 'opp_corsi_diff_avg_10' in val.columns and 'opp_puck_control_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10', 'opp_puck_control_avg_10'])
            mask = ((v['opp_corsi_pct_avg_10'] > v['opp_corsi_pct_avg_10'].quantile(0.75)) &
                    (v['opp_corsi_diff_avg_10'] > v['opp_corsi_diff_avg_10'].quantile(0.75)) &
                    (v['opp_puck_control_avg_10'] > v['opp_puck_control_avg_10'].quantile(0.75)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['PF1_over_corsi3'][sname] = simulate_bets_detailed(filtered, 'over')

        # PF2
        if 'opp_corsi_pct_avg_10' in val.columns and 'opp_puck_control_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_pct_avg_10', 'opp_puck_control_avg_10'])
            mask = ((v['opp_corsi_pct_avg_10'] > v['opp_corsi_pct_avg_10'].quantile(0.75)) &
                    (v['opp_puck_control_avg_10'] > v['opp_puck_control_avg_10'].quantile(0.75)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['PF2_over_corsi_puck'][sname] = simulate_bets_detailed(filtered, 'over')

        # MF1
        if 'opp_corsi_diff_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_diff_avg_10', 'pred'])
            mask = ((v['model_side'] == 'under') & (v['model_gap'] >= 2) &
                    (v['opp_corsi_diff_avg_10'] < v['opp_corsi_diff_avg_10'].quantile(0.25)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['MF1_under_model2_corsi_diff'][sname] = simulate_bets_detailed(filtered, 'under')

        # MF2
        v = val.dropna(subset=['pred', 'days_rest'])
        mask = ((v['model_side'] == 'under') & (v['model_gap'] >= 2) & (v['days_rest'] <= 1))
        filtered = v[mask]
        if len(filtered) > 0:
            strategies['MF2_under_model2_b2b'][sname] = simulate_bets_detailed(filtered, 'under')

        # MF3
        if 'opp_corsi_pct_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_pct_avg_10', 'pred'])
            mask = ((v['model_side'] == 'under') & (v['model_gap'] >= 1) &
                    (v['opp_corsi_pct_avg_10'] < v['opp_corsi_pct_avg_10'].quantile(0.25)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['MF3_under_model1_corsi'][sname] = simulate_bets_detailed(filtered, 'under')

    return strategies
