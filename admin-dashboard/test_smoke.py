"""Admin dashboard project regression tests."""

from pathlib import Path

PROJECT = Path(__file__).parent


def test_project_exists():
    assert PROJECT.is_dir()


def test_readme_has_content():
    readme = PROJECT / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert "dashboard" in content.lower()


def test_init_exists():
    assert (PROJECT / "__init__.py").exists()


def test_backend_exists():
    assert (PROJECT / "backend" / "main.py").exists()


def test_frontend_exists():
    assert (PROJECT / "frontend").is_dir()


def test_docs_page_exists():
    docs_page = PROJECT.parent / "docs" / "admin-dashboard.md"
    assert docs_page.exists()
