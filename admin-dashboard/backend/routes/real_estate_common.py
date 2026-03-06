"""Shared helpers for real-estate dashboard routes."""


def normalize_town(town: str | None) -> str | None:
    if not town:
        return None
    normalized = town.strip()
    if normalized.lower().endswith("ct"):
        return normalized
    return f"{normalized}CT"
