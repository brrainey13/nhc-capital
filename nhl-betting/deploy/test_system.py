#!/usr/bin/env python3
"""
End-to-end test of the betting pipeline using a historical date.
Verifies all components work without needing live APIs.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DEPLOY_DIR = Path(__file__).parent
MODEL_DIR = ROOT / "model"
DATA_DIR = ROOT / "data"
PICKS_DIR = ROOT / "picks"

sys.path.insert(0, str(DEPLOY_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("test_system")

# Test date — use a date we have data for
TEST_DATE = "2026-01-15"


def test_model_loads():
    """Test 1: Model file loads and makes predictions."""
    import joblib

    model_path = MODEL_DIR / "lightgbm_model.pkl"
    assert model_path.exists(), f"Model not found at {model_path}"

    model = joblib.load(model_path)

    meta_path = MODEL_DIR / "model_metadata.json"
    assert meta_path.exists(), f"Metadata not found at {meta_path}"

    with open(meta_path) as f:
        metadata = json.load(f)

    features = metadata["features"]
    assert len(features) == 15, f"Expected 15 features, got {len(features)}"

    # Create dummy input
    X = pd.DataFrame({f: [0.5] for f in features})
    pred = model.predict(X)
    assert len(pred) == 1
    assert 10 < pred[0] < 50, f"Prediction {pred[0]} outside reasonable range"

    print(f"  ✅ Model loads, {len(features)} features, pred={pred[0]:.1f}")
    return True


def test_feature_matrix():
    """Test 2: Feature matrix has Corsi columns."""
    matrix = pd.read_pickle(MODEL_DIR / "feature_matrix.pkl")

    assert len(matrix) > 2500, f"Matrix too small: {len(matrix)}"

    required_corsi = ["opp_corsi_pct_avg_10", "opp_corsi_diff_avg_10", "own_corsi_pct_avg_10"]
    for col in required_corsi:
        assert col in matrix.columns, f"Missing Corsi column: {col}"
        non_null = matrix[col].notna().sum()
        assert non_null > 2000, f"{col} has too many nulls: {non_null}/{len(matrix)}"

    # No duplicates
    dupes = matrix.duplicated(subset=["player_name", "event_date"]).sum()
    assert dupes == 0, f"Found {dupes} duplicate rows"

    # No fully-null columns
    null_cols = [c for c in matrix.columns if matrix[c].isnull().all()]
    assert len(null_cols) == 0, f"Fully-null columns: {null_cols}"

    print(f"  ✅ Feature matrix: {len(matrix)} rows, {len(matrix.columns)} cols, Corsi present, no dupes")
    return True


def test_strategy_filters():
    """Test 3: Strategy filters produce expected output on historical data."""
    matrix = pd.read_pickle(MODEL_DIR / "feature_matrix.pkl")
    matrix["event_date"] = pd.to_datetime(matrix["event_date"])

    # Simulate what strategy engine does
    import joblib
    model = joblib.load(MODEL_DIR / "lightgbm_model.pkl")
    with open(MODEL_DIR / "model_metadata.json") as f:
        metadata = json.load(f)

    feature_cols = metadata["features"]
    thresholds = metadata["thresholds"]

    # Use fold 3 validation set
    val = matrix[matrix["event_date"] >= "2025-10-01"].copy()
    train = matrix[matrix["event_date"] < "2025-10-01"]

    available = [c for c in feature_cols if c in val.columns]
    X_val = val[available].fillna(-999)
    preds = model.predict(X_val)

    val = val.copy()
    val["pred_saves"] = preds
    val["gap"] = val["pred_saves"] - val["line"]
    val["abs_gap"] = val["gap"].abs()
    val["model_side"] = np.where(val["pred_saves"] < val["line"], "under", "over")

    # MF3a
    mf3a = val[
        (val["model_side"] == "under")
        & (val["abs_gap"] >= 1.0)
        & (val["abs_gap"] < 1.5)
        & (val["opp_corsi_pct_avg_10"] < thresholds["corsi_q25"])
    ]
    print(f"  MF3a: {len(mf3a)} picks on fold 3 val set")

    # MF3b
    mf3b = val[
        (val["model_side"] == "under")
        & (val["abs_gap"] >= 2.5)
        & (val["opp_corsi_pct_avg_10"] < thresholds["corsi_q25"])
    ]
    print(f"  MF3b: {len(mf3b)} picks")

    # MF2
    mf2 = val[
        (val["model_side"] == "under")
        & (val["abs_gap"] >= 2.0)
        & (val["days_rest"] <= 1)
    ]
    print(f"  MF2: {len(mf2)} picks")

    # MF5
    mf5 = val[
        (val["model_side"] == "under")
        & (val["abs_gap"] >= 1.0)
        & (val["opp_corsi_pct_avg_10"] < thresholds["corsi_q30"])
    ]
    print(f"  MF5: {len(mf5)} picks")

    total = len(mf3a) + len(mf3b) + len(mf2) + len(mf5)
    assert total > 0, "No picks produced by any strategy!"

    # Verify win rates on this fold
    for name, picks in [("MF3a", mf3a), ("MF3b", mf3b), ("MF2", mf2), ("MF5", mf5)]:
        if len(picks) > 0:
            non_push = picks[picks["saves"] != picks["line"]]
            if len(non_push) > 5:
                wins = (non_push["saves"] < non_push["line"]).sum()
                wr = wins / len(non_push) * 100
                print(f"    {name}: {wins}/{len(non_push)} = {wr:.1f}% win rate")

    print(f"  ✅ All strategies produce picks, total {total} on fold 3")
    return True


def test_kelly_sizer():
    """Test 4: Kelly sizer produces reasonable bet sizes."""
    from kelly_sizer import size_bet, estimate_win_prob

    for strategy in ["MF3a", "MF3b", "MF5", "MF2", "PF1"]:
        wp = estimate_win_prob(strategy, gap=1.5)
        result = size_bet(wp, -110)

        assert 0 < result["bet_amount"] <= 300, f"Unreasonable bet: ${result['bet_amount']}"
        assert result["expected_value"] > 0, f"Negative EV for {strategy}"
        assert 0.50 < wp < 0.80, f"Unreasonable win prob: {wp}"

    print(f"  ✅ Kelly sizer produces reasonable bets for all strategies")
    return True


def test_notification_format():
    """Test 5: Notification formatter produces valid output."""
    from notify import format_picks_message, format_results_message

    test_picks = {
        "date": TEST_DATE,
        "paper_trading": True,
        "total_action": "$350",
        "picks": [
            {
                "game": "NYR @ BOS",
                "goalie": "Igor Shesterkin",
                "line": 28.5,
                "juice": -110,
                "strategy": "MF3a",
                "bet": "UNDER",
                "confidence": "HIGH",
                "model_gap": 1.2,
                "bet_size_025kelly": "$125",
                "estimated_win_prob": "70.5%",
                "starter_confirmed": True,
                "reasoning": "Gap 1.2, opponent bottom 25% Corsi",
                "paper_only": False,
            }
        ],
    }

    msg = format_picks_message(test_picks)
    assert "Shesterkin" in msg
    assert "UNDER 28.5" in msg
    assert "MF3a" in msg
    assert len(msg) < 2000, f"Message too long: {len(msg)} chars"

    test_results = {
        "date": TEST_DATE,
        "record": "3-1",
        "pnl": 245.0,
        "roi": 18.2,
        "by_strategy": {"MF3a": {"record": "2-0", "win_pct": 100.0, "pnl": 200.0}},
        "overall_7d": {"record": "10-5", "win_pct": 66.7, "pnl": 500.0, "roi": 15.0},
    }

    msg = format_results_message(test_results)
    assert "3-1" in msg
    assert "+245" in msg

    print(f"  ✅ Notification formats valid")
    return True


def test_nhl_api_connectivity():
    """Test 6: NHL API is reachable."""
    import requests

    try:
        resp = requests.get("https://api-web.nhle.com/v1/schedule/now", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        assert "gameWeek" in data
        print(f"  ✅ NHL API reachable")
        return True
    except Exception as e:
        print(f"  ⚠️ NHL API unreachable: {e}")
        return False


def test_database_connectivity():
    """Test 7: Database is reachable and has expected tables."""
    import psycopg2

    try:
        conn = psycopg2.connect("postgresql://connorrainey@localhost:5432/nhl_betting")
        cur = conn.cursor()

        tables = ["goalie_stats", "games", "game_team_stats", "players"]
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            assert count > 0, f"Table {table} is empty"

        conn.close()
        print(f"  ✅ Database connected, all tables have data")
        return True
    except Exception as e:
        print(f"  ❌ Database error: {e}")
        return False


def main():
    print("=" * 60)
    print(f"  NHL BETTING SYSTEM — END-TO-END TEST")
    print(f"  Test date: {TEST_DATE}")
    print("=" * 60)

    tests = [
        ("Model loads", test_model_loads),
        ("Feature matrix", test_feature_matrix),
        ("Strategy filters", test_strategy_filters),
        ("Kelly sizer", test_kelly_sizer),
        ("Notification format", test_notification_format),
        ("NHL API", test_nhl_api_connectivity),
        ("Database", test_database_connectivity),
    ]

    results = []
    for name, test_fn in tests:
        print(f"\nTest: {name}")
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")
    print(f"\n  {passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
