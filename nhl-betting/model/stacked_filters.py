#!/usr/bin/env python3
"""
Stacked filter strategy research for goalie saves O/U.
Combines the best-performing filters from rounds 1-3.
"""

import warnings
from datetime import datetime
from itertools import combinations
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2

warnings.filterwarnings('ignore')

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"
MODEL_DIR = Path('/Users/connorrainey/nhc-capital/nhl-betting/model')
STRATEGY_FILE = MODEL_DIR / 'strategy.md'


def load_matrix():
    return pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')


def derive_corsi_features(matrix):
    """Same as strategy_research.py — derive Corsi & possession."""
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

    merged['corsi_for'] = merged['shots_attempted']
    merged['corsi_against'] = merged['opp_shots_attempted']
    merged['corsi_pct'] = merged['corsi_for'] / (merged['corsi_for'] + merged['corsi_against'])
    merged['corsi_diff'] = merged['corsi_for'] - merged['corsi_against']
    merged['possession_proxy'] = 0.4 * merged['faceoff_win_pct'] / 100 + 0.6 * merged['corsi_pct']
    merged['puck_control'] = merged['takeaways'] - merged['giveaways']
    merged['opp_puck_control'] = merged['opp_takeaways'] - merged['opp_giveaways']

    merged = merged.sort_values(['team_id', 'game_date'])

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
    opp_corsi_cols = [c for c in corsi_df.columns if c.endswith(('_5', '_10', '_20')) and
                      any(c.startswith(p) for p in ['corsi_pct', 'corsi_diff', 'possession', 'puck_control', 'faceoff_pct', 'opp_puck'])]

    opp_corsi = corsi_df[['game_id', 'team_id'] + opp_corsi_cols].copy()
    opp_rename = {c: f'opp_{c}' for c in opp_corsi_cols}
    opp_corsi = opp_corsi.rename(columns=opp_rename)

    matrix_new = matrix.merge(opp_corsi, left_on=['game_id', 'opponent_team_id'],
                               right_on=['game_id', 'team_id'], how='left', suffixes=('', '_corsi_opp'))

    own_corsi = corsi_df[['game_id', 'team_id'] + opp_corsi_cols].copy()
    own_rename = {c: f'own_{c}' for c in opp_corsi_cols}
    own_corsi = own_corsi.rename(columns=own_rename)

    matrix_new = matrix_new.merge(own_corsi, left_on=['game_id', 'team_id'],
                                   right_on=['game_id', 'team_id'], how='left', suffixes=('', '_corsi_own'))
    return matrix_new


def walk_forward_split(matrix):
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    splits = [
        {'name': '22-23→23-24', 'train': matrix[matrix['event_date'] < '2023-10-01'],
         'val': matrix[(matrix['event_date'] >= '2023-10-01') & (matrix['event_date'] < '2024-10-01')]},
        {'name': '22-24→24-25', 'train': matrix[matrix['event_date'] < '2024-10-01'],
         'val': matrix[(matrix['event_date'] >= '2024-10-01') & (matrix['event_date'] < '2025-10-01')]},
        {'name': '22-25→25-26', 'train': matrix[matrix['event_date'] < '2025-10-01'],
         'val': matrix[matrix['event_date'] >= '2025-10-01']},
    ]
    return [s for s in splits if len(s['train']) > 100 and len(s['val']) > 50]


def calc_payout(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, 100 / (-odds), odds / 100)


def simulate_bets(df, side_col='side'):
    """Simulate flat $100 bets. side_col has 'over'/'under'/'skip'."""
    profits = []
    for _, row in df.iterrows():
        if row[side_col] == 'skip':
            continue
        if row[side_col] == 'over':
            won = row['saves'] > row['line']
            push = row['saves'] == row['line']
            payout = calc_payout(np.array([row['over_odds']]))[0]
        else:
            won = row['saves'] < row['line']
            push = row['saves'] == row['line']
            payout = calc_payout(np.array([row['under_odds']]))[0]

        if push:
            profits.append(0)
        elif won:
            profits.append(payout)
        else:
            profits.append(-1)

    if not profits:
        return None
    n = len(profits)
    wins = sum(1 for p in profits if p > 0)
    return {
        'roi': round((sum(profits) / n) * 100, 2),
        'win_rate': round(wins / n * 100, 1),
        'n_bets': n,
        'profit_units': round(sum(profits), 2),
    }


# ============================================================
# INDIVIDUAL FILTERS (building blocks)
# ============================================================

def filter_high_opp_corsi(val, quantile=0.75):
    """Opponent has high Corsi% → more shots → lean OVER."""
    if 'opp_corsi_pct_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    thresh = val['opp_corsi_pct_avg_10'].quantile(quantile)
    return val['opp_corsi_pct_avg_10'] > thresh, 'over'

def filter_low_opp_corsi(val, quantile=0.25):
    """Opponent has low Corsi% → fewer shots → lean UNDER."""
    if 'opp_corsi_pct_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'under'
    thresh = val['opp_corsi_pct_avg_10'].quantile(quantile)
    return val['opp_corsi_pct_avg_10'] < thresh, 'under'

def filter_high_opp_corsi_diff(val, quantile=0.75):
    """Opponent positive Corsi diff → more shot attempts → OVER."""
    if 'opp_corsi_diff_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    thresh = val['opp_corsi_diff_avg_10'].quantile(quantile)
    return val['opp_corsi_diff_avg_10'] > thresh, 'over'

def filter_low_opp_corsi_diff(val, quantile=0.25):
    if 'opp_corsi_diff_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'under'
    thresh = val['opp_corsi_diff_avg_10'].quantile(quantile)
    return val['opp_corsi_diff_avg_10'] < thresh, 'under'

def filter_b2b(val):
    """Goalie on back-to-back → fatigue → lean UNDER."""
    return val['days_rest'] <= 1, 'under'

def filter_rested(val, min_rest=3):
    """Goalie well-rested → lean OVER."""
    return val['days_rest'] >= min_rest, 'over'

def filter_high_pull_rate(val, thresh=0.15):
    """Goalie with high recent pull rate → UNDER."""
    if 'pull_rate_10' not in val.columns:
        return pd.Series(False, index=val.index), 'under'
    return val['pull_rate_10'] > thresh, 'under'

def filter_saves_above_line(val, gap=1.5):
    """Rolling avg well above the line → OVER."""
    if 'saves_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    return (val['saves_avg_10'] - val['line']) > gap, 'over'

def filter_saves_below_line(val, gap=1.5):
    """Rolling avg well below the line → UNDER."""
    if 'saves_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'under'
    return (val['line'] - val['saves_avg_10']) > gap, 'under'

def filter_high_pp_opps(val, quantile=0.75):
    """Opponent draws lots of penalties → more PP shots → OVER for goalie."""
    if 'opp_team_pp_opps_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    thresh = val['opp_team_pp_opps_avg_10'].quantile(quantile)
    return val['opp_team_pp_opps_avg_10'] > thresh, 'over'

def filter_own_d_missing(val, min_missing=1):
    """Own team missing defensemen → worse defense → more shots → OVER."""
    if 'own_def_missing' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    return val['own_def_missing'] >= min_missing, 'over'

def filter_heavy_workload(val, min_starts=3):
    """Heavy recent workload (3+ starts in 7 days) → fatigue → UNDER."""
    if 'starts_last_7d' not in val.columns:
        return pd.Series(False, index=val.index), 'under'
    return val['starts_last_7d'] >= min_starts, 'under'

def filter_line_dropped(val, min_drop=1):
    """Line dropped from open → sharp money on under → UNDER."""
    if 'line_movement' not in val.columns:
        return pd.Series(False, index=val.index), 'under'
    return val['line_movement'] <= -min_drop, 'under'

def filter_line_rose(val, min_rise=1):
    """Line rose from open → sharp money on over → OVER."""
    if 'line_movement' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    return val['line_movement'] >= min_rise, 'over'

def filter_high_opp_possession(val, quantile=0.75):
    """Opponent has high possession proxy → more zone time → OVER."""
    if 'opp_possession_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    thresh = val['opp_possession_avg_10'].quantile(quantile)
    return val['opp_possession_avg_10'] > thresh, 'over'

def filter_opp_good_puck_control(val, quantile=0.75):
    """Opponent high takeaway-giveaway diff → more controlled offense → OVER."""
    if 'opp_puck_control_avg_10' not in val.columns:
        return pd.Series(False, index=val.index), 'over'
    thresh = val['opp_puck_control_avg_10'].quantile(quantile)
    return val['opp_puck_control_avg_10'] > thresh, 'over'

def filter_model_confident(val, matrix, splits, gap=2.0):
    """LightGBM prediction is 2+ saves from line."""
    # This one needs training, handled separately
    return pd.Series(False, index=val.index), 'best'


# ============================================================
# OVER FILTER COMBOS
# ============================================================

OVER_FILTERS = {
    'high_corsi': filter_high_opp_corsi,
    'high_corsi_diff': filter_high_opp_corsi_diff,
    'rested': filter_rested,
    'saves_above_line': filter_saves_above_line,
    'high_pp_opps': filter_high_pp_opps,
    'own_d_missing': filter_own_d_missing,
    'line_rose': filter_line_rose,
    'high_possession': filter_high_opp_possession,
    'good_puck_control': filter_opp_good_puck_control,
}

UNDER_FILTERS = {
    'low_corsi': filter_low_opp_corsi,
    'low_corsi_diff': filter_low_opp_corsi_diff,
    'b2b': filter_b2b,
    'saves_below_line': filter_saves_below_line,
    'high_pull_rate': filter_high_pull_rate,
    'heavy_workload': filter_heavy_workload,
    'line_dropped': filter_line_dropped,
}


def test_stacked_combo(val, filters, side):
    """Apply multiple filters (AND logic) and simulate bets."""
    required = ['line', 'saves', 'over_odds', 'under_odds']
    val = val.dropna(subset=required)
    if len(val) < 20:
        return None

    combined_mask = pd.Series(True, index=val.index)
    for name, func in filters:
        mask, _ = func(val)
        combined_mask = combined_mask & mask

    filtered = val[combined_mask].copy()
    if len(filtered) < 5:
        return None

    filtered['side'] = side
    result = simulate_bets(filtered)
    if result:
        result['filter_count'] = len(filters)
        result['filter_names'] = [n for n, _ in filters]
    return result


def run_stacked_research(matrix, splits):
    """Test all 2-filter and 3-filter stacks."""
    all_results = []

    for split in splits:
        val = split['val'].copy()

        # Test OVER stacks (2-filter combos)
        over_items = list(OVER_FILTERS.items())
        for combo in combinations(over_items, 2):
            result = test_stacked_combo(val, list(combo), 'over')
            if result:
                result['split'] = split['name']
                result['side'] = 'over'
                result['combo_name'] = ' + '.join([c[0] for c in combo])
                all_results.append(result)

        # Test UNDER stacks (2-filter combos)
        under_items = list(UNDER_FILTERS.items())
        for combo in combinations(under_items, 2):
            result = test_stacked_combo(val, list(combo), 'under')
            if result:
                result['split'] = split['name']
                result['side'] = 'under'
                result['combo_name'] = ' + '.join([c[0] for c in combo])
                all_results.append(result)

        # Test 3-filter OVER combos
        for combo in combinations(over_items, 3):
            result = test_stacked_combo(val, list(combo), 'over')
            if result:
                result['split'] = split['name']
                result['side'] = 'over'
                result['combo_name'] = ' + '.join([c[0] for c in combo])
                all_results.append(result)

        # Test 3-filter UNDER combos
        for combo in combinations(under_items, 3):
            result = test_stacked_combo(val, list(combo), 'under')
            if result:
                result['split'] = split['name']
                result['side'] = 'under'
                result['combo_name'] = ' + '.join([c[0] for c in combo])
                all_results.append(result)

        # Test CROSS stacks: OVER filter + UNDER filter applied together for "skip uncertain"
        # Not applicable — over and under filters point different directions

    return all_results


def run_lgbm_with_filters(matrix, splits):
    """Train LightGBM, then only bet when model agrees with stacked filter."""
    feats = ['sa_avg_10', 'sa_avg_20', 'svpct_avg_10', 'svpct_avg_20', 'is_home',
             'opp_team_sog_avg_10', 'days_rest', 'own_def_missing_toi',
             'opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10', 'opp_possession_avg_10',
             'own_corsi_pct_avg_10', 'pull_rate_10', 'starts_last_7d',
             'opp_team_pp_opps_avg_10', 'line']
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
                                   verbose=-1, reg_alpha=0.5, reg_lambda=0.5,
                                   feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=5)
        model.fit(train[feats].fillna(-999), train['saves'])
        val = val.copy()
        val['pred'] = model.predict(val[feats].fillna(-999))
        val['model_side'] = np.where(val['pred'] > val['line'], 'over', 'under')
        val['model_gap'] = np.abs(val['pred'] - val['line'])

        # Test: model + each over filter
        for fname, ffunc in OVER_FILTERS.items():
            mask, _ = ffunc(val)
            for gap in [0, 1, 1.5, 2]:
                combined = mask & (val['model_side'] == 'over') & (val['model_gap'] >= gap)
                filtered = val[combined].copy()
                if len(filtered) < 5:
                    continue
                filtered['side'] = 'over'
                res = simulate_bets(filtered)
                if res:
                    res['split'] = split['name']
                    res['combo'] = f'model(gap>={gap}) + {fname}'
                    res['side'] = 'over'
                    results.append(res)

        # Test: model + each under filter
        for fname, ffunc in UNDER_FILTERS.items():
            mask, _ = ffunc(val)
            for gap in [0, 1, 1.5, 2]:
                combined = mask & (val['model_side'] == 'under') & (val['model_gap'] >= gap)
                filtered = val[combined].copy()
                if len(filtered) < 5:
                    continue
                filtered['side'] = 'under'
                res = simulate_bets(filtered)
                if res:
                    res['split'] = split['name']
                    res['combo'] = f'model(gap>={gap}) + {fname}'
                    res['side'] = 'under'
                    results.append(res)

    return results


def analyze_results(all_results, label=""):
    """Find combos that are profitable across multiple splits."""
    if not all_results:
        print(f"  No results for {label}")
        return []

    df = pd.DataFrame(all_results)

    # Group by combo name and check cross-split consistency
    if 'combo_name' in df.columns:
        group_col = 'combo_name'
    elif 'combo' in df.columns:
        group_col = 'combo'
    else:
        return []

    summary = []
    for combo, group in df.groupby(group_col):
        n_splits = len(group)
        avg_roi = group['roi'].mean()
        total_bets = group['n_bets'].sum()
        total_profit = group['profit_units'].sum() if 'profit_units' in group.columns else 0
        avg_win = group['win_rate'].mean()
        all_positive = (group['roi'] > 0).all()
        n_positive = (group['roi'] > 0).sum()
        side = group['side'].iloc[0] if 'side' in group.columns else '?'

        summary.append({
            'combo': combo,
            'side': side,
            'avg_roi': round(avg_roi, 2),
            'total_bets': total_bets,
            'total_profit': round(total_profit, 2),
            'avg_win_rate': round(avg_win, 1),
            'n_splits': n_splits,
            'n_positive': n_positive,
            'all_positive': all_positive,
            'per_split': group[['split', 'roi', 'n_bets', 'win_rate']].to_dict('records'),
        })

    # Sort by: all_positive first, then avg_roi
    summary.sort(key=lambda x: (-int(x['all_positive']), -x['avg_roi']))
    return summary


def main():
    print("=" * 60)
    print("  STACKED FILTER RESEARCH")
    print("=" * 60)

    print("\nLoading matrix...")
    matrix = load_matrix()
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])

    print("Deriving Corsi features...")
    matrix = derive_corsi_features(matrix)

    splits = walk_forward_split(matrix)
    print(f"{len(splits)} walk-forward splits, {len(matrix)} rows")

    # Part 1: Pure filter stacks
    print("\n--- PURE FILTER STACKS ---")
    filter_results = run_stacked_research(matrix, splits)
    filter_summary = analyze_results(filter_results, "pure filters")

    print(f"\nTotal combos tested: {len(set(r.get('combo_name','') for r in filter_results))}")
    print("Profitable across ALL splits:")
    winners = [s for s in filter_summary if s['all_positive'] and s['total_bets'] >= 30]
    for w in winners[:15]:
        print(f"  {w['side'].upper()} | {w['combo']:50s} | ROI: {w['avg_roi']:+6.1f}% | Win: {w['avg_win_rate']:.0f}% | Bets: {w['total_bets']:4d} | All+: {w['n_positive']}/{w['n_splits']}")
        for sp in w['per_split']:
            print(f"      {sp['split']}: ROI {sp['roi']:+.1f}%, {sp['n_bets']} bets, {sp['win_rate']:.0f}% win")

    if not winners:
        print("  None found with all-positive splits and 30+ bets")
        # Show best anyway
        print("\n  Top 10 by avg ROI (any split count):")
        for w in filter_summary[:10]:
            print(f"  {w['side'].upper()} | {w['combo']:50s} | ROI: {w['avg_roi']:+6.1f}% | Bets: {w['total_bets']:4d} | +Splits: {w['n_positive']}/{w['n_splits']}")

    # Part 2: LightGBM + filter stacks
    print("\n--- MODEL + FILTER STACKS ---")
    model_results = run_lgbm_with_filters(matrix, splits)
    model_summary = analyze_results(model_results, "model+filter")

    print(f"\nTotal model+filter combos tested: {len(set(r.get('combo','') for r in model_results))}")
    print("Profitable across ALL splits:")
    model_winners = [s for s in model_summary if s['all_positive'] and s['total_bets'] >= 30]
    for w in model_winners[:15]:
        print(f"  {w['side'].upper()} | {w['combo']:50s} | ROI: {w['avg_roi']:+6.1f}% | Win: {w['avg_win_rate']:.0f}% | Bets: {w['total_bets']:4d}")
        for sp in w['per_split']:
            print(f"      {sp['split']}: ROI {sp['roi']:+.1f}%, {sp['n_bets']} bets, {sp['win_rate']:.0f}% win")

    if not model_winners:
        print("  None found with all-positive splits and 30+ bets")
        print("\n  Top 10 by avg ROI:")
        for w in model_summary[:10]:
            print(f"  {w['side'].upper()} | {w['combo']:50s} | ROI: {w['avg_roi']:+6.1f}% | Bets: {w['total_bets']:4d} | +Splits: {w['n_positive']}/{w['n_splits']}")

    # Write to strategy.md
    lines = [f"\n## Stacked Filters — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]

    if winners:
        lines.append("\n### ✅ Pure Filter Winners (all splits positive)")
        for w in winners[:5]:
            lines.append(f"- **{w['side'].upper()} {w['combo']}**: ROI {w['avg_roi']:+.1f}%, Win {w['avg_win_rate']:.0f}%, {w['total_bets']} bets")
    else:
        lines.append("\n### Pure Filters: No all-positive combos with 30+ bets")
        if filter_summary:
            lines.append(f"- Best: **{filter_summary[0]['side'].upper()} {filter_summary[0]['combo']}** ROI {filter_summary[0]['avg_roi']:+.1f}%, {filter_summary[0]['total_bets']} bets")

    if model_winners:
        lines.append("\n### ✅ Model + Filter Winners (all splits positive)")
        for w in model_winners[:5]:
            lines.append(f"- **{w['side'].upper()} {w['combo']}**: ROI {w['avg_roi']:+.1f}%, Win {w['avg_win_rate']:.0f}%, {w['total_bets']} bets")
    else:
        lines.append("\n### Model + Filters: No all-positive combos with 30+ bets")
        if model_summary:
            lines.append(f"- Best: **{model_summary[0]['side'].upper()} {model_summary[0]['combo']}** ROI {model_summary[0]['avg_roi']:+.1f}%, {model_summary[0]['total_bets']} bets")

    lines.append("")

    with open(STRATEGY_FILE, 'a') as f:
        f.write('\n'.join(lines))

    print(f"\nResults logged to {STRATEGY_FILE}")


if __name__ == '__main__':
    main()
