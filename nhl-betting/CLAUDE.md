# CLAUDE.md — NHL Betting


> ⚠️ **All changes must go through Merge Requests on GitLab.** Never push to `main` directly. See root `CLAUDE.md` for the full PR workflow.

Read `docs/nhl-betting.md` for full schema, scraper docs, and project status.

## Quick Context

- **Python:** `nhl-betting/.venv/bin/python` — **always use this, never system Python**
- **Setup:** `cd nhl-betting && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- **DB:** `nhl_betting` @ localhost:5432, 28 tables, 400K+ rows
- **psql:** `/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql -d nhl_betting`
- **Scrapers:** `scrapers/` — BettingPros odds, NHL API stats, injuries, advanced goalie
- **Models:** `model/` — feature engineering + training (artifacts are gitignored: `.pkl`, `.joblib`, etc.)
- **Status:** Strategy #1 work exists; player-odds expansion/backfill is next
- **Player odds note:** `player_odds` currently has partial historical coverage in DB; run fast backfill to extend
- **Backfill command:** `cd ~/nhc-capital/nhl-betting && .venv/bin/python scrapers/scrape_player_odds_fast.py`
- **Empty tables:** `predictions`, `model_runs` — full model pipeline still in progress

## Key Tables

| Table | Rows | Notes |
|---|---|---|
| `games` | 5,939 | Game results with scores, dates, teams |
| `teams` | 34 | NHL teams |
| `players` | 2,373 | Player roster |
| `player_stats` | 199,119 | Per-game skater stats |
| `goalie_stats` | 22,125 | Per-game goalie stats |
| `goalie_advanced` | 9,541 | Advanced goalie metrics |
| `goalie_saves_by_strength` | 10,016 | Saves split by game situation |
| `goalie_starts` | 9,226 | Goalie start/bench tracking |
| `saves_odds` | 44,049 | Goalie saves O/U props (BettingPros) |
| `standings` | 7,616 | Team standings over time |
| `period_scores` | 36,360 | Period-by-period scoring |
| `injuries_live` | ~94 | Current injury report |
| `lineup_absences` | 11,289 | Lineup absence tracking |
| `game_team_stats` | 11,064 | Per-game team-level stats |
| `api_snapshots` | 26,030 | Raw API response snapshots |

## Rules

- **Never commit model artifacts** — `.pkl`, `.joblib`, `.h5`, `.pt` are gitignored
- **All SQL must be parameterized** — no f-string injection
- **Update `docs/nhl-betting.md`** when you add tables, scrapers, or change schema
- **`make ci` before commit** — always
