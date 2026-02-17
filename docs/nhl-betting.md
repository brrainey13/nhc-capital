---
summary: 'NHL betting project — database schema, data pipeline, scrapers, and model status.'
read_when:
  - Working on NHL betting models or data
  - Adding new scrapers or data sources
  - Querying the nhl_betting database
  - Building predictions or analysis
---

# NHL Betting

## Database: `nhl_betting`

Connection: `postgresql://connorrainey@localhost:5432/nhl_betting`

### Table Inventory (28 tables, ~400K+ rows)

| Table | Rows | Description |
|---|---|---|
| `teams` | 34 | NHL teams |
| `players` | 2,373 | Player roster data |
| `games` | 5,939 | Game results |
| `schedules` | 5,939 | Game schedule (mirrors games) |
| `standings` | 7,616 | Team standings over time |
| `player_stats` | 199,119 | Per-game skater stats |
| `goalie_stats` | 22,125 | Per-game goalie stats |
| `goalie_advanced` | 9,541 | Advanced goalie metrics (quality starts, really bad starts, goals saved above average) |
| `goalie_saves_by_strength` | 10,016 | Saves split by even-strength, power-play, shorthanded |
| `goalie_starts` | 9,226 | Goalie start/bench tracking |
| `game_team_stats` | 11,064 | Per-game team-level stats |
| `period_scores` | 36,360 | Period-by-period scoring |
| `injuries` | 26 | Historical injury data |
| `injuries_live` | ~94 | Current live injury report |
| `lineup_absences` | 11,289 | Lineup absence tracking |
| `saves_odds` | 44,049 | Goalie saves O/U prop odds (BettingPros, 2022-present) |
| `api_snapshots` | 26,030 | Raw API response snapshots |
| `live_game_snapshots` | 0 | Live game state (empty) |
| `predictions` | 0 | Model predictions (empty — not yet built) |
| `model_runs` | 0 | Model run metadata (empty — not yet built) |

### Non-NHL Tables (in same DB — should be migrated)

| Table | Description |
|---|---|
| `cook_county_appeals` | Cook County property tax appeals |
| `cook_county_assessments` | Property assessments |
| `cook_county_properties` | Property records |
| `cook_county_sales` | Property sales |
| `cook_county_tax_rates` | Tax rates by area |
| `sf_rentals` | San Francisco rental listings |
| `kanban_events` | Task/event tracking |
| `kanban_tasks` | Task tracking |

## Scrapers

Located in `nhl-betting/scrapers/`.

### `scrape_saves_odds.py`
Scrapes historical NHL goalie saves O/U prop odds from BettingPros API.
- **Source:** `https://api.bettingpros.com/v3/`
- **Coverage:** 2022-23 season onward
- **Fields:** event_date, player, line, over/under odds, opening line, fair probability, market EV

```bash
python scrapers/scrape_saves_odds.py                    # All seasons
python scrapers/scrape_saves_odds.py --season 2025      # 2025-26 only
```

### `scrape_advanced_goalie.py`
Scrapes advanced goalie stats from NHL API.
- **Tables:** `goalie_advanced`, `goalie_saves_by_strength`, `goalie_starts`

### `scrape_injuries.py`
Scrapes current NHL injury report.
- **Table:** `injuries_live`

## Models

Located in `nhl-betting/model/`. **Model artifacts (`.pkl`, `.joblib`, etc.) are gitignored.**

- `build_features.py` — Feature engineering, builds feature matrix from DB
- `train_models.py` — Model training pipeline

## Next Steps

1. Build prediction models (`predictions` and `model_runs` tables are empty)
2. Add more scrapers (game odds, player props beyond saves)
3. Separate non-NHL tables into their own databases
4. Backtest model performance against historical odds
