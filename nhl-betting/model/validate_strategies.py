#!/usr/bin/env python3
"""
Validation diagnostics for the 5 winning goalie saves strategies.
Tests: overlap, fold stability, CLV proxy, juice sensitivity, confidence intervals.
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


# ============================================================
# STRATEGY DEFINITIONS
# ============================================================

def get_strategy_bets(matrix, splits):
    """Return dict of {strategy_name: DataFrame of bets per split}."""
    strategies = {}

    # Train model once per split for model-based strategies
    feats = ['sa_avg_10', 'sa_avg_20', 'svpct_avg_10', 'svpct_avg_20', 'is_home',
             'opp_team_sog_avg_10', 'days_rest', 'own_def_missing_toi',
             'opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10',
             'own_corsi_pct_avg_10', 'pull_rate_10', 'starts_last_7d',
             'opp_team_pp_opps_avg_10', 'line']
    feats = [f for f in feats if f in matrix.columns]

    for strat_name in ['PF1_over_corsi3', 'PF2_over_corsi_puck', 'MF1_under_model2_corsi_diff',
                        'MF2_under_model2_b2b', 'MF3_under_model1_corsi']:
        strategies[strat_name] = {}

    for split in splits:
        val = split['val'].copy()
        val = val.dropna(subset=['line', 'saves', 'over_odds', 'under_odds'])

        # Train model
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

        # PF1: OVER high_corsi + high_corsi_diff + good_puck_control
        if 'opp_corsi_pct_avg_10' in val.columns and 'opp_corsi_diff_avg_10' in val.columns and 'opp_puck_control_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_pct_avg_10', 'opp_corsi_diff_avg_10', 'opp_puck_control_avg_10'])
            mask = ((v['opp_corsi_pct_avg_10'] > v['opp_corsi_pct_avg_10'].quantile(0.75)) &
                    (v['opp_corsi_diff_avg_10'] > v['opp_corsi_diff_avg_10'].quantile(0.75)) &
                    (v['opp_puck_control_avg_10'] > v['opp_puck_control_avg_10'].quantile(0.75)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['PF1_over_corsi3'][sname] = simulate_bets_detailed(filtered, 'over')

        # PF2: OVER high_corsi + good_puck_control
        if 'opp_corsi_pct_avg_10' in val.columns and 'opp_puck_control_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_pct_avg_10', 'opp_puck_control_avg_10'])
            mask = ((v['opp_corsi_pct_avg_10'] > v['opp_corsi_pct_avg_10'].quantile(0.75)) &
                    (v['opp_puck_control_avg_10'] > v['opp_puck_control_avg_10'].quantile(0.75)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['PF2_over_corsi_puck'][sname] = simulate_bets_detailed(filtered, 'over')

        # MF1: UNDER model(gap>=2) + low_corsi_diff
        if 'opp_corsi_diff_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_diff_avg_10', 'pred'])
            mask = ((v['model_side'] == 'under') & (v['model_gap'] >= 2) &
                    (v['opp_corsi_diff_avg_10'] < v['opp_corsi_diff_avg_10'].quantile(0.25)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['MF1_under_model2_corsi_diff'][sname] = simulate_bets_detailed(filtered, 'under')

        # MF2: UNDER model(gap>=2) + b2b
        v = val.dropna(subset=['pred', 'days_rest'])
        mask = ((v['model_side'] == 'under') & (v['model_gap'] >= 2) & (v['days_rest'] <= 1))
        filtered = v[mask]
        if len(filtered) > 0:
            strategies['MF2_under_model2_b2b'][sname] = simulate_bets_detailed(filtered, 'under')

        # MF3: UNDER model(gap>=1) + low_corsi
        if 'opp_corsi_pct_avg_10' in val.columns:
            v = val.dropna(subset=['opp_corsi_pct_avg_10', 'pred'])
            mask = ((v['model_side'] == 'under') & (v['model_gap'] >= 1) &
                    (v['opp_corsi_pct_avg_10'] < v['opp_corsi_pct_avg_10'].quantile(0.25)))
            filtered = v[mask]
            if len(filtered) > 0:
                strategies['MF3_under_model1_corsi'][sname] = simulate_bets_detailed(filtered, 'under')

    return strategies


# ============================================================
# DIAGNOSTICS
# ============================================================

def diag_overlap(strategies, splits):
    """1. Strategy overlap — % of bets on same game_id+player_id."""
    print("\n" + "=" * 60)
    print("  1. STRATEGY OVERLAP MATRIX")
    print("=" * 60)

    # Collect all bet keys per strategy (across all splits)
    strat_keys = {}
    for sname, split_data in strategies.items():
        keys = set()
        for label, df in split_data.items():
            for _, r in df.iterrows():
                keys.add((r['game_id'], r['player_id']))
        strat_keys[sname] = keys

    names = list(strat_keys.keys())
    len(names)

    print(f"\n{'':40s}", end='')
    for name in names:
        print(f"{name[:8]:>10s}", end='')
    print()

    overlap_data = []
    for i, a in enumerate(names):
        print(f"{a:40s}", end='')
        for j, b in enumerate(names):
            if not strat_keys[a] or not strat_keys[b]:
                pct = 0
            elif a == b:
                pct = 100
            else:
                overlap = len(strat_keys[a] & strat_keys[b])
                pct = overlap / min(len(strat_keys[a]), len(strat_keys[b])) * 100
            print(f"{pct:9.0f}%", end='')
            if i != j:
                overlap_data.append((a, b, pct))
        print()

    # Flag high overlaps
    high = [(a, b, p) for a, b, p in overlap_data if p > 70]
    if high:
        print("\n⚠️ High overlap (>70%):")
        for a, b, p in high:
            print(f"  {a} ↔ {b}: {p:.0f}%")
    else:
        print("\n✅ No pair has >70% overlap — strategies are reasonably independent")

    return overlap_data


def diag_fold_stability(strategies, splits):
    """2. ROI by individual season/fold."""
    print("\n" + "=" * 60)
    print("  2. FOLD-LEVEL STABILITY")
    print("=" * 60)

    split_labels = [s['label'] for s in splits]
    header = f"{'Strategy':40s}"
    for sl in split_labels:
        header += f"{'  ' + sl + ' ROI':>12s}{'  ' + sl + ' Bets':>10s}"
    header += f"{'  Avg ROI':>10s}{'  Flag':>8s}"
    print(f"\n{header}")
    print("-" * len(header))

    results = []
    for sname, split_data in strategies.items():
        row = f"{sname:40s}"
        rois = []
        flagged = False
        for sl in split_labels:
            if sl in split_data and len(split_data[sl]) > 0:
                df = split_data[sl]
                n_bets = len(df)
                df['won'].sum()
                roi = (df['profit'].sum() / n_bets) * 100
                rois.append(roi)
                row += f"{roi:+10.1f}%  {n_bets:8d}"
                if roi < 0:
                    flagged = True
                elif roi < 5:
                    flagged = True
            else:
                row += f"{'N/A':>12s}{'0':>10s}"
                rois.append(None)

        avg_roi = np.mean([r for r in rois if r is not None]) if rois else 0
        flag = "⚠️" if flagged else "✅"
        row += f"{avg_roi:+8.1f}%  {flag}"
        print(row)
        results.append({'strategy': sname, 'rois': rois, 'flagged': flagged})

    return results


def diag_clv_proxy(strategies, splits):
    """3. Closing Line Value proxy — line movement analysis."""
    print("\n" + "=" * 60)
    print("  3. CLV PROXY (Line Movement Analysis)")
    print("=" * 60)

    for sname, split_data in strategies.items():
        all_bets = pd.concat(split_data.values(), ignore_index=True) if split_data else pd.DataFrame()
        if len(all_bets) == 0:
            continue

        avg_movement = all_bets['line_movement'].mean()

        # For UNDER bets: negative line movement (line dropped) = CLV positive (we're on right side)
        # For OVER bets: positive line movement (line rose) = CLV positive
        side = all_bets['side'].iloc[0]
        if side == 'under':
            clv_aligned = (all_bets['line_movement'] < 0).mean() * 100
            clv_signal = "GOOD" if avg_movement < 0 else "NEUTRAL"
        else:
            clv_aligned = (all_bets['line_movement'] > 0).mean() * 100
            clv_signal = "GOOD" if avg_movement > 0 else "NEUTRAL"

        # Compare movement on our bets vs all games
        print(f"\n  {sname} ({side.upper()}):")
        print(f"    Avg line movement on our bets: {avg_movement:+.2f} saves")
        print(f"    % bets where line moved in our direction: {clv_aligned:.0f}%")
        print(f"    CLV signal: {clv_signal}")

        # Correlation: did we win more when line moved in our favor?
        if side == 'under':
            all_bets['line_favor'] = all_bets['line_movement'] < 0
        else:
            all_bets['line_favor'] = all_bets['line_movement'] > 0

        favor_wr = all_bets[all_bets['line_favor']]['won'].mean() * 100 if all_bets['line_favor'].sum() > 5 else 0
        against_wr = all_bets[~all_bets['line_favor']]['won'].mean() * 100 if (~all_bets['line_favor']).sum() > 5 else 0
        print(f"    Win rate when line moved in our favor: {favor_wr:.0f}%")
        print(f"    Win rate when line moved against us: {against_wr:.0f}%")


def diag_juice_sensitivity(strategies, splits):
    """4. Juice sensitivity — ROI at different vig levels."""
    print("\n" + "=" * 60)
    print("  4. JUICE SENSITIVITY")
    print("=" * 60)

    juice_levels = {
        '-105 (sharp)': -105,
        '-110 (standard)': -110,
        '-115 (bad book)': -115,
        '-120 (terrible)': -120,
    }

    # Breakeven win rates
    print("\n  Breakeven win rates:")
    for label, juice in juice_levels.items():
        be = (-juice) / (-juice + 100) * 100
        print(f"    {label}: {be:.1f}%")

    print(f"\n  {'Strategy':40s}{'Win%':>8s}{'@-105':>10s}{'@-110':>10s}{'@-115':>10s}{'@-120':>10s}{'Margin':>10s}")
    print("  " + "-" * 108)

    for sname, split_data in strategies.items():
        all_bets = pd.concat(split_data.values(), ignore_index=True) if split_data else pd.DataFrame()
        if len(all_bets) == 0:
            continue

        actual_wr = all_bets['won'].mean() * 100
        n = len(all_bets)

        rois = {}
        for label, juice in juice_levels.items():
            payout = 100 / (-juice)  # e.g., -110 → 0.909
            profit = all_bets['won'].sum() * payout - (~all_bets['won'] & ~all_bets['push']).sum()
            roi = (profit / n) * 100
            rois[label] = roi

        # Margin of safety: how far is our win% above -110 breakeven?
        be_110 = 110 / 210 * 100  # 52.38%
        margin = actual_wr - be_110

        row = f"  {sname:40s}{actual_wr:7.1f}%"
        for label in juice_levels:
            r = rois[label]
            emoji = "🟢" if r > 0 else "🔴"
            row += f"  {emoji}{r:+6.1f}%"
        row += f"  {margin:+7.1f}pp"
        print(row)


def diag_confidence_intervals(strategies, splits):
    """5. 95% CI on win rate."""
    print("\n" + "=" * 60)
    print("  5. SAMPLE SIZE CONFIDENCE INTERVALS (95%)")
    print("=" * 60)

    be_110 = 110 / 210  # 0.5238

    print(f"\n  {'Strategy':40s}{'Win%':>8s}{'CI Low':>10s}{'CI High':>10s}{'Bets':>8s}{'vs BE':>10s}")
    print("  " + "-" * 86)

    for sname, split_data in strategies.items():
        all_bets = pd.concat(split_data.values(), ignore_index=True) if split_data else pd.DataFrame()
        if len(all_bets) == 0:
            continue

        n = len(all_bets)
        wins = all_bets['won'].sum()
        p = wins / n

        # Wilson score interval
        z = 1.96
        denom = 1 + z**2 / n
        center = (p + z**2 / (2 * n)) / denom
        spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
        ci_low = max(0, center - spread)
        ci_high = min(1, center + spread)

        safe = "✅ SAFE" if ci_low > be_110 else "⚠️ CAUTION"
        print(f"  {sname:40s}{p*100:7.1f}%{ci_low*100:9.1f}%{ci_high*100:9.1f}%{n:8d}  {safe}")


def write_report(overlap_data, fold_results, strategies, splits):
    """Write validation_diagnostics.md."""
    lines = [f"# Validation Diagnostics — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]

    lines.append("## 1. Strategy Overlap")
    high_overlaps = [(a, b, p) for a, b, p in overlap_data if p > 70]
    if high_overlaps:
        lines.append(f"⚠️ {len(high_overlaps)} pairs have >70% overlap — not fully independent edges.")
        for a, b, p in high_overlaps:
            lines.append(f"- {a} ↔ {b}: {p:.0f}% overlap")
    else:
        lines.append("✅ No pair exceeds 70% overlap — strategies fire on different games and provide independent signals.")
    lines.append("")

    lines.append("## 2. Fold Stability")
    for r in fold_results:
        flag = "⚠️" if r['flagged'] else "✅"
        rois_str = " | ".join([f"{x:+.1f}%" if x is not None else "N/A" for x in r['rois']])
        lines.append(f"- {flag} **{r['strategy']}**: {rois_str}")
    flagged = [r for r in fold_results if r['flagged']]
    if flagged:
        lines.append(f"\n{len(flagged)} strategies have a weak season (<5% ROI) — signals may be inconsistent in certain market regimes.")
    else:
        lines.append("\nAll strategies profitable every season — strong temporal consistency.")
    lines.append("")

    lines.append("## 3. CLV Proxy")
    for sname, split_data in strategies.items():
        if split_data:
            ab = pd.concat(split_data.values(), ignore_index=True)
            avg_mv = ab['line_movement'].mean()
            side = ab['side'].iloc[0]
            aligned = "favorable" if (side == 'under' and avg_mv < 0) or (side == 'over' and avg_mv > 0) else "neutral/unfavorable"
            lines.append(f"- **{sname}**: Avg line movement {avg_mv:+.2f}, direction {aligned} for our {side} bets.")
    lines.append("\nLine movement correlation with bet direction suggests whether we're capturing closing line value or fighting it.")
    lines.append("")

    lines.append("## 4. Juice Sensitivity")
    be_105 = 105 / 205 * 100
    be_110 = 110 / 210 * 100
    be_115 = 115 / 215 * 100
    lines.append(f"Breakeven: -105 → {be_105:.1f}%, -110 → {be_110:.1f}%, -115 → {be_115:.1f}%\n")
    for sname, split_data in strategies.items():
        if split_data:
            ab = pd.concat(split_data.values(), ignore_index=True)
            wr = ab['won'].mean() * 100
            survives_115 = "✅ survives -115" if wr > be_115 else "⚠️ breaks at -115"
            lines.append(f"- **{sname}**: {wr:.1f}% win rate — {survives_115}")
    lines.append("")

    lines.append("## 5. Confidence Intervals")
    be = 110 / 210
    for sname, split_data in strategies.items():
        if split_data:
            ab = pd.concat(split_data.values(), ignore_index=True)
            n = len(ab)
            p = ab['won'].mean()
            z = 1.96
            denom = 1 + z**2 / n
            center = (p + z**2 / (2*n)) / denom
            spread = z * np.sqrt((p*(1-p) + z**2/(4*n)) / n) / denom
            ci_low = max(0, center - spread)
            safe = "✅" if ci_low > be else "⚠️"
            lines.append(f"- {safe} **{sname}**: {p*100:.1f}% [{ci_low*100:.1f}%, {min(1,center+spread)*100:.1f}%] on {n} bets")
    lines.append("\nStrategies where CI lower bound falls below 52.4% (breakeven at -110) need larger sample or tighter filters.")
    lines.append("")

    report_path = MODEL_DIR / 'validation_diagnostics.md'
    with open(report_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"\n\nReport saved to {report_path}")

    # Also append summary to strategy.md
    with open(MODEL_DIR / 'strategy.md', 'a') as f:
        f.write(f"\n## Validation Diagnostics — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("See validation_diagnostics.md for full report.\n")
        safe_count = sum(1 for r in fold_results if not r['flagged'])
        f.write(f"- {safe_count}/{len(fold_results)} strategies pass all stability checks\n")
        if high_overlaps:
            f.write(f"- ⚠️ {len(high_overlaps)} high-overlap pairs detected\n")
        else:
            f.write("- ✅ All strategy pairs have <70% overlap\n")
    return report_path


def main():
    print("Loading data...")
    matrix = load_matrix()
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    matrix = derive_corsi_features(matrix)
    splits = walk_forward_split(matrix)
    print(f"Matrix: {len(matrix)} rows, {len(splits)} splits")

    print("\nGenerating strategy bets...")
    strategies = get_strategy_bets(matrix, splits)
    for sname, sdata in strategies.items():
        total = sum(len(df) for df in sdata.values())
        print(f"  {sname}: {total} bets across {len(sdata)} splits")

    overlap_data = diag_overlap(strategies, splits)
    fold_results = diag_fold_stability(strategies, splits)
    diag_clv_proxy(strategies, splits)
    diag_juice_sensitivity(strategies, splits)
    diag_confidence_intervals(strategies, splits)
    write_report(overlap_data, fold_results, strategies, splits)


if __name__ == '__main__':
    main()
