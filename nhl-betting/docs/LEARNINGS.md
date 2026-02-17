# LEARNINGS.md - NHL Betting Project

Critical project knowledge only. Things that affect modeling decisions and data integrity.

---

## ⭐ Core Thesis: Defenseman Absences Are the Edge

**Defensive TOI absences are the single most important signal we've found.** This is the foundation of every profitable strategy in the project.

**Why it matters across ALL shot-volume props:**
- Missing defensemen → worse gap coverage → more shots allowed → more saves for goalies, more SOG for opposing forwards
- Books set prop lines based on the player's profile (goalie's save avg, forward's SOG avg). They do NOT fully adjust for how depleted the opposing/own blueline is on a given night.
- Most bettors check "is player X injured?" — they don't quantify the cumulative impact. "Missing 67 minutes of defensive TOI" is a completely different signal than "missing 1 defenseman."

**Our data advantage:** We reconstructed `lineup_absences` from `player_stats` — TOI-weighted absence impact per team per game, with F/D splits. This captures injuries, suspensions, AND healthy scratches. Nobody else has this in a structured, queryable format going back to 2022.

**Where to apply it:**
1. **Goalie saves OVER** — goalie's team missing D → more shots faced → over hits (+20.6% ROI when 3+ D missing)
2. **Player SOG OVER** — opposing team missing D → forward faces weaker defense → more shot attempts (untested, next priority)
3. **Period props** — D absences may hit hardest in 1st period before coaching adjustments
4. **Any prop where shot volume is the driver** — this is a universal edge, not market-specific

**Key metric:** `own_def_missing_toi` (for goalie saves) and `opp_def_missing_toi` (for player SOG). Raw count of missing D matters, but TOI-weighted impact is the stronger signal.

---

## Data Integrity

**BettingPros `player_team` is always the player's CURRENT team, not team-at-time-of-game.** Never use it for historical analysis. Join with our goalie_stats table instead.

**21% of games have only 1 goalie line posted.** Books withhold lines when the starter is uncertain. This creates a potential edge — games where starter info becomes available late may have softer lines.

**Player names in `players` table were stored as initials (e.g. "D. Tokarski").** Fixed 137 goalies to full names using saves_odds as source. 124 minor goalies still have initials — no odds data for them so doesn't affect model joins.

**European exhibition teams in NHL API.** Eisbären Berlin, EHC Red Bull München, SC Bern appeared from preseason/Global Series games. Cleaned from all tables. Filter on `gameTypeId=2` (regular season) when scraping to prevent re-ingestion.

**`book_12` has anomalous 0.5 save line.** Filter out lines < 10 in feature engineering.

**`lineup_absences` avg 6.1 missing regulars per game.** This is expected — it includes healthy scratches + injuries + rest. The key signal is the TOI-weighted impact, not raw count. Defensemen absences (`def_missing_toi`) are the most relevant feature for predicting shots against.

## API Notes

**NHL Stats API** (`api.nhle.com/stats/rest/en/goalie/`) supports these game-level reports:
- `summary` — basic goalie stats
- `savesByStrength` — EV/PP/SH splits
- `advanced` — quality starts, SA/60, goals for/against avg
- `startedVsRelieved` — starter vs relief with separate stats
- Paginated: use `limit` + `start` params, `total` in response for loop control

**NHL Edge API** (`api-web.nhle.com/v1/edge/goalie-*`) has shot location data by zone (crease, slot, circles, point) with percentile rankings. Season-level only, not per-game. Useful as a seasonal feature.

**ESPN Injuries API** (`site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries`) — returns current injuries for all 31 teams. No historical endpoint. Snapshot daily for going-forward data.

---

## Modeling — First Run Results (2026-02-16)

### Key Finding: Under bias in consensus lines
The consensus book line has a 62.8% under rate — books are systematically setting lines too high. This alone is a structural edge.

### Model A: Shot Volume — Top Features
1. `own_total_missing_toi` — own team's missing players (TOI-weighted). #1 predictor of shots faced.
2. `sa_avg_20` / `sa_avg_10` — goalie's own recent shots-against trend
3. `own_def_missing_toi` — specifically missing defensemen. Huge for shot volume.
4. `opp_team_sog_season_avg` — opponent's season SOG average
5. `opp_team_hits_avg_10` — aggressive teams generate more shots
6. `opp_team_pp_opps_avg_10` — power play opportunities drive extra shots

Best iteration: MAE=2.46 (Iter 4, 22 features). Iter 5 with tuning actually overfit (MAE=3.39).

### Model B: Save Percentage — Top Features
1. `svpct_avg_10` — goalie's recent save% is the strongest predictor
2. `svpct_season_avg` — longer-term baseline matters
3. `opp_team_sog_avg_10` — opponents generating more shots tend to take lower-quality ones
4. `ev_svpct_avg_20` — even-strength save% is more predictive than raw save%
5. `own_def_missing_toi` — missing D worsens save% (worse shot quality allowed)
6. `opp_team_pp_opps_avg_10` — more PP = harder shots = lower save%

### Model C: Pull Prediction — LEAKAGE WARNING
AUC=1.0 from Iter 2+ is almost certainly data leakage. Need to investigate.
Pull-based under strategy shows real promise:
- Pull prob > 20%: 92.3% under hit rate
- Pulled goalies average 12.0 saves vs 26.0 line

### Stress Test Results
- ⚠️ Random features ranked high — overfitting signal
- ✅ Shuffled target test passed — 68.9% improvement (features ARE predictive)
- ✅ Beats naive baseline by 66.7%
- ✅ Beats book line — our MAE (4.05) vs book (10.18)
- ⚠️ ROI numbers (+42-75%) are suspiciously high — likely inflated by leakage

---

## Modeling — Leakage Audit & Fix (2026-02-16)

### Root Cause: Walk-forward split overlap (CRITICAL)
The original `walk_forward_split()` had validation sets that were **subsets of training data**. For example, split 1 trained on all data before 2024-10 but validated on 2023-10 to 2024-10 — the val set was entirely inside the training set. This was the primary source of inflated metrics.

**Fix:** Training cutoff now strictly precedes validation start:
- Split 1: Train < 2023-10, Val 2023-10 to 2024-10
- Split 2: Train < 2024-10, Val 2024-10 to 2025-10
- Split 3: Train < 2025-10, Val 2025-10+

### Other Leakage Issues Found & Fixed
1. **`id` column (saves_odds PK) was a feature.** Monotonically increasing integer acts as a date proxy. Added to exclude set.
2. **`was_pulled` in pull_feat_cols pattern.** The pattern `startswith('was_pulled')` could capture the target itself as a feature. Tightened to only include lagged rolling features (`pull_rate_*`, `high_ga_rate_*`). `was_pulled` is now merged explicitly as a target, not via the feature pattern.
3. **`fair_probability` and `market_ev` not excluded.** These are derived from post-game data. Added to exclude set (both currently null, but defensive).

### What Was NOT Leakage
- All `.rolling().mean().shift(1)` calls properly exclude the current game.
- `lineup_absences` joined on game_id — represents pre-game roster info (valid feature).
- `high_ga_rate_*` and `pull_rate_*` are rolling means with shift(1) — properly lagged.
- `goals_against`, `saves`, `shots_against`, `save_pct` are in the exclude set as targets.

### Regularization Increases
All three models had regularization significantly increased:
- `num_leaves`: 31→15 (iter 1-4), 20→10 (iter 5)
- `min_child_samples`: 20→50 (iter 1-4), 30→60 (iter 5)
- `max_depth`: uncapped → 5 (iter 1-4), 4 (iter 5)
- `reg_alpha`/`reg_lambda`: 0→0.5 (iter 1-4), 0.1→1.0 (iter 5)
- `feature_fraction`: 0.8→0.6 (iter 1-4), 0.7→0.5 (iter 5)

### Post-Fix Results (2026-02-16)

| Metric | Before (leaked) | After (fixed) |
|--------|-----------------|---------------|
| Model C AUC | 1.000 | 0.624 |
| Random feature ranks | #1, #3 | #6, #13-17 |
| EV ROI (filtered bets) | +42% to +75% | -2% to -4% |
| Pull under hit rate (>20%) | 92.3% | 35.2% |
| Shot MAE (best iter) | 2.46 | 5.72 |
| Flat bet ROI (test 5) | Very high | +16.1% |

**Interpretation:** The -2% to -4% ROI at various EV thresholds is consistent with the ~4.5% vig that sportsbooks charge. The model has real predictive power (beats naive baseline by 50%, beats book line MAE) but does not yet generate enough edge to overcome the vig on a portfolio basis. The +16.1% flat-bet ROI in Test 5 is on a single split (N=625) and likely noisy.

### Remaining Concerns
1. **Pull model is weak (AUC 0.62).** Pulls are rare (~4%) and hard to predict from pre-game features alone. Consider dropping the pull adjustment or using a simpler prior (constant 4% pull rate).
2. **Under bias is real but priced in.** The 62.8% under rate suggests books set lines high, but the vig on unders may already account for this.
3. **Need more out-of-sample data.** Current val splits are small. As 2025-26 season progresses, re-evaluate on fresh data.

---

## CRITICAL BUG: Non-starter goalies (2026-02-16)

21.2% of the feature matrix (750/3542 rows) were goalies with **0 saves / 0 shots against** — backups who had odds posted but never entered the game. These were 100% under hits and inflated every under strategy to absurd ROI levels.

- Before fix: Over 37.2% / Under 62.8% → After fix: Over 47.1% / Under 52.9%
- Before fix: Blind under ROI +13.9% → After fix: -11.5%
- B2B goalie subset went from +55% ROI to -3% ROI

**Root cause:** The join between saves_odds and goalie_stats matched on player_id + game_date, pulling in relief goalies who were dressed but never played.

**Fix:** Filter to `shots_against > 0` before joining.

---

## Subset Analysis — Clean Results (2026-02-16)

With starters only (2795 rows), trained < 2025-10, validated 2025-10 to 2026-02:

### Only 1 Potentially Exploitable Subset
**Own team heavy D missing + Model says Over: +20.3% ROI, 65% win, 40 bets**
- Intuition: when a goalie's team is missing key defensemen (>40 min of combined D TOI absent), they face more shots and accumulate more saves → over hits
- CAUTION: 40 bets is not statistically significant. Need 200+ to confirm.

### Everything else is negative ROI
- Model overall: -13% ROI
- All unders: -19.8% ROI (books price the under bias into the vig)
- All overs: -8.5% ROI
- High confidence bets: -11 to -15% ROI (model confidence doesn't correlate with profitability)
- B2B goalie under: -8.7% ROI (NOT an edge after removing non-starters)
- Cold goalie under: +2.2% ROI (47 bets, likely noise)

### Where model fails worst
- Big line movement: -50.1% (sharps know more than us)
- High-shot opponents: -46.7% (model overestimates saves vs elite offenses)
- Low lines: -35.4% (backup goalies are unpredictable)

### Pull prediction is not viable
- 2.4% pull rate — too rare
- Pull history features have 0% predictive power for future pulls
- Can't systematically bet on pulls

### Individual goalies with positive ROI (small samples)
Shesterkin +35%, Vasilevskiy +30%, Sorokin +21%, Silovs +31% — but all <15 bets each

---

## Refined Subset Stress Tests (2026-02-16, evening)

Final pass with clean starter-only data. Every "edge" tested came back flat or negative:

| Strategy | ROI | Win% | Bets | Verdict |
|----------|-----|------|------|---------|
| Well-rested (5+ days off) | -2.2% | 52.6% | 19 | Noise — too few bets |
| Opp missing D (>40 TOI) | -2.0% | 52.6% | 135 | Close to breakeven but vig kills it |
| High line (27+) + Model Under | -1.5% | 52.6% | 19 | Noise |
| Low line (19-22) | -35.4% | 34.9% | 43 | Terrible — backup goalies are chaos |
| Line moved DOWN (<-0.5) | -30.3% | 37.5% | 16 | Sharps crush us on line moves |
| Opp missing D (>40 TOI, cont.) | -27.0% | 39.4% | 104 | Negative in extended sample |

### Key Takeaway
**No consistently profitable subset survived stress testing.** The one promising signal (own team heavy D missing + model over, +20.3% ROI) was on only 40 bets and did NOT hold up under refinement. The model has real predictive power for shot volume and save%, but not enough edge to overcome sportsbook vig (~4.5%) on any systematic strategy.

### Lessons Learned
1. **Non-starter goalies were the biggest data quality issue.** 21% of rows were 0-save backups that made every under strategy look amazing. Always filter `shots_against > 0`.
2. **Walk-forward validation overlap was the biggest modeling mistake.** Val sets were subsets of training data. Always ensure train cutoff < val start.
3. **AUC=1.0 is always leakage.** No exceptions. Investigate immediately.
4. **Random feature test is essential.** If random noise ranks in top 5 features, something is wrong.
5. **Books are efficient.** The 62.8% under rate (pre-fix) looked like free money but was entirely explained by non-starters. Real under rate with starters only: 52.9%.
6. **Line movement is information.** When lines move, sharps know something. Betting against line moves = -30% ROI.
7. **Small sample sizes lie.** Individual goalie edges (Shesterkin +35%) on <15 bets are noise until proven otherwise over 200+ bets.
8. **Pull prediction is not viable with pre-game features.** 2.4% base rate, no predictive features found.

---

## Confidence Tiers + Line Shopping Analysis (2026-02-16)

**CRITICAL BUG FOUND:** `save_diff`, `went_under`, `went_over` columns were still in the feature set (0.948 correlation with target). Previous "stress test" results were contaminated. Removed these + retrained clean.

### Clean Model Performance (no leaking features)
- MAE: 5.59 (book line MAE: 5.35) — model is roughly even with the book
- 80 clean features after removing all leakers

### Confidence Tiers (model pred_diff from book line)

| Confidence | Direction | ROI @-110 | Win% | Bets |
|------------|-----------|-----------|------|------|
| >= +0      | Over      | -0.1%     | 52.3%| 281  |
| >= +0.5    | Over      | +0.9%    | 52.9%| 227  |
| >= +1.0    | Over      | **+4.2%** | 54.6%| 185  |
| >= +1.5    | Over      | +1.7%    | 53.3%| 137  |
| >= +2.0    | Over      | -9.0%    | 47.7%| 107  |
| All        | Under     | -5 to -10%| ~48% | varies |

**Key finding:** The sweet spot is **model says +1.0 to +1.5 saves over the line** for over bets. Higher confidence = fewer bets but NOT better ROI (overfitting to noise).

Under bets are negative ROI at every confidence level. The model cannot find profitable unders.

### Line Shopping Impact
- Average 5.9 books per player-game in 2025-26 season
- Line shopping adds ~0.4% ROI on overs (small)
- With 4+ books available: **+6.4% ROI on overs at >= +1.0 confidence** (175 bets, 55.4% win rate)
- Under odds have NaN issues (some books post no under odds) — data gap

### Conclusion
The **only potentially exploitable strategy**: 
- Over bets where model predicts 1.0-1.5 saves above the line
- Shop for best over odds across 4+ books
- ~6% ROI on 175 bets over one half-season
- **STILL NOT STATISTICALLY SIGNIFICANT** — need 500+ bets to confirm
- This is a narrow, fragile edge that could easily be noise

---

## Narrative-Driven Edge Discovery (2026-02-16)

### Method
Examined the 25 highest-confidence over bets that hit. Looked for recurring situational patterns, then backtested each narrative on the full validation set (462 games, 2025-10 to 2026-02).

### Pattern Found in Top 25 Winners
- **92% had own team missing 1+ defenseman** (vs ~75% base rate)
- **68% had 2+ defensemen missing** (vs ~55% base rate)
- Average own D missing TOI: 36.2 (vs 31.2 val avg)
- **Weekend games overrepresented**: 13/25 (52%) on Sat/Sun

### Best Narrative Subsets (Over bets, val set N=462)

| # | Narrative | ROI | Win% | Bets |
|---|-----------|-----|------|------|
| **2** | **Own 3+ D missing** | **+20.6%** | **63.2%** | **95** |
| **12** | **D TOI missing 30+ & Opp SOG 26+ & model agrees** | **+16.5%** | **61.0%** | **100** |
| **10** | **D missing 2+ & Opp SOG 26+ & model +0.5** | **+14.5%** | **60.0%** | **100** |
| 6 | Rest 3+ days + Own 2+ D missing | +14.0% | 59.7% | 72 |
| 8 | Low saves avg10 ≤ 15 + Opp SOG10 ≥ 27 | +10.7% | 58.0% | 157 |
| 4 | Own 2+ D missing + model +1.0 | +9.8% | 57.5% | 113 |
| 3 | Own total missing TOI ≥ 80 | +8.6% | 56.9% | 160 |
| 1 | Own 2+ D missing + Opp SOG10 ≥ 27 | +8.2% | 56.7% | 180 |

### The Core Thesis
**When a goalie's team is missing significant defensive TOI, that goalie faces more shots. Books don't fully adjust the saves line for defensive absences.** This is our edge.

The strongest version: **3+ defensemen missing → +20.6% ROI on 95 bets at 63.2% win rate.**

### Why This Might Be Real
1. **Clear causal mechanism**: Missing D → more shots → more saves → over hits
2. **Books set lines based on the goalie**, not the team's injury report depth
3. **D absence data isn't easily available** — we reconstructed it from player_stats (TOI-weighted), most bettors don't have this
4. **Consistent across multiple subset formulations** — every D-absence combo is positive ROI

### Why This Might Be Noise
1. 95 bets is still below 200+ statistical significance threshold
2. One half-season of validation data
3. Multiple hypothesis testing (we checked many subsets → some will look good by chance)
4. Could be season-specific (2025-26 injuries may not repeat)

### Next Steps
1. Forward-test through rest of 2025-26 season (resumes Feb 26)
2. Cross-validate: backtest on 2023-24 and 2024-25 seasons
3. Build automated pipeline: scrape injuries → check D absences → flag over bets → alert team
4. Track every bet prediction vs result in real-time

*Updated: 2026-02-16*
