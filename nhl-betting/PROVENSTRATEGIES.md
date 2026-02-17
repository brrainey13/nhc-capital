# Proven Goalie Saves O/U Strategies

**Validated:** 2026-02-17 | **Data:** 2,795 games, 3-season walk-forward (22-23 → 25-26)

## Strategy Matrix (Quick Reference)

| Strategy | Side | Gap Range | Corsi Threshold | Other Filters | Bets | Win% | ROI | Independence |
|----------|------|-----------|-----------------|---------------|------|------|-----|-------------|
| **MF3** | UNDER | ≥1.0 | Bottom 25% | — | 197 | 63.5% | +16.4% | Baseline |
| **MF3a** | UNDER | [1.0-1.5) | Bottom 25% | — | 47 | 72.3% | +34.3% | Subset of MF3 |
| **MF3b / MF4** | UNDER | ≥2.5 | Bottom 25% | — | 92 | 65.2% | +20.6% | Subset of MF3 |
| **MF5** | UNDER | ≥1.0 | Bottom 30% | — | 233 | 62.7% | +16.0% | Superset of MF3 |
| **MF2** | UNDER | ≥2.0 | None | B2B (rest ≤1d) | 89 | 64.0% | +23.0% | 40% overlap w/ MF3 |
| **PF1** | OVER | Any | Top 25% Corsi + Diff + Puck | No model | 98 | 59.2% | +8.8% | 0% overlap w/ unders |

**Note:** MF3b and MF4 are identical — same filter logic (gap ≥2.5, bottom 25% Corsi). MF3a is the [1.0-1.5) slice. Together MF3a + dead zone skip + MF3b = MF3 without gap [1.5-2.5).

### Dead Zone: Gap [1.5-2.5) — 53.4% win rate, -13.3% ROI
Skip this range. See `model/dead_zone_analysis.md` for full investigation. Key cause: home goalies vs elite offenses where low Corsi doesn't mean low danger. Model prediction is directionally correct but actual saves cluster at the line.

---

## Strategy 1: MF3 — UNDER: Model + Low Opponent Corsi
**Best overall. Highest volume, statistically significant.**

- **Signal:** LightGBM predicts saves ≥1 below the line AND opponent's 10-game rolling Corsi% is in bottom 25th percentile
- **Side:** UNDER only
- **Results:** 63.5% win rate | +16.4% ROI | 197 bets | 95% CI [56.5%, 69.9%]
- **Per season:** S1 +24.9% (86 bets) | S2 +11.4% (93 bets) | S3 +12.8% (18 bets)
- **Juice buffer:** Survives -120 vig (+11.1pp margin over breakeven)

### Recommended deployment: Split into MF3a + MF3b, skip dead zone
- **MF3a** (gap [1.0-1.5)): 47 bets, 72.3% win, +34.3% ROI — sharpest signal
- **Dead zone** (gap [1.5-2.5)): SKIP — 58 bets, 53.4% win, -13.3% ROI
- **MF3b** (gap ≥2.5): 92 bets, 65.2% win, +20.6% ROI — high conviction

### Model Features (LightGBM regressor, target=saves)
```
sa_avg_10, sa_avg_20, svpct_avg_10, svpct_avg_20, is_home,
opp_team_sog_avg_10, days_rest, own_def_missing_toi,
opp_corsi_pct_avg_10, opp_corsi_diff_avg_10,
own_corsi_pct_avg_10, pull_rate_10, starts_last_7d,
opp_team_pp_opps_avg_10, line
```

### Model Params
```
objective=regression, num_leaves=10, max_depth=4, min_child_samples=50,
learning_rate=0.05, n_estimators=300, reg_alpha=0.5, reg_lambda=0.5,
feature_fraction=0.6, bagging_fraction=0.7, bagging_freq=5
```

### Filter Logic
```python
pred = model.predict(features)
model_gap = abs(pred - line)
model_side = 'under' if pred < line else 'over'
opp_corsi_q25 = val['opp_corsi_pct_avg_10'].quantile(0.25)

BET UNDER when:
  model_side == 'under'
  AND model_gap >= 1.0
  AND opp_corsi_pct_avg_10 < opp_corsi_q25
```

---

## Strategy 2: MF2 — UNDER: Model + Back-to-Back Goalie
**Highest ROI. Most independent signal (only 34-40% overlap with Corsi strategies).**

- **Signal:** LightGBM predicts saves ≥2 below the line AND goalie is on a back-to-back (days_rest ≤ 1)
- **Side:** UNDER only
- **Results:** 64.0% win rate | +23.0% ROI | 89 bets | 95% CI [53.7%, 73.2%]
- **Per season:** S1 +30.8% (27 bets) | S2 +7.0% (45 bets) | S3 +31.3% (17 bets)
- **Juice buffer:** Survives -120 vig (+11.7pp margin)

### Filter Logic
```python
BET UNDER when:
  model_side == 'under'
  AND model_gap >= 2.0
  AND days_rest <= 1
```
Same model as MF3 above.

---

## Strategy 3: PF1 — OVER: Triple Corsi Filter (needs more data)
**Pure filter, no model. Good diversifier but CI dips below breakeven.**

- **Signal:** Opponent's 10-game Corsi%, Corsi diff, AND puck control (takeaways - giveaways) all in top 25th percentile
- **Side:** OVER only
- **Results:** 59.2% win rate | +8.8% ROI | 98 bets | 95% CI [49.3%, 68.4%] ⚠️
- **Per season:** S1 +4.5% (37 bets) | S2 +13.8% (34 bets) | S3 +7.9% (27 bets)
- **Juice buffer:** Survives -120 vig (+6.8pp margin)

### Filter Logic
```python
BET OVER when:
  opp_corsi_pct_avg_10 > quantile(0.75)
  AND opp_corsi_diff_avg_10 > quantile(0.75)
  AND opp_puck_control_avg_10 > quantile(0.75)
```

---

## Note: MF4 = MF3b
MF4 was originally created as "high-conviction MF3 with gap ≥ 2.5". It is **identical** to MF3b. Use MF3b nomenclature going forward.

---

## Strategy 5: MF5 — UNDER: Optimized Corsi Threshold (30th percentile)
**Wider Corsi net, maximizes edge × volume.**

- **Signal:** Same model as MF3 but uses bottom 30% Corsi instead of 25%
- **Side:** UNDER only
- **Results:** 62.7% win rate | +16.0% ROI | 233 bets
- **Edge×Volume score:** 24.0 (best of all threshold/gap combos tested)
- **Rationale:** Threshold sweep tested 20%/25%/30%/35% at gap 1.0/1.5/2.0. Bottom 30% + gap≥1 maximizes the product of (win_rate - breakeven) × bet_volume. Slightly lower win% than MF3 (62.7 vs 63.5) but 18% more volume.

### Filter Logic
```python
BET UNDER when:
  model_side == 'under'
  AND model_gap >= 1.0
  AND opp_corsi_pct_avg_10 < quantile(0.30)
```

---

## MF3 Gap Distribution (for reference)
| Gap Bucket | Bets | Win% | ROI |
|-----------|------|------|-----|
| [1.0-1.5) | 47 | 72.3% | +34.3% |
| [1.5-2.0) | 26 | 61.5% | +13.6% |
| [2.0-2.5) | 32 | 46.9% | -13.3% |
| [2.5+] | 92 | 65.2% | +20.6% |

## MF2 Gap Distribution
| Gap Bucket | Bets | Win% | ROI |
|-----------|------|------|-----|
| [2.0-2.5) | 29 | 58.6% | +8.9% |
| [2.5-3.0) | 17 | 88.2% | +62.9% |
| [3.0+] | 43 | 58.1% | +8.1% |

**MF2 sweet spot:** Gap [2.5-3.0) is absurd — 88.2% win rate, +62.9% ROI on 17 bets. Small sample but worth tracking separately.

---

## Key Derived Features

### Corsi (from `game_team_stats.shots_attempted`)
- `corsi_pct = shots_attempted / (shots_attempted + opp_shots_attempted)` — possession proxy
- `corsi_diff = shots_attempted - opp_shots_attempted` — shot attempt differential
- Rolling windows: 5, 10, 20 games (10 is primary)

### Puck Control
- `puck_control = takeaways - giveaways` per game, rolled over 10 games

### Possession Proxy
- `0.4 * faceoff_win_pct/100 + 0.6 * corsi_pct` (not used in final strategies but available)

### Data Sources
- **Feature matrix:** `model/feature_matrix.pkl` (2,795 rows, 110+ cols)
- **Corsi derived at runtime** from `game_team_stats` table (shots_attempted, takeaways, giveaways, faceoff_win_pct)
- **Model trained per split** — walk-forward, never sees future data

---

## Validation Summary
| Test | MF3 | MF2 | MF4 | MF5 | PF1 |
|------|-----|-----|-----|-----|-----|
| All seasons positive | ✅ | ✅ | — | — | ✅ |
| No season <5% ROI | ✅ | ✅ | — | — | ⚠️ S1=4.5% |
| Survives -115 juice | ✅ | ✅ | ✅ | ✅ | ✅ |
| 95% CI above breakeven | ✅ | ✅ | — | — | ⚠️ |
| Independent signal | — | ✅ (40% overlap w/ MF3) | subset of MF3 | superset of MF3 | ✅ (0% overlap w/ unders) |

## Deployment Recommendations
- **Core pair:** MF3 + MF2 (independent signals, both validated)
- **MF4:** Use as confidence tier within MF3 — same bets, flag gap≥2.5 for larger sizing
- **MF5:** Replace MF3 with this if you want more volume (+18%) at slight win% cost
- **PF1:** Track paper only until sample reaches ~200 bets
