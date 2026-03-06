"""Feature definitions and hyperparameters for Models A, B, and C."""


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
        'sa_avg_10', 'sa_avg_20',
    ]
    if iteration == 3:
        return iter3

    iter4 = iter3 + [
        'ev_shots_avg_10', 'pp_shots_avg_10', 'sh_shots_avg_10',
        'opp_rest_days', 'days_rest',
        'own_team_sog_avg_10',
    ]
    if iteration == 4:
        return iter4

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
        'opp_team_sog_avg_10',
        'high_ga_rate_10',
        'starts_last_14d',
    ]
    if iteration == 3:
        return iter3

    iter4 = iter3 + [
        'ga_avg_10', 'ga_avg_20',
        'opp_team_pp_opps_avg_10',
        'own_def_missing_toi',
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
        'opp_fwd_missing',
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
            'scale_pos_weight': 5,
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
