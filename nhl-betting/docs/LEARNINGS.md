# LEARNINGS.md - NHL Betting Project

Critical project knowledge only. Things that affect modeling decisions and data integrity.

---

## Data Integrity

**BettingPros `player_team` is always the player's CURRENT team, not team-at-time-of-game.** Never use it for historical analysis. Join with our goalie_stats table instead.

**21% of games have only 1 goalie line posted.** Books withhold lines when the starter is uncertain. This creates a potential edge — games where starter info becomes available late may have softer lines.

**Player names in `players` table were stored as initials (e.g. "D. Tokarski").** Fixed 137 goalies to full names using saves_odds as source. 124 minor goalies still have initials — no odds data for them so doesn't affect model joins.

**European exhibition teams in NHL API.** Eisbären Berlin, EHC Red Bull München, SC Bern appeared from preseason/Global Series games. Cleaned from all tables. Filter on `gameTypeId=2` (regular season) when scraping to prevent re-ingestion.

**`book_12` has anomalous 0.5 save line.** Filter out lines < 10 in feature engineering.

**`lineup_absences` avg 6.1 missing regulars per game.** This is expected — it includes healthy scratches + injuries + rest. The key signal is the TOI-weighted impact, not raw count. Defensemen absences (`def_missing_toi`) are the most relevant feature for predicting shots against.

## API Notes

**NHL Stats API** (`api.nhle.com/stats/rest/en/goalie/`) supports these game-level reports:
- `summary` — basic goalie stats
- `savesByStrength` — EV/PP/SH splits
- `advanced` — quality starts, SA/60, goals for/against avg
- `startedVsRelieved` — starter vs relief with separate stats
- Paginated: use `limit` + `start` params, `total` in response for loop control

**NHL Edge API** (`api-web.nhle.com/v1/edge/goalie-*`) has shot location data by zone (crease, slot, circles, point) with percentile rankings. Season-level only, not per-game. Useful as a seasonal feature.

**ESPN Injuries API** (`site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries`) — returns current injuries for all 31 teams. No historical endpoint. Snapshot daily for going-forward data.

---

*Updated: 2026-02-16*
