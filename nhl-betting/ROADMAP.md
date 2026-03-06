# NHL Betting Model — Improvement Roadmap

> Generated from Codex GPT-5.4 statistical audit + skills analysis (2026-03-06)

## Where We Are

**Current architecture:**
- LightGBM regression on goalie saves (rolling features over 5/10/20 game windows)
- 400K+ rows across 28 tables, 3 seasons of data
- Temporal season-based walk-forward splits (good!)
- MF2/MF3/PF1 strategy filters for bet selection
- **Currently profitable** (small sample — could be variance)

**Known issues (from audit):**
1. Live model ≠ research model (two separate codepaths)
2. Feature bug: `sa_avg_*` computed from saves, not shots_against
3. Validation leakage in strategy threshold selection
4. EV calculation is arbitrary linear heuristic, not calibrated
5. Model doesn't beat book line as point predictor in backtests
6. Training entry point crashes

## Phase 1: Fix the Foundation (This Week)
_Codex agent currently working on this_

- [ ] Fix live feature bug (`sa_avg_*` → shots_against)
- [ ] Fix validation leakage (thresholds from training set only)
- [ ] Fix training entry point crash
- [ ] Unify research + live codepaths
- [ ] Standardize DB connection config
- [ ] Run full backtest with fixed code, report MAE vs line

## Phase 2: Statistical Rigor (Next 1-2 Weeks)
_Using statsmodels + time-series skills_

### Calibration (statsmodels skill)
- [ ] Replace linear EV heuristic with **calibrated probability model**
  - Fit logistic regression on (pred_saves - line) → actual over/under outcome
  - Use `statsmodels.discrete.Logit` for proper probabilistic output
  - Plot calibration curves (reliability diagrams)
  - Report Brier score and log-loss alongside ROI

### Diagnostics (statsmodels skill)
- [ ] **Residual analysis** — are prediction errors random or structured?
  - Breusch-Pagan test for heteroskedasticity
  - Durbin-Watson for autocorrelation in residuals
  - Q-Q plots for normality
- [ ] **Feature significance** — which features actually matter?
  - OLS regression with p-values on top LightGBM features
  - Check for multicollinearity (VIF)
  - Permutation importance vs. built-in importance

### Closing Line Value (CLV) Analysis
- [ ] Track opening line → closing line → our prediction
- [ ] If we consistently predict where the line moves, that's real alpha
- [ ] If we don't, our ROI is likely variance

## Phase 3: Time Series Best Practices (Weeks 2-3)
_Using ai-ml-timeseries skill_

### Proper Backtesting Framework
- [ ] **Rolling window backtest** (not just 3 season splits)
  - Walk-forward: train on N games, predict next M, slide forward
  - Report performance by horizon (1-day, 3-day, 7-day ahead)
  - Segment by strategy (MF2 vs MF3 vs PF1)
- [ ] **Baseline comparison** — always benchmark against:
  - Naive baseline (predict the line)
  - Seasonal naive (goalie's season average)
  - Last-10 average
  - If LightGBM doesn't beat these, the model adds no value

### Feature Engineering Improvements
- [ ] **Lag feature audit** — verify all features are strictly point-in-time
- [ ] **Feature freshness** — does the model degrade when data is stale?
- [ ] Consider **team schedule features**: back-to-back, travel distance, rest patterns
- [ ] Consider **opponent-adjusted metrics**: saves vs expected saves based on opponent shot quality

### Probabilistic Forecasting
- [ ] Instead of point predictions, output **prediction intervals**
  - Quantile regression (LightGBM supports this natively)
  - Use 10th/50th/90th percentile predictions
  - Bet sizing based on confidence width, not just point gap
- [ ] **CRPS metric** for probabilistic accuracy

## Phase 4: Production Pipeline (Weeks 3-4)

### API-Driven Model Runs
- [ ] `POST /api/nhl/model-run` — triggers deterministic model run
- [ ] `GET /api/nhl/results` — returns structured JSON (no hallucinations)
- [ ] Dashboard charts: predictions vs actuals, P/L tracking, calibration curves
- [ ] Discord threads call API instead of generating picks from memory

### Monitoring & Drift Detection
- [ ] Daily model performance tracking (MAE, win rate, P/L by strategy)
- [ ] **Concept drift detection** — alert if model accuracy degrades
  - Track rolling 30-day MAE, alert if 2σ above historical
- [ ] **Data quality checks** — alert on missing odds, stale game data
- [ ] Automated retraining trigger when performance drops below threshold

## Data Limits & Honest Assessment

### What We Have
- ~3 seasons of goalie saves data (2023-2026)
- ~44K odds records, ~22K goalie stat records
- ~9.5K goalie advanced metrics
- Full team-level Corsi/shot data

### What Limits Us
- **Sample size**: ~5,200 games across 3 seasons. For a strategy that fires on 5% of games, that's ~260 bets. Need 1000+ for statistical significance on ROI.
- **Regime changes**: NHL rule changes, team roster turnover, coaching changes mean old data may not predict current behavior
- **Odds market efficiency**: The book line already incorporates most public information. Beating it consistently requires exploiting specific inefficiencies.
- **Data latency**: Odds data scraped hourly. Lines can move significantly in the last hour before puck drop.

### When to Trust Results
- **Win rate**: Need 300+ graded picks before claiming a strategy "works" (p < 0.05 on binomial test vs 50%)
- **ROI**: Need 500+ bets before claiming positive ROI is real (Kelly criterion assumes accurate probabilities)
- **CLV**: If we consistently beat closing lines, that's the strongest signal — but we don't track this yet

### Skills Reference
- `statsmodels` — calibration, diagnostics, significance testing, GLMs
- `ai-ml-timeseries` — rolling backtests, leakage prevention, LightGBM patterns, drift monitoring
- `pandas` — data manipulation and EDA
- `python-dataviz` — calibration plots, residual analysis, performance charts
- `data-analysis` — hypothesis testing, EDA workflows

## Decision: What Stats Libraries Do We Need?

### Definitely Using
- **LightGBM** — keep as primary model (fast, handles tabular data well)
- **statsmodels** — calibration (Logit), diagnostics (Breusch-Pagan, Durbin-Watson), significance tests
- **scikit-learn** — metrics (MAE, RMSE, Brier, log-loss, AUC), calibration curves
- **pandas** — already using, keep

### Probably Using
- **scipy.stats** — binomial tests for win rate significance, confidence intervals
- **matplotlib/seaborn** — calibration plots, residual analysis, performance dashboards

### Maybe Later
- **Prophet** — if we detect strong seasonality patterns (day-of-week, monthly trends)
- **Chronos/TimesFM** — foundation models for time series, useful if we move to multi-step forecasting
- **XGBoost** — benchmark against LightGBM (usually similar, but worth checking)
- **Polars** — faster than pandas for large feature engineering (not needed yet at our scale)
