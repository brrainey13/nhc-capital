"""Shared pytest fixtures for NHC Capital tests."""

import os

import pytest

# Ensure we use nhc_agent for reads in tests
os.environ.setdefault("DB_USER", "nhc_agent")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")


@pytest.fixture
def sample_rows():
    """Sample row data for ingestion tests."""
    return [
        {"player_name": "Connor McDavid", "team": "EDM", "goals": 5},
        {"player_name": "Auston Matthews", "team": "TOR", "goals": 3},
    ]


@pytest.fixture
def sample_df():
    """Sample DataFrame for validation tests."""
    import pandas as pd
    return pd.DataFrame({
        "player_name": ["McDavid", "Matthews", "Draisaitl"],
        "team": ["EDM", "TOR", "EDM"],
        "goals": [5, 3, 4],
        "assists": [10, 7, 8],
    })


@pytest.fixture
def sample_df_with_nulls():
    """DataFrame with null values for validation tests."""
    import pandas as pd
    return pd.DataFrame({
        "player_name": ["McDavid", None, "Draisaitl"],
        "team": ["EDM", "TOR", None],
        "goals": [5, 3, 4],
    })


@pytest.fixture
def sample_df_with_dupes():
    """DataFrame with duplicate rows."""
    import pandas as pd
    return pd.DataFrame({
        "player_name": ["McDavid", "McDavid", "Matthews"],
        "team": ["EDM", "EDM", "TOR"],
        "goals": [5, 5, 3],
    })


@pytest.fixture
def db_connection():
    """Live DB connection fixture (for integration tests)."""
    try:
        from lib.db import get_connection
        with get_connection("nhl_betting") as conn:
            yield conn
    except Exception:
        pytest.skip("Database not available")
