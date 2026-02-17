"""Smoke tests for real-estate."""


def test_project_exists():
    """Verify the project is wired into the test suite."""
    assert True


def test_etl_api_connectivity():
    """Verify SODA API connectivity (dry-run). Requires SODA_APP_TOKEN env."""
    import os
    import subprocess
    import sys

    token = os.environ.get("SODA_APP_TOKEN")
    if not token:
        import pytest
        pytest.skip("SODA_APP_TOKEN not set — skip API connectivity test")

    # Run from real-estate folder
    root = __file__.replace("\\", "/").rsplit("/", 1)[0]
    result = subprocess.run(
        [sys.executable, "scripts/etl_parcel_universe.py", "--limit", "2", "--dry-run"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"ETL dry-run failed: {result.stderr}"
    assert "rows_fetched" in result.stdout or "Would upsert" in result.stdout
