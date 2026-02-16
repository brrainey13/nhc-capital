"""Real estate project regression tests."""

from pathlib import Path

PROJECT = Path(__file__).parent


def test_project_exists():
    assert PROJECT.is_dir()


def test_readme_has_content():
    readme = PROJECT / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert len(content.strip()) > 20


def test_init_exists():
    assert (PROJECT / "__init__.py").exists()
