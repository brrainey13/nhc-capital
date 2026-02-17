#!/usr/bin/env python3
"""
Daily Picks Pipeline — Live prediction for NHL goalie saves O/U.

Fetches today's odds, builds features, trains model on all historical data,
applies proven strategy filters, and outputs picks.

Usage:
    .venv/bin/python pipeline/daily_picks.py                  # Today's picks
    .venv/bin/python pipeline/daily_picks.py --date 2025-12-15  # Historical backtest
    .venv/bin/python pipeline/daily_picks.py --dry-run          # No DB writes
"""
import argparse
import json
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import requests

# Add model dir to path for imports
MODEL_DIR = Path(__file__).resolve().parent.parent / "model"
sys.path.insert(0, str(MODEL_DIR))

from build_features import load_tables  # noqa: E402
from train_models import (  # noqa: E402
    get_shot_features_by_iteration,
    get_shot_params,
    get_svpct_features_by_iteration,
    get_svpct_params,
)
from validate_strategies import derive_corsi_features  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"

# BettingPros API config (from scrape_saves_odds.py)
API_BASE = "https://api.bettingpros.com/v3"
API_KEY = "CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh"
MARKET_ID = 322  # Saves O/U
HEADERS = {"x-api-key": API_KEY, "User-Agent": "Mozilla/5.0"}
BOOK_MAP = {
    0: "consensus",
    10: "fanduel",
    13: "caesars",
    19: "betmgm",
    33: "espnbet",
    39: "draftkings",
    45: "bet365",
    49: "hardrock",
    60: "novig",
}


def _api_get(endpoint: str, params: dict) -> dict:
    """Make API request with retry logic."""
    import time as _time

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
    """Fetch saves odds for a specific date from BettingPros API.

    Uses the same two-step approach as scrape_saves_odds.py:
    1. GET /events to find games
    2. GET /offers per event to find saves props
    """
    import time as _time

    log.info(f"Fetching saves odds for {target_date}...")

    # Step 1: Get events
    data = _api_get("events", {"sport": "NHL", "date": target_date})
    events = data.get("events", [])
    if not events:
        log.info("No events found for this date.")
        return pd.DataFrame()

    log.info(f"Found {len(events)} games")

    # Step 2: Get offers per event
    rows = []
    for event in events:
        event_id = event.get("id")
        home_team = event.get("home", "")
        away_team = event.get("visitor", "")
        event_date = event.get("scheduled", "")[:10]

        _time.sleep(0.3)  # Rate limit
        offers_data = _api_get(
            "offers",
            {
                "sport": "NHL",
                "market_id": MARKET_ID,
                "event_id": event_id,
                "location": "OH",
            },
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

            # Get consensus line
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

                    # Find matching under odds
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
    dfs = load_tables()
    matrix = _build_full_matrix(dfs, target_date)
    return matrix


def _build_full_matrix(dfs: dict, up_to_date: str) -> pd.DataFrame:
    """Rebuild the feature matrix. Returns the full matrix for training."""
    # This reuses the existing build logic from build_features.py
    # We load the pre-built matrix and filter by date
    matrix_path = MODEL_DIR / "feature_matrix.pkl"
    if matrix_path.exists():
        matrix = pd.read_pickle(matrix_path)
        matrix["event_date"] = pd.to_datetime(matrix["event_date"])
        # Derive Corsi features (needed for strategy filters)
        if "opp_corsi_pct_avg_10" not in matrix.columns:
            log.info("Deriving Corsi features...")
            matrix = derive_corsi_features(matrix)
        log.info(f"Loaded feature matrix: {len(matrix)} rows")
        return matrix
    else:
        log.error("Feature matrix not found! Run model/build_features.py first.")
        sys.exit(1)


def get_goalie_features_for_prediction(
    matrix: pd.DataFrame, player_name: str, target_date: str
) -> dict | None:
    """Extract the most recent rolling features for a goalie."""
    target_dt = pd.to_datetime(target_date)
    goalie_data = matrix[
        (matrix["player_name"] == player_name)
        & (matrix["event_date"] < target_dt)
    ].sort_values("event_date")

    if len(goalie_data) == 0:
        return None

    # Use the most recent row's features as the basis
    latest = goalie_data.iloc[-1]
    return latest.to_dict()


def train_production_model(matrix: pd.DataFrame, target_date: str):
    """Train shot and save% models on all data before target_date."""
    target_dt = pd.to_datetime(target_date)
    train_df = matrix[matrix["event_date"] < target_dt].dropna(
        subset=["shots_against", "save_pct"]
    )

    if len(train_df) < 100:
        log.error(f"Not enough training data: {len(train_df)} rows")
        return None, None, None, None

    log.info(f"Training on {len(train_df)} games (up to {target_date})")

    # Recency weights (half-life 365 days)
    max_date = train_df["event_date"].max()
    days_ago = (max_date - train_df["event_date"]).dt.days
    weights = np.exp(-days_ago * np.log(2) / 365)

    # Feature lists (iteration 5)
    shot_features = [
        c for c in get_shot_features_by_iteration(5) if c in train_df.columns
    ]
    svpct_features = [
        c for c in get_svpct_features_by_iteration(5) if c in train_df.columns
    ]

    # Train shots model
    sp = get_shot_params(5)
    sp.pop("n_estimators", None)
    sp.pop("verbose", None)
    model_shots = lgb.LGBMRegressor(**sp, n_estimators=500, verbose=-1)
    model_shots.fit(
        train_df[shot_features].fillna(-999),
        train_df["shots_against"],
        sample_weight=weights,
    )

    # Train save% model
    svp = get_svpct_params(5)
    svp.pop("n_estimators", None)
    svp.pop("verbose", None)
    model_svpct = lgb.LGBMRegressor(**svp, n_estimators=500, verbose=-1)
    model_svpct.fit(
        train_df[svpct_features].fillna(-999),
        train_df["save_pct"],
        sample_weight=weights,
    )

    # Compute Corsi quantiles from recent data (last 2 seasons)
    recent = train_df[train_df["event_date"] >= target_dt - pd.Timedelta(days=730)]
    corsi_q25 = recent["opp_corsi_pct_avg_10"].quantile(0.25) if "opp_corsi_pct_avg_10" in recent.columns else 48.0
    corsi_q75 = recent["opp_corsi_pct_avg_10"].quantile(0.75) if "opp_corsi_pct_avg_10" in recent.columns else 52.0

    log.info(f"Corsi Q25={corsi_q25:.1f}, Q75={corsi_q75:.1f}")

    return model_shots, model_svpct, shot_features, svpct_features


def predict_saves(
    model_shots, model_svpct, shot_features, svpct_features, features_dict: dict
) -> float:
    """Predict saves for a single goalie game."""
    shot_vals = pd.DataFrame([{f: features_dict.get(f, -999) for f in shot_features}])
    svpct_vals = pd.DataFrame([{f: features_dict.get(f, -999) for f in svpct_features}])

    pred_shots = model_shots.predict(shot_vals)[0]
    pred_svpct = model_svpct.predict(svpct_vals)[0]
    pred_saves = pred_shots * pred_svpct

    return pred_saves


def apply_strategy_filters(picks: list[dict], matrix: pd.DataFrame, target_date: str) -> list[dict]:
    """Apply proven strategy filters (MF3a, MF3b, MF2, PF1) to picks."""
    target_dt = pd.to_datetime(target_date)
    recent = matrix[matrix["event_date"] >= target_dt - pd.Timedelta(days=730)]

    corsi_q25 = recent["opp_corsi_pct_avg_10"].quantile(0.25) if "opp_corsi_pct_avg_10" in recent.columns else 48.0
    corsi_q75 = recent["opp_corsi_pct_avg_10"].quantile(0.75) if "opp_corsi_pct_avg_10" in recent.columns else 52.0

    for pick in picks:
        strategies = []
        feat = pick.get("features", {})
        edge = pick["pred_saves"] - pick["line"]
        gap = abs(edge)
        opp_corsi = feat.get("opp_corsi_pct_avg_10")
        days_rest = feat.get("days_rest")
        opp_corsi_diff = feat.get("opp_corsi_diff_avg_10")

        # UNDER strategies (edge < 0 means model predicts fewer saves than line)
        if edge < 0:
            # MF3a: gap [1.0, 1.5), opponent Corsi bottom 25%
            if 1.0 <= gap < 1.5 and opp_corsi is not None and opp_corsi < corsi_q25:
                strategies.append("MF3a")

            # MF3b: gap >= 2.5, opponent Corsi bottom 25%
            if gap >= 2.5 and opp_corsi is not None and opp_corsi < corsi_q25:
                strategies.append("MF3b")

            # MF2: gap >= 2.0, back-to-back
            if gap >= 2.0 and days_rest is not None and days_rest <= 1:
                strategies.append("MF2")

        # OVER strategies (edge > 0)
        if edge > 0:
            # PF1: opponent top 25% in Corsi%, Corsi diff, AND puck possession
            opp_puck = feat.get("opp_puck_control_avg_10")
            corsi_diff_q75 = (
                recent["opp_corsi_diff_avg_10"].quantile(0.75)
                if "opp_corsi_diff_avg_10" in recent.columns else 3.0
            )
            puck_q75 = (
                recent["opp_puck_control_avg_10"].quantile(0.75)
                if "opp_puck_control_avg_10" in recent.columns else -1.0
            )
            if (
                opp_corsi is not None and opp_corsi > corsi_q75
                and opp_corsi_diff is not None and opp_corsi_diff > corsi_diff_q75
                and opp_puck is not None and opp_puck > puck_q75
            ):
                strategies.append("PF1")

        pick["strategies"] = strategies
        pick["side"] = "UNDER" if edge < 0 else "OVER"
        pick["edge"] = edge
        pick["gap"] = gap
        pick["has_signal"] = len(strategies) > 0
        pick["confidence"] = len(strategies)  # More overlapping strategies = higher confidence

    return picks


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal payout."""
    if odds < 0:
        return 100 / (-odds)
    return odds / 100


def format_picks(picks: list[dict]) -> str:
    """Format picks as a readable table."""
    # Filter to only picks with signal
    signaled = [p for p in picks if p.get("has_signal")]
    if not signaled:
        return "No strategy signals found for today's games."

    # Sort by confidence (desc), then gap (desc)
    signaled.sort(key=lambda p: (-p["confidence"], -p["gap"]))

    lines = []
    lines.append("=" * 80)
    lines.append(f"  NHL GOALIE SAVES PICKS — {signaled[0].get('date', 'Today')}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(
        f"  {'Player':<22} {'Team':<5} {'Line':>5} {'Pred':>5} {'Edge':>6} "
        f"{'Side':<6} {'Odds':>6} {'Strategies':<20}"
    )
    lines.append(f"  {'-' * 76}")

    for p in signaled:
        odds = p.get("under_odds") if p["side"] == "UNDER" else p.get("over_odds")
        odds_str = f"{odds:+d}" if odds else "N/A"
        strats = ", ".join(p["strategies"])
        lines.append(
            f"  {p['player_name']:<22} {p.get('player_team', ''):<5} "
            f"{p['line']:>5.1f} {p['pred_saves']:>5.1f} {p['edge']:>+5.1f} "
            f"{p['side']:<6} {odds_str:>6} {strats:<20}"
        )

    lines.append("")
    lines.append(f"  Total signals: {len(signaled)} / {len(picks)} games")
    lines.append("=" * 80)
    return "\n".join(lines)


def save_predictions(picks: list[dict], dry_run: bool = False):
    """Save predictions and model run to database."""
    if dry_run:
        log.info("Dry run — skipping DB writes")
        return

    signaled = [p for p in picks if p.get("has_signal")]
    if not signaled:
        return

    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    # Record model run
    cur.execute(
        """INSERT INTO model_runs (model_name, model_version, trained_at,
           train_start_date, train_end_date, row_count, metrics_json)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING run_id""",
        (
            "saves_strategy_v2",
            "1.0",
            datetime.now().isoformat(),
            "2022-10-01",
            signaled[0].get("date", datetime.now().strftime("%Y-%m-%d")),
            len(signaled),
            json.dumps({
                "strategies": [p["strategies"] for p in signaled],
                "picks": [
                    {
                        "player": p["player_name"],
                        "side": p["side"],
                        "edge": round(p["edge"], 2),
                        "line": p["line"],
                    }
                    for p in signaled
                ],
            }),
        ),
    )
    run_id = cur.fetchone()[0]
    log.info(f"Saved model run #{run_id}")

    conn.commit()
    cur.close()
    conn.close()


def run_pipeline(target_date: str, dry_run: bool = False):
    """Main pipeline: fetch odds → build features → predict → filter → output."""
    log.info(f"Running daily picks pipeline for {target_date}")

    # Step 1: Get today's odds
    odds_df = fetch_todays_odds(target_date)
    if odds_df.empty:
        log.info("No odds available. Season may be on break.")
        print("\nNo games with saves odds found for this date.")
        print("The NHL season is likely on break (All-Star / bye week).")
        return []

    # Step 2: Load feature matrix
    matrix = _build_full_matrix({}, target_date)

    # Step 3: Train production model
    result = train_production_model(matrix, target_date)
    if result[0] is None:
        return []
    model_shots, model_svpct, shot_features, svpct_features = result

    # Step 4: Predict for each goalie
    picks = []
    for _, row in odds_df.iterrows():
        player_name = row["player_name"]
        features = get_goalie_features_for_prediction(matrix, player_name, target_date)

        if features is None:
            log.warning(f"No historical data for {player_name} — skipping")
            continue

        # Update features with today's context
        features["line"] = row["line"]

        pred_saves = predict_saves(
            model_shots, model_svpct, shot_features, svpct_features, features
        )

        picks.append({
            "date": target_date,
            "player_name": player_name,
            "player_team": row.get("player_team", ""),
            "line": row["line"],
            "over_odds": row.get("over_odds"),
            "under_odds": row.get("under_odds"),
            "pred_saves": pred_saves,
            "features": features,
        })

    # Step 5: Apply strategy filters
    picks = apply_strategy_filters(picks, matrix, target_date)

    # Step 6: Output
    output = format_picks(picks)
    print(output)

    # Step 7: Save to DB
    save_predictions(picks, dry_run=dry_run)

    return picks


def main():
    parser = argparse.ArgumentParser(description="NHL Goalie Saves Daily Picks")
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Target date (YYYY-MM-DD), default today",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to database",
    )
    args = parser.parse_args()
    run_pipeline(args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
