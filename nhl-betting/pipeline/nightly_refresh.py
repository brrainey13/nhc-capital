"""
Nightly Data Refresh — runs at 2 AM EST.

1. Ingest completed games from yesterday (boxscores → player_stats, goalie_stats, game_team_stats)
2. Refresh rosters (trades, call-ups, waivers)
3. Log results

This ensures all data is fresh before the 4 PM picks run.
"""
import json
import urllib.request
from datetime import datetime, timedelta

import psycopg2
from model.db_config import get_dsn

DB = get_dsn()
API = "https://api-web.nhle.com/v1"


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def ingest_game(conn, game_id):
    """Pull play-by-play and ingest player_stats, goalie_stats, game_team_stats.

    Uses PBP endpoint because the boxscore API returns empty player arrays
    for completed games.
    """
    cur = conn.cursor()

    # Skip if already ingested
    cur.execute("SELECT 1 FROM player_stats WHERE game_id = %s LIMIT 1", (game_id,))
    if cur.fetchone():
        return 0

    try:
        pbp = fetch_json(f"{API}/gamecenter/{game_id}/play-by-play")
    except Exception as e:
        print(f"  ERROR fetching {game_id}: {e}")
        return 0

    game_date = pbp.get("gameDate", "")
    away_team = pbp.get("awayTeam", {})
    home_team = pbp.get("homeTeam", {})
    away_id = away_team.get("id")
    home_id = home_team.get("id")

    # Upsert game row (update state/scores if it was FUT)
    cur.execute(
        "INSERT INTO games (game_id, game_date, away_team_id, home_team_id, "
        "season, game_type, game_state, away_score, home_score) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (game_id) DO UPDATE SET "
        "game_state = EXCLUDED.game_state, "
        "away_score = EXCLUDED.away_score, "
        "home_score = EXCLUDED.home_score",
        (game_id, game_date, away_id, home_id, 20252026, 2,
         pbp.get("gameState", "OFF"),
         away_team.get("score", 0), home_team.get("score", 0)),
    )

    # Build roster lookup from rosterSpots
    roster = {}  # pid -> {teamId, firstName, lastName, positionCode}
    for rs in pbp.get("rosterSpots", []):
        pid = rs.get("playerId")
        if pid:
            roster[pid] = {
                "teamId": rs.get("teamId"),
                "firstName": rs.get("firstName", {}).get("default", ""),
                "lastName": rs.get("lastName", {}).get("default", ""),
                "positionCode": rs.get("positionCode", ""),
            }

    # Aggregate player stats from plays
    from collections import defaultdict
    pstats = defaultdict(lambda: {
        "goals": 0, "assists": 0, "points": 0, "shots": 0,
        "hits": 0, "blocked_shots": 0, "takeaways": 0, "giveaways": 0,
        "pim": 0, "ppg": 0, "ppp": 0, "shp": 0,
    })

    # Track goalie shots faced
    goalie_shots = defaultdict(lambda: {"saves": 0, "goals_against": 0})

    for play in pbp.get("plays", []):
        t = play["typeDescKey"]
        d = play.get("details", {})
        sit = play.get("situationCode", "0000")

        if t == "goal":
            scorer = d.get("scoringPlayerId")
            owner_team = d.get("eventOwnerTeamId")
            goalie_id = d.get("goalieInNetId")

            # Determine PP/SH from situation code
            try:
                away_sk, home_sk = int(sit[1]), int(sit[3])
            except (IndexError, ValueError):
                away_sk, home_sk = 5, 5

            if owner_team == away_id:
                is_pp = away_sk > home_sk
                is_sh = away_sk < home_sk
            else:
                is_pp = home_sk > away_sk
                is_sh = home_sk < away_sk

            if scorer:
                pstats[scorer]["goals"] += 1
                pstats[scorer]["points"] += 1
                pstats[scorer]["shots"] += 1
                if is_pp:
                    pstats[scorer]["ppg"] += 1
                    pstats[scorer]["ppp"] += 1
                if is_sh:
                    pstats[scorer]["shp"] += 1

            for akey in ["assist1PlayerId", "assist2PlayerId"]:
                aid = d.get(akey)
                if aid:
                    pstats[aid]["assists"] += 1
                    pstats[aid]["points"] += 1
                    if is_pp:
                        pstats[aid]["ppp"] += 1
                    if is_sh:
                        pstats[aid]["shp"] += 1

            if goalie_id:
                goalie_shots[goalie_id]["goals_against"] += 1

        elif t == "shot-on-goal":
            pid = d.get("shootingPlayerId")
            if pid:
                pstats[pid]["shots"] += 1
            goalie_id = d.get("goalieInNetId")
            if goalie_id:
                goalie_shots[goalie_id]["saves"] += 1

        elif t == "hit":
            pid = d.get("hittingPlayerId")
            if pid:
                pstats[pid]["hits"] += 1

        elif t == "blocked-shot":
            pid = d.get("blockingPlayerId")
            if pid:
                pstats[pid]["blocked_shots"] += 1

        elif t == "takeaway":
            pid = d.get("playerId")
            if pid:
                pstats[pid]["takeaways"] += 1

        elif t == "giveaway":
            pid = d.get("playerId")
            if pid:
                pstats[pid]["giveaways"] += 1

        elif t == "penalty":
            pid = d.get("committedByPlayerId")
            mins = d.get("duration", 2)
            if pid:
                pstats[pid]["pim"] += mins

    # Game team stats
    for team_info, is_home in [(away_team, 0), (home_team, 1)]:
        tid = team_info.get("id")
        score = team_info.get("score", 0)
        sog = team_info.get("sog", 0)
        cur.execute(
            "INSERT INTO game_team_stats (game_id, team_id, is_home, score, shots_on_goal) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (game_id, tid, is_home, score, sog),
        )

    rows = 0

    # Insert skater stats (non-goalies with events, plus all rostered skaters)
    all_skater_ids = set()
    for pid, info in roster.items():
        if info["positionCode"] != "G":
            all_skater_ids.add(pid)
    # Also include anyone with events not in roster (rare)
    all_skater_ids.update(pid for pid in pstats if pid not in goalie_shots)

    for pid in all_skater_ids:
        info = roster.get(pid)
        if not info or info["positionCode"] == "G":
            continue
        team_id = info["teamId"]
        is_home = 1 if team_id == home_id else 0
        s = pstats.get(pid, {})

        # Ensure player exists
        cur.execute("SELECT 1 FROM players WHERE player_id = %s", (pid,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO players (player_id, first_name, last_name, "
                "position_code, current_team_id) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (pid, info["firstName"], info["lastName"],
                 info["positionCode"], team_id),
            )

        cur.execute(
            "INSERT INTO player_stats "
            "(game_id, player_id, team_id, is_home, position_code, "
            "toi_minutes, goals, assists, points, plus_minus, pim, "
            "hits, blocked_shots, faceoff_win_pct, shots, "
            "power_play_goals, power_play_points, shorthanded_points, "
            "takeaways, giveaways) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                game_id, pid, team_id, is_home, info["positionCode"],
                0,  # TOI not available from PBP
                s.get("goals", 0), s.get("assists", 0),
                s.get("points", 0), 0,  # plus_minus not in PBP
                s.get("pim", 0), s.get("hits", 0),
                s.get("blocked_shots", 0), 0,  # faceoff pct complex
                s.get("shots", 0),
                s.get("ppg", 0), s.get("ppp", 0), s.get("shp", 0),
                s.get("takeaways", 0), s.get("giveaways", 0),
            ),
        )
        rows += 1

    # Insert goalie stats
    for pid, gs in goalie_shots.items():
        info = roster.get(pid)
        if not info:
            continue
        team_id = info["teamId"]
        is_home = 1 if team_id == home_id else 0
        saves = gs["saves"]
        ga = gs["goals_against"]

        cur.execute("SELECT 1 FROM players WHERE player_id = %s", (pid,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO players (player_id, first_name, last_name, "
                "position_code, current_team_id) "
                "VALUES (%s, %s, %s, 'G', %s) ON CONFLICT DO NOTHING",
                (pid, info["firstName"], info["lastName"], team_id),
            )

        cur.execute(
            "INSERT INTO goalie_stats "
            "(game_id, player_id, team_id, is_home, toi_minutes, "
            "saves, shots_against, goals_against, decision) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (game_id, pid, team_id, is_home, 0,
             saves, saves + ga, ga, ""),
        )
        rows += 1

    conn.commit()
    return rows


def ingest_date(conn, date_str):
    """Ingest all completed regular season games for a date."""
    data = fetch_json(f"{API}/schedule/{date_str}")
    total_games = 0
    total_rows = 0

    for week in data.get("gameWeek", []):
        if week["date"] != date_str:
            continue
        for g in week.get("games", []):
            if g["gameState"] not in ("OFF", "FINAL"):
                continue
            if g.get("gameType") != 2:  # regular season only
                continue
            rows = ingest_game(conn, g["id"])
            if rows > 0:
                total_games += 1
                total_rows += rows
                print(f"  Game {g['id']}: {rows} rows")

    return total_games, total_rows


def main():
    from pipeline.grade_picks import grade_tracker
    from pipeline.roster_refresh import refresh_rosters

    print("=" * 60)
    print(f"NIGHTLY REFRESH — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    conn = psycopg2.connect(DB)

    # Ingest yesterday's games (and day before, in case of late finishes)
    today = datetime.now()
    dates_to_check = [
        (today - timedelta(days=1)).strftime("%Y-%m-%d"),
        (today - timedelta(days=2)).strftime("%Y-%m-%d"),
    ]

    total_g = 0
    total_r = 0
    for d in dates_to_check:
        print(f"\nChecking {d}...")
        g, r = ingest_date(conn, d)
        total_g += g
        total_r += r
        if g > 0:
            print(f"  Ingested {g} games, {r} rows")
        else:
            print("  Already up to date")

    conn.close()

    # Refresh rosters
    print("\nRefreshing rosters...")
    result = refresh_rosters(verbose=False)
    print(f"  {result['updates']} roster updates")

    # Grade yesterday's picks
    print("\n" + "=" * 60)
    print("GRADING YESTERDAY'S PICKS")
    print("=" * 60)
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    grade_result = grade_tracker(yesterday)

    print(f"\nDONE: {total_g} new games, {total_r} rows, "
          f"{result['updates']} roster updates")
    if isinstance(grade_result, dict) and "wins" in grade_result:
        print(f"PICKS: {grade_result['wins']}-{grade_result['losses']}, "
              f"P/L: ${grade_result['profit']:+.2f}")


if __name__ == "__main__":
    main()
