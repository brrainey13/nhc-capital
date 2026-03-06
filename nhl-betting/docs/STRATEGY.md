# Goalie Saves O/U Strategy Log

## Baseline (existing model)
- 2795 samples, 110 features, 3-season walk-forward validation
- Top shot features: sa_avg_10, opp_sog_season_avg, own_def_missing_toi
- Top svpct features: svpct_avg_10, own_def_missing_toi, svpct_season_avg

---

## Round 1 — 2026-02-17 11:52
- **S1: Baseline LightGBM**: 🔴 Avg ROI: -7.0%, Win rate: 50%, Bets: 4254
- **S2: Corsi for shot prediction**: 🔴 Avg ROI: -8.7%, Win rate: 49%, Bets: 4254
- **S3: Possession proxy saves**: 🔴 Avg ROI: -10.2%, Win rate: 48%, Bets: 4254
- **S4: High Corsi quartile over/under**: 🔴 Avg ROI: -0.8%, Win rate: 53%, Bets: 1063
- **S5: Rest days B2B filter**: 🔴 Avg ROI: -4.2%, Win rate: 52%, Bets: 899

## Round 2 — 2026-02-17 12:22
- **S6: Line movement signal**: 🔴 Avg ROI: -9.9%, Win rate: 48%, Bets: 260
- **S7: SvPct mean reversion**: 🔴 Avg ROI: -8.4%, Win rate: 49%, Bets: 1112
- **S8: Opponent missing D**: 🔴 Avg ROI: -6.5%, Win rate: 50%, Bets: 1536
- **S9: Full Corsi LightGBM**: 🔴 Avg ROI: -4.0%, Win rate: 52%, Bets: 4254
- **S10: Pull probability under**: 🔴 Avg ROI: -2.8%, Win rate: 52%, Bets: 1009

## Round 3 — 2026-02-17 12:52
- **S11: Extreme lines regression**: 🔴 Avg ROI: -12.1%, Win rate: 48%, Bets: 994
- **S12: Corsi diff threshold**: 🔴 Avg ROI: -0.1%, Win rate: 54%, Bets: 1053
- **S13: Faceoff possession proxy**: No valid data.
- **S14: Saves vs line gap**: 🔴 Avg ROI: -3.1%, Win rate: 52%, Bets: 2013
- **S15: Home/away split**: 🔴 Avg ROI: -8.0%, Win rate: 50%, Bets: 2125

## Stacked Filters — 2026-02-17 13:01

### ✅ Pure Filter Winners (all splits positive)
- **UNDER low_corsi_diff + line_dropped**: ROI +40.2%, Win 75%, 32 bets
- **UNDER low_corsi_diff + saves_below_line + line_dropped**: ROI +38.4%, Win 74%, 31 bets
- **OVER high_corsi + high_corsi_diff + good_puck_control**: ROI +8.8%, Win 59%, 98 bets
- **OVER high_corsi_diff + own_d_missing + good_puck_control**: ROI +5.7%, Win 58%, 99 bets
- **OVER high_corsi + good_puck_control**: ROI +5.6%, Win 58%, 106 bets

### ✅ Model + Filter Winners (all splits positive)
- **UNDER model(gap>=2) + low_corsi_diff**: ROI +27.9%, Win 69%, 119 bets
- **UNDER model(gap>=2) + b2b**: ROI +23.0%, Win 66%, 89 bets
- **UNDER model(gap>=2) + low_corsi**: ROI +21.3%, Win 66%, 124 bets
- **UNDER model(gap>=1) + low_corsi**: ROI +16.4%, Win 63%, 197 bets
- **UNDER model(gap>=1.5) + low_corsi**: ROI +15.8%, Win 63%, 150 bets

## Validation Diagnostics — 2026-02-17 16:07
See validation_diagnostics.md for full report.
- 2/5 strategies pass all stability checks
- ⚠️ 4 high-overlap pairs detected

## Optimization Results — 2026-02-17 16:54
### Gap Distribution
- MF3 [1.0-1.5): 47 bets, 72.3% win, +34.3% ROI
- MF3 [1.5-2.0): 26 bets, 61.5% win, +13.6% ROI
- MF3 [2.0-2.5): 32 bets, 46.9% win, -13.3% ROI
- MF3 [2.5+]: 92 bets, 65.2% win, +20.6% ROI
- MF2 [2.0-2.5): 29 bets, 58.6% win, +8.9% ROI
- MF2 [2.5-3.0): 17 bets, 88.2% win, +62.9% ROI
- MF2 [3.0+]: 43 bets, 58.1% win, +8.1% ROI

### Optimal Corsi Threshold
- Best: bottom 30%, gap≥1.0 → 233 bets, +16.0% ROI
