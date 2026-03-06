"""Shared pytest fixtures for NHC Capital tests."""

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
ADMIN_BACKEND = REPO_ROOT / "admin-dashboard" / "backend"
NHL_ROOT = REPO_ROOT / "nhl-betting"

for path in (str(ADMIN_BACKEND), str(NHL_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("DB_USER", "nhc_agent")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key-1")
os.environ.setdefault("ODDS_API_KEY_2", "test-odds-key-2")


@pytest.fixture(autouse=True)
def test_env_vars():
    """Set test auth env vars without freezing values at import time."""
    with patch.dict(
        os.environ,
        {
            "ALLOWED_EMAILS": "test@example.com,second@example.com",
            "DASHBOARD_API_KEY": "super-secret-test-key",
            "ODDS_API_KEY": "test-odds-key-1",
            "ODDS_API_KEY_2": "test-odds-key-2",
        },
        clear=False,
    ):
        yield


@pytest.fixture
def mock_db_connection():
    """Mock DB connection with context-managed cursor support."""
    conn = MagicMock(name="connection")
    cur = MagicMock(name="cursor")
    conn.cursor.return_value = cur
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    return conn


@pytest.fixture
def mock_api_response():
    """Factory for simple mocked HTTP responses."""

    def _build(payload, *, status_code=200, headers=None):
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        response.json.return_value = payload
        return response

    return _build


@pytest.fixture
def fastapi_client():
    """Factory for FastAPI clients with DB startup disabled."""
    import main

    @contextmanager
    def _make_client(*, base_url="http://dashboard.test", headers=None):
        with (
            patch.object(main, "init_pools", AsyncMock()),
            patch.object(main, "close_pools", AsyncMock()),
            TestClient(main.app, base_url=base_url, headers=headers or {}) as client,
        ):
            yield client

    return _make_client


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

    return pd.DataFrame(
        {
            "player_name": ["McDavid", "Matthews", "Draisaitl"],
            "team": ["EDM", "TOR", "EDM"],
            "goals": [5, 3, 4],
            "assists": [10, 7, 8],
        }
    )


@pytest.fixture
def sample_df_with_nulls():
    """DataFrame with null values for validation tests."""
    import pandas as pd

    return pd.DataFrame(
        {
            "player_name": ["McDavid", None, "Draisaitl"],
            "team": ["EDM", "TOR", None],
            "goals": [5, 3, 4],
        }
    )


@pytest.fixture
def sample_df_with_dupes():
    """DataFrame with duplicate rows."""
    import pandas as pd

    return pd.DataFrame(
        {
            "player_name": ["McDavid", "McDavid", "Matthews"],
            "team": ["EDM", "EDM", "TOR"],
            "goals": [5, 5, 3],
        }
    )


@pytest.fixture
def db_connection():
    """Live DB connection fixture (for integration tests)."""
    try:
        from lib.db import get_connection

        with get_connection("nhl_betting") as conn:
            yield conn
    except Exception:
        pytest.skip("Database not available")
