# LEARNINGS.md — SOG Model Diary

Read this before every task. Write to it after every task. Keep entries brief.

---

## 2026-02-18: Audit Fix — Corsi Features Missing from feature_matrix.pkl

### Root Cause
`build_features.py` computed team rolling features (`team_sog_avg`, `team_sa_avg`, etc.) but never derived Corsi from `game_team_stats.shots_attempted`. The research scripts (`strategy_research.py`, `stacked_filters.py`) derived Corsi inline and produced MF3 results that went into PROVENSTRATEGIES.md — but the pkl never had Corsi. MF3 was non-functional from the saved data.

### Fix
- Added Corsi derivation to `build_features.py`: self-join `game_team_stats` to get opponent `shots_attempted`, compute `corsi_pct`, `corsi_diff`, `puck_control` (takeaways - giveaways), then rolling 5/10/20 for both own and opponent teams.
- Fixed column filter that only picked `team_*` prefixed columns — now also picks `corsi_*` and `puck_control_*`.
- Added deduplication (5 rows had same goalie+date with different lines).
- Dropped 2 fully-null columns (`market_ev`, `fair_probability`).
- Result: 2,790 rows × 134 columns with 20 Corsi + 6 puck control features.

### Re-Audit Results
- **MF3**: 214 bets, 62.1% WR, +18.6% ROI, p=0.0025 ✅
- **MF2**: 98 bets, 62.2% WR, +18.8% ROI, p=0.031 ✅
- Both survive ±10% threshold sensitivity
- MF3 Fold 3 is weak (54.2%, 24 bets) — possible signal decay

### Lesson
**Never derive features only in research scripts.** If a feature matters for a strategy, it MUST be in `build_features.py` and persisted in the pkl. Research scripts should read from the pkl, not compute their own features.

---

## 2026-02-17: PP TOI Feature Discovery & Testing

### Data Acquisition
- NHL Stats API has per-game PP stats: `api.nhle.com/stats/rest/en/skater/powerplay`
- Use `isGame=true&isAggregate=false` for per-game granularity
- **10k record hard cap** — must paginate by team (`teamId=X`) to get all data
- ~47k records/season, ~1,476 per team per season
- Loaded into `player_pp_stats` table: 168,165 rows across 4 seasons (2022-23 through 2025-26)
- Long scrapes get SIGKILL'd — run in team-sized chunks, not full season loops

### Key Fields Available
- `pp_toi_seconds` — the main feature (convert to minutes)
- `pp_shots`, `pp_shots_per60`, `pp_goals`, `pp_assists`, `pp_points`
- `pp_individual_cf` (Corsi on PP), `pp_shooting_pct`
- `pp_goals_for_per60` (team PP goals/60 while player on ice)

### Feature Test Results
- **PP TOI avg (10g) → next game shots: r=0.3227** — 2nd strongest predictor after sog_avg_20 (0.3833)
- Nearly **2x stronger than total TOI** (toi_avg_10 = 0.1848)
- SHAP ranking: #3 overall (0.0692), ties with toi_avg_5 (0.0690), dominates toi_avg_10 (0.0237)
- MAE improvement: only +0.05% — tree model already partially infers PP usage from other features
- Stronger for forwards (r=0.317) than defensemen (r=0.280), but works for both

### Verdict
- **Include PP TOI alongside total TOI, don't replace it** — different signal (PP role vs general ice time)
- Biggest edge at margins: PP1 vs PP2 distinction matters most for high-line players
- Rolling windows: 10-game avg is the sweet spot (5g noisier, 20g slightly better but slower to react)

### Gotchas
- `sog_odds` table uses `bp_player_id` + `event_date`, NOT `player_id` + `game_id` — joins need mapping
- `sog_odds` line bucket analysis failed because ID systems don't align cleanly with `player_stats.player_id`
- Need to build a player ID crosswalk between `bp_player_id` (BestProps) and NHL `player_id` for full SOG model
- Dashboard `PROJECT_GROUPS` in `App.tsx` needs manual update when adding new NHL tables

### Existing Best Features (baseline)
- `sog_avg_20` (r=0.3833) — king feature, hard to beat
- `toi_avg_5` / `toi_avg_10` (r≈0.185)
- `sog_allowed_avg_10` (r=0.004) — weak, nearly useless as raw correlation
- `is_home`, `position` (categorical controls)

## 2026-02-17: SOG Odds Name Bridge (SOLVED)

### The Problem
- `sog_odds` uses `bp_player_id` (BestProps) + `event_date` — completely different ID system from NHL `player_id` + `game_id`
- `event_id` range (10k-15k) vs `game_id` range (2B+) — zero overlap, different systems entirely
- Dates DO overlap — `event_date` matches `game_date` reliably

### Solution: Name + date bridge
- Normalize names (lowercase, strip accents, handle nicknames) → join `sog_odds.player_name` to `player_pp_stats.player_name`
- **99.9% match rate** — 457 of 457 players matched (173,754 of 173,985 rows)
- Only 2 mismatches: "Yegor Chinakhov" vs "Egor Chinakhov" (fixed manually), "Alex Nylander" vs "Alexander Nylander" (auto-caught)

### Bridge File
- `model/player_odds_bridge.csv` — 457 mappings: `bp_player_id` → `player_id`
- Line values validated: range [0.5, 5.5], mean 2.44, all reasonable
- Spot checks pass: McDavid avg 3.57, Matthews 4.31, MacKinnon 4.53, Draisaitl 2.94, Kucherov 3.53

### Key Gotchas
- `sog_odds` has multiple rows per player per date (different books) — need to aggregate or pick best line
- Name normalization must handle: accents (é→e), hyphens, Jr/Sr suffixes, "Yegor"/"Egor" variants
- Bridge is at player level, not game level — join via `bp_player_id → player_id` then `event_date = game_date`

## 2026-02-17: Full SOG Backtest

### Setup
- Train: 2022-23 (7,990 rows), Test: 2023-24 (8,959 rows)
- Separate XGBoost models for forwards and defensemen
- Features: sog_avg_20/10/5, pp_toi_avg_10/5, toi_avg_5, sog_allowed_avg_10, is_home, team_book_bias
- Consensus line = avg across all books per player per date
- Edge threshold: |predicted - line| > 0.75

### Results
- **63.5% win rate, +11.6% ROI, +287.26 units** over 2,475 bets
- Kelly P&L: +$2,538.56, max drawdown $70.56, Sharpe 1.23
- Model MAE (1.2400) slightly worse than book MAE (1.2307) — but betting edge comes from directional accuracy, not MAE

### Key Findings
- **OVER bets dominate**: 2,418 over vs 57 under. Over win rate 63.7%/+12.0% ROI. Under barely triggered.
- **Low lines (0-2) are the sweet spot**: 67.5% win rate, +13.6% ROI, 1,822 bets
- **High lines (4+) are death**: 30.2% win rate, -44.7% ROI — avoid
- **Defense slightly more profitable**: D +17.0% ROI vs F +10.2% ROI (but fewer bets)
- **Bigger edges = better ROI**: 0.75-1.0 edge = +9.9%, 1.0-1.5 = +13.1%, 1.5+ = +20.0%
- **Oilers most profitable team**: +70.5% ROI (small sample, 64 bets)

### Gotchas
- `games` table uses `season` not `season_id`
- `teams` table uses `team_name` not `name`
- sog_odds date coverage: 2022-23 full, 2023-24 partial (163 dates), 2024-25 ZERO, 2025-26 barely 3 dates
- No odds data gap = can't backtest on recent seasons without scraping more odds
- Pandas can't assign NaN to bool column — use float for `won` column with pushes

### Outputs
- `sog_backtest_results` table in DB (2,479 rows, on dashboard under NHL Betting)
- `docs/backtest_summary.md`
- `model/pnl_curve.png`

### Open Questions
- Can we get PP unit assignment (PP1 vs PP2)? API only gives total PP TOI, not unit-level
- Would pp_shots_per60 add signal beyond pp_toi_minutes?
- Need to scrape 2024-25 odds to backtest on more recent data
- Why so few UNDER bets? Model may be biased toward over predictions
- Should we cap line bucket at 3.5 (avoid 4+ entirely)?
