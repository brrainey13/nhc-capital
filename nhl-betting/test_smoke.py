"""NHL betting project regression tests."""

from pathlib import Path

PROJECT = Path(__file__).parent


def test_project_exists():
    """Project folder is wired into test suite."""
    assert PROJECT.is_dir()


def test_readme_has_content():
    readme = PROJECT / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert "NHL" in content or "nhl" in content


def test_init_exists():
    assert (PROJECT / "__init__.py").exists()


def test_docs_page_exists():
    docs_page = PROJECT.parent / "docs" / "nhl-betting.md"
    assert docs_page.exists(), "Missing docs/nhl-betting.md"


def test_scrapers_dir_exists():
    scrapers = PROJECT / "scrapers"
    assert scrapers.is_dir(), "Missing scrapers/ directory"
