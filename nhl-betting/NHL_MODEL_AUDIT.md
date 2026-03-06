# NHL Model Audit

Date: 2026-03-06
Auditor: Codex (statistical/code audit)

## Executive Summary

The codebase currently contains two different goalie-saves systems:

1. `model/` is the research pipeline. It builds a historical feature matrix, trains three LightGBM models, and backtests season-by-season.
2. `models/goalie_saves.py` is the live-serving implementation used by `pipeline/daily_picks.py`. It rebuilds features directly from Postgres and trains a different LightGBM model on the fly.

That split is the core problem. The documented research claims in `docs/PROVENSTRATEGIES.md` are not backed by a single clean production path. The live model is not the same as the audited research model, and the live code contains feature-definition bugs severe enough to invalidate trust in current goalie-saves picks.

Statistically, the good news is that the core research stack in `model/` does use temporal season-based splits and mostly lagged rolling features, so the basic time-series framing is better than a random split. The bad news is that:

- strategy validation code leaks validation-set quantiles into filter selection,
- the model does not beat the bookmaker line as a point predictor in the folds I checked,
- the EV layer uses an arbitrary linear probability mapping rather than a calibrated predictive distribution,
- the training entry point crashes before completing.

Bottom line: the repository shows promising research structure, but I would not trust the current goalie-saves model as statistically production-ready.

## What The Model Actually Does

### Research pipeline under `model/`

- `model/build_features.py`
  - Pulls historical data from Postgres tables such as `saves_odds`, `goalie_stats`, `games`, `game_team_stats`, `goalie_saves_by_strength`, `goalie_advanced`, `goalie_starts`, `lineup_absences`, and `schedules`.
  - Builds lagged rolling goalie features (`saves_avg_*`, `sa_avg_*`, `svpct_avg_*`, `ga_avg_*`, `days_rest`, `starts_last_*d`).
  - Builds lagged rolling team features including Corsi and puck control.
  - Merges odds lines and actual outcomes into `model/feature_matrix.pkl`.

- `model/train_models.py`
  - Loads `feature_matrix.pkl`.
  - Trains:
    - Model A: LightGBM regressor for `shots_against`
    - Model B: LightGBM regressor for `save_pct`
    - Model C: LightGBM classifier for `was_pulled`
  - Uses season-based walk-forward splits from `model/train_utils.py`:
    - train `< 2023-10-01`, validate `2023-10-01` to `2024-09-30`
    - train `< 2024-10-01`, validate `2024-10-01` to `2025-09-30`
    - train `< 2025-10-01`, validate `>= 2025-10-01`
  - Combines predictions in `model/train_evaluation.py` as:
    - `pred_saves = pred_shots * pred_svpct`
    - `pred_saves_adj = pred_saves * (1 - 0.4 * pred_pull)`

- `model/validate_config.py` / `model/audit_strategy.py`
  - Train a separate direct LightGBM regressor on `saves` using handpicked features:
    - `sa_avg_10`, `sa_avg_20`, `svpct_avg_10`, `svpct_avg_20`, `is_home`, `opp_team_sog_avg_10`, `days_rest`, `own_def_missing_toi`, `opp_corsi_pct_avg_10`, `opp_corsi_diff_avg_10`, `own_corsi_pct_avg_10`, `pull_rate_10`, `starts_last_7d`, `opp_team_pp_opps_avg_10`, `line`
  - Apply strategy filters like MF2, MF3, PF1 on validation folds.

### Live picks pipeline under `pipeline/` and `models/`

- `pipeline/daily_picks.py`
  - Pulls live odds and player stats.
  - Calls `models.goalie_saves.run_goalie_saves()` plus other non-goalie strategy modules.
  - Writes picks to `nhl_picks`.

- `models/goalie_saves.py`
  - Does not import the `model/` training stack.
  - Rebuilds its own rolling features from DB each run.
  - Trains a single LightGBM regressor directly on historical goalie saves.
  - Computes quantile-based filters and returns live picks.

## Architecture Diagram

```text
Postgres tables
  saves_odds
  goalie_stats
  games
  game_team_stats
  goalie_saves_by_strength
  goalie_advanced
  lineup_absences
  schedules
        |
        v
model/build_features.py
  -> lagged rolling goalie/team features
  -> odds merge
  -> actual outcomes merge
  -> model/feature_matrix.pkl
        |
        +--> model/train_models.py
        |      -> LightGBM A: shots_against
        |      -> LightGBM B: save_pct
        |      -> LightGBM C: was_pulled
        |      -> combined pred_saves
        |      -> EV analysis
        |
        +--> model/validate_config.py / model/audit_strategy.py
               -> direct LightGBM on saves
               -> MF2 / MF3 / PF1 backtests

Live path:

live odds + NHL API + Postgres
        |
        v
pipeline/daily_picks.py
        |
        +--> models/goalie_saves.py
        |      -> rebuild features from DB
        |      -> direct LightGBM on saves
        |      -> MF2 / MF3 / PF1-style filters
        |
        +--> other player/game models
        |
        v
printed picks + optional nhl_picks insert
```

## Statistical Findings

### 1. Severe: The live goalie model is not the same as the audited research model

The repo mixes at least three distinct goalie-saves modeling approaches:

- shot-volume model + save% model + pull model in `model/train_models.py`
- direct saves model in `model/validate_config.py` / `model/audit_strategy.py`
- separate live direct saves model in `models/goalie_saves.py`

This makes the headline strategy claims difficult to trust because the production code path is not the same implementation as the research/backtest code path.

### 2. Severe: The live goalie-serving code has feature-semantic bugs

In `models/goalie_saves.py`, the variables named `sa_avg_10` and `sa_avg_20` are computed from historical `saves`, not `shots_against`:

- `models/goalie_saves.py:189`
- `models/goalie_saves.py:190`

That is a serious modeling bug. A feature documented and interpreted as shot volume against is actually save count. The same file also hardcodes:

- `pull_rate_10 = 0  # placeholder`
  - `models/goalie_saves.py:204`

So the live feature vector does not match the documented feature set in `docs/PROVENSTRATEGIES.md`.

### 3. Severe: Validation leakage exists in strategy-threshold selection

`model/validate_config.py` computes validation filters using validation-set quantiles for PF1, PF2, MF1, and MF3:

- `model/validate_config.py:169-171`
- `model/validate_config.py:179-180`
- `model/validate_config.py:189`
- `model/validate_config.py:205`

That is leakage. Thresholds like bottom-25% Corsi should be computed from training data only, then applied unchanged to validation. `model/audit_strategy.py` does this correctly for one audit path, but the reusable validation module does not.

### 4. High: The model does not beat the book line as a point predictor in the folds tested

I ran fold-level checks on both the direct-saves strategy model and the documented shot-volume × save% model using `model/feature_matrix.pkl`.

#### Direct saves model (`saves` target, includes `line`)

| Fold | Train MAE | Val MAE | Book line MAE | Model - Book |
|---|---:|---:|---:|---:|
| 23-24 | 4.756 | 5.929 | 5.804 | +0.125 |
| 24-25 | 4.603 | 5.804 | 5.708 | +0.096 |
| 25-26 | 4.776 | 5.789 | 5.453 | +0.336 |

#### Shot × save% research stack

| Fold | Saves MAE | Book line MAE | Model - Book | Pull AUC |
|---|---:|---:|---:|---:|
| 23-24 | 5.911 | 5.778 | +0.133 | 0.501 |
| 24-25 | 5.802 | 5.674 | +0.128 | 0.590 |
| 25-26 | 5.642 | 5.363 | +0.279 | 0.562 |

Interpretation:

- Both model variants are slightly worse than the posted line as point predictors in every fold I checked.
- That does not prove no betting edge can exist on filtered subsets, but it is a major warning sign.
- Any claim that the model is “beating the market” is not established by these results.

### 5. High: The EV layer is not statistically calibrated

`model/train_evaluation.py` converts prediction gap to probability with:

```python
pred_over_prob = 0.5 + (pred_saves_adj - line) * 0.05
pred_over_prob = pred_over_prob.clip(0.1, 0.9)
```

Source:

- `model/train_evaluation.py:89`
- `model/train_evaluation.py:90`

This is not a calibrated probability model. It is an arbitrary linear heuristic with clipping. There is no fitted outcome distribution for saves, no empirical calibration curve, and no uncertainty model. As written, the EV outputs are not statistically defensible.

### 6. High: The advertised training entry point is broken

`model/train_models.py` trains the three models, then crashes because it expects `fair_probability` and `market_ev` columns that are not present in `feature_matrix.pkl`:

- `model/train_evaluation.py:73-75`

The exact runtime error is included below in Raw Output.

### 7. Medium: The daily picks entrypoints are inconsistent and partially broken

- Running `.venv/bin/python pipeline/daily_picks.py` fails with `ModuleNotFoundError: No module named 'models'`.
- The file’s own docstring says it should be run as a module: `.venv/bin/python -m pipeline.daily_picks`.
- Running module mode got farther but failed on local Postgres socket access in this sandbox.
- `pipeline/gameday.py` imports `run_pipeline` from `daily_picks`, but `pipeline/daily_picks.py` does not define `run_pipeline`.
  - `pipeline/gameday.py:67`

This is an engineering reproducibility problem even if some of it is environment-specific.

### 8. Medium: The pull model is weak

Observed pull-model AUCs were approximately:

- 0.5375 / 0.4836 / 0.5046 / 0.5380 / 0.5510 from `model/train_models.py`
- 0.501 / 0.590 / 0.562 in my fold check

That is only marginally better than chance. The pull adjustment should not be treated as a strong alpha source in its current form.

### 9. Medium: Overfitting is present, though not the main problem

For the direct-saves model, train MAE is around 4.6 to 4.8 while validation MAE is around 5.8 to 5.9. That is a real generalization gap, but not the biggest issue. The bigger issue is that even the validation result does not beat the line.

### 10. Medium: Strategy claims in `docs/PROVENSTRATEGIES.md` are not yet audit-grade

The documented MF2/MF3/PF1 strategy claims rely on code paths that are not fully reproducible from the shipped entrypoints, and one of the main validation utilities leaks validation quantiles. Until that is fixed and rerun, the claimed ROI and win-rate numbers should be treated as provisional research findings, not production-validated evidence.

## Leakage / Bias Checklist

### Train/test split methodology

Mostly good in the research stack:

- `model/train_utils.py` uses season-based walk-forward splits.
- `model/build_features.py` uses shifted rolling and expanding windows for most historical features.

### Look-ahead bias in features

Mostly good in `model/build_features.py`:

- rolling goalie stats are shifted by one game,
- rolling team Corsi features are shifted by one game,
- season averages are shifted by one game.

Concerns:

- strategy-threshold leakage in `model/validate_config.py` as described above,
- live-serving feature code in `models/goalie_saves.py` is a separate manual implementation with weaker guarantees and bugs.

### Odds incorporation

The direct-saves validation model includes `line` as an input feature. That is not automatically wrong, but it means the model is partly learning the market line. Because the resulting MAE is still worse than the line itself, there is no evidence here that the model extracts useful incremental signal from odds rather than merely anchoring to them.

### Survivorship / backtest realism

Concerns remain:

- No robust closing-line-value analysis is implemented in the runnable stack I reviewed.
- `train_evaluation.py` expects `fair_probability` and `market_ev` but the current matrix does not contain them, suggesting the economics layer is incomplete or stale.
- The live-serving code uses current DB state and on-the-fly feature building rather than frozen training artifacts, which makes exact historical reproducibility harder.

## What Works Well

- The research code in `model/build_features.py` generally uses lagged rolling features rather than future information.
- `model/train_utils.py` uses temporal season-based splits rather than random train/test splitting.
- SQL that takes runtime parameters is generally parameterized rather than built with unsafe string interpolation.
- The feature matrix is reasonably rich and joins the right hockey primitives: goalie form, team shot generation, Corsi, puck control, absences, and rest.
- In the direct-saves fold check, `line` was not dominating feature importance rankings, which suggests the model is not trivially a line-copying machine. The issue is still that it does not outperform the line.

## Code Quality / Engineering Issues

- Hardcoded DSNs and inconsistent DB users:
  - `pipeline/daily_picks.py` uses `nhc_etl`
  - `pipeline/picks_output.py` defaults to `nhc_agent`
  - `models/goalie_saves.py` uses `connorrainey`
- Entry point mismatch:
  - script mode vs module mode for `pipeline/daily_picks.py`
  - `pipeline/gameday.py` expects missing `run_pipeline`
- Stale assumptions:
  - `train_evaluation.py` requires missing `fair_probability` and `market_ev`
- Placeholder logic in live model:
  - `pull_rate_10 = 0`
- Manual duplicated feature engineering across `model/` and `models/`
  - this is a maintenance and statistical consistency hazard

## Recommendations

1. Collapse to one goalie-saves codepath.
   - Pick either the research `model/` stack or the live `models/goalie_saves.py` stack and make the other one a thin wrapper.
   - Production should use the exact same feature definitions and training logic that are validated offline.

2. Fix the live feature bug immediately.
   - `sa_avg_*` in `models/goalie_saves.py` must use `shots_against`, not `saves`.
   - Replace placeholder pull-rate logic with a real lagged feature or remove it.

3. Remove validation leakage and rerun all claimed strategy results.
   - Compute all quantiles and thresholds from training data only.
   - Freeze thresholds before applying them to validation.

4. Stop using the current EV heuristic.
   - Fit a predictive distribution for saves or at minimum calibrate probabilities empirically from historical residuals.
   - Report calibration plots and Brier/log-loss for over/under probabilities.

5. Benchmark against the line explicitly.
   - Every report should include:
     - book line MAE / RMSE
     - model MAE / RMSE
     - delta vs line
     - CLV if available
   - If the model does not beat the line, strategy ROI claims need stronger subset-level evidence.

6. Make the pipeline reproducible.
   - Fix `pipeline/daily_picks.py` so both documented invocation and programmatic imports work.
   - Add a real `run_pipeline()` if `pipeline/gameday.py` depends on it.
   - Remove hardcoded DB usernames from code and load one DSN from config.

7. Add formal audit outputs.
   - Save fold-by-fold predictions with timestamps, lines, odds, model outputs, and realized results.
   - Add calibration, residual, and CLV diagnostics to CI or a reproducible audit script.

## Raw Output From Attempted Runs

### Command

```bash
.venv/bin/python model/train_models.py
```

### Output

```text
/Users/connorrainey/.matplotlib is not a writable directory
Matplotlib created a temporary cache directory at /var/folders/zs/ms67qt1j7fnbypg81csdc1500000gn/T/matplotlib-a62ic3ks because there was an issue with the default path (/Users/connorrainey/.matplotlib); it is highly recommended to set the MPLCONFIGDIR environment variable to a writable directory, in particular to speed up the import of Matplotlib and to better support multiprocessing.
  File "/Users/connorrainey/nhc-capital/nhl-betting/.venv/lib/python3.14/site-packages/joblib/externals/loky/backend/context.py", line 249, in _count_physical_cores
    cpu_count_physical = _count_physical_cores_darwin()
  File "/Users/connorrainey/nhc-capital/nhl-betting/.venv/lib/python3.14/site-packages/joblib/externals/loky/backend/context.py", line 312, in _count_physical_cores_darwin
    cpu_info = subprocess.run(
        "sysctl -n hw.physicalcpu".split(),
        capture_output=True,
        text=True,
    )
  File "/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/lib/python3.14/subprocess.py", line 554, in run
    with Popen(*popenargs, **kwargs) as process:
         ~~~~~^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/lib/python3.14/subprocess.py", line 1038, in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
    ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                        pass_fds, cwd, env,
                        ^^^^^^^^^^^^^^^^^^^
    ...<5 lines>...
                        gid, gids, uid, umask,
                        ^^^^^^^^^^^^^^^^^^^^^^
                        start_new_session, process_group)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/lib/python3.14/subprocess.py", line 1989, in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
Loading feature matrix...
Matrix: 2790 rows, 134 cols
Date range: 2022-10-07 00:00:00 to 2026-02-05 00:00:00

============================================================
  MODEL A: Shot Volume
============================================================
  Iter 1 (3 features): MAE=5.90, RMSE=7.55
  Iter 2 (8 features): MAE=5.94, RMSE=7.63
  Iter 3 (16 features): MAE=6.01, RMSE=7.74
  Iter 4 (22 features): MAE=5.98, RMSE=7.61
  Iter 5 (22 features): MAE=5.82, RMSE=7.43

  Top 10 features (MODEL A: Shot Volume):
    sa_avg_20: 778
    opp_team_sog_season_avg: 740
    own_total_missing_toi: 739
    own_team_sog_avg_10: 679
    own_def_missing_toi: 659
    opp_team_hits_avg_10: 598
    sa_avg_10: 591
    opp_team_sog_avg_20: 556
    opp_team_pp_opps_avg_10: 541
    pp_shots_avg_10: 494

============================================================
  MODEL B: Save Percentage
============================================================
  Iter 1 (2 features): MAE=0.05, RMSE=0.08
  Iter 2 (6 features): MAE=0.06, RMSE=0.08
  Iter 3 (11 features): MAE=0.06, RMSE=0.08
  Iter 4 (16 features): MAE=0.06, RMSE=0.08
  Iter 5 (16 features): MAE=0.05, RMSE=0.08

  Top 10 features (MODEL B: Save Percentage):
    opp_team_pp_opps_avg_10: 781
    svpct_season_avg: 759
    own_def_missing_toi: 751
    svpct_avg_20: 737
    svpct_avg_10: 679
    ev_svpct_avg_20: 515
    opp_team_sog_avg_10: 507
    ev_svpct_avg_10: 493
    ga_avg_20: 366
    ga_avg_10: 333

============================================================
  MODEL C: Pull Prediction
============================================================
  Iter 1 (3 features): AUC=0.5375, Acc=0.9420
  Iter 2 (7 features): AUC=0.4836, Acc=0.9404
  Iter 3 (13 features): AUC=0.5046, Acc=0.9477
  Iter 4 (18 features): AUC=0.5380, Acc=0.9540
  Iter 5 (18 features): AUC=0.5510, Acc=0.9538

  Top 10 features (MODEL C: Pull Prediction):
    sa_avg_10: 876
    opp_team_pp_opps_avg_10: 733
    own_def_missing_toi: 723
    ev_svpct_avg_10: 713
    svpct_avg_20: 680
    pull_rate_season: 671
    svpct_avg_10: 624
    opp_team_sog_avg_10: 549
    ga_avg_10: 488
    svpct_season_avg: 475

============================================================
  COMBINED MODEL + EV ANALYSIS
============================================================
Traceback (most recent call last):
  File "/Users/connorrainey/nhc-capital/nhl-betting/model/train_models.py", line 78, in <module>
    main()
    ~~~~^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/model/train_models.py", line 53, in main
    combined_prediction_and_ev(matrix)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/model/train_evaluation.py", line 73, in combined_prediction_and_ev
    val_result = val_df[['event_date', 'player_name', 'line', 'over_odds', 'under_odds',
                 ~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                         'saves', 'shots_against', 'went_over', 'went_under', 'was_pulled',
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                         'opening_line', 'fair_probability', 'market_ev']].copy()
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/.venv/lib/python3.14/site-packages/pandas/core/frame.py", line 4384, in __getitem__
    indexer = self.columns._get_indexer_strict(key, "columns")[1]
              ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/.venv/lib/python3.14/site-packages/pandas/core/indexes/base.py", line 6302, in _get_indexer_strict
    self._raise_if_missing(keyarr, indexer, axis_name)
    ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/.venv/lib/python3.14/site-packages/pandas/core/indexes/base.py", line 6355, in _raise_if_missing
    raise KeyError(f"{not_found} not in index")
KeyError: "['fair_probability', 'market_ev'] not in index"

EXIT_CODE:1
```

### Command

```bash
.venv/bin/python pipeline/daily_picks.py
```

### Output

```text
Traceback (most recent call last):
  File "/Users/connorrainey/nhc-capital/nhl-betting/pipeline/daily_picks.py", line 21, in <module>
    from models.game_totals import run_game_total_over
ModuleNotFoundError: No module named 'models'

EXIT_CODE:1
```

### Command

```bash
.venv/bin/python -m pipeline.daily_picks
```

### Output

```text
/Users/connorrainey/.matplotlib is not a writable directory
Matplotlib created a temporary cache directory at /var/folders/zs/ms67qt1j7fnbypg81csdc1500000gn/T/matplotlib-xo84rzo7 because there was an issue with the default path (/Users/connorrainey/.matplotlib); it is highly recommended to set the MPLCONFIGDIR environment variable to a writable directory, in particular to speed up the import of Matplotlib and to better support multiprocessing.
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/Users/connorrainey/nhc-capital/nhl-betting/pipeline/daily_picks.py", line 439, in <module>
    main()
    ~~~~^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/pipeline/daily_picks.py", line 240, in main
    roster_result = refresh_rosters(verbose=False)
  File "/Users/connorrainey/nhc-capital/nhl-betting/pipeline/roster_refresh.py", line 19, in refresh_rosters
    conn = psycopg2.connect(DB_CONN)
  File "/Users/connorrainey/nhc-capital/nhl-betting/.venv/lib/python3.14/site-packages/psycopg2/__init__.py", line 122, in connect
    conn = _connect(dsn, connection_factory=connection_factory, **kwasync)
psycopg2.OperationalError: connection to server on socket "/tmp/.s.PGSQL.5432" failed: Operation not permitted
	Is the server running locally and accepting connections on that socket?

======================================================================
PRE-FLIGHT: ROSTER REFRESH
======================================================================

EXIT_CODE:1
```

### Additional attempted audit command

```bash
.venv/bin/python model/audit.py
```

```text
/Users/connorrainey/.matplotlib is not a writable directory
Matplotlib created a temporary cache directory at /var/folders/zs/ms67qt1j7fnbypg81csdc1500000gn/T/matplotlib-br9fq128 because there was an issue with the default path (/Users/connorrainey/.matplotlib); it is highly recommended to set the MPLCONFIGDIR environment variable to a writable directory, in particular to speed up the import of Matplotlib and to better support multiprocessing.
Loading feature matrix...
======================================================================
CHECK 1: FEATURE MATRIX STATS
======================================================================
Rows: 2790
Columns: 134
Date range: 2022-10-07 to 2026-02-05
Unique goalies (player_name): 125

Null % per column (showing >0% only):
  svpct_avg_5: 35.91%
  ev_svpct_avg_20: 15.38%
  ev_svpct_avg_10: 15.38%
  ev_shots_avg_10: 15.34%
  pp_shots_avg_10: 15.34%
  ev_shots_avg_20: 15.34%
  sh_shots_avg_20: 15.34%
  pp_shots_avg_20: 15.34%
  sh_shots_avg_10: 15.34%
  svpct_avg_10: 10.9%
  svpct_avg_20: 5.41%
  svpct_season_avg: 4.84%
  pull_rate_season: 2.26%
  high_ga_rate_20: 2.26%
  pull_rate_20: 2.26%
  pull_rate_10: 2.26%
  high_ga_rate_10: 2.26%
  saves_season_avg: 2.26%
  ga_avg_10: 2.26%
  ga_avg_5: 2.26%
  saves_avg_10: 2.26%
  sa_avg_10: 2.26%
  sa_avg_5: 2.26%
  saves_avg_20: 2.26%
  sa_avg_20: 2.26%
  ga_avg_20: 2.26%
  saves_avg_5: 2.26%
  own_team_pp_opps_avg_5: 1.68%
  own_corsi_pct_avg_10: 1.68%
  own_team_hits_avg_5: 1.68%
  own_corsi_pct_avg_5: 1.68%
  own_corsi_diff_avg_5: 1.68%
  own_puck_control_avg_5: 1.68%
  own_team_sog_avg_10: 1.68%
  own_team_sa_avg_10: 1.68%
  own_team_pp_opps_avg_10: 1.68%
  own_team_hits_avg_10: 1.68%
  opp_team_sa_avg_10: 1.68%
  own_corsi_diff_avg_10: 1.68%
  own_puck_control_avg_10: 1.68%
  own_team_sog_avg_20: 1.68%
  own_team_sa_avg_20: 1.68%
  own_team_pp_opps_avg_20: 1.68%
  own_team_hits_avg_20: 1.68%
  own_corsi_pct_avg_20: 1.68%
  own_corsi_diff_avg_20: 1.68%
  own_puck_control_avg_20: 1.68%
  own_team_sog_avg_5: 1.68%
  own_team_sa_avg_5: 1.68%
  own_team_sog_season_avg: 1.68%
  opp_team_sog_season_avg: 1.68%
  opp_puck_control_avg_20: 1.68%
  opp_team_sog_avg_5: 1.68%
  opp_team_sa_avg_5: 1.68%
  opp_team_pp_opps_avg_5: 1.68%
  opp_team_hits_avg_5: 1.68%
  opp_corsi_pct_avg_5: 1.68%
  opp_corsi_diff_avg_5: 1.68%
  opp_puck_control_avg_5: 1.68%
  opp_team_sog_avg_10: 1.68%
  opp_team_pp_opps_avg_10: 1.68%
  opp_team_hits_avg_10: 1.68%
  opp_corsi_pct_avg_10: 1.68%
  opp_corsi_diff_avg_10: 1.68%
  opp_puck_control_avg_10: 1.68%
  opp_team_sog_avg_20: 1.68%
  opp_team_sa_avg_20: 1.68%
  opp_team_pp_opps_avg_20: 1.68%
  opp_team_hits_avg_20: 1.68%
  opp_corsi_pct_avg_20: 1.68%
  opp_corsi_diff_avg_20: 1.68%
  under_odds: 0.04%

======================================================================
CHECK 2: CROSS-REFERENCE 5 RANDOM ROWS VS SOURCE TABLES
======================================================================
Traceback (most recent call last):
  File "/Users/connorrainey/nhc-capital/nhl-betting/model/audit.py", line 32, in <module>
    main()
    ~~~~^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/model/audit.py", line 18, in main
    check2(df)
    ~~~~~~^^^^
  File "/Users/connorrainey/nhc-capital/nhl-betting/model/audit_checks.py", line 43, in check2
    conn = psycopg2.connect(DB)
  File "/Users/connorrainey/nhc-capital/nhl-betting/.venv/lib/python3.14/site-packages/psycopg2/__init__.py", line 122, in connect
    conn = _connect(dsn, connection_factory=connection_factory, **kwasync)
psycopg2.OperationalError: connection to server at "localhost" (::1), port 5432 failed: Operation not permitted
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Operation not permitted
	Is the server running on that host and accepting TCP/IP connections?


EXIT_CODE:1
```
