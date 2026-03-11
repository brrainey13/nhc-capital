"""Shared helpers for real-estate dashboard routes."""


def normalize_town(town: str | None) -> str | None:
    """Normalize foreclosure town name to match ct_vision_parcels format.

    Parcels use concatenated format: 'WestHartfordCT', 'NewHavenCT'
    Foreclosures use spaced format: 'West Hartford', 'New Haven'
    """
    if not town:
        return None
    normalized = town.strip().replace(" ", "")
    if normalized.lower().endswith("ct"):
        return normalized
    return f"{normalized}CT"
