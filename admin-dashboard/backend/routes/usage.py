"""Usage telemetry route — session stats, token consumption, rate limits."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["usage"])

SESSIONS_FILE = Path(
    os.environ.get("OPENCLAW_SESSIONS_FILE", str(Path.home() / ".openclaw/agents/main/sessions/sessions.json"))
)

CHANNEL_LABELS: dict[str, str] = {
    "1473042410614292746": "general",
    "1473073236253212804": "nhl-betting",
    "1473074661016338545": "real-estate",
    "1473074662312513597": "polymarket",
    "1473074663356629078": "admin-dashboard",
}


def _friendly_label(raw: str) -> str:
    m = re.search(r"discord:\d+#(.+)$", raw)
    if m:
        return f"#{m.group(1)}"
    m2 = re.search(r"<#(\d+)>", raw)
    if m2 and m2.group(1) in CHANNEL_LABELS:
        return f"#{CHANNEL_LABELS[m2.group(1)]}"
    m3 = re.search(r"Guild #(\S+)", raw)
    if m3:
        return f"#{m3.group(1)}"
    return raw


def _format_iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_timestamp_ms(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        if value >= 1_000_000_000_000:
            return int(value)
        if value >= 1_000_000_000:
            return int(value * 1000)
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.isdigit():
            return _parse_timestamp_ms(int(raw))
        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    return None


def _iter_fields(obj: object, prefix: str = ""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield (path, value)
            yield from _iter_fields(value, path)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            path = f"{prefix}[{i}]"
            yield (path, value)
            yield from _iter_fields(value, path)


def _detect_claude_rate_limit(sessions: list[dict], now: datetime) -> dict:
    now_ms = int(now.timestamp() * 1000)
    claude_sessions = [
        s for s in sessions
        if "claude" in str(s.get("model", "")).lower()
        or str(s.get("model_provider", "")).lower() == "anthropic"
    ]
    if not claude_sessions:
        return {"status": "unknown", "reset_at": None, "seconds_until_reset": None,
                "reason": "No Claude sessions found.", "source": "none"}

    timestamp_candidates: list[tuple[int, str]] = []
    for session in claude_sessions:
        raw_meta = session.get("raw_session")
        if not isinstance(raw_meta, dict):
            continue
        for path, value in _iter_fields(raw_meta):
            if not re.search(r"(rate|limit|reset|throttle|cooldown|retry)", path.lower()):
                continue
            parsed_ms = _parse_timestamp_ms(value)
            if parsed_ms:
                timestamp_candidates.append((parsed_ms, path))

    if not timestamp_candidates:
        return {"status": "unknown", "reset_at": None, "seconds_until_reset": None,
                "reason": "No reset timestamp in session metadata.", "source": "session_metadata"}

    future = [c for c in timestamp_candidates if c[0] > now_ms]
    chosen_ms, chosen_path = (
        min(future, key=lambda c: c[0]) if future
        else max(timestamp_candidates, key=lambda c: c[0])
    )
    seconds_until = max(int((chosen_ms - now_ms) / 1000), 0)
    return {
        "status": "limited" if chosen_ms > now_ms else "active",
        "reset_at": _format_iso(chosen_ms),
        "seconds_until_reset": seconds_until,
        "reason": None, "source": "session_metadata", "source_field": chosen_path,
    }


def _load_usage_sessions(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    empty = {
        "sessions": [], "totals": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "session_count": 0},
        "models": [], "claude_rate_limit": {"status": "unknown", "reset_at": None,
        "seconds_until_reset": None, "reason": "Session file not found.", "source": "none"},
        "windows": {}, "top_consumers": [],
        "trend": {"window_hours": 24, "bucket_minutes": 120, "buckets": []},
        "freshness": {"generated_at": now.isoformat(), "latest_session_update_at": None, "staleness_seconds": None},
    }
    if not SESSIONS_FILE.exists():
        return empty

    data = json.loads(SESSIONS_FILE.read_text())
    sessions = []
    for key, s in data.items():
        raw_label = s.get("displayName") or s.get("origin", {}).get("label", key)
        label = _friendly_label(raw_label)
        if label == "#vinder":
            continue

        updated_ms = _parse_timestamp_ms(s.get("updatedAt")) or _parse_timestamp_ms(s.get("updated_at")) or 0
        age_hours = None
        if updated_ms:
            delta = (now - datetime.fromtimestamp(updated_ms / 1000, tz=timezone.utc)).total_seconds()
            age_hours = max(delta / 3600, 0)

        model_name = str(s.get("model") or s.get("modelOverride") or s.get("providerModel") or "")
        sessions.append({
            "key": key, "label": label,
            "total_tokens": _safe_int(s.get("totalTokens")),
            "input_tokens": _safe_int(s.get("inputTokens")),
            "output_tokens": _safe_int(s.get("outputTokens")),
            "context_window": _safe_int(s.get("contextTokens")),
            "model": model_name, "model_provider": str(s.get("modelProvider", "") or ""),
            "updated_at": _format_iso(updated_ms), "updated_at_ms": updated_ms,
            "age_hours": age_hours, "raw_session": s,
        })

    totals = {
        "total_tokens": sum(s["total_tokens"] for s in sessions),
        "input_tokens": sum(s["input_tokens"] for s in sessions),
        "output_tokens": sum(s["output_tokens"] for s in sessions),
        "session_count": len(sessions),
    }

    for s in sessions:
        s["share_pct"] = round(s["total_tokens"] / totals["total_tokens"] * 100, 2) if totals["total_tokens"] else 0
        is_recent = s["age_hours"] is not None and s["age_hours"] <= 24
        s["burn_rate_24h_est"] = round(s["total_tokens"] / 24, 2) if is_recent else 0

    sessions.sort(key=lambda x: x["total_tokens"], reverse=True)

    windows: dict[str, dict] = {}
    for hours in (1, 24):
        cutoff = now.timestamp() * 1000 - hours * 3600 * 1000
        recent = [s for s in sessions if s["updated_at_ms"] and s["updated_at_ms"] >= cutoff]
        tokens = sum(s["total_tokens"] for s in recent)
        windows[f"last_{hours}h"] = {
            "hours": hours, "session_count": len(recent), "total_tokens": tokens,
            "input_tokens": sum(s["input_tokens"] for s in recent),
            "output_tokens": sum(s["output_tokens"] for s in recent),
            "burn_rate_tokens_per_hour": round(tokens / hours, 2),
        }

    top_consumers = [{
        "key": s["key"], "label": s["label"], "total_tokens": s["total_tokens"],
        "share_pct": s["share_pct"], "updated_at": s["updated_at"],
        "burn_rate_24h_est": s["burn_rate_24h_est"],
    } for s in sessions[:10]]

    model_rollup: dict[str, dict] = {}
    for session in sessions:
        mn = session["model"] or "(unknown)"
        bucket = model_rollup.setdefault(mn, {
            "model": mn, "total_tokens": 0, "input_tokens": 0, "output_tokens": 0,
            "session_count": 0, "top_sessions": [],
        })
        bucket["total_tokens"] += session["total_tokens"]
        bucket["input_tokens"] += session["input_tokens"]
        bucket["output_tokens"] += session["output_tokens"]
        bucket["session_count"] += 1
        bucket["top_sessions"].append({
            "key": session["key"], "label": session["label"],
            "total_tokens": session["total_tokens"], "updated_at": session["updated_at"],
        })

    models = list(model_rollup.values())
    for model in models:
        top = sorted(model["top_sessions"], key=lambda i: i["total_tokens"], reverse=True)[:3]
        for ts in top:
            ts["share_within_model_pct"] = round(
                ts["total_tokens"] / model["total_tokens"] * 100, 2
            ) if model["total_tokens"] else 0
        model["top_sessions"] = top
    models.sort(key=lambda m: m["total_tokens"], reverse=True)

    claude_rate_limit = _detect_claude_rate_limit(sessions, now)

    bucket_minutes = 120
    bucket_ms = bucket_minutes * 60 * 1000
    start_ms = int(now.timestamp() * 1000) - 24 * 3600 * 1000
    buckets = []
    for i in range(12):
        b_start = start_ms + i * bucket_ms
        b_end = b_start + bucket_ms
        bs = [s for s in sessions if s["updated_at_ms"] and b_start <= s["updated_at_ms"] < b_end]
        buckets.append({
            "start": _format_iso(b_start), "end": _format_iso(b_end),
            "session_count": len(bs), "total_tokens": sum(s["total_tokens"] for s in bs),
        })

    latest_ms = max((s["updated_at_ms"] for s in sessions if s["updated_at_ms"]), default=None)
    staleness = max(int(now.timestamp() - latest_ms / 1000), 0) if latest_ms else None

    for s in sessions:
        s.pop("updated_at_ms", None)
        s.pop("raw_session", None)

    return {
        "sessions": sessions, "totals": totals, "models": models,
        "claude_rate_limit": claude_rate_limit, "windows": windows,
        "top_consumers": top_consumers,
        "trend": {"window_hours": 24, "bucket_minutes": bucket_minutes, "buckets": buckets},
        "freshness": {
            "generated_at": now.isoformat(),
            "latest_session_update_at": _format_iso(latest_ms),
            "staleness_seconds": staleness,
        },
    }


@router.get("/usage")
async def usage():
    return _load_usage_sessions()
