#!/usr/bin/env python3
"""Data fetching: odds API and feature matrix loading for daily picks."""

import logging
import os
import sys
import time as _time
from pathlib import Path

import pandas as pd
import requests

MODEL_DIR = Path(__file__).resolve().parent.parent / "model"
sys.path.insert(0, str(MODEL_DIR))

from validate_strategies import derive_corsi_features  # noqa: E402

log = logging.getLogger(__name__)

DB_CONN = os.environ.get("DATABASE_URL", "postgresql://nhc_agent@localhost:5432/nhl_betting")

API_BASE = "https://api.bettingpros.com/v3"
API_KEY = os.environ.get("ODDS_API_KEY", "")
MARKET_ID = 322
HEADERS = {"x-api-key": API_KEY, "User-Agent": "Mozilla/5.0"}
BOOK_MAP = {
    0: "consensus", 10: "fanduel", 13: "caesars", 19: "betmgm",
    33: "espnbet", 39: "draftkings", 45: "bet365", 49: "hardrock", 60: "novig",
}


def _api_get(endpoint: str, params: dict) -> dict:
    """Make API request with retry logic."""
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt == 2:
                log.error(f"API failed after 3 attempts: {e}")
                return {}
            _time.sleep((attempt + 1) * 2)
    return {}


def fetch_todays_odds(target_date: str) -> pd.DataFrame:
    """Fetch saves odds for a specific date from BettingPros API."""
    log.info(f"Fetching saves odds for {target_date}...")

    data = _api_get("events", {"sport": "NHL", "date": target_date})
    events = data.get("events", [])
    if not events:
        log.info("No events found for this date.")
        return pd.DataFrame()

    log.info(f"Found {len(events)} games")

    rows = []
    for event in events:
        event_id = event.get("id")
        home_team = event.get("home", "")
        away_team = event.get("visitor", "")
        event_date = event.get("scheduled", "")[:10]

        _time.sleep(0.3)
        offers_data = _api_get(
            "offers",
            {"sport": "NHL", "market_id": MARKET_ID, "event_id": event_id, "location": "OH"},
        )

        for offer in offers_data.get("offers", []):
            participant = offer.get("participants", [{}])[0]
            player_name = participant.get("name", "")
            player = participant.get("player", {})
            player_team = player.get("team", "")

            selections = offer.get("selections", [])
            over_sel = next((s for s in selections if s.get("selection") == "over"), None)
            under_sel = next((s for s in selections if s.get("selection") == "under"), None)

            if not over_sel:
                continue

            for book in over_sel.get("books", []):
                book_id = book.get("id")
                book_name = BOOK_MAP.get(book_id, f"book_{book_id}")
                if book_name != "consensus":
                    continue

                for line_data in book.get("lines", []):
                    line_val = line_data.get("line")
                    over_odds = line_data.get("cost")
                    if line_val is None:
                        continue

                    under_odds = None
                    if under_sel:
                        for ubook in under_sel.get("books", []):
                            if ubook.get("id") == book_id:
                                ulines = ubook.get("lines", [])
                                if ulines:
                                    under_odds = ulines[0].get("cost")
                                break

                    rows.append({
                        "event_id": event_id,
                        "event_date": event_date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "player_name": player_name,
                        "player_team": player_team,
                        "line": float(line_val),
                        "over_odds": int(over_odds) if over_odds else None,
                        "under_odds": int(under_odds) if under_odds else None,
                    })

    if not rows:
        log.info("No saves odds found.")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    log.info(f"Found {len(df)} odds lines for {len(df['player_name'].unique())} goalies")
    return df


def build_live_features(target_date: str) -> pd.DataFrame:
    """Build feature matrix including all historical data up to target_date."""
    log.info("Loading tables and building features...")
    matrix_path = MODEL_DIR / "feature_matrix.pkl"
    if matrix_path.exists():
        matrix = pd.read_pickle(matrix_path)
        matrix["event_date"] = pd.to_datetime(matrix["event_date"])
        if "opp_corsi_pct_avg_10" not in matrix.columns:
            log.info("Deriving Corsi features...")
            matrix = derive_corsi_features(matrix)
        log.info(f"Loaded feature matrix: {len(matrix)} rows")
        return matrix
    else:
        log.error("Feature matrix not found! Run model/build_features.py first.")
        sys.exit(1)
