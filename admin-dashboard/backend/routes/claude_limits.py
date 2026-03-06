"""Claude cost/usage endpoint — codexbar CLI + optional Anthropic OAuth API.

Auth: All dashboard endpoints are protected by Cloudflare Access middleware (see backend/auth.py).
The auth check happens at the FastAPI app level, not per-route. Do not add redundant auth here.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["usage"])

_cache: dict = {"data": None, "fetched_at": 0.0}
CACHE_TTL = 300  # 5 minutes


def _try_oauth() -> dict | None:
    """Best-effort: try Anthropic OAuth usage API."""
    import urllib.error
    import urllib.request

    # Try to read token from common locations
    token = None
    import pathlib
    for candidate in [
        pathlib.Path.home() / ".claude" / ".credentials.json",
        pathlib.Path.home() / ".claude" / "credentials.json",
    ]:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text())
                token = data.get("access_token") or data.get("token") or data.get("oauth_token")
                if token:
                    break
            except Exception:
                pass

    # Try macOS keychain
    if not token:
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                blob = r.stdout.strip()
                try:
                    cred = json.loads(blob)
                    token = cred.get("access_token") or cred.get("token")
                except json.JSONDecodeError:
                    token = blob
        except Exception:
            pass

    if not token:
        return None

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _fetch_codexbar() -> dict:
    now = time.time()
    if _cache["data"] and (now - _cache["fetched_at"]) < CACHE_TTL:
        return _cache["data"]

    fetched_at = datetime.now(timezone.utc).isoformat()

    # 1. Codexbar cost data
    daily_costs: list[dict] = []
    total_cost = 0.0
    total_tokens = 0
    models: dict[str, dict] = {}
    codexbar_error = None

    try:
        result = subprocess.run(
            [os.environ.get("CODEXBAR_PATH", "codexbar"), "cost", "--provider", "claude", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        raw = json.loads(result.stdout)
        provider_data = None
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict) and entry.get("provider") == "claude":
                    provider_data = entry
                    break
            if not provider_data and raw:
                provider_data = raw[0]
        provider_data = provider_data or {}

        daily_usage = provider_data.get("daily") or provider_data.get("dailyUsage") or []

        for day in daily_usage[-7:]:
            cost = day.get("totalCost", 0) or 0
            tokens = day.get("totalTokens", 0) or 0
            daily_costs.append({
                "date": day.get("date"),
                "cost": round(cost, 4),
                "tokens": tokens,
            })
            total_cost += cost
            total_tokens += tokens
            for mb in day.get("modelBreakdowns", []):
                name = mb.get("modelName", "unknown")
                bucket = models.setdefault(name, {"tokens": 0, "cost": 0.0})
                bucket["cost"] += mb.get("cost", 0) or 0
                # model-level tokens not always present; skip if missing
                bucket["tokens"] += mb.get("tokens", 0) or mb.get("totalTokens", 0) or 0

        for v in models.values():
            v["cost"] = round(v["cost"], 4)

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError) as exc:
        codexbar_error = str(exc)

    # 2. OAuth usage (best-effort)
    oauth = _try_oauth()

    payload: dict = {
        "daily_costs": daily_costs,
        "total_cost_7d": round(total_cost, 2),
        "total_tokens_7d": total_tokens,
        "models_7d": models,
        "fetched_at": fetched_at,
    }
    if codexbar_error:
        payload["error"] = codexbar_error
    if oauth:
        payload["oauth"] = oauth

    _cache["data"] = payload
    _cache["fetched_at"] = now
    return payload


@router.get("/usage/claude-limits")
async def claude_limits():
    return _fetch_codexbar()
