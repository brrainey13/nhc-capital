# Saves Odds Data Schema

## Source
- **API**: BettingPros (https://www.bettingpros.com/nhl/odds/player-props/saves/)
- **Endpoint**: `https://api.bettingpros.com/v3/offers?sport=NHL&market_id=322`
- **Coverage**: 2022-23 season onward (Oct 2022 - present)
- **API Key**: `CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh` (public, embedded in site)
- **Rate limit**: ~0.3s delay between calls (no documented limit, being respectful)

## Table: `saves_odds`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Auto-increment |
| event_id | INTEGER | BettingPros event ID |
| event_date | TEXT | Game date (YYYY-MM-DD) |
| home_team | TEXT | Home team abbreviation (e.g. NYR) |
| away_team | TEXT | Away team abbreviation (e.g. CAR) |
| bp_player_id | INTEGER | BettingPros player ID |
| player_name | TEXT | Goalie full name |
| player_team | TEXT | Goalie's team abbreviation |
| book_id | INTEGER | Sportsbook ID |
| book_name | TEXT | Sportsbook name |
| line | DOUBLE PRECISION | Save line (e.g. 26.5) |
| over_odds | INTEGER | American odds for over (e.g. -115) |
| under_odds | INTEGER | American odds for under (e.g. -130) |
| opening_line | DOUBLE PRECISION | Opening line when first posted |
| opening_over_odds | INTEGER | Opening over odds |
| opening_created | TEXT | Timestamp when line first appeared |
| is_best | BOOLEAN | Whether this was the best available line |
| fair_probability | DOUBLE PRECISION | BettingPros fair probability estimate |
| market_ev | DOUBLE PRECISION | Market expected value |
| updated_at | TEXT | Last update timestamp from BettingPros |
| scraped_at | TIMESTAMP | When we scraped this row |

**Unique constraint**: `(event_id, bp_player_id, book_id)` — one row per goalie per book per game.

## Sportsbook IDs

| book_id | book_name |
|---------|-----------|
| 0 | consensus |
| 10 | fanduel |
| 13 | caesars |
| 19 | betmgm |
| 33 | espnbet |
| 39 | draftkings |
| 45 | bet365 |
| 49 | hardrock |
| 60 | novig |

## Example Row

```
event_date: 2026-02-05
player_name: Jonathan Quick
player_team: NYR
home_team: NYR
away_team: CAR
book_name: fanduel
line: 26.5
over_odds: -102
under_odds: -130
opening_line: 26.5
opening_over_odds: -137
```

## Joining with Goalie Stats

To match saves odds to actual results:

```sql
SELECT
    so.event_date,
    so.player_name,
    so.line,
    so.over_odds,
    so.under_odds,
    gs.saves as actual_saves,
    gs.shots_against,
    CASE WHEN gs.saves > so.line THEN 'OVER'
         WHEN gs.saves < so.line THEN 'UNDER'
         ELSE 'PUSH' END as result
FROM saves_odds so
JOIN goalie_stats gs ON gs.saves = (gs.shots_against - gs.goals_against)
-- Note: Need to map bp_player_id to our player_id
-- and event_id/date to our game_id
WHERE so.book_name = 'consensus'
ORDER BY so.event_date;
```

**TODO**: Build a mapping table between BettingPros player IDs and our NHL API player IDs.

## Scraper

- **Script**: `scrapers/scrape_saves_odds.py`
- **Run all**: `python3 scrapers/scrape_saves_odds.py`
- **Single season**: `python3 scrapers/scrape_saves_odds.py --season 2025`
- **Resume**: `python3 scrapers/scrape_saves_odds.py --resume`
- **Date range**: `python3 scrapers/scrape_saves_odds.py --start 2024-01-01 --end 2024-06-01`

## Expected Volume

- ~1,312 regular season games per season
- ~2 goalies per game
- ~6-8 books per goalie
- **~15,000-20,000 lines per season**
- **~60,000-80,000 total lines across 4 seasons**
