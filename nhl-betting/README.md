# NHL Betting

Goalie saves over/under prediction model. Scrapes historical odds and NHL stats, builds features, and identifies +EV betting opportunities.

## Status
- **Database:** `nhl_betting` (Postgres, localhost:5432)
- **Stage:** Data collection complete, model build next
- **Coverage:** 2022-10-07 → 2026-02-06

## Database Schema

### Core NHL Data
| Table | Rows | Description |
|-------|------|-------------|
| `teams` | 34 | NHL teams (32 active + ARI old + ARI2) |
| `games` | 5,936 | Game results (scores, dates, teams) |
| `schedules` | 5,936 | Full schedule including future games |
| `standings` | 7,616 | Daily standings snapshots |
| `players` | 2,312 | Player info (name, position, team) |
| `player_stats` | 199,006 | Per-game skater stats (goals, assists, TOI, shots, hits) |
| `goalie_stats` | 22,114 | Per-game goalie stats (saves, shots against, save%) |
| `game_team_stats` | 11,058 | Per-game team stats (SOG, shot attempts, PP, hits) |
| `period_scores` | 36,342 | Period-by-period scoring |

### Advanced Goalie Data
| Table | Rows | Description |
|-------|------|-------------|
| `goalie_saves_by_strength` | 9,957 | EV/PP/SH saves & shots per game |
| `goalie_advanced` | 9,481 | Quality starts, SA/60, goals for/against avg |
| `goalie_starts` | 9,212 | Started vs relieved with separate save stats |

### Odds Data
| Table | Rows | Description |
|-------|------|-------------|
| `saves_odds` | 44,464 | Goalie saves O/U lines from 10 books (BettingPros) |

### Injury / Absence Data
| Table | Rows | Description |
|-------|------|-------------|
| `lineup_absences` | 11,051 | Derived: missing regulars per team per game (F/D splits, TOI impact) |
| `injuries_live` | 94+ | ESPN daily injury snapshots (current injuries, status, detail) |

### Other
| Table | Description |
|-------|-------------|
| `injuries` | Legacy injury data (26 rows, mostly unused) |
| `api_snapshots` | Raw API response cache |
| `live_game_snapshots` | Live game tracking (empty) |
| `predictions` | Model predictions (empty, to be populated) |
| `model_runs` | Model run metadata (empty, to be populated) |

## Scrapers

All in `scrapers/`:

| Script | Source | What it does |
|--------|--------|-------------|
| `scrape_saves_odds.py` | BettingPros API | Goalie saves O/U odds from 10 sportsbooks |
| `scrape_advanced_goalie.py` | NHL Stats API | Saves by strength, advanced stats, started vs relieved |
| `scrape_injuries.py --historical` | Derived from player_stats | Reconstructs lineup absences for all historical games |
| `scrape_injuries.py --live` | ESPN API | Current injury report snapshot |

### Setup
```bash
cd nhl-betting
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Running scrapers
```bash
cd nhl-betting

# Full odds backfill (takes ~1hr)
.venv/bin/python scrapers/scrape_saves_odds.py

# Advanced goalie stats (takes ~4min)
.venv/bin/python scrapers/scrape_advanced_goalie.py

# Injuries (historical + live)
.venv/bin/python scrapers/scrape_injuries.py --all
.venv/bin/python scrapers/scrape_injuries.py --live    # daily ESPN snapshot only
.venv/bin/python scrapers/scrape_injuries.py --historical  # rebuild absences only
```

## Data Quality Notes
- Player names in `players` table fixed to full names (was initials). 137 goalies updated to match `saves_odds` names. 124 minor goalies still have initials (no odds data, won't affect model).
- European exhibition teams (Eisbären, EHC Red Bull München, SC Bern) cleaned from all tables.
- `saves_odds` stops at 2026-02-06 (last date with settled odds).
- 404 games with null scores are future scheduled games — expected.
- `book_12` has one anomalous 0.5 line — filter in feature engineering.

## Model Plan
- **Target:** Predict goalie saves → compare to book's line → find +EV over/unders
- **Architecture:** Two stacked models (shot volume prediction + save% prediction)
- **Algorithm:** LightGBM
- **Validation:** Walk-forward by season (no lookahead)
- **Evaluation:** ROI on simulated bets, not just prediction accuracy

## Stack
- Python, PostgreSQL, LightGBM
- Discord: #nhl-betting
