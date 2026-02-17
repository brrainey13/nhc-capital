"""Top-level regression tests — validates monorepo structure, scripts, and cross-project integrity."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent

# ── Repo structure ──

REQUIRED_PROJECTS = ["nhl-betting", "admin-dashboard", "real-estate", "polymarket"]
REQUIRED_DOCS = [
    "admin-dashboard.md", "ci-pipeline.md", "coding-agents.md",
    "infrastructure.md", "networking-security.md", "nhl-betting.md",
    "polymarket.md", "real-estate.md", "subagents.md",
]
REQUIRED_ROOT_FILES = [
    "CLAUDE.md", "AGENTS.md", "codex.md", "Makefile", "pyproject.toml",
    ".github/workflows/ci.yml",
]


def test_project_folders_exist():
    """Every project folder must exist with __init__.py and at least one test file."""
    for proj in REQUIRED_PROJECTS:
        proj_dir = ROOT / proj
        assert proj_dir.is_dir(), f"Missing project folder: {proj}"
        assert (proj_dir / "__init__.py").exists(), f"Missing __init__.py in {proj}"
        test_files = list(proj_dir.rglob("test_*.py"))
        assert len(test_files) > 0, f"No test files in {proj}"


def test_project_readmes_exist():
    """Every project folder must have a README.md."""
    for proj in REQUIRED_PROJECTS:
        readme = ROOT / proj / "README.md"
        assert readme.exists(), f"Missing README.md in {proj}"
        content = readme.read_text().strip()
        assert len(content) > 20, f"README.md in {proj} is too short — add real content"


def test_docs_exist():
    """All required docs must exist with YAML front-matter."""
    docs_dir = ROOT / "docs"
    assert docs_dir.is_dir(), "Missing docs/ directory"
    for doc in REQUIRED_DOCS:
        doc_path = docs_dir / doc
        assert doc_path.exists(), f"Missing doc: docs/{doc}"
        content = doc_path.read_text()
        assert content.startswith("---"), f"docs/{doc} missing YAML front-matter"


def test_root_files_exist():
    """Critical root files must be present."""
    for f in REQUIRED_ROOT_FILES:
        assert (ROOT / f).exists(), f"Missing root file: {f}"


# ── Scripts ──

def test_scripts_executable():
    """Scripts must be executable."""
    scripts_dir = ROOT / "scripts"
    assert scripts_dir.is_dir(), "Missing scripts/ directory"
    for script in scripts_dir.iterdir():
        if script.is_file() and not script.name.startswith("."):
            assert os.access(script, os.X_OK), f"Script not executable: {script.name}"


def test_docs_list_runs():
    """scripts/docs-list must run successfully."""
    result = subprocess.run(
        ["scripts/docs-list"], cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"docs-list failed: {result.stderr}"
    assert "Read when" in result.stdout, "docs-list output looks wrong"


def test_committer_rejects_dot():
    """scripts/committer must reject 'git add .' style usage."""
    result = subprocess.run(
        ["scripts/committer", "test: bad commit", "."],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, "committer should reject '.'"


def test_docs_guard_passes():
    """scripts/docs-guard must pass — all docs have proper front-matter."""
    result = subprocess.run(
        ["python3", "scripts/docs-guard"], cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"docs-guard failed:\n{result.stdout}"
    assert "passed" in result.stdout, "docs-guard output looks wrong"


def test_project_claude_md_exists():
    """Every project subfolder must have a CLAUDE.md."""
    for proj in REQUIRED_PROJECTS:
        claude_md = ROOT / proj / "CLAUDE.md"
        assert claude_md.exists(), f"Missing {proj}/CLAUDE.md — agents need project context"


def test_committer_rejects_empty_message():
    """scripts/committer must reject empty commit messages."""
    result = subprocess.run(
        ["scripts/committer", "   ", "Makefile"],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, "committer should reject empty messages"


# ── Lint ──

def test_ruff_passes():
    """Ruff lint must pass on the entire repo."""
    result = subprocess.run(
        ["ruff", "check", "."], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"Ruff lint failures:\n{result.stdout}"


# ── pyproject.toml ──

def test_pyproject_testpaths():
    """pyproject.toml must list all project folders in testpaths."""
    content = (ROOT / "pyproject.toml").read_text()
    for proj in REQUIRED_PROJECTS:
        assert proj in content, f"pyproject.toml missing testpath: {proj}"
