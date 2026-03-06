"""Tests for the daily picks pipeline.

Requires nhl-betting venv (lightgbm, pandas, numpy).
Skipped automatically when deps aren't available.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).parent / "model"))

pytest.importorskip("lightgbm", reason="requires nhl-betting venv")


def test_strategy_filter_mf3a():
    """MF3a: UNDER, gap [1.0, 1.5), opponent Corsi bottom 25%."""
    import numpy as np
    import pandas as pd
    from daily_picks import apply_strategy_filters

    # Create a minimal matrix with Corsi features
    np.random.seed(42)
    n = 200
    matrix = pd.DataFrame({
        "event_date": pd.date_range("2024-01-01", periods=n),
        "opp_corsi_pct_avg_10": np.random.uniform(0.42, 0.58, n),
        "opp_corsi_diff_avg_10": np.random.uniform(-10, 10, n),
        "opp_puck_control_avg_10": np.random.uniform(-15, 5, n),
    })

    q25 = matrix["opp_corsi_pct_avg_10"].quantile(0.25)

    # Pick with gap=1.2 (in [1.0, 1.5)), low Corsi
    picks = [{
        "pred_saves": 22.3,
        "line": 23.5,
        "features": {
            "opp_corsi_pct_avg_10": q25 - 0.01,  # Below Q25
            "opp_corsi_diff_avg_10": -5,
            "opp_puck_control_avg_10": -10,
            "days_rest": 3,
        },
    }]

    result = apply_strategy_filters(picks, matrix, "2025-06-01")
    assert "MF3a" in result[0]["strategies"]
    assert result[0]["side"] == "UNDER"


def test_strategy_filter_mf3b():
    """MF3b: UNDER, gap >= 2.5, opponent Corsi bottom 25%."""
    import numpy as np
    import pandas as pd
    from daily_picks import apply_strategy_filters

    np.random.seed(42)
    n = 200
    matrix = pd.DataFrame({
        "event_date": pd.date_range("2024-01-01", periods=n),
        "opp_corsi_pct_avg_10": np.random.uniform(0.42, 0.58, n),
        "opp_corsi_diff_avg_10": np.random.uniform(-10, 10, n),
        "opp_puck_control_avg_10": np.random.uniform(-15, 5, n),
    })

    q25 = matrix["opp_corsi_pct_avg_10"].quantile(0.25)

    picks = [{
        "pred_saves": 20.5,
        "line": 23.5,
        "features": {
            "opp_corsi_pct_avg_10": q25 - 0.01,
            "opp_corsi_diff_avg_10": -5,
            "opp_puck_control_avg_10": -10,
            "days_rest": 3,
        },
    }]

    result = apply_strategy_filters(picks, matrix, "2025-06-01")
    assert "MF3b" in result[0]["strategies"]


def test_strategy_filter_mf2():
    """MF2: UNDER, gap >= 2.0, back-to-back."""
    import numpy as np
    import pandas as pd
    from daily_picks import apply_strategy_filters

    np.random.seed(42)
    n = 200
    matrix = pd.DataFrame({
        "event_date": pd.date_range("2024-01-01", periods=n),
        "opp_corsi_pct_avg_10": np.random.uniform(0.42, 0.58, n),
        "opp_corsi_diff_avg_10": np.random.uniform(-10, 10, n),
        "opp_puck_control_avg_10": np.random.uniform(-15, 5, n),
    })

    picks = [{
        "pred_saves": 21.0,
        "line": 23.5,
        "features": {
            "opp_corsi_pct_avg_10": 0.50,  # Not low Corsi
            "opp_corsi_diff_avg_10": 0,
            "opp_puck_control_avg_10": -5,
            "days_rest": 1,  # Back-to-back
        },
    }]

    result = apply_strategy_filters(picks, matrix, "2025-06-01")
    assert "MF2" in result[0]["strategies"]


def test_no_signal_when_edge_too_small():
    """No strategies should fire when edge is tiny."""
    import numpy as np
    import pandas as pd
    from daily_picks import apply_strategy_filters

    np.random.seed(42)
    n = 200
    matrix = pd.DataFrame({
        "event_date": pd.date_range("2024-01-01", periods=n),
        "opp_corsi_pct_avg_10": np.random.uniform(0.42, 0.58, n),
        "opp_corsi_diff_avg_10": np.random.uniform(-10, 10, n),
        "opp_puck_control_avg_10": np.random.uniform(-15, 5, n),
    })

    picks = [{
        "pred_saves": 23.3,
        "line": 23.5,
        "features": {
            "opp_corsi_pct_avg_10": 0.45,
            "opp_corsi_diff_avg_10": -3,
            "opp_puck_control_avg_10": -8,
            "days_rest": 1,
        },
    }]

    result = apply_strategy_filters(picks, matrix, "2025-06-01")
    assert len(result[0]["strategies"]) == 0


def test_format_picks_no_signal():
    """format_picks returns message when no signals."""
    from daily_picks import format_picks

    picks = [{"has_signal": False, "player_name": "Test", "strategies": []}]
    output = format_picks(picks)
    assert "No strategy signals" in output


def test_american_to_decimal():
    """Test odds conversion."""
    from daily_picks import american_to_decimal

    assert abs(american_to_decimal(-110) - 0.909) < 0.01
    assert abs(american_to_decimal(+150) - 1.5) < 0.01
    assert abs(american_to_decimal(-200) - 0.5) < 0.01
