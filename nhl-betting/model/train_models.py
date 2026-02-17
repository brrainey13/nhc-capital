#!/usr/bin/env python3
"""
Phases 2-5: Model Training, Pull Model, and Stress Testing.

Runs 5 iterations each for:
- Model A: Shot volume prediction
- Model B: Save percentage prediction
- Model C: Pull prediction (binary)

Then combines A*B for saves prediction, finds +EV bets, and stress tests.
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)

warnings.filterwarnings('ignore')

MODEL_DIR = Path('/Users/connorrainey/nhc-capital/nhl-betting/model')
RESULTS = {}


def load_matrix():
    matrix = pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    return matrix


def walk_forward_split(matrix):
    """Walk-forward splits by season. Training STRICTLY before validation."""
    splits = [
        {
            'name': 'Train 22-23, Val 23-24',
            'train': matrix[matrix['event_date'] < '2023-10-01'],
            'val': matrix[(matrix['event_date'] >= '2023-10-01') & (matrix['event_date'] < '2024-10-01')],
        },
        {
            'name': 'Train 22-24, Val 24-25',
            'train': matrix[matrix['event_date'] < '2024-10-01'],
            'val': matrix[(matrix['event_date'] >= '2024-10-01') & (matrix['event_date'] < '2025-10-01')],
        },
        {
            'name': 'Train 22-25, Val 25-26',
            'train': matrix[matrix['event_date'] < '2025-10-01'],
            'val': matrix[matrix['event_date'] >= '2025-10-01'],
        },
    ]
    # Filter to splits that have enough data
    return [s for s in splits if len(s['train']) > 100 and len(s['val']) > 50]


# ============================================================
# MODEL A: Shot Volume (predict shots_against)
# ============================================================

def get_shot_features_by_iteration(iteration):
    """Progressive feature sets for shot volume model."""
    base = ['is_home', 'opp_team_sog_avg_10', 'opp_team_sog_avg_20']

    if iteration == 1:
        return base

    iter2 = base + [
        'own_def_missing', 'own_def_missing_toi', 'opp_b2b',
        'opp_team_pp_opps_avg_10', 'opp_team_sa_avg_10',
    ]
    if iteration == 2:
        return iter2

    iter3 = iter2 + [
        'opp_team_sog_avg_5', 'opp_team_hits_avg_10',
        'opp_team_sog_season_avg', 'own_total_missing_toi',
        'opp_def_missing', 'opp_fwd_missing',
        'sa_avg_10', 'sa_avg_20',  # goalie's own shots-against trend
    ]
    if iteration == 3:
        return iter3

    iter4 = iter3 + [
        'ev_shots_avg_10', 'pp_shots_avg_10', 'sh_shots_avg_10',
        'opp_rest_days', 'days_rest',
        'own_team_sog_avg_10',  # own team offense (game script)
    ]
    if iteration == 4:
        return iter4

    # Iteration 5: same features, tuned hyperparameters
    return iter4


def get_shot_params(iteration):
    if iteration < 5:
        return {
            'objective': 'regression',
            'metric': 'mae',
            'learning_rate': 0.05,
            'num_leaves': 15,
            'max_depth': 5,
            'min_child_samples': 50,
            'feature_fraction': 0.6,
            'bagging_fraction': 0.7,
            'bagging_freq': 5,
            'reg_alpha': 0.5,
            'reg_lambda': 0.5,
            'verbose': -1,
            'n_estimators': 300,
        }
    else:
        return {
            'objective': 'regression',
            'metric': 'mae',
            'learning_rate': 0.02,
            'num_leaves': 10,
            'max_depth': 4,
            'min_child_samples': 60,
            'feature_fraction': 0.5,
            'bagging_fraction': 0.6,
            'bagging_freq': 5,
            'reg_alpha': 1.0,
            'reg_lambda': 1.0,
            'verbose': -1,
            'n_estimators': 500,
        }


# ============================================================
# MODEL B: Save Percentage
# ============================================================

def get_svpct_features_by_iteration(iteration):
    base = ['svpct_avg_10', 'is_home']

    if iteration == 1:
        return base

    iter2 = base + [
        'svpct_avg_20', 'svpct_season_avg', 'days_rest', 'starts_last_7d',
    ]
    if iteration == 2:
        return iter2

    iter3 = iter2 + [
        'ev_svpct_avg_10', 'ev_svpct_avg_20',
        'opp_team_sog_avg_10',  # opponent quality affects shot quality
        'high_ga_rate_10',
        'starts_last_14d',
    ]
    if iteration == 3:
        return iter3

    iter4 = iter3 + [
        'ga_avg_10', 'ga_avg_20',
        'opp_team_pp_opps_avg_10',  # more PP = harder shots
        'own_def_missing_toi',  # worse D = worse shots allowed
        'pull_rate_10',
    ]
    if iteration == 4:
        return iter4

    return iter4


def get_svpct_params(iteration):
    if iteration < 5:
        return {
            'objective': 'regression',
            'metric': 'mae',
            'learning_rate': 0.05,
            'num_leaves': 10,
            'max_depth': 4,
            'min_child_samples': 50,
            'feature_fraction': 0.6,
            'reg_alpha': 0.5,
            'reg_lambda': 0.5,
            'verbose': -1,
            'n_estimators': 300,
        }
    else:
        return {
            'objective': 'regression',
            'metric': 'mae',
            'learning_rate': 0.02,
            'num_leaves': 8,
            'max_depth': 3,
            'min_child_samples': 60,
            'feature_fraction': 0.5,
            'reg_alpha': 1.0,
            'reg_lambda': 1.0,
            'verbose': -1,
            'n_estimators': 500,
        }


# ============================================================
# MODEL C: Pull Prediction (binary)
# ============================================================

def get_pull_features_by_iteration(iteration):
    base = ['svpct_avg_10', 'ga_avg_10', 'is_home']

    if iteration == 1:
        return base

    iter2 = base + [
        'pull_rate_10', 'pull_rate_20', 'high_ga_rate_10',
        'opp_team_sog_avg_10',
    ]
    if iteration == 2:
        return iter2

    iter3 = iter2 + [
        'days_rest', 'starts_last_7d', 'starts_last_14d',
        'svpct_avg_20', 'svpct_season_avg',
        'own_def_missing_toi',
    ]
    if iteration == 3:
        return iter3

    iter4 = iter3 + [
        'opp_team_pp_opps_avg_10',
        'opp_fwd_missing',  # opponent missing forwards = weaker offense = less pull risk
        'ev_svpct_avg_10',
        'pull_rate_season',
        'sa_avg_10',
    ]
    if iteration == 4:
        return iter4

    return iter4


def get_pull_params(iteration):
    if iteration < 5:
        return {
            'objective': 'binary',
            'metric': 'auc',
            'learning_rate': 0.05,
            'num_leaves': 10,
            'max_depth': 4,
            'min_child_samples': 50,
            'feature_fraction': 0.6,
            'scale_pos_weight': 5,  # pulls are rare (~15%)
            'reg_alpha': 0.5,
            'reg_lambda': 0.5,
            'verbose': -1,
            'n_estimators': 300,
        }
    else:
        return {
            'objective': 'binary',
            'metric': 'auc',
            'learning_rate': 0.02,
            'num_leaves': 8,
            'max_depth': 3,
            'min_child_samples': 60,
            'feature_fraction': 0.5,
            'scale_pos_weight': 5,
            'reg_alpha': 1.0,
            'reg_lambda': 1.0,
            'verbose': -1,
            'n_estimators': 500,
        }


# ============================================================
# TRAINING
# ============================================================

def train_and_evaluate(matrix, model_name, target_col, get_features_fn, get_params_fn, is_classifier=False):
    """Train a model through 5 iterations with walk-forward validation."""
    print(f"\n{'='*60}")
    print(f"  {model_name}")
    print(f"{'='*60}")

    splits = walk_forward_split(matrix)
    all_results = []
    best_importances = None

    for iteration in range(1, 6):
        feature_cols = get_features_fn(iteration)
        params = get_params_fn(iteration)

        # Filter to available features
        available = [c for c in feature_cols if c in matrix.columns]
        missing = [c for c in feature_cols if c not in matrix.columns]
        if missing:
            print(f"  Iter {iteration}: Missing features: {missing}")

        if not available:
            print(f"  Iter {iteration}: No features available, skipping")
            continue

        iter_results = []
        iter_importances = {}

        for split in splits:
            train_df = split['train'].dropna(subset=[target_col])
            val_df = split['val'].dropna(subset=[target_col])

            # Drop rows where features are all NaN
            train_valid = train_df[available].notna().any(axis=1)
            val_valid = val_df[available].notna().any(axis=1)
            train_df = train_df[train_valid]
            val_df = val_df[val_valid]

            if len(train_df) < 50 or len(val_df) < 20:
                continue

            X_train = train_df[available].fillna(-999)
            y_train = train_df[target_col]
            X_val = val_df[available].fillna(-999)
            y_val = val_df[target_col]

            n_est = params.pop('n_estimators', 300)

            model = lgb.LGBMRegressor(**params, n_estimators=n_est) if not is_classifier else lgb.LGBMClassifier(**params, n_estimators=n_est)
            model.fit(X_train, y_train)

            preds = model.predict(X_val)

            result = {'split': split['name'], 'n_train': len(train_df), 'n_val': len(val_df)}

            if is_classifier:
                pred_proba = model.predict_proba(X_val)[:, 1] if hasattr(model, 'predict_proba') else preds
                result['auc'] = roc_auc_score(y_val, pred_proba) if len(y_val.unique()) > 1 else 0
                result['accuracy'] = accuracy_score(y_val, (pred_proba > 0.5).astype(int))
                result['brier'] = brier_score_loss(y_val, pred_proba)
                result['pull_rate_actual'] = y_val.mean()
                result['pull_rate_pred'] = (pred_proba > 0.5).mean()
            else:
                result['mae'] = mean_absolute_error(y_val, preds)
                result['rmse'] = np.sqrt(mean_squared_error(y_val, preds))
                result['mean_actual'] = y_val.mean()
                result['mean_pred'] = preds.mean()

            iter_results.append(result)

            # Feature importances
            for feat, imp in zip(available, model.feature_importances_):
                iter_importances[feat] = iter_importances.get(feat, 0) + imp

            params['n_estimators'] = n_est  # restore

        if not iter_results:
            print(f"  Iter {iteration}: No valid splits")
            continue

        # Summarize iteration
        if is_classifier:
            avg_auc = np.mean([r['auc'] for r in iter_results])
            avg_acc = np.mean([r['accuracy'] for r in iter_results])
            print(f"  Iter {iteration} ({len(available)} features): AUC={avg_auc:.4f}, Acc={avg_acc:.4f}")
        else:
            avg_mae = np.mean([r['mae'] for r in iter_results])
            avg_rmse = np.mean([r['rmse'] for r in iter_results])
            print(f"  Iter {iteration} ({len(available)} features): MAE={avg_mae:.2f}, RMSE={avg_rmse:.2f}")

        all_results.append({
            'iteration': iteration,
            'n_features': len(available),
            'features': available,
            'results': iter_results,
            'importances': iter_importances,
        })

        best_importances = iter_importances

    # Print top features from best iteration
    if best_importances:
        sorted_imp = sorted(best_importances.items(), key=lambda x: -x[1])
        print(f"\n  Top 10 features ({model_name}):")
        for feat, imp in sorted_imp[:10]:
            print(f"    {feat}: {imp:.0f}")

    return all_results, best_importances


# ============================================================
# COMBINED PREDICTION + EV ANALYSIS
# ============================================================

def combined_prediction_and_ev(matrix):
    """Combine shot volume * save% models, find +EV bets."""
    print(f"\n{'='*60}")
    print("  COMBINED MODEL + EV ANALYSIS")
    print(f"{'='*60}")

    # Use the best feature sets (iteration 5)
    shot_features = [c for c in get_shot_features_by_iteration(5) if c in matrix.columns]
    svpct_features = [c for c in get_svpct_features_by_iteration(5) if c in matrix.columns]
    pull_features = [c for c in get_pull_features_by_iteration(5) if c in matrix.columns]

    splits = walk_forward_split(matrix)
    all_ev_results = []

    for split in splits:
        train_df = split['train'].dropna(subset=['shots_against', 'save_pct'])
        val_df = split['val'].dropna(subset=['shots_against', 'save_pct'])

        train_valid = train_df[shot_features + svpct_features].notna().any(axis=1)
        val_valid = val_df[shot_features + svpct_features].notna().any(axis=1)
        train_df = train_df[train_valid]
        val_df = val_df[val_valid]

        if len(val_df) < 20:
            continue

        # Train Model A: shots
        shot_params = get_shot_params(5)
        shot_params.pop('n_estimators', None)
        model_a = lgb.LGBMRegressor(**shot_params, n_estimators=500)
        model_a.fit(train_df[shot_features].fillna(-999), train_df['shots_against'])
        pred_shots = model_a.predict(val_df[shot_features].fillna(-999))

        # Train Model B: save%
        svpct_params = get_svpct_params(5)
        svpct_params.pop('n_estimators', None)
        model_b = lgb.LGBMRegressor(**svpct_params, n_estimators=500)
        model_b.fit(train_df[svpct_features].fillna(-999), train_df['save_pct'])
        pred_svpct = model_b.predict(val_df[svpct_features].fillna(-999))

        # Train Model C: pull probability
        pull_train = train_df.dropna(subset=['was_pulled'])
        pull_val = val_df.dropna(subset=['was_pulled'])
        pull_available = [c for c in pull_features if c in pull_train.columns]

        model_c = None
        pred_pull = np.zeros(len(val_df))
        if len(pull_available) > 0 and len(pull_train) > 50:
            pull_p = get_pull_params(5)
            pull_p.pop('n_estimators', None)
            model_c = lgb.LGBMClassifier(**pull_p, n_estimators=500)
            model_c.fit(pull_train[pull_available].fillna(-999), pull_train['was_pulled'])
            if len(pull_val) > 0:
                pred_pull_subset = model_c.predict_proba(pull_val[pull_available].fillna(-999))[:, 1]
                pred_pull = np.zeros(len(val_df))
                pred_pull[val_df.index.isin(pull_val.index)] = pred_pull_subset

        # Combined: predicted saves = shots * save%
        pred_saves = pred_shots * pred_svpct

        # Adjust for pull probability: if pulled, expect ~60% of normal saves
        pred_saves_adj = pred_saves * (1 - 0.4 * pred_pull)

        val_result = val_df[['event_date', 'player_name', 'line', 'over_odds', 'under_odds',
                             'saves', 'shots_against', 'went_over', 'went_under', 'was_pulled',
                             'opening_line', 'fair_probability', 'market_ev']].copy()
        val_result['pred_saves'] = pred_saves
        val_result['pred_saves_adj'] = pred_saves_adj
        val_result['pred_shots'] = pred_shots
        val_result['pred_svpct'] = pred_svpct
        val_result['pred_pull_prob'] = pred_pull

        # Implied probabilities from odds
        def american_to_prob(odds):
            odds = np.array(odds, dtype=float)
            prob = np.where(odds < 0, -odds / (-odds + 100), 100 / (odds + 100))
            return prob

        val_result['implied_over'] = american_to_prob(val_result['over_odds'])
        val_result['implied_under'] = american_to_prob(val_result['under_odds'])

        # Our predicted probabilities
        # Simple: if pred_saves > line, lean over; magnitude indicates confidence
        val_result['pred_over_prob'] = 0.5 + (val_result['pred_saves_adj'] - val_result['line']) * 0.05
        val_result['pred_over_prob'] = val_result['pred_over_prob'].clip(0.1, 0.9)
        val_result['pred_under_prob'] = 1 - val_result['pred_over_prob']

        # EV calculation
        def calc_payout(odds):
            odds = np.array(odds, dtype=float)
            return np.where(odds < 0, 100 / (-odds), odds / 100)

        over_payout = calc_payout(val_result['over_odds'])
        under_payout = calc_payout(val_result['under_odds'])

        val_result['ev_over'] = val_result['pred_over_prob'] * over_payout - (1 - val_result['pred_over_prob'])
        val_result['ev_under'] = val_result['pred_under_prob'] * under_payout - (1 - val_result['pred_under_prob'])

        val_result['best_bet'] = np.where(val_result['ev_over'] > val_result['ev_under'], 'OVER', 'UNDER')
        val_result['best_ev'] = np.maximum(val_result['ev_over'], val_result['ev_under'])

        val_result['split'] = split['name']
        all_ev_results.append(val_result)

    if not all_ev_results:
        print("  No valid results")
        return None

    results = pd.concat(all_ev_results, ignore_index=True)

    # Analyze results at different EV thresholds
    print("\n  --- EV Analysis ---")
    print(f"  Total predictions: {len(results)}")
    print(f"  Pred saves MAE: {mean_absolute_error(results['saves'], results['pred_saves_adj']):.2f}")
    print(f"  Pred shots MAE: {mean_absolute_error(results['shots_against'], results['pred_shots']):.2f}")

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

        # Simulate flat betting $100
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

    # Pull-specific analysis
    print("\n  --- Pull Impact ---")
    pulled = results[results['was_pulled'] == 1]
    not_pulled = results[results['was_pulled'] != 1]
    if len(pulled) > 0:
        print(f"  Pulled games: {len(pulled)} ({len(pulled)/len(results):.1%})")
        print(f"    Avg saves when pulled: {pulled['saves'].mean():.1f} (line: {pulled['line'].mean():.1f})")
        print(f"    Under hit rate when pulled: {pulled['went_under'].mean():.1%}")
        print(f"    Avg saves normal: {not_pulled['saves'].mean():.1f} (line: {not_pulled['line'].mean():.1f})")
        print(f"    Under hit rate normal: {not_pulled['went_under'].mean():.1%}")

    return results


# ============================================================
# STRESS TESTS
# ============================================================

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

    split = splits[-1]  # Use last split
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

    model_rand = lgb.LGBMRegressor(**{k:v for k,v in get_shot_params(5).items() if k!="n_estimators"}, n_estimators=500)
    model_rand.fit(X_train_rand, y_train)

    importances = dict(zip(X_train_rand.columns, model_rand.feature_importances_))
    sorted_imp = sorted(importances.items(), key=lambda x: -x[1])
    random_ranks = [i+1 for i, (name, _) in enumerate(sorted_imp) if name.startswith('random_')]
    print(f"    Random feature ranks: {random_ranks} (out of {len(sorted_imp)})")
    if any(r <= 3 for r in random_ranks):
        print("    ⚠️ WARNING: Random feature in top 3 — possible overfitting!")
    else:
        print("    ✅ Random features ranked low — features are meaningful")

    # Test 2: Shuffled target
    print("\n  TEST 2: Shuffled Target")
    y_train_shuffled = y_train.sample(frac=1, random_state=42).values
    model_shuf = lgb.LGBMRegressor(**{k:v for k,v in get_shot_params(5).items() if k!="n_estimators"}, n_estimators=500)
    model_shuf.fit(X_train, y_train_shuffled)
    preds_shuf = model_shuf.predict(X_val)
    mae_shuf = mean_absolute_error(y_val, preds_shuf)

    model_real = lgb.LGBMRegressor(**{k:v for k,v in get_shot_params(5).items() if k!="n_estimators"}, n_estimators=500)
    model_real.fit(X_train, y_train)
    preds_real = model_real.predict(X_val)
    mae_real = mean_absolute_error(y_val, preds_real)

    print(f"    Real target MAE: {mae_real:.2f}")
    print(f"    Shuffled target MAE: {mae_shuf:.2f}")
    if mae_real < mae_shuf * 0.95:
        print(f"    ✅ Model learns real signal (improvement: {(1-mae_real/mae_shuf)*100:.1f}%)")
    else:
        print("    ⚠️ WARNING: Model barely beats shuffled — weak signal")

    # Test 3: Naive baseline
    print("\n  TEST 3: Naive Baseline")
    naive_pred = np.full(len(y_val), y_train.mean())
    mae_naive = mean_absolute_error(y_val, naive_pred)
    print(f"    Naive (predict mean) MAE: {mae_naive:.2f}")
    print(f"    Our model MAE: {mae_real:.2f}")
    print(f"    Improvement: {(1-mae_real/mae_naive)*100:.1f}%")

    # Test 4: Book line as sole predictor
    print("\n  TEST 4: Book Line as Predictor")
    val_with_line = val_df.dropna(subset=['line'])
    if len(val_with_line) > 0:
        # The book's line IS their prediction of saves
        mae_book = mean_absolute_error(val_with_line['saves'], val_with_line['line'])
        mae_model = mean_absolute_error(val_with_line['saves'], model_real.predict(val_with_line[shot_features].fillna(-999)) * val_with_line.get('svpct_avg_10', pd.Series(0.91)).fillna(0.91))
        print(f"    Book line MAE: {mae_book:.2f}")
        print(f"    Our saves pred MAE: {mae_model:.2f}")
        if mae_model < mae_book:
            print("    ✅ Our model beats the book line!")
        else:
            print("    ⚠️ Book line is better — need to find edge elsewhere (subsets, timing)")

    # Test 5: Bet simulation — flat bet every prediction
    print("\n  TEST 5: Flat Bet Simulation (all bets, no filter)")
    val_bets = val_df.dropna(subset=['line', 'over_odds', 'under_odds', 'saves'])
    pred_saves = model_real.predict(val_bets[shot_features].fillna(-999)) * val_bets.get('svpct_avg_10', pd.Series(0.91)).fillna(0.91)

    profits = []
    pred_saves_list = list(pred_saves)
    for i, (_, row) in enumerate(val_bets.iterrows()):
        if pred_saves_list[i] > row['line']:
            # Bet over
            odds = row['over_odds']
            won = row['saves'] > row['line']
        else:
            odds = row['under_odds']
            won = row['saves'] < row['line']

        if won:
            payout = 100 / (-odds) if odds < 0 else odds / 100
            profits.append(payout)
        elif row['saves'] == row['line']:
            profits.append(0)  # push
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

        model_pull = lgb.LGBMClassifier(**{k:v for k,v in get_pull_params(5).items() if k!="n_estimators"}, n_estimators=500)
        model_pull.fit(pull_train_df[pull_feats].fillna(-999), pull_train_df['was_pulled'])
        pull_probs = model_pull.predict_proba(pull_val[pull_feats].fillna(-999))[:, 1]

        for threshold in [0.15, 0.20, 0.25, 0.30]:
            high_pull = pull_val[pull_probs > threshold].copy()
            if len(high_pull) < 5:
                continue
            under_hits = (high_pull['saves'] < high_pull['line']).sum()
            actual_pulls = high_pull['was_pulled'].sum()
            print(f"    Pull prob > {threshold:.0%}: {len(high_pull)} games, Under hit: {under_hits/len(high_pull):.1%}, Actual pulls: {actual_pulls} ({actual_pulls/len(high_pull):.1%})")


# ============================================================
# MAIN
# ============================================================

def main():
    print("Loading feature matrix...")
    matrix = load_matrix()
    print(f"Matrix: {len(matrix)} rows, {len(matrix.columns)} cols")
    print(f"Date range: {matrix['event_date'].min()} to {matrix['event_date'].max()}")

    # Phase 2: Shot Volume Model
    shot_results, shot_imp = train_and_evaluate(
        matrix, "MODEL A: Shot Volume", "shots_against",
        get_shot_features_by_iteration, get_shot_params
    )

    # Phase 3: Save Percentage Model
    svpct_results, svpct_imp = train_and_evaluate(
        matrix, "MODEL B: Save Percentage", "save_pct",
        get_svpct_features_by_iteration, get_svpct_params
    )

    # Phase 2B: Pull Model
    pull_results, pull_imp = train_and_evaluate(
        matrix, "MODEL C: Pull Prediction", "was_pulled",
        get_pull_features_by_iteration, get_pull_params, is_classifier=True
    )

    # Phase 4: Combined + EV
    combined_prediction_and_ev(matrix)

    # Phase 5: Stress Tests
    stress_tests(matrix)

    # Save results summary
    summary = {
        'timestamp': datetime.now().isoformat(),
        'matrix_size': len(matrix),
        'shot_iterations': len(shot_results) if shot_results else 0,
        'svpct_iterations': len(svpct_results) if svpct_results else 0,
        'pull_iterations': len(pull_results) if pull_results else 0,
    }

    if shot_imp:
        summary['top_shot_features'] = sorted(shot_imp.items(), key=lambda x: -x[1])[:10]
    if svpct_imp:
        summary['top_svpct_features'] = sorted(svpct_imp.items(), key=lambda x: -x[1])[:10]
    if pull_imp:
        summary['top_pull_features'] = sorted(pull_imp.items(), key=lambda x: -x[1])[:10]

    with open(MODEL_DIR / 'results_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n\nResults saved to {MODEL_DIR / 'results_summary.json'}")


if __name__ == '__main__':
    main()
