# STRATEGY.md - NHL Betting Strategy Lab

Active strategy testing log. Each strategy gets tested, audited, and scored.
Read LEARNINGS.md before proposing any new strategy.

---

## Strategy #1: Top-Line Forward SOG vs Depleted D Corps

**Date:** 2026-02-17
**Status:** ⚠️ PROMISING BUT FRAGILE — needs real odds validation
**Hypothesis:** When a team is missing 3+ defensemen, the opposing top-line forwards absorb a disproportionate share of the extra shots because coaches match their best players against weak replacement D.

### The Signal

| Forward Type | Opp 0-1D Missing | Opp 3+D Missing | Boost | Concentration |
|---|---|---|---|---|
| Top-3 FWD (by TOI) | 2.878 avg SOG | 3.012 avg SOG | **+0.134** | 1.7x vs avg FWD |
| Top-1 FWD only | 2.998 avg SOG | 3.160 avg SOG | **+0.162** | 2.1x vs avg FWD |
| Other forwards | 2.055 avg SOG | 2.132 avg SOG | +0.077 | baseline |

**Top-1 forwards facing 3+ D missing:**
- Over 2.5 SOG rate: 58.5% (vs 53.2% baseline) → **+5.3pp boost**
- Over 3.5 SOG rate: 35.9% (vs 32.8% baseline) → +3.1pp boost
- Statistical significance: t=4.914, p=0.000001

### The Problem: Book Lines

The over 2.5 SOG line is NOT realistic for most top-line forwards. Actual book lines from our `sog_odds` data:

| Player | Avg Book Line |
|---|---|
| MacKinnon | 4.5 |
| Pastrnak | 4.5 |
| Matthews | 4.3 |
| J. Hughes | 3.8 |
| McDavid | 3.5 |
| Most top-line FWDs | **3.0 - 3.5** |

Books set lines at 3.0-4.5 for these players, not 2.5. Our "edge" exists at 2.5, which is below where books actually price them.

### Cross-Season Validation (over 2.5 — NOT at book lines)

| Season | Baseline | 3+D Missing | Boost | ROI@-110 |
|---|---|---|---|---|
| 2022-23 | 53.8% | 56.6% | +2.8pp | **+8.0%** ✅ |
| 2023-24 | 54.0% | 56.3% | +2.3pp | **+7.5%** ✅ |
| 2024-25 | 48.2% | 50.3% | +2.0pp | -4.1% ❌ |
| 2025-26 | 48.2% | 53.6% | +5.4pp | **+2.3%** ✅ |

3 of 4 seasons positive. 2024-25 is the weak link.

### Compound Conditions

| Filter | N | Over 2.5% | ROI@-110 |
|---|---|---|---|
| 3+D missing (all) | 7,380 | 54.3% | +3.7% |
| 3+D missing + HOME | 3,722 | 56.0% | **+6.8%** |
| 3+D missing + AWAY | 3,658 | 52.7% | +0.5% |

### Verdict

**The concentration effect is REAL (1.7-2.1x).** Top-line forwards get a measurably larger SOG boost when facing depleted D. But:

1. **+0.134 boost (top-3) or +0.162 (top-1) is still too small** to reliably clear the gap between a player's actual average and their book line
2. **Books set SOG lines at 3.0-4.5 for these players**, not 2.5. At the 3.5 line, the over rate only goes from 32.8% to 35.9% — deeply unprofitable
3. **Not all 4 seasons positive** even at the generous 2.5 line

**Next step:** Once full `player_odds` scrape finishes, test against ACTUAL per-player book lines. The edge might exist for players at the lower end of top-line (line=2.5) where the +0.134 boost matters more proportionally.

### What Would Make This Work
- Find players with book line of 2.5 who are top-3 on their team in TOI
- These players' baseline over rate is ~50-52% at their book line
- 3+D opponent boost pushes them to 54-56%
- That's barely profitable at -110 (need 52.4%)
- **Margin is razor thin. May not survive juice differences across books.**

---

*Next strategy due: 30 min*
