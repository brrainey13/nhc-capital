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

### Table Inventory

| Table | Rows | Description |
|---|---|---|
| `teams` | 37 | NHL teams |
| `players` | 2,373 | Player roster data |
| `games` | 5,939 | Game results |
| `schedules` | 5,939 | Game schedule (mirrors games) |
| `standings` | 7,616 | Team standings over time |
| `player_stats` | 199,119 | Per-game player stats |
| `goalie_stats` | 22,125 | Per-game goalie stats |
| `game_team_stats` | 11,064 | Per-game team-level stats |
| `period_scores` | 36,360 | Period-by-period scoring |
| `injuries` | 26 | Current injury report |
| `saves_odds` | 21,396 | Goalie saves O/U prop odds (BettingPros, 2022-present) |
| `api_snapshots` | 26,030 | Raw API response snapshots |
| `predictions` | 0 | Model predictions (empty — not yet built) |
| `model_runs` | 0 | Model run metadata (empty — not yet built) |
| `live_game_snapshots` | 0 | Live game state (empty) |

### Non-NHL Tables (in same DB)

| Table | Description |
|---|---|
| `cook_county_*` | Real estate data (appeals, assessments, properties, sales, tax rates) |
| `sf_rentals` | San Francisco rental data |
| `kanban_*` | Task/event tracking |

These should eventually be moved to their own databases.

## Scrapers

### `scrapers/scrape_saves_odds.py`

Scrapes historical NHL goalie saves O/U prop odds from BettingPros API.

- **Source:** `https://api.bettingpros.com/v3/`
- **Coverage:** 2022-23 season onward
- **Market:** ID 322 (NHL Goalie Saves O/U)
- **Books:** consensus, FanDuel, Caesars, etc.
- **Fields:** event_date, player, line, over/under odds, opening line, fair probability, market EV

```bash
python scrapers/scrape_saves_odds.py                    # All seasons
python scrapers/scrape_saves_odds.py --season 2025      # 2025-26 only
python scrapers/scrape_saves_odds.py --start 2024-10-01 # From date
```

## Next Steps

1. Explore existing data — understand what's there and quality
2. Build prediction models (predictions + model_runs tables are empty)
3. Add more scrapers (game odds, player props beyond saves)
4. Separate non-NHL tables into their own databases
