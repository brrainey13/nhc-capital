# Validation Diagnostics — 2026-02-17 16:07

## 1. Strategy Overlap
⚠️ 4 pairs have >70% overlap — not fully independent edges.
- PF1_over_corsi3 ↔ PF2_over_corsi_puck: 100% overlap
- PF2_over_corsi_puck ↔ PF1_over_corsi3: 100% overlap
- MF1_under_model2_corsi_diff ↔ MF3_under_model1_corsi: 97% overlap
- MF3_under_model1_corsi ↔ MF1_under_model2_corsi_diff: 97% overlap

## 2. Fold Stability
- ⚠️ **PF1_over_corsi3**: +4.5% | +13.8% | +7.9%
- ⚠️ **PF2_over_corsi_puck**: +6.8% | +7.5% | +2.5%
- ⚠️ **MF1_under_model2_corsi_diff**: +18.8% | +1.6% | +63.2%
- ✅ **MF2_under_model2_b2b**: +30.8% | +7.0% | +31.3%
- ✅ **MF3_under_model1_corsi**: +24.9% | +11.4% | +12.8%

3 strategies have a weak season (<5% ROI) — signals may be inconsistent in certain market regimes.

## 3. CLV Proxy
- **PF1_over_corsi3**: Avg line movement -0.02, direction neutral/unfavorable for our over bets.
- **PF2_over_corsi_puck**: Avg line movement -0.00, direction neutral/unfavorable for our over bets.
- **MF1_under_model2_corsi_diff**: Avg line movement +0.01, direction neutral/unfavorable for our under bets.
- **MF2_under_model2_b2b**: Avg line movement -0.01, direction favorable for our under bets.
- **MF3_under_model1_corsi**: Avg line movement +0.02, direction neutral/unfavorable for our under bets.

Line movement correlation with bet direction suggests whether we're capturing closing line value or fighting it.

## 4. Juice Sensitivity
Breakeven: -105 → 51.2%, -110 → 52.4%, -115 → 53.5%

- **PF1_over_corsi3**: 59.2% win rate — ✅ survives -115
- **PF2_over_corsi_puck**: 57.5% win rate — ✅ survives -115
- **MF1_under_model2_corsi_diff**: 61.3% win rate — ✅ survives -115
- **MF2_under_model2_b2b**: 64.0% win rate — ✅ survives -115
- **MF3_under_model1_corsi**: 63.5% win rate — ✅ survives -115

## 5. Confidence Intervals
- ⚠️ **PF1_over_corsi3**: 59.2% [49.3%, 68.4%] on 98 bets
- ⚠️ **PF2_over_corsi_puck**: 57.5% [48.0%, 66.5%] on 106 bets
- ⚠️ **MF1_under_model2_corsi_diff**: 61.3% [52.4%, 69.6%] on 119 bets
- ✅ **MF2_under_model2_b2b**: 64.0% [53.7%, 73.2%] on 89 bets
- ✅ **MF3_under_model1_corsi**: 63.5% [56.5%, 69.9%] on 197 bets

Strategies where CI lower bound falls below 52.4% (breakeven at -110) need larger sample or tighter filters.
