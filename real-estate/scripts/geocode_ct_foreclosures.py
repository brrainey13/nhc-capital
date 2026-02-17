#!/usr/bin/env python3
"""
Batch geocode ct_foreclosures addresses using Nominatim (OpenStreetMap).
Free, no API key. Rate limit: 1 req/sec.
"""
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.db import get_connection

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def clean_address(address: str, town: str) -> str:
    """Clean address for geocoding — strip unit/apt info, normalize."""
    addr = address.strip()
    # Remove AKA portions
    addr = re.split(r'\bA/?K/?A\b', addr, flags=re.IGNORECASE)[0].strip()
    # Remove unit/apt/building info that confuses geocoders
    addr = re.sub(r',?\s*(Unit|Apt|Building|Bldg|#)\s*[^,]*', '', addr, flags=re.IGNORECASE)
    # Remove parenthetical notes
    addr = re.sub(r'\([^)]*\)', '', addr)
    # Remove leading # numbers like "#6 283 Broad Street"
    addr = re.sub(r'^#\d+\s+', '', addr)
    # Normalize multi-address (take first): "176-178 FRENCH STREET" -> keep as is (geocoders handle this)
    # Ensure CT is present
    if not re.search(r'\bCT\b|\bConnecticut\b', addr, re.IGNORECASE):
        addr = f"{addr}, {town}, CT"
    # Normalize whitespace
    addr = re.sub(r'\s+', ' ', addr).strip().rstrip('.')
    return addr


def _geocode_nominatim(address: str) -> tuple:
    """Geocode via Nominatim. Returns (lat, lng) or (None, None)."""
    encoded = quote(address)
    url = f"{NOMINATIM_URL}?q={encoded}&format=json&limit=1&countrycodes=us"
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "10",
             "-H", "User-Agent: NHCCapital/1.0 (real-estate-research)",
             url],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        if data and len(data) > 0:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"    Nominatim error: {e}", flush=True)
    return None, None


PHOTON_URL = "https://photon.komoot.io/api/"


def _geocode_photon(address: str) -> tuple:
    """Fallback geocoder via Photon (Komoot). Returns (lat, lng) or (None, None)."""
    encoded = quote(address)
    url = f"{PHOTON_URL}?q={encoded}&limit=1&lat=41.5&lon=-72.7"
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "10",
             "-H", "User-Agent: NHCCapital/1.0 (real-estate-research)",
             url],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        feats = data.get("features", [])
        if feats:
            coords = feats[0]["geometry"]["coordinates"]  # [lon, lat]
            state = feats[0].get("properties", {}).get("state", "")
            if "Connecticut" in state or abs(coords[1] - 41.5) < 2:
                return coords[1], coords[0]
    except Exception as e:
        print(f"    Photon error: {e}", flush=True)
    return None, None


def geocode_address(address: str) -> tuple:
    """Geocode via Nominatim, fall back to Photon. Returns (lat, lng) or (None, None)."""
    lat, lng = _geocode_nominatim(address)
    if lat is not None:
        return lat, lng
    time.sleep(0.5)
    lat, lng = _geocode_photon(address)
    return lat, lng


def main():
    print("=== Geocoding CT Foreclosures (Nominatim) ===", flush=True)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, address, town FROM ct_foreclosures "
                "WHERE lat IS NULL AND address IS NOT NULL ORDER BY id"
            )
            rows = cur.fetchall()

    print(f"Found {len(rows)} addresses to geocode", flush=True)
    success = 0
    failed = 0
    failed_list = []

    for row_id, address, town in rows:
        clean = clean_address(address, town)
        lat, lng = geocode_address(clean)

        if lat and lng:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE ct_foreclosures SET lat=%s, lng=%s WHERE id=%s",
                        (lat, lng, row_id)
                    )
                conn.commit()
            success += 1
            print(f"  ✓ {clean[:60]} → ({lat:.4f}, {lng:.4f})", flush=True)
        else:
            failed += 1
            failed_list.append(clean)
            print(f"  ✗ {clean[:60]}", flush=True)

        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

    print(f"\n=== DONE === Geocoded: {success} | Failed: {failed}", flush=True)
    if failed_list:
        print("\nFailed addresses:", flush=True)
        for a in failed_list:
            print(f"  - {a}", flush=True)


if __name__ == "__main__":
    main()
