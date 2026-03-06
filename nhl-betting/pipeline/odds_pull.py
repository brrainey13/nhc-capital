"""
Pull live odds from The Odds API.
Sources: DraftKings, FanDuel, BetMGM, Hard Rock Bet.

Optimized: pulls ALL markets in a single call per event (not separate calls).
Stores every pull in odds_history table for historical tracking.
"""
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import psycopg2
import pytz
import requests
from model.db_config import get_dsn

API_KEYS = [
    k for k in [
        os.environ.get("ODDS_API_KEY", ""),
        os.environ.get("ODDS_API_KEY_2", ""),
    ] if k
]
if not API_KEYS:
    raise RuntimeError("ODDS_API_KEY not set — add it to admin-dashboard/.env")
API_KEY = API_KEYS[0]
_KEY_INDEX = 0
BOOKS = "draftkings,fanduel,betmgm,hardrockbet"
REGIONS = "us,us2"

# All markets we care about — pulled in ONE call per event
ALL_MARKETS = [
    "player_points",
    "player_assists",
    "player_shots_on_goal",
    "player_total_saves",
    "player_goals",          # anytime goalscorer
    "totals",                # game total O/U
]


def _rotate_key():
    """Switch to next API key if current is exhausted."""
    global API_KEY, _KEY_INDEX
    next_idx = (_KEY_INDEX + 1) % len(API_KEYS)
    if next_idx != _KEY_INDEX:
        _KEY_INDEX = next_idx
        API_KEY = API_KEYS[next_idx]
        print(f"  ⚠️ Rotated to API key #{next_idx + 1}")
        return True
    return False


def _api_get(url_path, extra_params=None):
    """Make an API request with automatic key rotation on quota exhaustion."""
    global API_KEY
    params = {"apiKey": API_KEY}
    if extra_params:
        params.update(extra_params)
    r = requests.get(url_path, params=params, timeout=30)
    if r.status_code in (401, 429):
        if _rotate_key():
            params["apiKey"] = API_KEY
            r = requests.get(url_path, params=params, timeout=30)
    return r


def get_todays_events(date_str=None):
    """Get tonight's NHL events from the Odds API."""
    r = _api_get("https://api.the-odds-api.com/v4/sports/icehockey_nhl/events")
    events = r.json()

    if date_str:
        events = [e for e in events if date_str in e["commence_time"]]
    else:
        est = pytz.timezone("America/New_York")
        now = datetime.now(est)
        window_start = now.replace(hour=12, minute=0, second=0, microsecond=0)
        window_end = (window_start + timedelta(days=1)).replace(hour=4)
        filtered = []
        for e in events:
            ct = datetime.fromisoformat(
                e["commence_time"].replace("Z", "+00:00")
            ).astimezone(est)
            if window_start <= ct < window_end:
                filtered.append(e)
        events = filtered

    return events


def pull_all_odds(events, markets=None):
    """Pull ALL odds for given events in a single call per event.

    Returns:
        tuple: (all_props, game_totals_by_event)
        - all_props: list of prop dicts (player markets)
        - game_totals_by_event: dict of event_id -> best over total
    """
    if markets is None:
        markets = ALL_MARKETS

    markets_str = ",".join(markets)
    all_props = []
    game_totals = {}
    pull_id = str(uuid.uuid4())
    est = pytz.timezone("America/New_York")

    # Collect rows for historical storage
    history_rows = []

    for ev in events:
        eid = ev["id"]
        game = f"{ev['away_team']} @ {ev['home_team']}"
        commence_time = ev.get("commence_time")

        # Parse event date (EST)
        if commence_time:
            ct_dt = datetime.fromisoformat(
                commence_time.replace("Z", "+00:00")
            ).astimezone(est)
            event_date = ct_dt.date()
        else:
            event_date = datetime.now(est).date()

        # ONE call per event with ALL markets
        r = _api_get(
            f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/"
            f"events/{eid}/odds",
            extra_params={
                "regions": REGIONS,
                "markets": markets_str,
                "oddsFormat": "american",
                "bookmakers": BOOKS,
            },
        )
        d = r.json()

        best_over = None
        for bk in d.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                for o in mkt.get("outcomes", []):
                    row = {
                        "game": game,
                        "event_id": eid,
                        "book": bk["key"],
                        "book_title": bk["title"],
                        "market": mkt["key"],
                        "player": o.get("description", ""),
                        "side": o["name"],
                        "line": o.get("point", 0),
                        "odds": o["price"],
                    }

                    # Historical storage row
                    history_rows.append((
                        pull_id,
                        eid,
                        str(event_date),
                        ev["home_team"],
                        ev["away_team"],
                        commence_time,
                        bk["key"],
                        mkt["key"],
                        o.get("description") or None,
                        o["name"],
                        o.get("point"),
                        o["price"],
                        _KEY_INDEX + 1,
                    ))

                    if mkt["key"] == "totals":
                        if o["name"] == "Over":
                            entry = {
                                "game": game,
                                "event_id": eid,
                                "book": bk["key"],
                                "book_title": bk["title"],
                                "total": o.get("point", 0),
                                "odds": o["price"],
                            }
                            if best_over is None or o["price"] > best_over["odds"]:
                                best_over = entry
                    else:
                        all_props.append(row)

        if best_over:
            game_totals[eid] = best_over

        time.sleep(0.3)

    # Store historical odds
    _store_odds_history(history_rows)

    print(f"  📊 Stored {len(history_rows)} odds lines (pull {pull_id[:8]})")
    return all_props, game_totals, pull_id


def _store_odds_history(rows):
    """Insert odds snapshot rows into odds_history table."""
    if not rows:
        return
    try:
        conn = psycopg2.connect(get_dsn().replace("nhc_agent", "nhc_etl"))
        cur = conn.cursor()
        from psycopg2.extras import execute_values
        execute_values(
            cur,
            """INSERT INTO odds_history
               (pull_id, event_id, event_date, home_team, away_team,
                commence_time, book, market, player, side, line, odds, api_key_used)
               VALUES %s""",
            rows,
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  ⚠️ Could not store odds history: {e}")


# --- Backward-compatible wrappers ---
# These call pull_all_odds internally so old code still works

def pull_player_props(events, markets=None):
    """Pull player prop lines for given events (backward compatible).

    Now uses the optimized pull_all_odds internally.
    """
    if markets is None:
        markets = ["player_points", "player_assists", "player_shots_on_goal"]

    all_markets = list(set(markets + ["totals"]))
    props, _, _ = pull_all_odds(events, markets=all_markets)

    # Filter to requested markets only
    if markets:
        props = [p for p in props if p["market"] in markets]
    return props


def pull_game_totals(events):
    """Pull game total O/U lines (backward compatible).

    Now uses the optimized pull_all_odds internally.
    """
    _, totals, _ = pull_all_odds(events, markets=["totals"])
    return totals


def get_best_odds(props):
    """Get best odds per player/market/side/line combo."""
    best = defaultdict(lambda: None)
    for p in props:
        key = (p["player"], p["market"], p["side"], p["line"])
        if best[key] is None or p["odds"] > best[key]["odds"]:
            best[key] = p
    return dict(best)


def check_quota():
    """Check remaining API request quota for all keys."""
    results = []
    for i, key in enumerate(API_KEYS):
        try:
            r = requests.get(
                "https://api.the-odds-api.com/v4/sports/",
                params={"apiKey": key},
                timeout=10,
            )
            remaining = str(r.headers.get("x-requests-remaining", "?"))
        except Exception:
            remaining = "error"
        results.append(f"Key#{i+1}: {remaining}")
    return " | ".join(results)


if __name__ == "__main__":
    events = get_todays_events()
    print(f"Events: {len(events)}")
    props, totals, pid = pull_all_odds(events[:1])  # test with 1 game
    print(f"Props: {len(props)} | Totals: {len(totals)}")
    print(f"Quota remaining: {check_quota()}")
