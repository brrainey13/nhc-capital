# OVER 1.5 Points Model — Summary

**Date:** 2026-02-26 | **Data:** 197K player-games, 2022-2026

## Model Architecture

- **Type:** LightGBM binary classifier (2+ points = 1, else 0)
- **Train:** 131,588 rows (Oct 2022 – Apr 2025)
- **Test:** 31,107 rows (Oct 2025 – Feb 2026)
- **Baseline multi-point rate:** 9.0%

## Performance

- **Test AUC: 0.7586** — strong discriminative power
- **Calibration:** Model overestimates probabilities (predicts 65% avg for top bucket, actual = 18%)
- **Use as ranking tool, not raw probability**

## Top Features (by importance)

| Rank | Feature | Importance | Interpretation |
|------|---------|-----------|----------------|
| 1 | `toi_avg_10` | 648 | Ice time = opportunity |
| 2 | `season_pts_avg` | 513 | Baseline production level |
| 3 | `opp_ga_avg_10` | 472 | **Opponent defensive quality — KEY** |
| 4 | `pp_toi_avg_10` | 420 | **Power play time — huge signal** |
| 5 | `shots_avg_10` | 382 | Shot volume = more chances |
| 6 | `season_mp_pct` | 366 | Historical multi-point frequency |
| 7 | `pts_avg_20` | 254 | Long-term production trend |
| 8 | `days_rest` | 140 | Rest matters (post-break, B2B) |
| 9 | `assists_avg_10` | 119 | Playmaking ability |
| 10 | `is_forward` | 79 | Forwards > defensemen for multi-point |

## Deployment Strategy: Hybrid (Model Rank + Hit Rate)

The model alone is miscalibrated. **Combining model ranking with actual season hit rate is the winning formula.**

### Results at +225 average odds (breakeven = 30.8%)

| Filter | Bets | Wins | Win Rate | ROI |
|--------|------|------|----------|-----|
| Model top 5% only | 1,556 | 525 | 33.7% | **+9.7%** |
| Model top 2% only | 623 | 242 | 38.8% | **+26.2%** |
| Model ≥30% + season rate ≥25% | 2,678 | 879 | 32.8% | **+6.7%** |
| Model ≥30% + season rate ≥30% | 1,401 | 536 | 38.3% | **+24.3%** |
| Model ≥30% + season rate ≥35% | 652 | 288 | 44.2% | **+43.6%** |
| Model ≥30% + season rate ≥40% | 444 | 210 | 47.3% | **+53.7%** |

### Recommended deploy rule:

**Bet OVER 1.5 points when:**
1. Model probability ≥ 30% (top ~60% of model output), AND
2. Player's season multi-point rate ≥ 30% (they actually hit 2+ points in 30%+ of games), AND  
3. Available odds ≥ +200 (to clear breakeven with margin)

**Expected: ~1,400 bets/season, 38.5% win rate, +25% ROI**

For higher conviction (smaller volume): require season rate ≥ 35% → 44% WR, +44% ROI on ~650 bets.

## What the Model Tells Us About Multi-Point Games

**The profile of a multi-point game:**
- High ice time (18+ min/game average)
- Significant PP deployment (3+ min PP TOI)
- Strong underlying production (0.8+ P/GP season average)
- Facing a defensively weak opponent (3.0+ GA/game avg)
- Recent point streak helps (pts_last_3 signal)

**What doesn't matter much:**
- Home/away (small effect)
- Power play goals specifically (PP TOI matters more than PP goals)
- Short-term rolling (5-game) vs medium-term (10-game) — both work

## Data Enhancement Recommendations (V2)

1. **Vegas game total (O/U)** — highest-priority missing feature. High-total games (6.5+) should strongly predict multi-point performances.
2. **PP1 vs PP2 unit assignment** — PP1 players get roughly 2x the opportunity. Currently proxied by pp_toi but explicit PP1 flag would sharpen the signal.
3. **Opponent PK%** (rolling 10g) — weak penalty kills = more PP points, directly feeds the multi-point thesis.
4. **Player-level xG/xA** (NaturalStatTrick) — quality-adjusted production separates real talent from lucky streaks.
5. **Line combination stability** — consistent linemates = better chemistry = more multi-point games.
6. **Score state / game script** — projected close games generate more even-strength offense for both teams.

## Files

- `model/points_15_model.py` — training script
- `model/points_15_feature_importance.csv` — feature rankings
- `model/points_15_test_predictions.csv` — out-of-sample predictions
