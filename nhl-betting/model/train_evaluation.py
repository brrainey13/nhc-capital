"""Combined prediction, EV analysis, and stress testing."""

import lightgbm as lgb
import numpy as np
import pandas as pd  # noqa: F811 — used in stress_tests eval
from sklearn.metrics import mean_absolute_error
from train_data_prep import (
    get_pull_features_by_iteration,
    get_pull_params,
    get_shot_features_by_iteration,
    get_shot_params,
    get_svpct_features_by_iteration,
    get_svpct_params,
)
from train_utils import calc_payout, walk_forward_split


def _predict_adjusted_saves(frame, shot_features, svpct_features, pull_features, model_a, model_b, model_c):
    """Run the three-model stack on an arbitrary frame."""
    pred_shots = model_a.predict(frame[shot_features].fillna(-999))
    pred_svpct = model_b.predict(frame[svpct_features].fillna(-999))

    pred_pull = np.zeros(len(frame))
    if model_c is not None and pull_features:
        pull_mask = frame[pull_features].notna().any(axis=1)
        if pull_mask.any():
            pred_pull[pull_mask.to_numpy()] = model_c.predict_proba(
                frame.loc[pull_mask, pull_features].fillna(-999)
            )[:, 1]

    pred_saves = pred_shots * pred_svpct
    pred_saves_adj = pred_saves * (1 - 0.4 * pred_pull)
    return pred_shots, pred_svpct, pred_pull, pred_saves, pred_saves_adj


def _empirical_over_probabilities(train_actual, train_pred, val_lines, val_pred):
    """Calibrate over probabilities from the training residual distribution only."""
    residuals = np.sort(np.asarray(train_actual) - np.asarray(train_pred))
    if len(residuals) == 0:
        return np.full(len(val_pred), 0.5)

    thresholds = np.asarray(val_lines) - np.asarray(val_pred)
    over_counts = len(residuals) - np.searchsorted(residuals, thresholds, side='right')
    return np.clip(over_counts / len(residuals), 0.01, 0.99)


def combined_prediction_and_ev(matrix):
    """Combine shot volume * save% models, find +EV bets."""
    print(f"\n{'='*60}")
    print("  COMBINED MODEL + EV ANALYSIS")
    print(f"{'='*60}")

    shot_features = [c for c in get_shot_features_by_iteration(5) if c in matrix.columns]
    svpct_features = [c for c in get_svpct_features_by_iteration(5) if c in matrix.columns]
    pull_features = [c for c in get_pull_features_by_iteration(5) if c in matrix.columns]

    splits = walk_forward_split(matrix)
    all_ev_results = []
    fold_metrics = []

    for split in splits:
        train_df = split['train'].dropna(subset=['shots_against', 'save_pct'])
        val_df = split['val'].dropna(subset=['shots_against', 'save_pct'])

        train_valid = train_df[shot_features + svpct_features].notna().any(axis=1)
        val_valid = val_df[shot_features + svpct_features].notna().any(axis=1)
        train_df = train_df[train_valid]
        val_df = val_df[val_valid]

        if len(val_df) < 20:
            continue

        shot_params = get_shot_params(5)
        shot_params.pop('n_estimators', None)
        model_a = lgb.LGBMRegressor(**shot_params, n_estimators=500)
        model_a.fit(train_df[shot_features].fillna(-999), train_df['shots_against'])
        svpct_params = get_svpct_params(5)
        svpct_params.pop('n_estimators', None)
        model_b = lgb.LGBMRegressor(**svpct_params, n_estimators=500)
        model_b.fit(train_df[svpct_features].fillna(-999), train_df['save_pct'])

        pull_train = train_df.dropna(subset=['was_pulled'])
        pull_available = [c for c in pull_features if c in pull_train.columns]

        model_c = None
        if len(pull_available) > 0 and len(pull_train) > 50:
            pull_p = get_pull_params(5)
            pull_p.pop('n_estimators', None)
            model_c = lgb.LGBMClassifier(**pull_p, n_estimators=500)
            model_c.fit(pull_train[pull_available].fillna(-999), pull_train['was_pulled'])

        pred_shots, pred_svpct, pred_pull, pred_saves, pred_saves_adj = _predict_adjusted_saves(
            val_df, shot_features, svpct_features, pull_available, model_a, model_b, model_c
        )
        _, _, _, _, train_saves_adj = _predict_adjusted_saves(
            train_df, shot_features, svpct_features, pull_available, model_a, model_b, model_c
        )

        base_cols = [
            'event_date', 'player_name', 'line', 'over_odds', 'under_odds',
            'saves', 'shots_against', 'went_over', 'went_under', 'was_pulled',
            'opening_line', 'line_movement', 'fair_probability', 'market_ev',
        ]
        val_result = val_df[[col for col in base_cols if col in val_df.columns]].copy()
        val_result['pred_saves'] = pred_saves
        val_result['pred_saves_adj'] = pred_saves_adj
        val_result['pred_shots'] = pred_shots
        val_result['pred_svpct'] = pred_svpct
        val_result['pred_pull_prob'] = pred_pull
        if 'opening_line' not in val_result.columns:
            val_result['opening_line'] = val_result['line']
        if 'line_movement' not in val_result.columns:
            val_result['line_movement'] = val_result['line'] - val_result['opening_line']
        if 'fair_probability' not in val_result.columns:
            val_result['fair_probability'] = np.nan
        if 'market_ev' not in val_result.columns:
            val_result['market_ev'] = np.nan

        def american_to_prob(odds):
            odds = np.array(odds, dtype=float)
            return np.where(odds < 0, -odds / (-odds + 100), 100 / (odds + 100))

        val_result['implied_over'] = american_to_prob(val_result['over_odds'])
        val_result['implied_under'] = american_to_prob(val_result['under_odds'])

        val_result['pred_over_prob'] = _empirical_over_probabilities(
            train_df['saves'],
            train_saves_adj,
            val_result['line'],
            val_result['pred_saves_adj'],
        )
        val_result['pred_under_prob'] = 1 - val_result['pred_over_prob']

        over_payout = calc_payout(val_result['over_odds'])
        under_payout = calc_payout(val_result['under_odds'])

        val_result['ev_over'] = val_result['pred_over_prob'] * over_payout - (1 - val_result['pred_over_prob'])
        val_result['ev_under'] = val_result['pred_under_prob'] * under_payout - (1 - val_result['pred_under_prob'])

        val_result['best_bet'] = np.where(val_result['ev_over'] > val_result['ev_under'], 'OVER', 'UNDER')
        val_result['best_ev'] = np.maximum(val_result['ev_over'], val_result['ev_under'])

        val_result['split'] = split['name']
        all_ev_results.append(val_result)
        fold_metrics.append({
            'split': split['name'],
            'model_mae_vs_line': mean_absolute_error(val_result['saves'], val_result['pred_saves_adj']),
            'book_line_mae': mean_absolute_error(val_result['saves'], val_result['line']),
            'pred_shots_mae': mean_absolute_error(val_result['shots_against'], val_result['pred_shots']),
        })

    if not all_ev_results:
        print("  No valid results")
        return None

    results = pd.concat(all_ev_results, ignore_index=True)

    print("\n  --- EV Analysis ---")
    print(f"  Total predictions: {len(results)}")
    print(f"  Pred saves MAE: {mean_absolute_error(results['saves'], results['pred_saves_adj']):.2f}")
    print(f"  Pred shots MAE: {mean_absolute_error(results['shots_against'], results['pred_shots']):.2f}")
    print("\n  --- Fold MAE vs Book ---")
    for metric in fold_metrics:
        delta = metric['model_mae_vs_line'] - metric['book_line_mae']
        print(
            f"  {metric['split']}: model MAE {metric['model_mae_vs_line']:.3f} | "
            f"book MAE {metric['book_line_mae']:.3f} | delta {delta:+.3f}"
        )

    for ev_threshold in [0.0, 0.03, 0.05, 0.08, 0.10]:
        bets = results[results['best_ev'] > ev_threshold]
        if len(bets) < 10:
            continue

        over_bets = bets[bets['best_bet'] == 'OVER']
        under_bets = bets[bets['best_bet'] == 'UNDER']

        over_wins = (over_bets['went_over'] == 1).sum() if len(over_bets) > 0 else 0
        under_wins = (under_bets['went_under'] == 1).sum() if len(under_bets) > 0 else 0
        total_wins = over_wins + under_wins
        total_bets = len(bets)

        roi_parts = []
        for _, bet in bets.iterrows():
            if bet['best_bet'] == 'OVER':
                payout = calc_payout(np.array([bet['over_odds']]))[0]
                won = bet['went_over'] == 1
            else:
                payout = calc_payout(np.array([bet['under_odds']]))[0]
                won = bet['went_under'] == 1
            roi_parts.append(payout if won else -1)

        total_roi = sum(roi_parts)
        roi_pct = (total_roi / total_bets) * 100

        print(f"\n  EV > {ev_threshold:.0%}: {total_bets} bets, {total_wins} wins ({total_wins/total_bets:.1%}), ROI: {roi_pct:+.1f}%")
        print(f"    Over: {len(over_bets)} bets, {over_wins} wins | Under: {len(under_bets)} bets, {under_wins} wins")

    print("\n  --- Pull Impact ---")
    pulled = results[results['was_pulled'] == 1]
    not_pulled = results[results['was_pulled'] != 1]
    if len(pulled) > 0:
        print(f"  Pulled games: {len(pulled)} ({len(pulled)/len(results):.1%})")
        print(f"    Avg saves when pulled: {pulled['saves'].mean():.1f} (line: {pulled['line'].mean():.1f})")
        print(f"    Under hit rate when pulled: {pulled['went_under'].mean():.1%}")
        print(f"    Avg saves normal: {not_pulled['saves'].mean():.1f} (line: {not_pulled['line'].mean():.1f})")
        print(f"    Under hit rate normal: {not_pulled['went_under'].mean():.1%}")

    results.attrs['fold_metrics'] = fold_metrics
    return results


def stress_tests(matrix):
    """Phase 5: Prove the model doesn't work."""
    print(f"\n{'='*60}")
    print("  STRESS TESTS")
    print(f"{'='*60}")

    shot_features = [c for c in get_shot_features_by_iteration(5) if c in matrix.columns]
    splits = walk_forward_split(matrix)

    if not splits:
        print("  No valid splits for stress testing")
        return

    split = splits[-1]
    train_df = split['train'].dropna(subset=['shots_against'])
    val_df = split['val'].dropna(subset=['shots_against'])
    train_valid = train_df[shot_features].notna().any(axis=1)
    val_valid = val_df[shot_features].notna().any(axis=1)
    train_df = train_df[train_valid]
    val_df = val_df[val_valid]

    X_train = train_df[shot_features].fillna(-999)
    y_train = train_df['shots_against']
    X_val = val_df[shot_features].fillna(-999)
    y_val = val_df['shots_against']

    # Test 1: Random feature test
    print("\n  TEST 1: Random Feature Injection")
    rng = np.random.RandomState(42)
    X_train_rand = X_train.copy()
    X_val_rand = X_val.copy()
    for i in range(5):
        X_train_rand[f'random_{i}'] = rng.randn(len(X_train_rand))
        X_val_rand[f'random_{i}'] = rng.randn(len(X_val_rand))

    model_rand = lgb.LGBMRegressor(**{k: v for k, v in get_shot_params(5).items() if k != "n_estimators"}, n_estimators=500)
    model_rand.fit(X_train_rand, y_train)

    importances = dict(zip(X_train_rand.columns, model_rand.feature_importances_))
    sorted_imp = sorted(importances.items(), key=lambda x: -x[1])
    random_ranks = [i + 1 for i, (name, _) in enumerate(sorted_imp) if name.startswith('random_')]
    print(f"    Random feature ranks: {random_ranks} (out of {len(sorted_imp)})")
    if any(r <= 3 for r in random_ranks):
        print("    ⚠️ WARNING: Random feature in top 3 — possible overfitting!")
    else:
        print("    ✅ Random features ranked low — features are meaningful")

    # Test 2: Shuffled target
    print("\n  TEST 2: Shuffled Target")
    y_train_shuffled = y_train.sample(frac=1, random_state=42).values
    model_shuf = lgb.LGBMRegressor(**{k: v for k, v in get_shot_params(5).items() if k != "n_estimators"}, n_estimators=500)
    model_shuf.fit(X_train, y_train_shuffled)
    preds_shuf = model_shuf.predict(X_val)
    mae_shuf = mean_absolute_error(y_val, preds_shuf)

    model_real = lgb.LGBMRegressor(**{k: v for k, v in get_shot_params(5).items() if k != "n_estimators"}, n_estimators=500)
    model_real.fit(X_train, y_train)
    preds_real = model_real.predict(X_val)
    mae_real = mean_absolute_error(y_val, preds_real)

    print(f"    Real target MAE: {mae_real:.2f}")
    print(f"    Shuffled target MAE: {mae_shuf:.2f}")
    if mae_real < mae_shuf * 0.95:
        print(f"    ✅ Model learns real signal (improvement: {(1 - mae_real / mae_shuf) * 100:.1f}%)")
    else:
        print("    ⚠️ WARNING: Model barely beats shuffled — weak signal")

    # Test 3: Naive baseline
    print("\n  TEST 3: Naive Baseline")
    naive_pred = np.full(len(y_val), y_train.mean())
    mae_naive = mean_absolute_error(y_val, naive_pred)
    print(f"    Naive (predict mean) MAE: {mae_naive:.2f}")
    print(f"    Our model MAE: {mae_real:.2f}")
    print(f"    Improvement: {(1 - mae_real / mae_naive) * 100:.1f}%")

    # Test 4: Book line as sole predictor
    print("\n  TEST 4: Book Line as Predictor")
    val_with_line = val_df.dropna(subset=['line'])
    if len(val_with_line) > 0:
        mae_book = mean_absolute_error(val_with_line['saves'], val_with_line['line'])
        mae_model = mean_absolute_error(val_with_line['saves'], model_real.predict(val_with_line[shot_features].fillna(-999)) * val_with_line.get('svpct_avg_10', pd.Series(0.91)).fillna(0.91))
        print(f"    Book line MAE: {mae_book:.2f}")
        print(f"    Our saves pred MAE: {mae_model:.2f}")
        if mae_model < mae_book:
            print("    ✅ Our model beats the book line!")
        else:
            print("    ⚠️ Book line is better — need to find edge elsewhere (subsets, timing)")

    # Test 5: Flat bet simulation
    print("\n  TEST 5: Flat Bet Simulation (all bets, no filter)")
    val_bets = val_df.dropna(subset=['line', 'over_odds', 'under_odds', 'saves'])
    pred_saves = model_real.predict(val_bets[shot_features].fillna(-999)) * val_bets.get('svpct_avg_10', pd.Series(0.91)).fillna(0.91)

    profits = []
    pred_saves_list = list(pred_saves)
    for i, (_, row) in enumerate(val_bets.iterrows()):
        if pred_saves_list[i] > row['line']:
            odds = row['over_odds']
            won = row['saves'] > row['line']
        else:
            odds = row['under_odds']
            won = row['saves'] < row['line']

        if won:
            payout = 100 / (-odds) if odds < 0 else odds / 100
            profits.append(payout)
        elif row['saves'] == row['line']:
            profits.append(0)
        else:
            profits.append(-1)

    total_profit = sum(profits)
    roi = (total_profit / len(profits)) * 100 if profits else 0
    win_rate = sum(1 for p in profits if p > 0) / len(profits) * 100 if profits else 0
    print(f"    Bets: {len(profits)}, Win rate: {win_rate:.1f}%, ROI: {roi:+.2f}%")

    # Test 6: Pull model under-only strategy
    print("\n  TEST 6: Pull-Based Under Strategy")
    pull_val = val_df.dropna(subset=['was_pulled', 'line', 'under_odds', 'saves'])
    pull_feats = [c for c in get_pull_features_by_iteration(5) if c in pull_val.columns]

    if len(pull_feats) > 0 and len(pull_val) > 20:
        pull_train_df = split['train'].dropna(subset=['was_pulled'])
        pull_train_valid = pull_train_df[pull_feats].notna().any(axis=1)
        pull_train_df = pull_train_df[pull_train_valid]

        model_pull = lgb.LGBMClassifier(**{k: v for k, v in get_pull_params(5).items() if k != "n_estimators"}, n_estimators=500)
        model_pull.fit(pull_train_df[pull_feats].fillna(-999), pull_train_df['was_pulled'])
        pull_probs = model_pull.predict_proba(pull_val[pull_feats].fillna(-999))[:, 1]

        for threshold in [0.15, 0.20, 0.25, 0.30]:
            high_pull = pull_val[pull_probs > threshold].copy()
            if len(high_pull) < 5:
                continue
            under_hits = (high_pull['saves'] < high_pull['line']).sum()
            actual_pulls = high_pull['was_pulled'].sum()
            print(f"    Pull prob > {threshold:.0%}: {len(high_pull)} games, Under hit: {under_hits / len(high_pull):.1%}, Actual pulls: {actual_pulls} ({actual_pulls / len(high_pull):.1%})")
