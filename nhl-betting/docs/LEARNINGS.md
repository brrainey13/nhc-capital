# LEARNINGS.md - NHL Betting Project

Critical project knowledge only. Things that affect modeling decisions and data integrity.

---

## Data Integrity

**BettingPros `player_team` is always the player's CURRENT team, not team-at-time-of-game.** Never use it for historical analysis. Join with our goalie_stats table instead.

**21% of games have only 1 goalie line posted.** Books withhold lines when the starter is uncertain. This creates a potential edge — games where starter info becomes available late may have softer lines.

## Modeling

*(to be filled as we build)*

---

*Updated: 2026-02-16*
