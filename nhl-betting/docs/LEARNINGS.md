# LEARNINGS.md - NHL Betting Project

Living document. Mistakes, discoveries, and ideas logged as we go.

---

## 2026-02-16 — Project Kickoff

### What We Learned

**1. Historical prop odds are hard to find for free — but not impossible**
- Polymarket: Only futures (Stanley Cup winner etc.), no game-level props
- PrizePicks API (`api.prizepicks.com`): Public JSON API, has NHL (league_id=8), but no goalie saves stat type. Useful for skater props potentially.
- Underdog Fantasy API (`api.underdogfantasy.com`): Public, has hockey, but saves not offered as a stat. Has goals, points, shots, SOG.
- The Odds API: Free tier (500 credits/month) only covers current/upcoming odds. Historical requires $30+/month.
- **BettingPros API**: The jackpot. Free, public API key embedded in their website JS. Has historical goalie saves O/U lines from Oct 2022 onward, across 7+ sportsbooks with opening/closing lines and fair probability estimates.

**Lesson**: Before paying for data, always inspect the network requests on free sports betting sites. Many have public APIs that aren't documented but are fully functional.

**2. BettingPros API structure**
- `/v3/events?sport=NHL&date=YYYY-MM-DD` → list of games
- `/v3/offers?sport=NHL&market_id=322&event_id=X&location=OH` → saves props
- Market IDs: 322=saves, 318=goals, 319=points, 320=assists, 321=shots, 362=blocked shots
- API key: `CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh` (from site JS)
- Location param affects which books appear (OH gets good coverage)
- Data goes back to Oct 2022 (start of 2022-23 season). Nothing before that for saves.

**3. Sportsbook coverage varies by season**
- 2022-23: Only ~3 books (FanDuel, Caesars, consensus) → ~5-6 lines per game
- 2024-25+: 7-8 books (added ESPN BET, Hard Rock, Novig, DraftKings) → more lines per game
- Earlier seasons have less data per game but still have the key consensus line.

**4. NHL season structure matters for scraping**
- Regular season: ~Oct 7 to mid-April (~1,312 games)
- Playoffs: mid-April to mid-June (~80-90 games)
- Off days: No games on some dates, scraper handles gracefully
- All-Star break, Olympic break: gaps in schedule
- Our date range (Oct to Jun) overshoots, but the scraper skips empty days cheaply

### Mistakes Made

**1. Python 3.9 compatibility**
- Used `str | None` type hint syntax (3.10+). Failed on the Mac Mini's Python 3.9. Fixed to remove type hints.
- **Lesson**: Always check Python version on target machine. System Python on macOS can be old.

**2. Metrics field can be None**
- BettingPros API sometimes returns `"metrics": null` instead of `{}`. Using `.get("metrics", {})` doesn't protect against explicit null.
- **Fix**: `metrics = line_data.get("metrics") or {}`
- **Lesson**: In JSON APIs, distinguish between missing key and explicit null. Use `x or {}` pattern.

**3. No psycopg2 installed**
- Had to `pip3 install psycopg2-binary`. Should document dependencies.
- **TODO**: Add a `requirements.txt` to the project.

### Ideas & Future Improvements

**Data Collection**
- [ ] Scrape other prop markets too (goals=318, shots=321, points=319) — same API, just different market_id
- [ ] Set up daily cron to collect live odds once season resumes (Feb 26)
- [ ] Collect PrizePicks lines too for comparison — their lines are sometimes different
- [ ] Track line movement (opening vs closing) — significant edge signal

**Modeling**
- [ ] Build player ID mapping between BettingPros and NHL API
- [ ] "Saves = shots_against - goals_against" — verify this matches across datasets
- [ ] Key features for saves model: opponent shots/game (rolling), goalie's recent workload, home/away, back-to-back, opposing team's shooting tendency
- [ ] The line itself is information — books are good at this. Our edge needs to be in situations they misprice (back-to-backs, goalie changes, etc.)

**Architecture**
- [ ] Add `requirements.txt`
- [ ] Add proper logging to file + console
- [ ] Consider storing raw API responses for replay/debugging
- [ ] The scraper could be parallelized per-season but rate limiting makes it not worth it

**Betting Strategy**
- Think about where the books are weakest on saves props:
  - Late goalie announcements (backup starts instead of starter)
  - Teams on back-to-backs (tend to give up more shots)
  - Blowout games where starters get pulled
  - Teams that changed systems/coaches mid-season (shot rate changes)
- The consensus line is probably the sharpest. Look for edges vs individual books.

---

*Updated: 2026-02-16*
