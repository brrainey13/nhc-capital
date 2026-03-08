"""Tests for the remediation driver."""

import importlib.util
import types
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "remediate"


def load_remediate():
    """Load scripts/remediate as a module."""
    spec = importlib.util.spec_from_file_location("remediate", str(SCRIPT_PATH))
    if spec is None or spec.loader is None:
        mod = types.ModuleType("remediate")
        mod.__file__ = str(SCRIPT_PATH)
        code = SCRIPT_PATH.read_text()
        exec(compile(code, str(SCRIPT_PATH), "exec"), mod.__dict__)
        return mod
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_findings_from_review_comment():
    """Should extract critical findings and suggestions from review comment text."""
    mod = load_remediate()
    body = """<!-- nhc-review-agent -->
## 🤖 NHC Automated Code Review — `sha:abc1234`

### 🚨 Critical Issues

- **backend/auth.py**: SQL injection risk in user input
  - 💡 Use parameterized queries
"""
    findings = mod.parse_findings_from_review_comment(body)
    assert findings == [{
        "severity": "CRITICAL",
        "file": "backend/auth.py",
        "line": None,
        "message": "SQL injection risk in user input",
        "suggestion": "Use parameterized queries",
    }]


def test_count_attempts_filters_by_sha():
    """Attempt counting should be scoped to the current head SHA."""
    mod = load_remediate()
    comments = [
        {"body": "<!-- nhc-auto-remediation -->\n🔧 Auto-remediation attempt 1/3 for `sha:abc1234`"},
        {"body": "<!-- nhc-auto-remediation -->\n🔧 Auto-remediation attempt 2/3 for `sha:abc1234`"},
        {"body": "<!-- nhc-auto-remediation -->\n🔧 Auto-remediation attempt 1/3 for `sha:def5678`"},
    ]
    assert mod.count_attempts(comments, "abc1234567890") == 2
