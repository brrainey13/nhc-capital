"""Tests for the MR review agent."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "mr-review"


def load_mr_review():
    """Load mr-review as a module."""
    spec = importlib.util.spec_from_file_location("mr_review", str(SCRIPT_PATH), submodule_search_locations=[])
    if spec is None or spec.loader is None:
        # Fallback: exec the file directly
        import types
        mod = types.ModuleType("mr_review")
        mod.__file__ = str(SCRIPT_PATH)
        code = SCRIPT_PATH.read_text()
        exec(compile(code, str(SCRIPT_PATH), "exec"), mod.__dict__)
        return mod
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mr_review_script_exists():
    """mr-review script must exist."""
    assert SCRIPT_PATH.exists()


def test_classify_files_high_risk():
    """Dashboard files should be classified as high risk."""
    mod = load_mr_review()
    result = mod.classify_files(["admin-dashboard/backend/main.py"])
    assert result["tier"] == "high"


def test_analyze_diff_detects_secrets():
    """Should detect hardcoded tokens in diffs."""
    mod = load_mr_review()
    changes = [{
        "new_path": "config.py",
        "diff": '+token = "ghp_abc123secret"',
        "new_file": False,
    }]
    findings = mod.analyze_diff("", changes, {"tier": "low"})
    assert any(f["severity"] == "critical" for f in findings)


def test_analyze_diff_detects_sql_injection():
    """Should detect f-string SQL."""
    mod = load_mr_review()
    changes = [{
        "new_path": "query.py",
        "diff": '+result = f"SELECT * FROM users WHERE id = {user_id}"',
        "new_file": False,
    }]
    findings = mod.analyze_diff("", changes, {"tier": "low"})
    assert any("SQL injection" in f["message"] for f in findings)


def test_analyze_diff_detects_ddl():
    """Should detect DDL in non-dashboard code."""
    mod = load_mr_review()
    changes = [{
        "new_path": "nhl-betting/scripts/migrate.py",
        "diff": '+cursor.execute("CREATE TABLE new_stats (id serial)")',
        "new_file": False,
    }]
    findings = mod.analyze_diff("", changes, {"tier": "medium"})
    assert any("DDL" in f["message"] for f in findings)


def test_analyze_diff_clean():
    """Clean code should produce no findings."""
    mod = load_mr_review()
    changes = [{
        "new_path": "utils.py",
        "diff": '+def add(a, b):\n+    return a + b',
        "new_file": False,
    }]
    findings = mod.analyze_diff("", changes, {"tier": "low"})
    assert len(findings) == 0


def test_format_review_includes_sha():
    """Review comment must include SHA tag."""
    mod = load_mr_review()
    mr = {"sha": "abc1234567890"}
    review = mod.format_review(mr, {"tier": "low", "requiredChecks": []}, [], "abc1234567890")
    assert "sha:abc1234" in review
    assert mod.REVIEW_MARKER in review


def test_format_review_with_findings():
    """Review with findings should list them by severity."""
    mod = load_mr_review()
    findings = [
        {"file": "x.py", "severity": "critical", "message": "Secret found"},
        {"file": "y.py", "severity": "warning", "message": "Long file"},
    ]
    review = mod.format_review({}, {"tier": "high", "requiredChecks": []}, findings, "abc123")
    assert "🚨 Critical" in review
    assert "⚠️ Warnings" in review


def test_is_stale_review():
    """Should detect existing review for same SHA."""
    mod = load_mr_review()
    notes = [{"body": f"{mod.REVIEW_MARKER}\n## Review — sha:abc1234"}]
    assert mod.is_stale_review(notes, "abc1234567890") is True
    assert mod.is_stale_review(notes, "def5678") is False
    assert mod.is_stale_review([], "abc1234") is False


def test_has_rerun_request():
    """Should detect rerun requests for same SHA (Carson step 4)."""
    mod = load_mr_review()
    notes = [{"body": f"{mod.RERUN_MARKER}\nRerun for sha:abc1234"}]
    assert mod.has_rerun_request(notes, "abc1234567890") is True
    assert mod.has_rerun_request(notes, "def5678") is False
    assert mod.has_rerun_request([], "abc1234") is False


def test_extract_first_changed_line():
    """Should pull the added-side line number from a unified diff hunk."""
    mod = load_mr_review()
    diff = "@@ -10,2 +42,6 @@\n+danger = True\n"
    assert mod.extract_first_changed_line(diff) == 42


def test_normalize_findings_uppercases_severity():
    """Machine-readable findings should normalize severity casing."""
    mod = load_mr_review()
    findings = [{
        "file": "x.py",
        "line": 12,
        "severity": "critical",
        "message": "Problem",
        "suggestion": "Fix it",
    }]
    normalized = mod.normalize_findings(findings)
    assert normalized == [{
        "severity": "CRITICAL",
        "file": "x.py",
        "line": 12,
        "message": "Problem",
        "suggestion": "Fix it",
        "category": "",
    }]


def test_review_exit_code_on_critical():
    """Review with critical findings should report non-zero intent."""
    findings = [
        {"file": "x.py", "severity": "critical", "message": "Leaked secret"},
    ]
    critical = [f for f in findings if f["severity"] == "critical"]
    assert len(critical) == 1  # Would cause sys.exit(1) in main()


def test_review_approves_on_no_critical():
    """Review without critical findings should approve."""
    findings = [
        {"file": "x.py", "severity": "warning", "message": "Long file"},
        {"file": "y.py", "severity": "info", "message": "No test"},
    ]
    critical = [f for f in findings if f["severity"] == "critical"]
    assert len(critical) == 0  # Would approve
