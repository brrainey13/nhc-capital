"""Tests for the risk classifier."""

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CLASSIFIER = REPO_ROOT / "scripts" / "risk-classifier"


def test_risk_policy_json_exists():
    """risk-policy.json must exist and be valid JSON."""
    policy_file = REPO_ROOT / "risk-policy.json"
    assert policy_file.exists(), "risk-policy.json missing from repo root"
    policy = json.loads(policy_file.read_text())
    assert "version" in policy
    assert "riskTierRules" in policy
    assert "mergePolicy" in policy


def test_risk_policy_tiers_have_required_checks():
    """Every tier in mergePolicy must have requiredChecks."""
    policy = json.loads((REPO_ROOT / "risk-policy.json").read_text())
    for tier in ["high", "medium", "low"]:
        assert tier in policy["mergePolicy"], f"Missing tier: {tier}"
        assert "requiredChecks" in policy["mergePolicy"][tier], f"Missing requiredChecks for {tier}"
        assert len(policy["mergePolicy"][tier]["requiredChecks"]) > 0, f"Empty requiredChecks for {tier}"


def test_risk_policy_gate_always_required():
    """risk-policy-gate must be required for ALL tiers."""
    policy = json.loads((REPO_ROOT / "risk-policy.json").read_text())
    for tier in ["high", "medium", "low"]:
        checks = policy["mergePolicy"][tier]["requiredChecks"]
        assert "risk-policy-gate" in checks, f"risk-policy-gate missing from {tier} tier"


def test_classifier_classifies_high_risk():
    """Dashboard and workflow files should be classified as high risk."""
    result = subprocess.run(
        ["python3", str(CLASSIFIER), "admin-dashboard/backend/main.py", ".github/workflows/ci.yml"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    output = json.loads(result.stdout.strip().split("\n")[0])
    assert output["tier"] == "high"


def test_classifier_classifies_medium_risk():
    """Pipeline files should be classified as medium risk."""
    result = subprocess.run(
        ["python3", str(CLASSIFIER), "nhl-betting/pipeline/daily_picks.py"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    output = json.loads(result.stdout.strip().split("\n")[0])
    assert output["tier"] == "medium"


def test_classifier_classifies_low_risk():
    """Markdown files should be classified as low risk."""
    result = subprocess.run(
        ["python3", str(CLASSIFIER), "docs/admin-dashboard.md", "README.md"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    output = json.loads(result.stdout.strip().split("\n")[0])
    assert output["tier"] == "low"


def test_classifier_detects_schema_changes():
    """Schema-protected patterns should trigger warnings."""
    result = subprocess.run(
        ["python3", str(CLASSIFIER), "nhl-betting/sql/migrations/001.sql"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    output = json.loads(result.stdout.strip().split("\n")[0])
    assert len(output.get("schemaWarnings", [])) > 0
