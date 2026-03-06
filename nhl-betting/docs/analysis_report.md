# SOG Exploratory Analysis Report

**Date:** 2026-02-17 | **Data:** 183,743 player-game observations, 5,105 games, 1,290 players

---

## Top 5 Strongest Signals

### 1. Player's 20-Game Rolling SOG Average (r = +0.371)
The single most predictive pre-game feature. A player's long-term shooting rate is the best indicator of how many shots they'll take tonight. The 20-game window outperforms 10-game (r=0.344), 5-game (r=0.299), and 3-game (r=0.269) windows — longer smoothing wins because individual game SOG is noisy.

### 2. Position (D vs Forward: 1.94 vs 2.33 avg SOG)
Defensemen average 0.4 fewer shots per game than forwards. This is a massive structural difference — position should be a core feature, and ideally the model should treat D-men separately or include position as a strong categorical. Among forwards, wingers (R=2.40, L=2.33) slightly outshoot centers (2.27).

### 3. Rolling Ice Time (toi_avg_5: SHAP = 0.076)
Players who get more ice time take more shots. Recent 5-game TOI average is a strong pre-game signal and the third most important feature by SHAP. This captures coaching decisions (top-line promotion, power play time) that directly translate to shot opportunities.

### 4. Book Line Inefficiency at Low Lines (72.5% over rate at 0-2 lines)
The sportsbooks systematically set SOG lines too low for fringe players (lines of 0.5-2.0). Actual SOG exceeds the line 72.5% of the time in this range, with a +1.15 bias. This is the single biggest market inefficiency we found — the books underestimate how often low-usage players will get at least 1-2 shots.

### 5. Opponent Defensive Quality (r = +0.055, effect = +0.19 SOG)
Playing against a team that allows more shots (weak defense) adds ~0.19 SOG per game vs strong defenses. The correlation is modest (r=0.055) but the effect is consistent. Worst defenses: ANA (33.6 SOG allowed/game), ARI (33.4), CBJ (32.7). Best: CAR (25.4), UTA (26.0).

---

## Recommended Feature Priority for Full Model

### Tier 1 — Must Include
- `sog_avg_20` — dominant predictor (r=0.371, SHAP=0.303)
- `sog_avg_10` — shorter window captures recent form shifts
- `toi_avg_5` / `toi_avg_10` — ice time proxy for role/deployment
- `position_code` — structural difference between D and F
- `line` (from sog_odds) — the book's own prediction, strong baseline

### Tier 2 — Include
- `sog_allowed_avg_10` — opponent defense quality
- `is_home` — small but consistent +0.07 SOG home advantage
- `sog_avg_5` — noisier but captures hot streaks

### Tier 3 — Test but May Not Help
- `fwd_missing_toi` / `def_missing_toi` — near-zero correlation, but might interact with other features
- Team-level features (own team's shots_attempted rolling avg)

### Drop
- `fwd_missing`, `def_missing`, `total_missing` (count) — no signal
- All same-game stats (goals, assists, hits, etc.) — not available pre-game

---

## Surprising Findings

### 1. Books are biased HIGH on star players, LOW on depth players
Lines 0-2 (depth players) go over 72.5% of the time. Lines 3-4+ (stars) go over only 41-43%. The books overestimate stars and underestimate depth — there's a regression-to-the-mean effect they're not fully pricing.

### 2. Lineup absences don't matter for individual SOG
We expected missing teammates to increase remaining players' shots (more ice time, more opportunity). Correlation is essentially zero (r < -0.02). Either the effect is too diffuse across the roster or replacement players absorb the minutes without changing shot distribution.

### 3. Longer rolling windows beat shorter ones consistently
20-game > 10-game > 5-game > 3-game for predicting next-game SOG. This suggests SOG is more of a "talent rate" than a "momentum" stat — a player's shooting rate is relatively stable and recent hot/cold streaks don't persist strongly.

### 4. Team-level book biases are large and persistent
COL players consistently exceed their SOG lines by +1.04 shots on average. EDM by +0.85, TOR by +0.81. These aren't small samples (764, 904, 666 bets respectively). Books may be slow to adjust to team pace/style.

### 5. Opponent defense is weaker than expected
r=0.055 is surprisingly low. In hockey, you'd expect matchup to matter more. This suggests that individual player shooting tendencies dominate over opponent effects — a player who shoots a lot will shoot a lot regardless of opponent.

---

## Model Baseline

- **Book line MAE:** 1.41 shots
- **Pre-game LightGBM MAE:** 1.003 (in-sample — will degrade out-of-sample)
- **Naive baseline (predict mean):** ~1.38 MAE
- The gap between book (1.41) and model (1.00) is promising but needs walk-forward validation to confirm real edge

---

## Next Steps

1. Build walk-forward validated model with Tier 1+2 features
2. Focus on the low-line inefficiency (0-2 range) as primary edge
3. Test team-specific adjustments for COL/EDM/TOR over-bias
4. Consider separate models for D-men vs forwards
5. Add the book line as a feature — it encodes market consensus and is very informative
