"""
Pre-flight roster refresh: pull current NHL rosters and update current_team_id.
Run before every picks session to ensure player-team mappings are current.
"""
import json
import urllib.request
from datetime import datetime

import psycopg2
from model.db_config import get_dsn

DB_CONN = get_dsn()


def refresh_rosters(verbose=True):
    """Pull current rosters from NHL API and update players table.

    Returns dict with update count and any errors.
    """
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()
    cur.execute("SELECT team_id, tri_code FROM teams WHERE active = 1")
    teams = cur.fetchall()

    updates = 0
    errors = []

    for team_id, tri_code in teams:
        try:
            url = f"https://api-web.nhle.com/v1/roster/{tri_code}/current"
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            data = json.loads(
                urllib.request.urlopen(req, timeout=10).read()
            )

            for group in ["forwards", "defensemen", "goalies"]:
                for player in data.get(group, []):
                    pid = player["id"]
                    cur.execute(
                        "UPDATE players SET current_team_id = %s "
                        "WHERE player_id = %s "
                        "AND (current_team_id IS NULL "
                        "OR current_team_id != %s)",
                        (team_id, pid, team_id),
                    )
                    if cur.rowcount > 0:
                        first = player.get("firstName", {}).get("default", "")
                        last = player.get("lastName", {}).get("default", "")
                        if verbose:
                            print(f"  UPDATED: {first} {last} → {tri_code}")
                        updates += 1
        except Exception as e:
            errors.append(f"{tri_code}: {e}")
            if verbose:
                print(f"  ERROR {tri_code}: {e}")

    conn.commit()
    cur.close()
    conn.close()

    result = {
        "updates": updates,
        "errors": errors,
        "timestamp": datetime.now().isoformat(),
    }
    if verbose:
        print(f"\nRoster refresh: {updates} updates, {len(errors)} errors")
    return result


if __name__ == "__main__":
    refresh_rosters()
