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
