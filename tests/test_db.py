"""Tests for lib/db.py — shared database helpers."""

from unittest.mock import MagicMock, patch


class TestGetConnParams:
    def test_defaults(self):
        from lib.db import get_conn_params
        with patch.dict("os.environ", {}, clear=True):
            params = get_conn_params()
            assert params["host"] == "localhost"
            assert params["port"] == 5432
            assert params["user"] == "nhc_agent"
            assert params["dbname"] == "nhl_betting"

    def test_env_override(self):
        from lib.db import get_conn_params
        with patch.dict("os.environ", {"DB_HOST": "remotehost", "DB_PORT": "9999"}):
            params = get_conn_params()
            assert params["host"] == "remotehost"
            assert params["port"] == 9999

    def test_db_override(self):
        from lib.db import get_conn_params
        params = get_conn_params(db="polymarket")
        assert params["dbname"] == "polymarket"


class TestGetConnString:
    def test_basic(self):
        from lib.db import get_conn_string
        with patch.dict("os.environ", {}, clear=True):
            s = get_conn_string("testdb")
            assert "nhc_agent" in s
            assert "testdb" in s
            assert s.startswith("postgresql://")


class TestQueryHelpers:
    @patch("lib.db._get_pool")
    def test_query_returns_dicts(self, mock_pool):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "name": "test"}]
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool.return_value.getconn.return_value = mock_conn

        from lib.db import query
        result = query("SELECT 1", db="nhl_betting")
        assert result == [{"id": 1, "name": "test"}]

    @patch("lib.db._get_pool")
    def test_query_one_none(self, mock_pool):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool.return_value.getconn.return_value = mock_conn

        from lib.db import query_one
        result = query_one("SELECT 1 WHERE false", db="nhl_betting")
        assert result is None
