#!/usr/bin/env python3
"""
Subset Analysis: Find where our model has the strongest edge.
Analyze profitability across different slices of the data.
"""

import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

MODEL_DIR = Path('/Users/connorrainey/nhc-capital/nhl-betting/model')


def american_to_prob(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, -odds / (-odds + 100), 100 / (odds + 100))

def calc_payout(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, 100 / (-odds), odds / 100)


def load_and_prepare():
    matrix = pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])

    # Exclude leaky columns
    exclude = {
        'game_id', 'player_id', 'team_id', 'home_team_id', 'away_team_id',
        'opponent_team_id', 'event_id', 'event_date', 'game_date', 'game_date_str',
        'game_date_dt', 'player_name', 'player_team', 'home_team', 'away_team',
        'book_id', 'book_name', 'opening_created', 'updated_at', 'scraped_at',
        'is_best', 'bp_player_id', 'id',
        'saves', 'shots_against', 'goals_against', 'save_pct',
        'went_over', 'went_under', 'save_diff', 'was_pulled',
        'fair_probability', 'market_ev',
        'team_id_opp', 'team_id_own', 'team_id_oppabs', 'team_id_ownabs', 'team_id_opprest',
    }

    feature_cols = [c for c in matrix.columns if c not in exclude and matrix[c].dtype in ('float64', 'int64', 'int32', 'float32')]

    # Strict walk-forward: train < 2025-10-01, val >= 2025-10-01
    train = matrix[matrix['event_date'] < '2025-10-01'].copy()
    val = matrix[matrix['event_date'] >= '2025-10-01'].copy()

    print(f"Train: {len(train)}, Val: {len(val)}")
    print(f"Val date range: {val['event_date'].min()} to {val['event_date'].max()}")

    # Train combined saves model
    target_features = [c for c in feature_cols if c in train.columns]
    available = [c for c in target_features if train[c].notna().any()]

    X_train = train[available].fillna(-999)
    y_train = train['saves']
    X_val = val[available].fillna(-999)

    params = {
        'objective': 'regression', 'metric': 'mae',
        'learning_rate': 0.03, 'num_leaves': 10, 'max_depth': 5,
        'min_child_samples': 50, 'feature_fraction': 0.6,
        'reg_alpha': 0.5, 'reg_lambda': 0.5, 'verbose': -1,
    }

    model = lgb.LGBMRegressor(**params, n_estimators=400)
    model.fit(X_train, y_train)

    val['pred_saves'] = model.predict(X_val)
    val['pred_diff'] = val['pred_saves'] - val['line']

    # Determine bet direction
    val['bet_side'] = np.where(val['pred_diff'] > 0, 'OVER', 'UNDER')
    val['confidence'] = abs(val['pred_diff'])

    # Calculate profit per bet
    def calc_profit(row):
        if row['bet_side'] == 'OVER':
            won = row['saves'] > row['line']
            push = row['saves'] == row['line']
            payout = calc_payout(np.array([row['over_odds']]))[0]
        else:
            won = row['saves'] < row['line']
            push = row['saves'] == row['line']
            payout = calc_payout(np.array([row['under_odds']]))[0]

        if push:
            return 0
        return payout if won else -1

    val['profit'] = val.apply(calc_profit, axis=1)
    val['won'] = val['profit'] > 0

    return val, model, available


def analyze_subset(df, label):
    """Analyze a subset's profitability."""
    if len(df) < 10:
        return None

    n = len(df)
    wins = df['won'].sum()
    roi = df['profit'].sum() / n * 100
    win_rate = wins / n * 100
    avg_odds = df.apply(lambda r: r['over_odds'] if r['bet_side'] == 'OVER' else r['under_odds'], axis=1).mean()

    return {
        'subset': label,
        'bets': n,
        'wins': int(wins),
        'win_rate': f"{win_rate:.1f}%",
        'roi': f"{roi:+.1f}%",
        'avg_profit': f"{df['profit'].mean():+.3f}",
        'avg_odds': f"{avg_odds:.0f}",
    }


def main():
    print("=" * 70)
    print("  SUBSET ANALYSIS — Finding the Edge")
    print("=" * 70)

    val, model, features = load_and_prepare()

    results = []

    # 0. Baseline
    results.append(analyze_subset(val, "ALL BETS"))

    # ============================================
    # 1. BY CONFIDENCE LEVEL
    # ============================================
    print("\n--- By Model Confidence ---")
    for threshold in [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]:
        subset = val[val['confidence'] > threshold]
        r = analyze_subset(subset, f"Confidence > {threshold}")
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 2. BY BET DIRECTION
    # ============================================
    print("\n--- By Direction ---")
    for side in ['OVER', 'UNDER']:
        subset = val[val['bet_side'] == side]
        r = analyze_subset(subset, f"All {side}s")
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # Blind under strategy (no model)
    blind_under = val.copy()
    blind_under['profit'] = blind_under.apply(
        lambda r: calc_payout(np.array([r['under_odds']]))[0] if r['saves'] < r['line']
        else (0 if r['saves'] == r['line'] else -1), axis=1)
    blind_under['won'] = blind_under['profit'] > 0
    r = analyze_subset(blind_under, "BLIND UNDER (no model)")
    if r:
        results.append(r)
        print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 3. BY LINE HEIGHT
    # ============================================
    print("\n--- By Line Height ---")
    for low, high, label in [(19, 22, "Low line (19-22)"), (22, 25, "Mid line (22-25)"),
                              (25, 28, "High line (25-28)"), (28, 36, "Very high (28+)")]:
        subset = val[(val['line'] >= low) & (val['line'] < high)]
        r = analyze_subset(subset, label)
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # High line + under
    subset = val[(val['line'] >= 27) & (val['bet_side'] == 'UNDER')]
    r = analyze_subset(subset, "High line (27+) + Model Under")
    if r:
        results.append(r)
        print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 4. BY LINE MOVEMENT
    # ============================================
    print("\n--- By Line Movement ---")
    val['abs_movement'] = abs(val['line_movement'])

    for direction, label in [
        (val['line_movement'] > 0.5, "Line moved UP (>0.5)"),
        (val['line_movement'] < -0.5, "Line moved DOWN (<-0.5)"),
        (val['abs_movement'] < 0.1, "No line movement"),
        (val['abs_movement'] > 1.0, "Big movement (>1.0)"),
    ]:
        subset = val[direction]
        r = analyze_subset(subset, label)
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # Line moved down + bet under (sharp money agrees)
    subset = val[(val['line_movement'] < -0.5) & (val['bet_side'] == 'UNDER')]
    r = analyze_subset(subset, "Line DOWN + Model Under (sharp agrees)")
    if r:
        results.append(r)
        print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 5. BY GOALIE REST / WORKLOAD
    # ============================================
    print("\n--- By Goalie Workload ---")
    for condition, label in [
        (val['days_rest'] <= 1, "Back-to-back goalie"),
        (val['days_rest'] >= 5, "Well-rested (5+ days)"),
        (val['starts_last_7d'] >= 3, "Heavy workload (3+ in 7d)"),
        (val['starts_last_14d'] >= 6, "Very heavy (6+ in 14d)"),
    ]:
        subset = val[condition]
        r = analyze_subset(subset, label)
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # Heavy workload + under
    subset = val[(val['starts_last_7d'] >= 3) & (val['bet_side'] == 'UNDER')]
    r = analyze_subset(subset, "Heavy workload + Model Under")
    if r:
        results.append(r)
        print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 6. BY DEFENSIVE ABSENCES
    # ============================================
    print("\n--- By Defensive Absences (opponent missing D = more shots) ---")
    for condition, label in [
        (val['own_def_missing_toi'] > 40, "Own team missing D (>40 TOI)"),
        (val['own_def_missing_toi'] > 60, "Own team missing heavy D (>60 TOI)"),
        (val['opp_def_missing_toi'] > 40, "Opp missing D (>40 TOI)"),
    ]:
        subset = val[condition] if condition.any() else pd.DataFrame()
        r = analyze_subset(subset, label)
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # Own team missing heavy D + over (expect more shots)
    condition = (val['own_def_missing_toi'] > 50) & (val['bet_side'] == 'OVER')
    subset = val[condition]
    r = analyze_subset(subset, "Own heavy D missing + Model Over")
    if r:
        results.append(r)
        print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 7. BY GOALIE FORM
    # ============================================
    print("\n--- By Goalie Form ---")
    for condition, label in [
        (val['svpct_avg_5'] > 0.93, "Hot goalie (sv% > .930 L5)"),
        (val['svpct_avg_5'] < 0.88, "Cold goalie (sv% < .880 L5)"),
        (val['svpct_avg_10'] > 0.92, "Strong form (sv% > .920 L10)"),
        (val['svpct_avg_10'] < 0.89, "Struggling (sv% < .890 L10)"),
    ]:
        subset = val[condition] if isinstance(condition, pd.Series) and condition.any() else pd.DataFrame()
        r = analyze_subset(subset, label)
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # Cold goalie + under
    condition = (val['svpct_avg_5'] < 0.88) & (val['bet_side'] == 'UNDER')
    subset = val[condition] if condition.any() else pd.DataFrame()
    r = analyze_subset(subset, "Cold goalie + Model Under")
    if r:
        results.append(r)
        print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 8. BY OPPONENT SHOT VOLUME
    # ============================================
    print("\n--- By Opponent Shot Tendency ---")
    for condition, label in [
        (val['opp_team_sog_avg_10'] > 33, "High-shot opponent (>33 SOG)"),
        (val['opp_team_sog_avg_10'] < 27, "Low-shot opponent (<27 SOG)"),
    ]:
        subset = val[condition] if isinstance(condition, pd.Series) and condition.any() else pd.DataFrame()
        r = analyze_subset(subset, label)
        if r:
            results.append(r)
            print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # 9. PULLED GAMES ANALYSIS
    # ============================================
    print("\n--- Pull Analysis ---")
    pulled = val[val['was_pulled'] == 1]
    val[val['was_pulled'] != 1]

    if len(pulled) > 0:
        print(f"  Pulled games: {len(pulled)} ({len(pulled)/len(val):.1%})")
        print(f"    Avg saves: {pulled['saves'].mean():.1f} vs line: {pulled['line'].mean():.1f}")
        print(f"    Under rate: {(pulled['saves'] < pulled['line']).mean():.1%}")
        print(f"    If we bet under on ALL pulls: ROI = {pulled.apply(lambda r: calc_payout(np.array([r['under_odds']]))[0] if r['saves'] < r['line'] else (-1 if r['saves'] > r['line'] else 0), axis=1).sum() / len(pulled) * 100:+.1f}%")

    # Pull rate by goalie's recent pull history
    if 'pull_rate_10' in val.columns:
        for threshold in [0.1, 0.15, 0.2, 0.3]:
            high_pull_hist = val[val['pull_rate_10'] > threshold]
            if len(high_pull_hist) >= 10:
                actual_pull = high_pull_hist['was_pulled'].mean()
                under_rate = (high_pull_hist['saves'] < high_pull_hist['line']).mean()
                print(f"  Pull history > {threshold:.0%}: {len(high_pull_hist)} games, actual pull: {actual_pull:.1%}, under: {under_rate:.1%}")

    # ============================================
    # 10. COMBO STRATEGIES
    # ============================================
    print("\n--- Best Combo Strategies ---")

    combos = [
        ("High confidence + Under", (val['confidence'] > 2) & (val['bet_side'] == 'UNDER')),
        ("High confidence + High line + Under", (val['confidence'] > 2) & (val['line'] >= 27) & (val['bet_side'] == 'UNDER')),
        ("Cold goalie + High-shot opp + Under", (val['svpct_avg_5'] < 0.90) & (val['opp_team_sog_avg_10'] > 31) & (val['bet_side'] == 'UNDER')),
        ("Heavy workload + Cold + Under", (val['starts_last_7d'] >= 3) & (val['svpct_avg_5'] < 0.91) & (val['bet_side'] == 'UNDER')),
        ("Line dropped + High confidence Under", (val['line_movement'] < -0.5) & (val['confidence'] > 1.5) & (val['bet_side'] == 'UNDER')),
        ("Own D missing + High-shot opp + Over", (val['own_def_missing_toi'] > 40) & (val['opp_team_sog_avg_10'] > 31) & (val['bet_side'] == 'OVER')),
        ("Hot goalie + Low-shot opp + Under", (val['svpct_avg_5'] > 0.93) & (val['opp_team_sog_avg_10'] < 29)),
        ("B2B goalie + Under", (val['days_rest'] <= 1) & (val['bet_side'] == 'UNDER')),
        ("Rest + Strong form + Over", (val['days_rest'] >= 4) & (val['svpct_avg_10'] > 0.92) & (val['bet_side'] == 'OVER')),
    ]

    for label, condition in combos:
        try:
            subset = val[condition]
            r = analyze_subset(subset, label)
            if r:
                results.append(r)
                print(f"  {r['subset']}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")
        except Exception:
            pass

    # ============================================
    # 11. PER-GOALIE ANALYSIS (top volume goalies)
    # ============================================
    print("\n--- Per-Goalie Performance (top 15 by volume) ---")
    goalie_counts = val.groupby('player_name').size().sort_values(ascending=False)
    for goalie in goalie_counts.head(15).index:
        subset = val[val['player_name'] == goalie]
        r = analyze_subset(subset, goalie)
        if r:
            print(f"  {goalie}: {r['bets']} bets, {r['win_rate']} win, {r['roi']} ROI")

    # ============================================
    # SUMMARY
    # ============================================
    print("\n" + "=" * 70)
    print("  TOP PROFITABLE SUBSETS (ROI > 0)")
    print("=" * 70)

    profitable = [r for r in results if r and float(r['roi'].replace('%','').replace('+','')) > 0]
    profitable.sort(key=lambda x: -float(x['roi'].replace('%','').replace('+','')))

    for r in profitable[:20]:
        print(f"  {r['roi']:>8s} ROI | {r['win_rate']:>6s} win | {r['bets']:>4d} bets | {r['subset']}")

    if not profitable:
        print("  No profitable subsets found in validation period.")
        print("  This suggests the model doesn't have enough edge to overcome vig.")

    print("\n" + "=" * 70)
    print("  WORST SUBSETS (where model is most wrong)")
    print("=" * 70)

    worst = [r for r in results if r]
    worst.sort(key=lambda x: float(x['roi'].replace('%','').replace('+','')))
    for r in worst[:10]:
        print(f"  {r['roi']:>8s} ROI | {r['win_rate']:>6s} win | {r['bets']:>4d} bets | {r['subset']}")


if __name__ == '__main__':
    main()
