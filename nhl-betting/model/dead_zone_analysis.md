# Dead Zone Analysis — MF3 Gap [1.5-2.5)

**58 bets, 53.4% under win rate (vs 66%+ in adjacent buckets)**

## Summary

The dead zone is driven by **Season 2 (24-25) collapsing to 39% under win rate** while S1 was fine at 70%. The core issue: mean saves (25.2) equals mean line (25.2) in this bucket — the model's prediction (23.2) is directionally correct but actual saves cluster right at the line, turning would-be wins into coin flips.

**Key patterns in the losses:**
- **Home goalies are the problem:** 43.5% under win rate at home vs 60% away. Home goalies in the dead zone face more shots than expected (opponent desperation in road games doesn't materialize).
- **vs BOS (0-3) and vs TBL (0-2):** Elite offenses that generate quality chances even with low Corsi — they don't need volume, they score on efficiency. Low Corsi doesn't mean low danger against top teams.
- **Line rose ≥0.5 saves → 33% win rate (2/6):** When the line moves UP after open but our model still says under, the market is right and we're wrong. This is a potential exclusion filter.
- **Nedeljkovic (0-2, avg 38 saves) and Stolarz (0-2, avg 31.5 saves):** Backup-caliber goalies who got shelled — model underestimated shots against weak goalies behind weak teams.

**Recommended dead zone fix:** Either skip gap [1.5-2.5) entirely (bifurcate into MF3a + MF3b), or add an exclusion: skip when goalie is HOME and line rose ≥0.5.

## Raw Findings
- Home/Away split: Home 43% (23) vs Away 60% (35) under win rate
- B2B goalies: 8 bets at 62% vs rested 52%
- Avg saves: 25.2 vs avg line: 25.2 vs avg prediction: 23.2
- The model predicts correctly (pred < line) but actual saves cluster right around the line, leading to over-hits

## Bet Details
| Date | Goalie | Team | Opp | H/A | Line | Saves | Pred | Gap | Corsi | Rest | Result |
|------|--------|------|-----|-----|------|-------|------|-----|-------|------|--------|
| 2023-10-11 | Ilya Samsonov | TOR | MTL | H | 25.5 | 19 | 23.5 | 2.0 | 0.464 | 6d | ✅ |
| 2023-10-13 | Tristan Jarry | PIT | WSH | A | 27.5 | 19 | 25.5 | 2.0 | 0.444 | 3d | ✅ |
| 2023-10-21 | Sergei Bobrovsky | FLA | VAN | H | 27.5 | 26 | 25.3 | 2.2 | 0.434 | 2d | ✅ |
| 2023-12-09 | Linus Ullmark | BOS | ARI | H | 24.5 | 30 | 22.1 | 2.4 | 0.458 | 2d | ❌ |
| 2023-12-17 | Petr Mrazek | CHI | VAN | H | 27.5 | 23 | 25.9 | 1.6 | 0.458 | 3d | ✅ |
| 2023-12-31 | Alex Nedeljkovic | PIT | NYI | H | 26.5 | 37 | 24.5 | 2.0 | 0.468 | 1d | ❌ |
| 2024-02-24 | Jordan Binnington | STL | DET | A | 27.5 | 10 | 25.6 | 1.9 | 0.467 | 2d | ✅ |
| 2024-03-02 | Marc-Andre Fleury | MIN | STL | A | 25.5 | 24 | 23.3 | 2.2 | 0.450 | 2d | ✅ |
| 2024-03-11 | Joel Hofer | STL | BOS | A | 28.5 | 36 | 26.1 | 2.4 | 0.464 | 2d | ❌ |
| 2024-03-11 | Connor Hellebuyck | WPG | WSH | H | 25.5 | 23 | 23.4 | 2.1 | 0.453 | 2d | ✅ |
| 2024-03-16 | Ukko-Pekka Luukkon | BUF | DET | A | 25.5 | 22 | 23.6 | 1.9 | 0.470 | 2d | ✅ |
| 2024-03-21 | Ilya Sorokin | NYI | DET | A | 25.5 | 18 | 23.6 | 1.9 | 0.440 | 2d | ✅ |
| 2024-03-22 | Pyotr Kochetkov | CAR | WSH | A | 24.5 | 19 | 22.6 | 1.9 | 0.459 | 3d | ✅ |
| 2024-03-26 | Alex Lyon | DET | WSH | A | 26.5 | 26 | 24.2 | 2.3 | 0.449 | 3d | ✅ |
| 2024-03-29 | Devon Levi | BUF | NJD | H | 26.5 | 28 | 25.0 | 1.5 | 0.462 | 2d | ❌ |
| 2024-04-01 | Justus Annunen | COL | CBJ | A | 26.5 | 21 | 24.5 | 2.0 | 0.453 | 2d | ✅ |
| 2024-04-02 | Ukko-Pekka Luukkon | BUF | WSH | H | 24.5 | 24 | 22.6 | 1.9 | 0.439 | 3d | ✅ |
| 2024-04-02 | Anthony Stolarz | FLA | MTL | A | 24.5 | 33 | 22.4 | 2.1 | 0.439 | 1d | ❌ |
| 2024-04-08 | Ilya Samsonov | TOR | PIT | H | 26.5 | 31 | 24.0 | 2.5 | 0.474 | 2d | ❌ |
| 2024-04-11 | Ukko-Pekka Luukkon | BUF | WSH | H | 24.5 | 22 | 22.4 | 2.1 | 0.419 | 2d | ✅ |
| 2024-04-15 | Alex Lyon | DET | MTL | H | 25.5 | 17 | 24.0 | 1.5 | 0.424 | 2d | ✅ |
| 2024-04-26 | Igor Shesterkin | NYR | WSH | A | 24.5 | 29 | 22.7 | 1.8 | 0.465 | 3d | ❌ |
| 2024-05-16 | Frederik Andersen | CAR | NYR | H | 23.5 | 19 | 21.4 | 2.1 | 0.471 | 3d | ✅ |
| 2024-10-12 | Charlie Lindgren | WSH | NJD | H | 26.5 | 28 | 24.9 | 1.6 | 0.461 | 7d | ❌ |
| 2024-10-14 | Alex Lyon | DET | NYR | A | 28.5 | 24 | 26.6 | 1.9 | 0.454 | 2d | ✅ |
| 2024-10-15 | Andrei Vasilevskiy | TBL | VAN | H | 25.5 | 26 | 23.8 | 1.7 | 0.442 | 4d | ❌ |
| 2024-10-22 | Igor Shesterkin | NYR | MTL | A | 25.5 | 21 | 24.0 | 1.5 | 0.416 | 3d | ✅ |
| 2024-10-26 | Anthony Stolarz | TOR | BOS | A | 25.5 | 30 | 23.4 | 2.1 | 0.469 | 2d | ❌ |
| 2024-10-27 | Calvin Pickard | EDM | DET | A | 24.5 | 24 | 22.4 | 2.1 | 0.443 | 2d | ✅ |
| 2024-11-02 | Anton Forsberg | OTT | SEA | H | 25.5 | 22 | 23.2 | 2.3 | 0.473 | 1d | ✅ |
| 2024-11-09 | Sergei Bobrovsky | FLA | PHI | H | 24.5 | 34 | 22.3 | 2.2 | 0.457 | 2d | ❌ |
| 2024-12-01 | Elvis Merzlikins | CBJ | CHI | A | 24.5 | 28 | 22.1 | 2.4 | 0.435 | 2d | ❌ |
| 2024-12-01 | Kevin Lankinen | VAN | DET | A | 24.5 | 27 | 22.1 | 2.4 | 0.464 | 2d | ❌ |
| 2024-12-01 | Jeremy Swayman | BOS | MTL | H | 24.5 | 25 | 22.4 | 2.1 | 0.454 | 2d | ❌ |
| 2024-12-15 | Jonathan Quick | NYR | STL | A | 26.5 | 21 | 24.2 | 2.3 | 0.465 | 1d | ✅ |
| 2024-12-15 | Ilya Sorokin | NYI | CHI | A | 24.5 | 18 | 23.0 | 1.5 | 0.460 | 3d | ✅ |
| 2024-12-31 | Jordan Binnington | STL | CHI | A | 24.5 | 28 | 22.3 | 2.2 | 0.467 | 2d | ❌ |
| 2025-02-02 | Elvis Merzlikins | CBJ | DAL | A | 26.5 | 34 | 24.3 | 2.2 | 0.472 | 2d | ❌ |
| 2025-03-07 | Karel Vejmelka | ARI2 | CHI | A | 23.5 | 21 | 21.3 | 2.2 | 0.428 | 1d | ✅ |
| 2025-03-11 | Elvis Merzlikins | CBJ | NJD | A | 26.5 | 23 | 24.8 | 1.7 | 0.467 | 2d | ✅ |
| 2025-03-11 | Pyotr Kochetkov | CAR | TBL | H | 22.5 | 23 | 20.3 | 2.2 | 0.460 | 2d | ❌ |
| 2025-03-18 | Linus Ullmark | OTT | MTL | A | 23.5 | 27 | 21.3 | 2.2 | 0.467 | 3d | ❌ |
| 2025-03-20 | Dustin Wolf | CGY | NJD | A | 24.5 | 26 | 22.9 | 1.6 | 0.469 | 2d | ❌ |
| 2025-03-30 | Tristan Jarry | PIT | OTT | H | 25.5 | 31 | 23.2 | 2.3 | 0.462 | 3d | ❌ |
| 2025-04-01 | Vitek Vanecek | FLA | MTL | A | 22.5 | 18 | 20.7 | 1.8 | 0.467 | 2d | ✅ |
| 2025-04-05 | Frederik Andersen | CAR | BOS | A | 21.5 | 22 | 19.5 | 2.0 | 0.402 | 1d | ❌ |
| 2025-04-17 | Igor Shesterkin | NYR | TBL | H | 24.5 | 27 | 22.8 | 1.7 | 0.473 | 3d | ❌ |
| 2025-04-24 | Linus Ullmark | OTT | TOR | H | 23.5 | 17 | 21.8 | 1.7 | 0.464 | 2d | ✅ |
| 2025-04-25 | Logan Thompson | WSH | MTL | A | 23.5 | 30 | 21.4 | 2.1 | 0.438 | 2d | ❌ |
| 2025-04-26 | Linus Ullmark | OTT | TOR | H | 23.5 | 31 | 21.8 | 1.7 | 0.469 | 2d | ❌ |
| 2025-04-27 | Logan Thompson | WSH | MTL | A | 23.5 | 16 | 21.7 | 1.8 | 0.441 | 2d | ✅ |
| 2025-10-16 | Igor Shesterkin | NYR | TOR | A | 25.5 | 22 | 23.4 | 2.1 | 0.464 | 2d | ✅ |
| 2025-10-17 | Filip Gustavsson | MIN | WSH | A | 24.5 | 40 | 22.9 | 1.6 | 0.450 | 3d | ❌ |
| 2025-10-19 | Spencer Knight | CHI | ANA | H | 25.5 | 38 | 23.5 | 2.0 | 0.452 | 2d | ❌ |
| 2025-11-01 | Mackenzie Blackwoo | COL | SJS | A | 21.5 | 20 | 19.4 | 2.1 | 0.460 | 1d | ✅ |
| 2025-11-11 | Jet Greaves | CBJ | SEA | A | 27.5 | 22 | 25.5 | 2.0 | 0.470 | 1d | ✅ |
| 2025-12-27 | Igor Shesterkin | NYR | NYI | A | 25.5 | 24 | 23.5 | 2.0 | 0.444 | 4d | ✅ |
| 2026-01-31 | Alex Nedeljkovic | SJS | CGY | A | 25.5 | 39 | 23.3 | 2.2 | 0.470 | 2d | ❌ |
