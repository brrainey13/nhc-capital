#!/usr/bin/env python3
"""
Iterative goalie saves O/U strategy research.
Each run tests 5 strategies, logs findings to strategy.md.
Arg: --round N (which 30-min round, 1-8)
"""

import argparse
import json
import warnings
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2
from sklearn.metrics import mean_absolute_error

warnings.filterwarnings('ignore')

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"
MODEL_DIR = Path('/Users/connorrainey/nhc-capital/nhl-betting/model')
STRATEGY_FILE = MODEL_DIR / 'strategy.md'


def load_matrix():
    return pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')


def walk_forward_split(matrix):
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    splits = [
        {'name': '22-23→23-24',
         'train': matrix[matrix['event_date'] < '2023-10-01'],
         'val': matrix[(matrix['event_date'] >= '2023-10-01') & (matrix['event_date'] < '2024-10-01')]},
        {'name': '22-24→24-25',
         'train': matrix[matrix['event_date'] < '2024-10-01'],
         'val': matrix[(matrix['event_date'] >= '2024-10-01') & (matrix['event_date'] < '2025-10-01')]},
        {'name': '22-25→25-26',
         'train': matrix[matrix['event_date'] < '2025-10-01'],
         'val': matrix[matrix['event_date'] >= '2025-10-01']},
    ]
    return [s for s in splits if len(s['train']) > 100 and len(s['val']) > 50]


def american_to_prob(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, -odds / (-odds + 100), 100 / (odds + 100))


def calc_payout(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, 100 / (-odds), odds / 100)


def eval_betting_strategy(val_df, pred_col, line_col='line'):
    """Evaluate a prediction as a betting strategy. Returns ROI, win_rate, n_bets."""
    df = val_df.dropna(subset=[pred_col, line_col, 'over_odds', 'under_odds', 'saves']).copy()
    if len(df) < 20:
        return None

    profits = []
    for _, row in df.iterrows():
        if row[pred_col] > row[line_col]:
            won = row['saves'] > row[line_col]
            payout = calc_payout(np.array([row['over_odds']]))[0]
        else:
            won = row['saves'] < row[line_col]
            payout = calc_payout(np.array([row['under_odds']]))[0]

        if row['saves'] == row[line_col]:
            profits.append(0)
        elif won:
            profits.append(payout)
        else:
            profits.append(-1)

    n = len(profits)
    wins = sum(1 for p in profits if p > 0)
    roi = (sum(profits) / n) * 100 if n > 0 else 0
    return {'roi': round(roi, 2), 'win_rate': round(wins/n*100, 1), 'n_bets': n}


def eval_filtered_strategy(val_df, pred_col, filter_mask, side='best'):
    """Evaluate betting only on filtered subset."""
    df = val_df[filter_mask].dropna(subset=[pred_col, 'line', 'over_odds', 'under_odds', 'saves']).copy()
    if len(df) < 10:
        return None

    profits = []
    for _, row in df.iterrows():
        if side == 'over':
            won = row['saves'] > row['line']
            payout = calc_payout(np.array([row['over_odds']]))[0]
        elif side == 'under':
            won = row['saves'] < row['line']
            payout = calc_payout(np.array([row['under_odds']]))[0]
        else:  # best
            if row[pred_col] > row['line']:
                won = row['saves'] > row['line']
                payout = calc_payout(np.array([row['over_odds']]))[0]
            else:
                won = row['saves'] < row['line']
                payout = calc_payout(np.array([row['under_odds']]))[0]

        if row['saves'] == row['line']:
            profits.append(0)
        elif won:
            profits.append(payout)
        else:
            profits.append(-1)

    n = len(profits)
    if n < 10:
        return None
    wins = sum(1 for p in profits if p > 0)
    roi = (sum(profits) / n) * 100
    return {'roi': round(roi, 2), 'win_rate': round(wins/n*100, 1), 'n_bets': n}


def derive_corsi_features(matrix):
    """Derive Corsi and possession proxies from game_team_stats."""
    conn = psycopg2.connect(DB_CONN)

    gts = pd.read_sql("SELECT * FROM game_team_stats", conn)
    games = pd.read_sql("""
        SELECT game_id, game_date, home_team_id, away_team_id
        FROM games WHERE home_score IS NOT NULL AND game_type IN (2,3) AND game_state='OFF'
    """, conn)
    conn.close()

    # Corsi For = shots_attempted, Corsi Against = opponent's shots_attempted
    # Fenwick = shots_attempted - blocked_shots (unblocked attempts)
    gts_merged = gts.merge(games[['game_id', 'game_date', 'home_team_id', 'away_team_id']], on='game_id', how='inner')

    # Get opponent stats for each team in each game
    gts_merged[gts_merged['is_home']][['game_id', 'team_id', 'shots_attempted', 'shots_on_goal', 'blocked_shots',
                                                        'faceoff_win_pct', 'takeaways', 'giveaways']].copy()
    gts_merged[not gts_merged['is_home']][['game_id', 'team_id', 'shots_attempted', 'shots_on_goal', 'blocked_shots',
                                                         'faceoff_win_pct', 'takeaways', 'giveaways']].copy()

    # For each team, get their CF and CA per game
    team_games = gts_merged[['game_id', 'team_id', 'shots_attempted', 'shots_on_goal', 'blocked_shots',
                              'faceoff_win_pct', 'takeaways', 'giveaways', 'game_date']].copy()

    # Get opponent's shots_attempted as CA
    opp = gts_merged[['game_id', 'team_id', 'shots_attempted', 'shots_on_goal', 'blocked_shots',
                       'faceoff_win_pct', 'takeaways', 'giveaways']].copy()
    opp.columns = ['game_id', 'opp_team_id', 'opp_shots_attempted', 'opp_sog', 'opp_blocked',
                   'opp_faceoff_pct', 'opp_takeaways', 'opp_giveaways']

    # Merge: each game has 2 rows per team, opponent is the other team
    merged = team_games.merge(games[['game_id', 'home_team_id', 'away_team_id']], on='game_id')
    merged['opp_team_id'] = np.where(merged['team_id'] == merged['home_team_id'],
                                      merged['away_team_id'], merged['home_team_id'])
    merged = merged.merge(opp, on=['game_id', 'opp_team_id'], how='left')

    # Corsi% = CF / (CF + CA)
    merged['corsi_for'] = merged['shots_attempted']
    merged['corsi_against'] = merged['opp_shots_attempted']
    merged['corsi_pct'] = merged['corsi_for'] / (merged['corsi_for'] + merged['corsi_against'])
    merged['corsi_diff'] = merged['corsi_for'] - merged['corsi_against']

    # Fenwick (unblocked)
    merged['fenwick_for'] = merged['shots_attempted'] - merged['opp_blocked']  # approximate
    merged['fenwick_against'] = merged['opp_shots_attempted'] - merged['blocked_shots']

    # Possession proxy: faceoff% + corsi% weighted
    merged['possession_proxy'] = 0.4 * merged['faceoff_win_pct'] / 100 + 0.6 * merged['corsi_pct']

    # Puck control: takeaways - giveaways
    merged['puck_control'] = merged['takeaways'] - merged['giveaways']
    merged['opp_puck_control'] = merged['opp_takeaways'] - merged['opp_giveaways']

    merged = merged.sort_values(['team_id', 'game_date'])

    # Rolling averages
    new_feats = []
    for tid, group in merged.groupby('team_id'):
        g = group.copy().sort_values('game_date')
        for w in [5, 10, 20]:
            g[f'corsi_pct_avg_{w}'] = g['corsi_pct'].rolling(w, min_periods=3).mean().shift(1)
            g[f'corsi_diff_avg_{w}'] = g['corsi_diff'].rolling(w, min_periods=3).mean().shift(1)
            g[f'possession_avg_{w}'] = g['possession_proxy'].rolling(w, min_periods=3).mean().shift(1)
            g[f'puck_control_avg_{w}'] = g['puck_control'].rolling(w, min_periods=3).mean().shift(1)
            g[f'opp_puck_control_avg_{w}'] = g['opp_puck_control'].rolling(w, min_periods=3).mean().shift(1)
            g[f'faceoff_pct_avg_{w}'] = g['faceoff_win_pct'].rolling(w, min_periods=3).mean().shift(1)
        new_feats.append(g)

    corsi_df = pd.concat(new_feats, ignore_index=True)

    # Now merge into matrix — need opponent's Corsi features for goalie
    # Goalie faces opponent's offense, so we want opponent's corsi stats
    opp_corsi_cols = [c for c in corsi_df.columns if c.endswith(('_5', '_10', '_20')) and
                      any(c.startswith(p) for p in ['corsi_pct', 'corsi_diff', 'possession', 'puck_control', 'faceoff_pct', 'opp_puck'])]

    # Merge as opponent features
    opp_corsi = corsi_df[['game_id', 'team_id'] + opp_corsi_cols].copy()
    opp_rename = {c: f'opp_{c}' for c in opp_corsi_cols}
    opp_corsi = opp_corsi.rename(columns=opp_rename)

    matrix_new = matrix.merge(
        opp_corsi,
        left_on=['game_id', 'opponent_team_id'],
        right_on=['game_id', 'team_id'],
        how='left',
        suffixes=('', '_corsi_opp')
    )

    # Also own team's corsi (defensive quality)
    own_corsi = corsi_df[['game_id', 'team_id'] + opp_corsi_cols].copy()
    own_rename = {c: f'own_{c}' for c in opp_corsi_cols}
    own_corsi = own_corsi.rename(columns=own_rename)

    matrix_new = matrix_new.merge(
        own_corsi,
        left_on=['game_id', 'team_id'],
        right_on=['game_id', 'team_id'],
        how='left',
        suffixes=('', '_corsi_own')
    )

    return matrix_new


# ======= STRATEGY FUNCTIONS (each round picks 5) =======

def strategy_baseline_lgbm(matrix, splits):
    """S1: Baseline LightGBM with existing features."""
    feats = ['sa_avg_10', 'sa_avg_20', 'svpct_avg_10', 'svpct_avg_20', 'is_home',
             'opp_team_sog_avg_10', 'days_rest', 'own_def_missing_toi']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_baseline')


def strategy_corsi_shots(matrix, splits):
    """S2: Use Corsi features to predict shots against."""
    feats = ['sa_avg_10', 'opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10',
             'opp_possession_avg_10', 'is_home', 'opp_team_sog_avg_10']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'shots_against', 'pred_corsi_shots')


def strategy_possession_saves(matrix, splits):
    """S3: Possession proxy features for saves prediction."""
    feats = ['sa_avg_10', 'svpct_avg_10', 'opp_possession_avg_10', 'own_possession_avg_10',
             'opp_puck_control_avg_10', 'own_puck_control_avg_10', 'is_home',
             'opp_faceoff_pct_avg_10', 'days_rest']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_possession')


def strategy_high_corsi_over(matrix, splits):
    """S4: Bet OVER when opponent has high Corsi%, UNDER when low."""
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'opp_corsi_pct_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['opp_corsi_pct_avg_10', 'line', 'saves', 'over_odds', 'under_odds'])
        if len(val) < 20:
            continue

        # Top quartile Corsi = bet over
        q75 = val['opp_corsi_pct_avg_10'].quantile(0.75)
        q25 = val['opp_corsi_pct_avg_10'].quantile(0.25)

        over_mask = val['opp_corsi_pct_avg_10'] > q75
        under_mask = val['opp_corsi_pct_avg_10'] < q25

        over_res = eval_filtered_strategy(val, 'saves_avg_10', over_mask, side='over')
        under_res = eval_filtered_strategy(val, 'saves_avg_10', under_mask, side='under')
        results.append({'split': split['name'], 'over_q75': over_res, 'under_q25': under_res})

    return results


def strategy_rest_filter(matrix, splits):
    """S5: Filter by rest days — B2B goalies go under."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['days_rest', 'line', 'saves', 'over_odds', 'under_odds'])
        if len(val) < 20:
            continue

        b2b_mask = val['days_rest'] <= 1
        rested_mask = val['days_rest'] >= 3

        b2b_under = eval_filtered_strategy(val, 'saves_avg_10', b2b_mask, side='under')
        rested_over = eval_filtered_strategy(val, 'saves_avg_10', rested_mask, side='over')
        results.append({'split': split['name'], 'b2b_under': b2b_under, 'rested_over': rested_over})

    return results


def strategy_line_movement(matrix, splits):
    """S6: Line movement as signal — big drops = under."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['line_movement', 'line', 'saves', 'over_odds', 'under_odds'])
        if len(val) < 20:
            continue

        drop_mask = val['line_movement'] <= -1  # line dropped 1+ saves
        rise_mask = val['line_movement'] >= 1

        drop_under = eval_filtered_strategy(val, 'saves_avg_10', drop_mask, side='under')
        rise_over = eval_filtered_strategy(val, 'saves_avg_10', rise_mask, side='over')
        results.append({'split': split['name'], 'line_drop_under': drop_under, 'line_rise_over': rise_over})

    return results


def strategy_svpct_mean_reversion(matrix, splits):
    """S7: Goalies with recent svpct well above season avg → under (regression)."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['svpct_avg_5', 'svpct_season_avg', 'line', 'saves'])
        if len(val) < 20:
            continue

        hot_mask = (val['svpct_avg_5'] - val['svpct_season_avg']) > 0.015
        cold_mask = (val['svpct_avg_5'] - val['svpct_season_avg']) < -0.015

        hot_under = eval_filtered_strategy(val, 'saves_avg_10', hot_mask, side='under')
        cold_over = eval_filtered_strategy(val, 'saves_avg_10', cold_mask, side='over')
        results.append({'split': split['name'], 'hot_under': hot_under, 'cold_over': cold_over})

    return results


def strategy_opp_missing_d(matrix, splits):
    """S8: Opponent missing defensemen → fewer shots → under for goalie."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['opp_def_missing', 'line', 'saves'])
        if len(val) < 20:
            continue

        opp_d_missing = val['opp_def_missing'] >= 2
        opp_d_full = val['opp_def_missing'] == 0

        missing_under = eval_filtered_strategy(val, 'saves_avg_10', opp_d_missing, side='under')
        full_over = eval_filtered_strategy(val, 'saves_avg_10', opp_d_full, side='over')
        results.append({'split': split['name'], 'opp_d_missing_under': missing_under, 'opp_d_full_over': full_over})

    return results


def strategy_corsi_lgbm(matrix, splits):
    """S9: Full LightGBM with Corsi + possession features added."""
    feats = ['sa_avg_10', 'sa_avg_20', 'svpct_avg_10', 'svpct_avg_20', 'is_home',
             'opp_team_sog_avg_10', 'days_rest', 'own_def_missing_toi',
             'opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10', 'opp_possession_avg_10',
             'own_corsi_pct_avg_10', 'own_possession_avg_10',
             'opp_puck_control_avg_10', 'own_puck_control_avg_10']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_corsi_lgbm')


def strategy_pull_under(matrix, splits):
    """S10: High pull probability → bet under."""
    pull_feats = ['svpct_avg_10', 'ga_avg_10', 'pull_rate_10', 'pull_rate_20',
                  'high_ga_rate_10', 'opp_team_sog_avg_10', 'is_home', 'days_rest']
    pull_feats = [f for f in pull_feats if f in matrix.columns]

    results = []
    for split in splits:
        train = split['train'].dropna(subset=['was_pulled'])
        val = split['val'].dropna(subset=['was_pulled'])
        train_valid = train[pull_feats].notna().any(axis=1)
        val_valid = val[pull_feats].notna().any(axis=1)
        train = train[train_valid]
        val = val[val_valid]
        if len(train) < 50 or len(val) < 20:
            continue

        model = lgb.LGBMClassifier(objective='binary', num_leaves=8, max_depth=3,
                                    min_child_samples=50, learning_rate=0.05, n_estimators=300,
                                    scale_pos_weight=5, verbose=-1)
        model.fit(train[pull_feats].fillna(-999), train['was_pulled'])
        probs = model.predict_proba(val[pull_feats].fillna(-999))[:, 1]

        for thresh in [0.20, 0.25, 0.30]:
            mask = probs > thresh
            res = eval_filtered_strategy(val, 'saves_avg_10', pd.Series(mask, index=val.index), side='under')
            if res:
                results.append({'split': split['name'], f'pull>{thresh}': res})

    return results


def strategy_extreme_lines(matrix, splits):
    """S11: Extreme lines (very high/low) tend to regress."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['line', 'saves', 'over_odds', 'under_odds'])
        if len(val) < 20:
            continue

        high_line = val['line'] >= val['line'].quantile(0.85)
        low_line = val['line'] <= val['line'].quantile(0.15)

        high_under = eval_filtered_strategy(val, 'saves_avg_10', high_line, side='under')
        low_over = eval_filtered_strategy(val, 'saves_avg_10', low_line, side='over')
        results.append({'split': split['name'], 'high_line_under': high_under, 'low_line_over': low_over})

    return results


def strategy_corsi_diff_threshold(matrix, splits):
    """S12: Strong Corsi diff teams generate more shots."""
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'opp_corsi_diff_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['opp_corsi_diff_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        strong_opp = val['opp_corsi_diff_avg_10'] > val['opp_corsi_diff_avg_10'].quantile(0.75)
        weak_opp = val['opp_corsi_diff_avg_10'] < val['opp_corsi_diff_avg_10'].quantile(0.25)

        strong_over = eval_filtered_strategy(val, 'saves_avg_10', strong_opp, side='over')
        weak_under = eval_filtered_strategy(val, 'saves_avg_10', weak_opp, side='under')
        results.append({'split': split['name'], 'strong_corsi_over': strong_over, 'weak_corsi_under': weak_under})

    return results


def strategy_faceoff_possession(matrix, splits):
    """S13: Faceoff % as possession proxy."""
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'opp_faceoff_pct_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['opp_faceoff_pct_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        good_fo = val['opp_faceoff_pct_avg_10'] > val['opp_faceoff_pct_avg_10'].quantile(0.75)
        bad_fo = val['opp_faceoff_pct_avg_10'] < val['opp_faceoff_pct_avg_10'].quantile(0.25)

        good_over = eval_filtered_strategy(val, 'saves_avg_10', good_fo, side='over')
        bad_under = eval_filtered_strategy(val, 'saves_avg_10', bad_fo, side='under')
        results.append({'split': split['name'], 'good_fo_over': good_over, 'bad_fo_under': bad_under})

    return results


def strategy_saves_vs_line_gap(matrix, splits):
    """S14: When rolling avg saves is far from line, bet the gap."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['saves_avg_10', 'line', 'saves', 'over_odds', 'under_odds'])
        if len(val) < 20:
            continue

        gap = val['saves_avg_10'] - val['line']
        over_gap = gap > 2  # avg 2+ saves above line
        under_gap = gap < -2

        over_res = eval_filtered_strategy(val, 'saves_avg_10', over_gap, side='over')
        under_res = eval_filtered_strategy(val, 'saves_avg_10', under_gap, side='under')
        results.append({'split': split['name'], 'avg_above_line_over': over_res, 'avg_below_line_under': under_res})

    return results


def strategy_home_away_split(matrix, splits):
    """S15: Home vs away goalie performance difference."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['is_home', 'line', 'saves'])
        if len(val) < 20:
            continue

        home = val['is_home'] == 1
        away = val['is_home'] == 0

        home_res = eval_filtered_strategy(val, 'saves_avg_10', home, side='over')
        away_res = eval_filtered_strategy(val, 'saves_avg_10', away, side='under')
        results.append({'split': split['name'], 'home_over': home_res, 'away_under': away_res})

    return results


def strategy_combined_corsi_rest(matrix, splits):
    """S16: Combine Corsi + rest for compound filter."""
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'opp_corsi_pct_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['opp_corsi_pct_avg_10', 'days_rest', 'line', 'saves'])
        if len(val) < 20:
            continue

        # Strong opponent + goalie on B2B
        compound_under = (val['opp_corsi_pct_avg_10'] > val['opp_corsi_pct_avg_10'].quantile(0.6)) & (val['days_rest'] <= 1)
        # Weak opponent + rested goalie
        compound_over = (val['opp_corsi_pct_avg_10'] < val['opp_corsi_pct_avg_10'].quantile(0.4)) & (val['days_rest'] >= 3)

        under_res = eval_filtered_strategy(val, 'saves_avg_10', compound_under, side='under')
        over_res = eval_filtered_strategy(val, 'saves_avg_10', compound_over, side='over')
        results.append({'split': split['name'], 'strong_opp_b2b_under': under_res, 'weak_opp_rested_over': over_res})

    return results


def strategy_period_scoring(matrix, splits):
    """S17: Teams that score early → opponent goalie pulled → under."""
    # We can derive this from period_scores
    conn = psycopg2.connect(DB_CONN)
    period_df = pd.read_sql("SELECT * FROM period_scores WHERE period_number=1", conn)
    conn.close()

    # Rolling 1st period goals for
    games_info = matrix[['game_id', 'opponent_team_id']].drop_duplicates()
    p1 = period_df.merge(games_info, left_on=['game_id', 'team_id'], right_on=['game_id', 'opponent_team_id'], how='inner')

    results = []
    for split in splits:
        val = split['val'].copy()
        # merge 1st period goals
        val = val.merge(p1[['game_id', 'team_id', 'goals']].rename(columns={'goals': 'opp_p1_goals', 'team_id': 'p1_team'}),
                        left_on=['game_id', 'opponent_team_id'], right_on=['game_id', 'p1_team'], how='left')
        # This is current game data = leakage for prediction, but useful to know the pattern
        # We'd need rolling 1st period averages for actual prediction
        results.append({'note': 'Need to build rolling P1 goals avg - deferred to next round'})

    return results


def strategy_workload_regression(matrix, splits):
    """S18: High recent workload (starts_last_7d >= 3) → regression."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['starts_last_7d', 'line', 'saves'])
        if len(val) < 20:
            continue

        heavy = val['starts_last_7d'] >= 3
        light = val['starts_last_7d'] <= 1

        heavy_under = eval_filtered_strategy(val, 'saves_avg_10', heavy, side='under')
        light_over = eval_filtered_strategy(val, 'saves_avg_10', light, side='over')
        results.append({'split': split['name'], 'heavy_load_under': heavy_under, 'light_load_over': light_over})

    return results


def strategy_wide_corsi_lgbm(matrix, splits):
    """S19: LightGBM with all Corsi windows (5/10/20)."""
    feats = ['sa_avg_5', 'sa_avg_10', 'sa_avg_20', 'svpct_avg_5', 'svpct_avg_10', 'svpct_avg_20',
             'is_home', 'days_rest', 'opp_team_sog_avg_10',
             'opp_corsi_pct_avg_5', 'opp_corsi_pct_avg_10', 'opp_corsi_pct_avg_20',
             'opp_corsi_diff_avg_5', 'opp_corsi_diff_avg_10', 'opp_corsi_diff_avg_20',
             'opp_possession_avg_5', 'opp_possession_avg_10', 'opp_possession_avg_20',
             'own_corsi_pct_avg_10', 'own_possession_avg_10',
             'opp_puck_control_avg_10', 'own_puck_control_avg_10',
             'own_def_missing_toi', 'opp_faceoff_pct_avg_10']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_wide_corsi')


def strategy_ev_strength_focus(matrix, splits):
    """S20: Even-strength save% and shot splits as primary features."""
    feats = ['ev_svpct_avg_10', 'ev_svpct_avg_20', 'ev_shots_avg_10', 'ev_shots_avg_20',
             'pp_shots_avg_10', 'sh_shots_avg_10', 'is_home',
             'opp_team_pp_opps_avg_10', 'opp_team_sog_avg_10']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_ev_strength')


def strategy_kitchen_sink(matrix, splits):
    """S21: All available numeric features — test if more is better."""
    exclude = {'id', 'game_id', 'player_id', 'team_id', 'home_team_id', 'away_team_id',
               'opponent_team_id', 'event_id', 'event_date', 'game_date', 'game_date_str',
               'game_date_dt', 'player_name', 'player_team', 'home_team', 'away_team',
               'book_id', 'book_name', 'opening_created', 'updated_at', 'scraped_at',
               'is_best', 'bp_player_id', 'saves', 'shots_against', 'goals_against', 'save_pct',
               'went_over', 'went_under', 'save_diff', 'was_pulled',
               'fair_probability', 'market_ev',
               'team_id_opp', 'team_id_own', 'team_id_oppabs', 'team_id_ownabs', 'team_id_opprest',
               'team_id_corsi_opp', 'team_id_corsi_own'}
    feats = [c for c in matrix.columns if c not in exclude and matrix[c].dtype in ('float64', 'int64', 'int32', 'float32', 'bool')]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_kitchen_sink')


def strategy_opponent_blocked_shots(matrix, splits):
    """S22: Teams that block more → goalie faces fewer shots → under."""
    # own team's blocked shots = fewer saves for own goalie (they block the shot)
    # This is already captured in shots_on_goal vs shots_attempted diff
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'own_team_sa_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['own_team_sa_avg_10', 'opp_team_sa_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        # High block rate = (shots_attempted - shots_on_goal) / shots_attempted
        # own_team_sa = own shots_attempted, own_team_sog = own shots_on_goal
        # For goalie saves: opponent's shot attempts that get through
        # opp_sa = opponent shots attempted, opp_sog = opponent shots on goal
        # block_rate_against_goalie = 1 - (opp_sog / opp_sa) — already implicit in data

        # Use the gap between opp shots attempted and opp SOG as block proxy
        val['opp_block_proxy'] = val['opp_team_sa_avg_10'] - val['opp_team_sog_avg_10']

        high_blocks = val['opp_block_proxy'] > val['opp_block_proxy'].quantile(0.75)
        low_blocks = val['opp_block_proxy'] < val['opp_block_proxy'].quantile(0.25)

        high_res = eval_filtered_strategy(val, 'saves_avg_10', high_blocks, side='under')
        low_res = eval_filtered_strategy(val, 'saves_avg_10', low_blocks, side='over')
        results.append({'split': split['name'], 'high_blocks_under': high_res, 'low_blocks_over': low_res})

    return results


def strategy_decomposed_saves(matrix, splits):
    """S23: Predict shots and svpct separately, multiply."""
    shot_feats = ['sa_avg_10', 'opp_team_sog_avg_10', 'is_home', 'opp_corsi_pct_avg_10',
                  'opp_possession_avg_10', 'own_def_missing_toi']
    svpct_feats = ['svpct_avg_10', 'svpct_avg_20', 'svpct_season_avg', 'ev_svpct_avg_10',
                   'days_rest', 'is_home']
    shot_feats = [f for f in shot_feats if f in matrix.columns]
    svpct_feats = [f for f in svpct_feats if f in matrix.columns]

    if not shot_feats or not svpct_feats:
        return [{'error': 'missing features'}]

    results = []
    for split in splits:
        train = split['train'].dropna(subset=['shots_against', 'save_pct'])
        val = split['val'].dropna(subset=['shots_against', 'save_pct'])
        t_valid = train[shot_feats + svpct_feats].notna().any(axis=1)
        v_valid = val[shot_feats + svpct_feats].notna().any(axis=1)
        train = train[t_valid]
        val = val[v_valid]
        if len(train) < 50 or len(val) < 20:
            continue

        params = dict(objective='regression', num_leaves=10, max_depth=4, min_child_samples=50,
                      learning_rate=0.05, n_estimators=300, verbose=-1, reg_alpha=0.5, reg_lambda=0.5)

        m_shots = lgb.LGBMRegressor(**params)
        m_shots.fit(train[shot_feats].fillna(-999), train['shots_against'])
        pred_shots = m_shots.predict(val[shot_feats].fillna(-999))

        m_svpct = lgb.LGBMRegressor(**params)
        m_svpct.fit(train[svpct_feats].fillna(-999), train['save_pct'])
        pred_svpct = m_svpct.predict(val[svpct_feats].fillna(-999))

        val = val.copy()
        val['pred_decomposed'] = pred_shots * pred_svpct

        res = eval_betting_strategy(val, 'pred_decomposed')
        shots_mae = mean_absolute_error(val['shots_against'], pred_shots)
        saves_mae = mean_absolute_error(val['saves'], val['pred_decomposed'])
        results.append({'split': split['name'], 'betting': res, 'shots_mae': round(shots_mae, 2),
                        'saves_mae': round(saves_mae, 2)})

    return results


def strategy_puck_control_compound(matrix, splits):
    """S24: Combine puck control + workload for filtered bets."""
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'opp_puck_control_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['opp_puck_control_avg_10', 'starts_last_7d', 'line', 'saves'])
        if len(val) < 20:
            continue

        # Opponent good puck control + heavy workload goalie → over
        over_mask = ((val['opp_puck_control_avg_10'] > val['opp_puck_control_avg_10'].quantile(0.6)) &
                     (val['starts_last_7d'] >= 2))
        # Opponent bad puck control + rested goalie → under
        under_mask = ((val['opp_puck_control_avg_10'] < val['opp_puck_control_avg_10'].quantile(0.4)) &
                      (val['days_rest'] >= 2))

        over_res = eval_filtered_strategy(val, 'saves_avg_10', over_mask, side='over')
        under_res = eval_filtered_strategy(val, 'saves_avg_10', under_mask, side='under')
        results.append({'split': split['name'], 'good_puck_heavy_over': over_res, 'bad_puck_rested_under': under_res})

    return results


def strategy_line_vs_rolling_corsi(matrix, splits):
    """S25: Combine rolling saves avg gap from line + Corsi signal."""
    feats = ['saves_avg_10', 'saves_avg_5', 'line', 'opp_corsi_pct_avg_10', 'svpct_avg_10',
             'sa_avg_10', 'is_home', 'days_rest']
    feats = [f for f in feats if f in matrix.columns]

    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['saves_avg_10', 'opp_corsi_pct_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        # Model says over: avg above line + strong opponent Corsi
        gap = val['saves_avg_10'] - val['line']
        opp_strong = val['opp_corsi_pct_avg_10'] > val['opp_corsi_pct_avg_10'].median()

        confident_over = (gap > 1) & opp_strong
        confident_under = (gap < -1) & (~opp_strong)

        over_res = eval_filtered_strategy(val, 'saves_avg_10', confident_over, side='over')
        under_res = eval_filtered_strategy(val, 'saves_avg_10', confident_under, side='under')
        results.append({'split': split['name'], 'gap+corsi_over': over_res, 'gap+corsi_under': under_res})

    return results


def strategy_weighted_ensemble(matrix, splits):
    """S26: Simple weighted average of multiple rolling predictions."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['saves_avg_5', 'saves_avg_10', 'saves_avg_20', 'line', 'saves'])
        if len(val) < 20:
            continue

        # Weight recent more heavily
        val = val.copy()
        val['pred_weighted'] = 0.5 * val['saves_avg_5'] + 0.3 * val['saves_avg_10'] + 0.2 * val['saves_avg_20']
        res = eval_betting_strategy(val, 'pred_weighted')
        results.append({'split': split['name'], 'betting': res})

    return results


def strategy_adjusted_for_strength(matrix, splits):
    """S27: Adjust rolling avg by strength-of-schedule (opponent Corsi)."""
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'opp_corsi_pct_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['saves_avg_10', 'opp_corsi_pct_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        val = val.copy()
        # Adjust: saves_avg * (opponent_corsi / league_avg_corsi)
        league_avg_corsi = val['opp_corsi_pct_avg_10'].mean()
        val['pred_sos_adj'] = val['saves_avg_10'] * (val['opp_corsi_pct_avg_10'] / league_avg_corsi)
        res = eval_betting_strategy(val, 'pred_sos_adj')
        results.append({'split': split['name'], 'betting': res})

    return results


def strategy_short_window_momentum(matrix, splits):
    """S28: 5-game momentum vs 20-game baseline — divergence signals."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['saves_avg_5', 'saves_avg_20', 'line', 'saves'])
        if len(val) < 20:
            continue

        momentum = val['saves_avg_5'] - val['saves_avg_20']
        hot_streak = momentum > 3  # 3+ saves above long-term avg
        cold_streak = momentum < -3

        # Hot streak might mean over, or regression → under. Test both.
        hot_over = eval_filtered_strategy(val, 'saves_avg_10', hot_streak, side='over')
        cold_under = eval_filtered_strategy(val, 'saves_avg_10', cold_streak, side='under')
        results.append({'split': split['name'], 'hot_over': hot_over, 'cold_under': cold_under})

    return results


def strategy_corsi_plus_pull(matrix, splits):
    """S29: High opponent Corsi + high pull rate → extreme under signal."""
    results = []
    for split in splits:
        val = split['val'].copy()
        if 'opp_corsi_pct_avg_10' not in val.columns:
            continue
        val = val.dropna(subset=['opp_corsi_pct_avg_10', 'pull_rate_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        extreme = ((val['opp_corsi_pct_avg_10'] > val['opp_corsi_pct_avg_10'].quantile(0.7)) &
                   (val['pull_rate_10'] > 0.15))

        res = eval_filtered_strategy(val, 'saves_avg_10', extreme, side='under')
        results.append({'split': split['name'], 'corsi+pull_under': res})

    return results


def strategy_lgbm_with_possession_only(matrix, splits):
    """S30: LightGBM using ONLY derived possession/Corsi features."""
    feats = ['opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10', 'opp_possession_avg_10',
             'own_corsi_pct_avg_10', 'own_possession_avg_10', 'opp_puck_control_avg_10',
             'own_puck_control_avg_10', 'opp_faceoff_pct_avg_10', 'is_home']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_possession_only')


def strategy_confidence_filter(matrix, splits):
    """S31: Only bet when model prediction is 2+ saves from line."""
    feats = ['sa_avg_10', 'sa_avg_20', 'svpct_avg_10', 'is_home',
             'opp_team_sog_avg_10', 'days_rest', 'opp_corsi_pct_avg_10', 'own_def_missing_toi']
    feats = [f for f in feats if f in matrix.columns]

    results = []
    for split in splits:
        train = split['train'].dropna(subset=['saves'])
        val = split['val'].dropna(subset=['saves'])
        t_valid = train[feats].notna().any(axis=1)
        v_valid = val[feats].notna().any(axis=1)
        train = train[t_valid]
        val = val[v_valid]
        if len(train) < 50 or len(val) < 20:
            continue

        model = lgb.LGBMRegressor(objective='regression', num_leaves=10, max_depth=4,
                                   min_child_samples=50, learning_rate=0.05, n_estimators=300,
                                   verbose=-1, reg_alpha=0.5, reg_lambda=0.5)
        model.fit(train[feats].fillna(-999), train['saves'])
        val = val.copy()
        val['pred'] = model.predict(val[feats].fillna(-999))

        for gap in [1.5, 2.0, 2.5, 3.0]:
            mask = np.abs(val['pred'] - val['line']) >= gap
            res = eval_filtered_strategy(val, 'pred', mask)
            if res:
                results.append({'split': split['name'], f'gap>={gap}': res})

    return results


def strategy_ev_shots_focus(matrix, splits):
    """S32: Even-strength shots are most predictable — focus there."""
    feats = ['ev_shots_avg_10', 'ev_shots_avg_20', 'ev_svpct_avg_10', 'is_home',
             'opp_corsi_pct_avg_10', 'opp_team_pp_opps_avg_10']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_ev_focus')


def strategy_recent_saves_only(matrix, splits):
    """S33: Just use 5-game saves avg as predictor — simplest possible."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['saves_avg_5', 'line', 'saves'])
        if len(val) < 20:
            continue
        res = eval_betting_strategy(val, 'saves_avg_5')
        results.append({'split': split['name'], 'betting': res})
    return results


def strategy_10game_saves_only(matrix, splits):
    """S34: Just use 10-game saves avg — slightly smoother baseline."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['saves_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue
        res = eval_betting_strategy(val, 'saves_avg_10')
        results.append({'split': split['name'], 'betting': res})
    return results


def strategy_corsi_window_sweep(matrix, splits):
    """S35: Compare Corsi at different windows to find optimal lookback."""
    results = []
    for w in [5, 10, 20]:
        col = f'opp_corsi_pct_avg_{w}'
        if col not in matrix.columns:
            continue
        for split in splits:
            val = split['val'].copy()
            val = val.dropna(subset=[col, 'line', 'saves'])
            if len(val) < 20:
                continue
            high = val[col] > val[col].quantile(0.75)
            res = eval_filtered_strategy(val, 'saves_avg_10', high, side='over')
            if res:
                results.append({'window': w, 'split': split['name'], f'high_corsi_{w}_over': res})
    return results


def strategy_own_team_offense(matrix, splits):
    """S36: Own team's offense quality affects game script → saves."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['own_team_sog_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        # Strong own offense → likely leading → fewer opponent desperate shots? Or blowout = pull?
        strong_offense = val['own_team_sog_avg_10'] > val['own_team_sog_avg_10'].quantile(0.75)
        weak_offense = val['own_team_sog_avg_10'] < val['own_team_sog_avg_10'].quantile(0.25)

        strong_res = eval_filtered_strategy(val, 'saves_avg_10', strong_offense, side='under')
        weak_res = eval_filtered_strategy(val, 'saves_avg_10', weak_offense, side='over')
        results.append({'split': split['name'], 'strong_offense_under': strong_res, 'weak_offense_over': weak_res})

    return results


def strategy_multi_signal_lgbm(matrix, splits):
    """S37: LightGBM with carefully selected Corsi + traditional features."""
    feats = ['sa_avg_10', 'svpct_avg_10', 'saves_avg_10', 'is_home', 'days_rest',
             'opp_team_sog_avg_10', 'opp_corsi_pct_avg_10', 'opp_possession_avg_10',
             'own_corsi_pct_avg_10', 'pull_rate_10', 'starts_last_7d',
             'own_def_missing_toi', 'opp_team_pp_opps_avg_10', 'line']
    feats = [f for f in feats if f in matrix.columns]
    return _train_eval(matrix, splits, feats, 'saves', 'pred_multi_signal')


def strategy_diff_from_season(matrix, splits):
    """S38: Difference between recent form and season avg as signal."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['saves_avg_5', 'saves_season_avg', 'line', 'saves'])
        if len(val) < 20:
            continue

        val = val.copy()
        val['form_diff'] = val['saves_avg_5'] - val['saves_season_avg']

        # Positive form_diff = hot → ride the streak or expect regression?
        hot = val['form_diff'] > 2
        cold = val['form_diff'] < -2

        hot_over = eval_filtered_strategy(val, 'saves_avg_10', hot, side='over')
        cold_under = eval_filtered_strategy(val, 'saves_avg_10', cold, side='under')
        hot_under = eval_filtered_strategy(val, 'saves_avg_10', hot, side='under')  # regression
        cold_over = eval_filtered_strategy(val, 'saves_avg_10', cold, side='over')  # regression

        results.append({'split': split['name'],
                        'hot_ride_over': hot_over, 'hot_regression_under': hot_under,
                        'cold_ride_under': cold_under, 'cold_regression_over': cold_over})

    return results


def strategy_starts_30d_fatigue(matrix, splits):
    """S39: 30-day start count as fatigue indicator."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['starts_last_30d', 'line', 'saves'])
        if len(val) < 20:
            continue

        heavy = val['starts_last_30d'] >= 12  # ~every 2.5 days for a month
        light = val['starts_last_30d'] <= 7

        heavy_under = eval_filtered_strategy(val, 'saves_avg_10', heavy, side='under')
        light_over = eval_filtered_strategy(val, 'saves_avg_10', light, side='over')
        results.append({'split': split['name'], 'heavy_30d_under': heavy_under, 'light_30d_over': light_over})

    return results


def strategy_pp_opps_filter(matrix, splits):
    """S40: More opponent PP opportunities → more shots → over."""
    results = []
    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['opp_team_pp_opps_avg_10', 'line', 'saves'])
        if len(val) < 20:
            continue

        high_pp = val['opp_team_pp_opps_avg_10'] > val['opp_team_pp_opps_avg_10'].quantile(0.75)
        low_pp = val['opp_team_pp_opps_avg_10'] < val['opp_team_pp_opps_avg_10'].quantile(0.25)

        high_over = eval_filtered_strategy(val, 'saves_avg_10', high_pp, side='over')
        low_under = eval_filtered_strategy(val, 'saves_avg_10', low_pp, side='under')
        results.append({'split': split['name'], 'high_pp_over': high_over, 'low_pp_under': low_under})

    return results


# ======= Helper =======

def _train_eval(matrix, splits, feats, target, pred_name):
    """Train LightGBM and evaluate as betting strategy."""
    if not feats:
        return [{'error': 'no features available'}]

    results = []
    for split in splits:
        train = split['train'].dropna(subset=[target])
        val = split['val'].dropna(subset=[target])
        t_valid = train[feats].notna().any(axis=1)
        v_valid = val[feats].notna().any(axis=1)
        train = train[t_valid]
        val = val[v_valid]
        if len(train) < 50 or len(val) < 20:
            continue

        model = lgb.LGBMRegressor(objective='regression', num_leaves=10, max_depth=4,
                                   min_child_samples=50, learning_rate=0.05, n_estimators=300,
                                   verbose=-1, reg_alpha=0.5, reg_lambda=0.5,
                                   feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=5)
        model.fit(train[feats].fillna(-999), train[target])
        val = val.copy()
        val[pred_name] = model.predict(val[feats].fillna(-999))

        mae = mean_absolute_error(val[target], val[pred_name])
        betting = eval_betting_strategy(val, pred_name)

        # Feature importance
        imp = sorted(zip(feats, model.feature_importances_), key=lambda x: -x[1])[:5]

        results.append({'split': split['name'], 'mae': round(mae, 2), 'betting': betting,
                        'top_features': imp, 'n_features': len(feats)})

    return results


# ======= Strategy Registry =======

ALL_STRATEGIES = {
    # Round 1: Baselines + Corsi introduction
    1: [
        ('S1: Baseline LightGBM', strategy_baseline_lgbm),
        ('S2: Corsi for shot prediction', strategy_corsi_shots),
        ('S3: Possession proxy saves', strategy_possession_saves),
        ('S4: High Corsi quartile over/under', strategy_high_corsi_over),
        ('S5: Rest days B2B filter', strategy_rest_filter),
    ],
    # Round 2: Line-based + regression signals
    2: [
        ('S6: Line movement signal', strategy_line_movement),
        ('S7: SvPct mean reversion', strategy_svpct_mean_reversion),
        ('S8: Opponent missing D', strategy_opp_missing_d),
        ('S9: Full Corsi LightGBM', strategy_corsi_lgbm),
        ('S10: Pull probability under', strategy_pull_under),
    ],
    # Round 3: Extreme filters + decomposed model
    3: [
        ('S11: Extreme lines regression', strategy_extreme_lines),
        ('S12: Corsi diff threshold', strategy_corsi_diff_threshold),
        ('S13: Faceoff possession proxy', strategy_faceoff_possession),
        ('S14: Saves vs line gap', strategy_saves_vs_line_gap),
        ('S15: Home/away split', strategy_home_away_split),
    ],
    # Round 4: Compound filters + advanced models
    4: [
        ('S16: Corsi + rest compound', strategy_combined_corsi_rest),
        ('S18: Workload regression', strategy_workload_regression),
        ('S19: Wide Corsi LightGBM', strategy_wide_corsi_lgbm),
        ('S20: EV strength focus', strategy_ev_strength_focus),
        ('S21: Kitchen sink LightGBM', strategy_kitchen_sink),
    ],
    # Round 5: Decomposed + puck control
    5: [
        ('S22: Blocked shots proxy', strategy_opponent_blocked_shots),
        ('S23: Decomposed saves (shots*svpct)', strategy_decomposed_saves),
        ('S24: Puck control + workload', strategy_puck_control_compound),
        ('S25: Line gap + Corsi', strategy_line_vs_rolling_corsi),
        ('S26: Weighted ensemble', strategy_weighted_ensemble),
    ],
    # Round 6: Adjustment + momentum
    6: [
        ('S27: SOS-adjusted saves', strategy_adjusted_for_strength),
        ('S28: Short window momentum', strategy_short_window_momentum),
        ('S29: Corsi + pull compound', strategy_corsi_plus_pull),
        ('S30: Possession-only LightGBM', strategy_lgbm_with_possession_only),
        ('S31: Confidence filter (gap from line)', strategy_confidence_filter),
    ],
    # Round 7: Feature focus + simplest baselines
    7: [
        ('S32: EV shots focus', strategy_ev_shots_focus),
        ('S33: 5-game saves avg only', strategy_recent_saves_only),
        ('S34: 10-game saves avg only', strategy_10game_saves_only),
        ('S35: Corsi window sweep', strategy_corsi_window_sweep),
        ('S36: Own team offense', strategy_own_team_offense),
    ],
    # Round 8: Multi-signal + fatigue + final
    8: [
        ('S37: Multi-signal LightGBM', strategy_multi_signal_lgbm),
        ('S38: Form diff from season', strategy_diff_from_season),
        ('S39: 30-day fatigue', strategy_starts_30d_fatigue),
        ('S40: PP opportunities filter', strategy_pp_opps_filter),
        ('S25b: Line gap + Corsi (repeat for consistency)', strategy_line_vs_rolling_corsi),
    ],
}


def run_round(round_num, matrix, splits):
    """Run 5 strategies for a given round."""
    strategies = ALL_STRATEGIES.get(round_num, [])
    if not strategies:
        return []

    results = []
    for name, func in strategies:
        try:
            res = func(matrix, splits)
            results.append((name, res))
            print(f"  ✓ {name}")
        except Exception as e:
            results.append((name, [{'error': str(e)}]))
            print(f"  ✗ {name}: {e}")

    return results


def summarize_and_log(round_num, results):
    """Write brief summary to strategy.md."""
    lines = [f"\n## Round {round_num} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]

    for name, res in results:
        # Extract the most interesting finding
        summary = summarize_result(name, res)
        lines.append(f"- **{name}**: {summary}")

    lines.append("")

    with open(STRATEGY_FILE, 'a') as f:
        f.write('\n'.join(lines))

    return '\n'.join(lines)


def summarize_result(name, res):
    """1-2 sentence summary of a strategy result."""
    if not res:
        return "No valid data."

    # Check for errors
    if isinstance(res[0], dict) and 'error' in res[0]:
        return f"Error: {res[0]['error']}"

    # For LightGBM strategies with betting results
    betting_results = []
    for r in res:
        if isinstance(r, dict):
            if 'betting' in r and r['betting']:
                betting_results.append(r['betting'])
            # Check for filtered strategy results
            for k, v in r.items():
                if isinstance(v, dict) and 'roi' in v:
                    betting_results.append(v)

    if betting_results:
        rois = [b['roi'] for b in betting_results if b and 'roi' in b]
        wins = [b['win_rate'] for b in betting_results if b and 'win_rate' in b]
        bets = [b['n_bets'] for b in betting_results if b and 'n_bets' in b]
        if rois:
            avg_roi = np.mean(rois)
            avg_win = np.mean(wins) if wins else 0
            total_bets = sum(bets) if bets else 0
            emoji = "🟢" if avg_roi > 0 else "🔴"
            return f"{emoji} Avg ROI: {avg_roi:+.1f}%, Win rate: {avg_win:.0f}%, Bets: {total_bets}"

    # For strategies with MAE
    maes = [r.get('mae') or r.get('saves_mae') for r in res if isinstance(r, dict) and (r.get('mae') or r.get('saves_mae'))]
    if maes:
        return f"MAE: {np.mean(maes):.2f}"

    # For note-only strategies
    notes = [r.get('note') for r in res if isinstance(r, dict) and r.get('note')]
    if notes:
        return notes[0]

    return "Completed — see detailed results."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', type=int, required=True, help='Round number 1-8')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  STRATEGY RESEARCH — ROUND {args.round}")
    print(f"{'='*60}")

    print("\nLoading matrix...")
    matrix = load_matrix()
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    print(f"  {len(matrix)} rows, {len(matrix.columns)} cols")

    # Derive Corsi features
    print("\nDeriving Corsi & possession features...")
    matrix = derive_corsi_features(matrix)
    corsi_cols = [c for c in matrix.columns if 'corsi' in c or 'possession' in c or 'puck_control' in c or 'faceoff_pct_avg' in c]
    print(f"  Added {len(corsi_cols)} new features")

    splits = walk_forward_split(matrix)
    print(f"  {len(splits)} walk-forward splits")

    print(f"\nRunning round {args.round} strategies...")
    results = run_round(args.round, matrix, splits)

    print("\nLogging to strategy.md...")
    summary = summarize_and_log(args.round, results)
    print(summary)

    # Also save detailed results
    detail_path = MODEL_DIR / f'round_{args.round}_details.json'
    detail = []
    for name, res in results:
        detail.append({'strategy': name, 'results': str(res)[:2000]})
    with open(detail_path, 'w') as f:
        json.dump(detail, f, indent=2, default=str)
    print(f"\nDetailed results saved to {detail_path}")


if __name__ == '__main__':
    main()
