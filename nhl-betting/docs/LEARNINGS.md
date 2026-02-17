# LEARNINGS.md - NHL Betting Project

Critical project knowledge only. Things that affect modeling decisions and data integrity.

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

### Known Issues
1. Pull model has data leakage — reconstruct with strictly lagged features
2. Random feature test shows overfitting — need stronger regularization
3. Win rates too high — verify no lookahead in feature engineering
4. Walk-forward splits may have overlap with rolling features

*Updated: 2026-02-16*
