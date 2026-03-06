"""
Pull live odds from The Odds API.
Sources: DraftKings, FanDuel, BetMGM, Hard Rock Bet.
"""
import os
import requests
import time
from collections import defaultdict

API_KEYS = [
    os.environ.get("ODDS_API_KEY", "53b74c4c440a14071dac325d834a55b8"),
    "2d240c499924015358260c955bbc4cb9",
]
API_KEY = API_KEYS[0]  # Active key, rotated on quota exhaustion
BOOKS = "draftkings,fanduel,betmgm,hardrockbet"
REGIONS = "us,us2"


def _rotate_key():
    """Switch to next API key if current is exhausted."""
    global API_KEY
    idx = API_KEYS.index(API_KEY) if API_KEY in API_KEYS else 0
    next_idx = (idx + 1) % len(API_KEYS)
    if next_idx != idx:
        API_KEY = API_KEYS[next_idx]
        print(f"  ⚠️ Rotated to API key #{next_idx + 1}")
        return True
    return False


def _api_get(url_template):
    """Make an API request with automatic key rotation on quota exhaustion."""
    global API_KEY
    url = url_template.replace("{API_KEY}", API_KEY)
    r = requests.get(url)
    if r.status_code == 401 or r.status_code == 429:
        remaining = r.headers.get("x-requests-remaining", "0")
        if remaining == "0" or r.status_code in (401, 429):
            if _rotate_key():
                url = url_template.replace("{API_KEY}", API_KEY)
                r = requests.get(url)
    return r


def get_todays_events(date_str=None):
    """Get tonight's NHL events from the Odds API.

    Filters to games starting today (EST) by default.
    Games at 7 PM EST = next day in UTC, so we check both.
    """
    from datetime import datetime, timedelta
    import pytz

    r = _api_get(
        "https://api.the-odds-api.com/v4/sports/icehockey_nhl/events"
        "?apiKey={API_KEY}"
    )
    events = r.json()

    if date_str:
        events = [
            e for e in events if date_str in e["commence_time"]
        ]
    else:
        # Filter to tonight's games only
        # Window: today at noon → tomorrow at 4 AM EST
        # This catches all evening NHL games (typically 7-10 PM starts)
        # without bleeding into next day's matinees
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


def pull_player_props(events, markets=None):
    """Pull player prop lines for given events.

    Args:
        events: list of event dicts from get_todays_events
        markets: list of market strings, default player_points + assists + SOG

    Returns:
        list of prop dicts with game, book, market, player, side, line, odds
    """
    if markets is None:
        markets = ["player_points", "player_assists", "player_shots_on_goal"]

    markets_str = ",".join(markets)
    all_props = []

    for ev in events:
        eid = ev["id"]
        game = f"{ev['away_team']} @ {ev['home_team']}"
        r = _api_get(
            f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/"
            f"events/{eid}/odds?apiKey={{API_KEY}}"
            f"&regions={REGIONS}&markets={markets_str}"
            f"&oddsFormat=american&bookmakers={BOOKS}"
        )
        d = r.json()

        for bk in d.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                for o in mkt.get("outcomes", []):
                    all_props.append({
                        "game": game,
                        "event_id": eid,
                        "book": bk["key"],
                        "book_title": bk["title"],
                        "market": mkt["key"],
                        "player": o.get("description", ""),
                        "side": o["name"],
                        "line": o.get("point", 0),
                        "odds": o["price"],
                    })
        time.sleep(0.3)

    return all_props


def pull_game_totals(events):
    """Pull game total O/U lines for given events.

    Returns dict keyed by event_id with best over line info.
    """
    totals = {}

    for ev in events:
        eid = ev["id"]
        game = f"{ev['away_team']} @ {ev['home_team']}"
        r = _api_get(
            f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/"
            f"events/{eid}/odds?apiKey={{API_KEY}}"
            f"&regions={REGIONS}&markets=totals"
            f"&oddsFormat=american&bookmakers={BOOKS}"
        )
        d = r.json()

        best_over = None
        for bk in d.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                for o in mkt.get("outcomes", []):
                    if o["name"] == "Over":
                        entry = {
                            "game": game,
                            "event_id": eid,
                            "book": bk["key"],
                            "book_title": bk["title"],
                            "total": o.get("point", 0),
                            "odds": o["price"],
                        }
                        if (
                            best_over is None
                            or o["price"] > best_over["odds"]
                        ):
                            best_over = entry
        if best_over:
            totals[eid] = best_over
        time.sleep(0.3)

    return totals


def get_best_odds(props):
    """Get best odds per player/market/side/line combo.

    Returns dict keyed by (player, market, side, line).
    """
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
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
        )
        remaining = r.headers.get("x-requests-remaining", "?")
        results.append(f"Key#{i+1}: {remaining}")
    return " | ".join(results)


if __name__ == "__main__":
    events = get_todays_events()
    print(f"Events: {len(events)}")
    props = pull_player_props(events[:1])  # test with 1 game
    print(f"Props: {len(props)}")
    print(f"Quota remaining: {check_quota()}")
