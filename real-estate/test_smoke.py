"""Real estate project regression tests."""

from pathlib import Path

PROJECT = Path(__file__).parent


def test_project_exists():
    """Verify the project is wired into the test suite."""
    assert PROJECT.is_dir()


def test_readme_has_content():
    readme = PROJECT / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert len(content.strip()) > 20


def test_init_exists():
    assert (PROJECT / "__init__.py").exists()


def test_etl_api_connectivity():
    """Verify SODA API connectivity (dry-run). Requires SODA_APP_TOKEN env."""
    import os
    import subprocess
    import sys

    token = os.environ.get("SODA_APP_TOKEN")
    if not token:
        import pytest
        pytest.skip("SODA_APP_TOKEN not set — skip API connectivity test")

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
