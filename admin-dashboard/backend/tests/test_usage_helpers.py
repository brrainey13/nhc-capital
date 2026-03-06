import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import routes.usage as usage_mod
from routes.usage import _load_usage_sessions


def test_load_usage_sessions_model_aggregation_and_claude_limit(tmp_path, monkeypatch):
    now = datetime(2026, 2, 17, 5, 0, tzinfo=timezone.utc)
    future_reset = now + timedelta(minutes=15)
    sample = {
        "one": {
            "displayName": "discord:1#general",
            "totalTokens": 2000, "inputTokens": 1000, "outputTokens": 1000,
            "contextTokens": 200000,
            "updatedAt": int((now - timedelta(minutes=5)).timestamp() * 1000),
            "model": "claude-opus-4-6", "modelProvider": "anthropic",
            "rateLimit": {"resetAt": future_reset.isoformat()},
        },
        "two": {
            "displayName": "discord:1#admin-dashboard",
            "totalTokens": 1500, "inputTokens": 1000, "outputTokens": 500,
            "contextTokens": 272000,
            "updatedAt": int((now - timedelta(hours=2)).timestamp() * 1000),
            "model": "gpt-5.3-codex", "modelProvider": "openai-codex",
        },
    }
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps(sample))
    monkeypatch.setattr(usage_mod, "SESSIONS_FILE", sessions_file)

    data = _load_usage_sessions(now=now)
    assert data["totals"]["total_tokens"] == 3500
    assert data["models"][0]["model"] == "claude-opus-4-6"
    assert data["models"][0]["session_count"] == 1
    assert data["models"][0]["top_sessions"][0]["label"] == "#general"
    assert data["claude_rate_limit"]["status"] == "limited"
    assert data["claude_rate_limit"]["reset_at"] is not None
    assert data["claude_rate_limit"]["seconds_until_reset"] == 900


def test_load_usage_sessions_claude_limit_unknown_without_reset(tmp_path, monkeypatch):
    now = datetime(2026, 2, 17, 5, 0, tzinfo=timezone.utc)
    sample = {
        "only": {
            "displayName": "discord:1#general",
            "totalTokens": 300, "inputTokens": 200, "outputTokens": 100,
            "updatedAt": int(now.timestamp() * 1000),
            "model": "claude-opus-4-6", "modelProvider": "anthropic",
        }
    }
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps(sample))
    monkeypatch.setattr(usage_mod, "SESSIONS_FILE", sessions_file)

    data = _load_usage_sessions(now=now)
    assert data["claude_rate_limit"]["status"] == "unknown"
    assert data["claude_rate_limit"]["reset_at"] is None
    reason = data["claude_rate_limit"]["reason"].lower()
    assert "unavailable" in reason or "no reset" in reason
