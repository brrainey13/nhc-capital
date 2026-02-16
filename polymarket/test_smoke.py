"""Polymarket project regression tests."""

from pathlib import Path

PROJECT = Path(__file__).parent


def test_project_exists():
    """Project folder is wired into test suite."""
    assert PROJECT.is_dir()


def test_readme_has_content():
    """README must describe the project."""
    readme = PROJECT / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert "Polymarket" in content
    assert "Status" in content


def test_init_exists():
    """Package must be importable."""
    assert (PROJECT / "__init__.py").exists()


def test_docs_page_exists():
    """Must have a corresponding docs page."""
    docs_page = PROJECT.parent / "docs" / "polymarket.md"
    assert docs_page.exists(), "Missing docs/polymarket.md"
