"""
Grade yesterday's picks — check results against actual game stats.

Reads pending picks from PICK_TRACKER.md, pulls actual stats from NHL API,
grades W/L, calculates P/L, updates the tracker.

Also provides grade_from_db() to grade picks stored in the nhl_picks table.
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

TRACKER_PATH = Path(__file__).parent.parent / "docs" / "PICK_TRACKER.md"
API = "https://api-web.nhle.com/v1"


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def get_player_stats_for_date(date_str):
    """Get all player stats for a given date from NHL API.

    Uses play-by-play endpoint (boxscore returns empty after games end).
    Returns dict keyed by player name with goals, assists, points, saves.
    """
    from collections import defaultdict

    schedule = fetch_json(f"{API}/schedule/{date_str}")
    player_stats = {}

    for week in schedule.get("gameWeek", []):
        if week["date"] != date_str:
            continue
        for game in week.get("games", []):
            if game["gameState"] not in ("OFF", "FINAL"):
                continue
            if game.get("gameType") != 2:
                continue

            gid = game["id"]
            try:
                pbp = fetch_json(f"{API}/gamecenter/{gid}/play-by-play")
            except Exception:
                continue

            # Build roster name lookup
            roster_names = {}
            for r in pbp.get("rosterSpots", []):
                pid = r["playerId"]
                first = r.get("firstName", {}).get("default", "")
                last = r.get("lastName", {}).get("default", "")
                roster_names[pid] = f"{first} {last}"

            # Accumulate from plays
            pstats = defaultdict(lambda: {
                "goals": 0, "assists": 0, "points": 0, "saves": 0,
            })

            for play in pbp.get("plays", []):
                ptype = play.get("typeDescKey", "")
                det = play.get("details", {})

                if ptype == "goal":
                    scorer = det.get("scoringPlayerId")
                    a1 = det.get("assist1PlayerId")
                    a2 = det.get("assist2PlayerId")
                    goalie = det.get("goalieInNetId")
                    if scorer:
                        pstats[scorer]["goals"] += 1
                        pstats[scorer]["points"] += 1
                    if a1:
                        pstats[a1]["assists"] += 1
                        pstats[a1]["points"] += 1
                    if a2:
                        pstats[a2]["assists"] += 1
                        pstats[a2]["points"] += 1
                    if goalie:
                        pstats[goalie]["saves"] += 0  # goal = not a save
                elif ptype == "shot-on-goal":
                    goalie = det.get("goalieInNetId")
                    if goalie:
                        pstats[goalie]["saves"] += 1

            # Map to names
            for pid, s in pstats.items():
                name = roster_names.get(pid, "")
                if name:
                    if name in player_stats:
                        # Merge (shouldn't happen but safety)
                        for k in s:
                            player_stats[name][k] += s[k]
                    else:
                        player_stats[name] = dict(s)

            # Ensure all roster players exist (even 0-stat ones)
            for pid, name in roster_names.items():
                if name and name not in player_stats:
                    player_stats[name] = {
                        "goals": 0, "assists": 0, "points": 0, "saves": 0,
                    }

    return player_stats


def calc_payout(odds, stake):
    """Calculate profit from American odds and stake."""
    if odds > 0:
        return round(stake * odds / 100, 2)
    else:
        return round(stake * 100 / abs(odds), 2)


def grade_tracker(date_str=None):
    """Grade pending picks for a given date.

    Args:
        date_str: YYYY-MM-DD to grade. Defaults to yesterday.

    Returns:
        dict with wins, losses, profit, updated_lines
    """
    if date_str is None:
        yesterday = datetime.now() - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    # Format date for matching in tracker (e.g., "Feb 26")
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    _date_header = dt.strftime("%b %-d")  # "Feb 26"

    if not TRACKER_PATH.exists():
        return {"error": "PICK_TRACKER.md not found"}

    content = TRACKER_PATH.read_text()

    # Check if this date has pending picks
    if "⏳" not in content:
        return {"wins": 0, "losses": 0, "profit": 0, "message": "No pending picks"}

    # Pull actual stats
    print(f"Pulling stats for {date_str}...")
    actual_stats = get_player_stats_for_date(date_str)
    print(f"  Got stats for {len(actual_stats)} players")

    if not actual_stats:
        return {"error": f"No completed games found for {date_str}"}

    # Parse and grade each pending line
    lines = content.split("\n")
    new_lines = []
    wins = 0
    losses = 0
    total_profit = 0.0

    for line in lines:
        if "⏳" not in line or "|" not in line:
            new_lines.append(line)
            continue

        # Parse the table row
        cols = [c.strip() for c in line.split("|")]
        # Expected: | Player | Bet | Odds | Book | Edge | Size | Result | P/L |
        if len(cols) < 9:
            new_lines.append(line)
            continue

        player = cols[1].strip()
        bet = cols[2].strip()
        odds_str = cols[3].strip()
        size_str = cols[6].strip()

        # Parse odds
        try:
            odds = int(odds_str.replace("+", ""))
        except ValueError:
            new_lines.append(line)
            continue

        # Parse stake from size (e.g., "4.5u ($112.50)")
        dollar_match = re.search(r"\$([0-9.]+)", size_str)
        stake = float(dollar_match.group(1)) if dollar_match else 25.0

        # Find player in actual stats (fuzzy match on last name)
        actual = actual_stats.get(player)
        if not actual:
            # Try matching by last name
            last_name = player.split()[-1]
            for name, stats in actual_stats.items():
                if name.split()[-1] == last_name and name[0] == player[0]:
                    actual = stats
                    break

        if not actual:
            # Player might not have played
            new_line = line.replace("⏳", "🚫 DNP").replace("— |", "$0.00 |")
            new_lines.append(new_line)
            continue

        # Grade the bet
        hit = False
        result_text = ""

        if "OVER 1.5 pts" in bet:
            pts = actual["points"]
            hit = pts >= 2
            result_text = f"{'✅' if hit else '❌'} {pts}P"
        elif "OVER 0.5 pts" in bet:
            pts = actual["points"]
            hit = pts >= 1
            result_text = f"{'✅' if hit else '❌'} {pts}P"
        elif "UNDER 0.5 ast" in bet or "Assists UNDER" in bet:
            ast = actual["assists"]
            hit = ast == 0
            result_text = f"{'✅' if hit else '❌'} {ast}A"
        elif "OVER 0.5 goals" in bet or "Goalscorer" in bet:
            goals = actual["goals"]
            hit = goals >= 1
            result_text = f"{'✅' if hit else '❌'} {goals}G"
        elif "saves" in bet.lower():
            saves = actual["saves"]
            # Parse the line number from bet
            line_match = re.search(r"(\d+\.?\d*)", bet)
            if line_match:
                save_line = float(line_match.group(1))
                hit = saves > save_line
                result_text = f"{'✅' if hit else '❌'} {saves}SV"
        else:
            new_lines.append(line)
            continue

        if hit:
            profit = calc_payout(odds, stake)
            wins += 1
        else:
            profit = -stake
            losses += 1

        total_profit += profit
        pl_str = f"+${profit:.2f}" if profit > 0 else f"-${abs(profit):.2f}"

        new_line = line.replace("⏳", result_text).replace("— |", f"{pl_str} |")
        new_lines.append(new_line)

    # Write updated tracker
    TRACKER_PATH.write_text("\n".join(new_lines))

    result = {
        "date": date_str,
        "wins": wins,
        "losses": losses,
        "total": wins + losses,
        "profit": round(total_profit, 2),
        "win_rate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
    }

    print(f"\nResults for {date_str}:")
    print(f"  Record: {wins}-{losses}")
    print(f"  P/L: ${total_profit:+.2f}")
    print(f"  Win Rate: {result['win_rate']}%")

    return result


READ_DSN = "dbname=nhl_betting user=nhc_agent host=localhost port=5432"
WRITE_DSN = "dbname=nhl_betting user=nhc_etl host=localhost port=5432"


def _grade_pick_row(market, bet, line, actual_value):
    """Return ('W' or 'L', pnl_multiplier) for a single pick.

    actual_value is the raw stat (points, assists, goals, saves).
    Returns (result, hit) where hit is True for a win.
    Returns (None, None) if the market is unrecognised.
    """
    if market in ("over_15_pts",):
        hit = actual_value is not None and actual_value >= 2
    elif market in ("over_05_pts",):
        hit = actual_value is not None and actual_value >= 1
    elif market in ("assists_under",):
        hit = actual_value is not None and actual_value == 0
    elif market in ("atg",):
        hit = actual_value is not None and actual_value >= 1
    elif market in ("goalie_saves",):
        if line is None or actual_value is None:
            return None, None
        # bet text encodes OVER/UNDER; default to over
        if bet and "UNDER" in bet.upper():
            hit = actual_value < line
        else:
            hit = actual_value > line
    elif market in ("game_total",):
        if line is None or actual_value is None:
            return None, None
        hit = actual_value > line
    else:
        return None, None

    return ("W" if hit else "L"), hit


def grade_from_db(date_str=None):
    """Grade ungraded picks in the nhl_picks table for a given date.

    Queries picks where result IS NULL and pick_date < today (or == date_str).
    Looks up actuals from player_stats / goalie_stats (via games join).
    Updates result, actual_value, pnl, graded_at via nhc_etl.

    Args:
        date_str: YYYY-MM-DD to grade. Defaults to yesterday.

    Returns:
        dict with wins, losses, skipped, profit.
    """
    import psycopg2

    if date_str is None:
        yesterday = datetime.now() - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    print(f"Grading DB picks for {date_str}...")

    # Fetch ungraded picks
    rconn = psycopg2.connect(READ_DSN)
    try:
        with rconn.cursor() as cur:
            cur.execute(
                """
                SELECT pick_id, player, player_team, market, bet, odds,
                       line, units, dollars
                FROM nhl_picks
                WHERE result IS NULL
                  AND pick_date = %s
                """,
                (date_str,),
            )
            rows = cur.fetchall()
    finally:
        rconn.close()

    if not rows:
        print(f"  No ungraded picks found for {date_str}")
        return {"date": date_str, "wins": 0, "losses": 0, "skipped": 0, "profit": 0.0}

    print(f"  Found {len(rows)} ungraded picks")

    # Pull actual stats from NHL API (reuse existing helper)
    actual_stats = get_player_stats_for_date(date_str)
    print(f"  Got NHL API stats for {len(actual_stats)} players")

    wins = 0
    losses = 0
    skipped = 0
    total_profit = 0.0
    updates = []

    for (pick_id, player, player_team, market, bet, odds, line, units, dollars) in rows:
        # Resolve actual value by market
        actual_value = None

        if market == "game_total":
            # game total: player column holds 'Away @ Home', actual_value = total goals
            # Look up via goalie stats (saves) or just use API — skip for now;
            # actual_value stays None → will be skipped
            actual_value = None
        else:
            actual = actual_stats.get(player)
            if not actual and player:
                last = player.split()[-1]
                for name, stats in actual_stats.items():
                    if name.split()[-1] == last and name[0] == player[0]:
                        actual = stats
                        break

            if actual:
                if market in ("over_15_pts", "over_05_pts"):
                    actual_value = float(actual.get("points", 0))
                elif market == "assists_under":
                    actual_value = float(actual.get("assists", 0))
                elif market == "atg":
                    actual_value = float(actual.get("goals", 0))
                elif market == "goalie_saves":
                    actual_value = float(actual.get("saves", 0))

        result, hit = _grade_pick_row(market, bet, line, actual_value)

        if result is None:
            skipped += 1
            updates.append((None, actual_value, None, pick_id))
            continue

        if hit:
            pnl = calc_payout(odds, dollars) if dollars else 0.0
            wins += 1
        else:
            pnl = -(dollars or 0.0)
            losses += 1

        total_profit += pnl
        updates.append((result, actual_value, round(pnl, 2), pick_id))

    # Write updates via nhc_etl
    wconn = psycopg2.connect(WRITE_DSN)
    try:
        with wconn:
            with wconn.cursor() as cur:
                for result, actual_value, pnl, pick_id in updates:
                    if result is None and actual_value is None:
                        # No data — leave result NULL, just mark graded_at
                        cur.execute(
                            """
                            UPDATE nhl_picks
                            SET graded_at = NOW()
                            WHERE pick_id = %s
                            """,
                            (pick_id,),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE nhl_picks
                            SET result = %s,
                                actual_value = %s,
                                pnl = %s,
                                graded_at = NOW()
                            WHERE pick_id = %s
                            """,
                            (result, actual_value, pnl, pick_id),
                        )
    finally:
        wconn.close()

    summary = {
        "date": date_str,
        "wins": wins,
        "losses": losses,
        "skipped": skipped,
        "profit": round(total_profit, 2),
        "win_rate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
    }

    print(f"\nDB Grade Results for {date_str}:")
    print(f"  Record:   {wins}W - {losses}L ({skipped} skipped/no data)")
    print(f"  P/L:      ${total_profit:+.2f}")
    if wins + losses > 0:
        print(f"  Win Rate: {summary['win_rate']}%")

    return summary


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if args and args[0] == "--db":
        # Grade from DB
        date_arg = args[1] if len(args) > 1 else None
        grade_from_db(date_arg)
    else:
        date_arg = args[0] if args else None
        grade_tracker(date_arg)
