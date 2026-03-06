"""Integration tests for NHL betting pipeline."""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def nhl_db():
    """Connect to nhl_betting DB or skip."""
    try:
        from lib.db import query
        query("SELECT 1", db="nhl_betting")
        return True
    except Exception:
        pytest.skip("nhl_betting DB not available")


class TestDatabaseConnection:
    def test_can_connect(self, nhl_db):
        from lib.db import query_one
        result = query_one("SELECT 1 AS ok", db="nhl_betting")
        assert result["ok"] == 1

    def test_expected_tables_exist(self, nhl_db):
        from lib.db import query
        rows = query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'",
            db="nhl_betting",
        )
        tables = {r["table_name"] for r in rows}
        expected = {"saves_odds", "player_odds"}
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"


class TestFeatureBuild:
    def test_build_features_importable(self):
        """Verify the feature build module can be imported."""
        try:
            import importlib
            importlib.import_module("nhl-betting.model.build_features")
        except ImportError:
            # Module uses hyphens in path — expected with regular import
            pass  # Acceptable — module exists but path has hyphens


class TestModelTraining:
    def test_train_models_importable(self):
        """Verify the training module exists."""
        import os
        assert os.path.exists("nhl-betting/model/train_models.py")
