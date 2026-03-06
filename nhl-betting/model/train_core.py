"""Core model training and evaluation logic."""

import lightgbm as lgb
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)
from train_utils import walk_forward_split


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

            for feat, imp in zip(available, model.feature_importances_):
                iter_importances[feat] = iter_importances.get(feat, 0) + imp

            params['n_estimators'] = n_est

        if not iter_results:
            print(f"  Iter {iteration}: No valid splits")
            continue

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

    if best_importances:
        sorted_imp = sorted(best_importances.items(), key=lambda x: -x[1])
        print(f"\n  Top 10 features ({model_name}):")
        for feat, imp in sorted_imp[:10]:
            print(f"    {feat}: {imp:.0f}")

    return all_results, best_importances
