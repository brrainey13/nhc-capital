# LEARNINGS.md - NHL Betting Project

Curated findings only. Dead-end strategies are documented as lessons learned, not as opportunities.

---

## Core Thesis: Defensive TOI Absences

**Defensive TOI absences are the strongest predictive signal we've found.** Missing defensemen → more shots allowed → measurable impact on shot volume.

**The signal (validated across 4 seasons):**
- 3+ D missing → +1.44 extra team shots on goal (p<0.00000001)
- Consistent every season: +0.65 to +1.86 extra shots
- `own_def_missing_toi` is the strongest single feature for goalie saves prediction
- D absences are highly persistent within a season (r=0.83 from 3-game rolling avg)
- But team injury-proneness does NOT carry year-to-year (r=0.05)

**Why it doesn't translate to betting profit on goalie saves:**
- Books partially price in D absences (adjust line by +0.6 to +1.0)
- The remaining ~0.5 save gap can't overcome 4.5% vig
- Cross-season validation: -2.8% ROI combined across 3 test seasons

**Where it DOES create real edge — Team SOG totals (if market exists):**

| Season | Line | ROI (Opp 3+D, over) | Win% | N |
|--------|------|---------------------|------|-----|
| 2022-23 | 30.5 | **+5.6%** | 55.3% | 1,012 |
| 2023-24 | 29.5 | **+7.0%** | 56.0% | 1,128 |
| 2024-25 | 27.5 | **+6.9%** | 56.0% | 1,068 |
| 2025-26 | 26.5 | **+12.7%** | 59.0% | 505 |

**Blocker:** No sportsbook confirmed to offer team SOG totals. Need to verify on DraftKings/FanDuel/PrizePicks.

---

## Data Integrity Notes

**BettingPros `player_team` is always the player's CURRENT team, not team-at-time-of-game.** Join with goalie_stats instead.

**Non-starter goalies:** 21% of saves_odds rows were backups with 0 saves who never played. Filter `shots_against > 0` before any analysis.

**Preseason games in the database.** ~784 preseason games (Sept/early Oct) exist in game_team_stats. Many have 0 hits, 0 blocks, abnormal stats. **Always filter to regular season (Oct 10+ or use gameTypeId=2).** Failing to do this contaminated the Dr. Strange V1 hits analysis.

**European exhibition teams.** Eisbären Berlin, EHC Red Bull München, SC Bern in NHL API from preseason/Global Series. Cleaned from all tables.

**Player names:** 137 goalies fixed from initials to full names. 124 minor goalies still have initials (no odds data, doesn't affect model).

---

## API Reference

**BettingPros API** (`api.bettingpros.com/v3/`):
- Key: `CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh`
- NHL markets (full map):
  - 193 = Moneyline (3-way)
  - 194 = Total Goals O/U (game-level)
  - 195 = Puck Line (spread)
  - 316 = 1st Period Winner
  - 317 = Team Goals O/U
  - 318 = Player Goals
  - 319 = Player Assists
  - 320 = Player Points
  - 321 = Player SOG
  - 322 = Goalie Saves
  - 362 = D-man Shots
- No team SOG or team hits market available
- Events: `/events?sport=NHL&date=YYYY-MM-DD`
- Offers: `/offers?sport=NHL&market_id=X&event_id=Y`
- Books in data: consensus(0), fanduel(3), caesars(10), betmgm(13), espnbet(19), hardrock(22), draftkings(25), novig(28)

**NHL Stats API** (`api.nhle.com/stats/rest/en/goalie/`):
- Reports: summary, savesByStrength, advanced, startedVsRelieved
- Paginated: `limit` + `start`, `total` in response

**ESPN Injuries** (`site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries`):
- Current injuries only, no historical endpoint

---

## Leading Indicators for D Absences

Best predictors (pre-game knowable):
1. **3-game D absence rolling avg: r=0.832** — strongest by far
2. **Rule: avg_3 ≥ 3.0 → 89.2% precision** for predicting 3+ D missing tonight
3. D absence TOI (3-game): r=0.807
4. D missing streak: r=0.423
5. **B2Bs don't matter** for D absences (34.5% vs 33.5%)
6. Season progression: games 1-20 have 50% rate of 3+ D missing vs 23% mid-season

---

## What Didn't Work (Lessons)

### Goalie Saves Model
- Built 3 LightGBM models (shots, save%, pull). Beats naive baselines but can't overcome vig.
- Best subset: +20.6% ROI on 3+ D missing overs — **failed cross-season validation** (-5.9% and -7.6% in prior seasons).
- Pull model: AUC=1.0 was data leakage. Real AUC=0.62. Pull prediction not viable (2.4% base rate).

### Player SOG Props
- D absences boost individual forward SOG by only +0.056 (2.5%). Too small to bet on.
- Even elite players: +0.13 SOG, not enough to shift a 2.5 line after vig.
- The team-level +1.44 shot boost gets spread across 12 forwards.

### Team Hits Strategy (Dr. Strange Search)
- Initial results showed +44% ROI across 4 seasons. **Integrity audit found major problems:**
  1. **784 preseason games** contaminated the data (0-hit games, abnormal stats)
  2. **Expanding season avg as "book line"** had unstable base rates (37.7% to 58.3% per season)
  3. **2025-26 was -22.8% ROI** — most recent season contradicts the thesis
  4. **2023-24 had 58.3% base over rate** — inflated every strategy that season
- After cleaning preseason: strategy still shows +31.9% combined but is unreliable due to base rate instability and recent-season failure.
- **Verdict: Not deployable.** Need actual book hits lines to test against, not proxy lines.

### Dr. Strange V2 — Dynamic Lines (2026-02-17)
- Rebuilt with per-season median lines instead of hardcoded below-market lines.
- Added blind rate validation: every strategy must beat the baseline over rate by 2%+ or it's rejected.
- **Top result: team_hits_over_(median-1), hits_avg_5_high & is_home → 51% ROI, 79% win rate, 1,168 bets across 4 seasons.**
- Full audit confirmed: no leakage, no duplicates, statistically significant (p=10⁻⁷³).
- **BUT: the line is fake.** We test at median-1 (~21 hits). Books set lines per-team — for high-hitting home teams (avg 28-31), the book line would be ~27-30. At the team's own rolling avg as line: **-29% ROI**. The "edge" completely vanishes.
- **Fundamental lesson: Dr. Strange can't find real edges without real odds data.** Any condition that predicts higher totals is already priced into per-team lines. The only edges will be from conditions books **don't adjust for** (e.g., same-day lineup changes).

### Key Modeling Mistakes Made
1. **Walk-forward validation overlap** — val sets were subsets of training data. Always ensure train cutoff < val start.
2. **`save_diff`, `went_under`, `went_over` left as features** — literally the target encoded. r=0.948 with saves. Check correlations > 0.5 before training.
3. **`id` column as feature** — monotonically increasing PK acts as date proxy.
4. **AUC=1.0 is always leakage.** No exceptions.
5. **Preseason in regular season data.** Always filter by date or game type.
6. **Testing against below-median lines** makes everything look profitable. Use dynamic lines at the actual book level.
7. **Multiple hypothesis testing** — testing 16,000+ strategies guarantees false positives. Require 4-season consistency AND recent-season positive.
8. **Static lines ≠ book lines.** Books set per-team, per-game lines that already price in team identity, home/away, and recent form. Testing against league medians finds "physical teams hit more" — not edges.
9. **Always ask: "Would a book already know this?"** If the condition (home, high-hitting team, etc.) is obvious and persistent, it's already in the line. Only late-breaking or non-obvious conditions have edge potential.

---

## What Actually Matters (Strategic Framework)

### The Only Way to Find Real Edges
1. **Get real book lines** — without actual odds, any analysis is just proving "good teams do good things"
2. **Test conditions against the book line, not static thresholds** — the question isn't "does this team go over 21 hits?" it's "does this team go over what the BOOK set for them?"
3. **Focus on information asymmetry** — only conditions that books can't or don't adjust for in time have edge potential
4. **Late-breaking info is where edges live** — same-day lineup confirmations, last-minute scratches, pre-game warmup absences. Books set lines 12-24h before game, injury info trickles in closer to puck drop.

### Categories of Potential Edges
- **Timing edge:** Book sets line before info is public (D-absence confirmed late)
- **Correlation edge:** Books price individual props but miss team-level correlations
- **Market inefficiency:** Less liquid markets (assists, blocks) may have wider margins for error
- **Opening line → closing line drift:** If we can identify systematic line movements, the opening line itself is mispriced

---

## Active Opportunities

### Team SOG Totals (Pending Market Verification)
- **+5.6% to +12.7% ROI** when opponent has 3+ D missing → bet team SOG over
- Positive all 4 seasons, 3,713 total bets
- **BLOCKED:** Need to find a sportsbook that offers team SOG over/under
- Scraper built: `scrapers/scrape_sog_odds.py`, table: `sog_odds`

### Real Odds Data Pipeline (In Progress)
- Scraping all BettingPros player props: goals (318), assists (319), points (320), SOG (321)
- Plus team-level: team goals (317), total goals (194)
- Tables: `player_odds`, `team_odds` — 4 seasons, ~786 game dates
- **This is the foundation.** Once we have real lines per player per game, Dr. Strange can test conditions against actual book lines instead of guessing.
- Scraper: `scrapers/scrape_player_odds_fast.py`

### Forward-Testing Pipeline (Build When Season Resumes Feb 26)
- Daily: scrape injuries → compute D absence TOI → flag games with 3+ opp D missing
- Alert team with specific bets if team SOG market found
- Track every prediction vs result

---

## Process Learnings

- **Read LEARNINGS.md before starting any new analysis.** Prevents repeating dead ends.
- **Always audit top findings before reporting.** Reproduce from raw SQL, check blind rates, test at realistic lines.
- **Preseason filter is mandatory.** Added `game_type IN (2,3) AND game_state='OFF'` everywhere. Created `games_analysis` DB view.
- **Backfill gaps proactively.** 263 games in 2022-23 had NULL SOG in `games` table — data existed in `game_team_stats`, just needed backfill.
- **psycopg2 bulk inserts >> subprocess psql per-row.** Orders of magnitude faster for scrapers.

---

*Updated: 2026-02-17*
