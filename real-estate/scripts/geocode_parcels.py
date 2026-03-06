#!/usr/bin/env python3
"""
Batch geocode ct_vision_parcels using Photon (free, OSM-based).

Usage:
    python geocode_parcels.py [--town StamfordCT] [--delay 0.1] [--batch-size 500] [--limit 10000]
    python geocode_parcels.py --all [--delay 0.1] [--workers 4]

Photon rate limit: ~1-2 req/sec for polite usage. No API key needed.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PHOTON_URL = "https://photon.komoot.io/api/"
UA = "NHC-Capital-Research/1.0 (property-geocoding)"


ABBREVS = {
    "RD": "ROAD", "ST": "STREET", "AVE": "AVENUE", "DR": "DRIVE",
    "LN": "LANE", "CT": "COURT", "PL": "PLACE", "CIR": "CIRCLE",
    "BLVD": "BOULEVARD", "HWY": "HIGHWAY", "PKWY": "PARKWAY",
    "TER": "TERRACE", "TPKE": "TURNPIKE", "EXT": "EXTENSION",
    "HL": "HILL", "HLS": "HILLS", "MTN": "MOUNTAIN", "PT": "POINT",
    "SQ": "SQUARE", "TRL": "TRAIL", "WAY": "WAY", "XING": "CROSSING",
}


def _expand_abbrevs(address: str) -> str:
    """Expand common street abbreviations for better geocoding."""
    parts = address.split()
    expanded = []
    for p in parts:
        up = p.upper().rstrip(".,")
        if up in ABBREVS:
            expanded.append(ABBREVS[up])
        else:
            expanded.append(p)
    return " ".join(expanded)


def _geocode_nominatim(query: str) -> tuple[float | None, float | None]:
    """Geocode via Nominatim (OSM official). 1 req/sec policy."""
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1&countrycodes=us"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
                # Rough CT bounding box check
                if 40.9 < lat < 42.1 and -73.8 < lon < -71.7:
                    return (lat, lon)
    except Exception:
        pass
    return (None, None)


def _geocode_photon(query: str) -> tuple[float | None, float | None]:
    """Geocode via Photon (Komoot). Faster, less strict rate limit."""
    url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(query)}&limit=1&lang=en"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("features"):
                feat = data["features"][0]
                coords = feat["geometry"]["coordinates"]
                props = feat.get("properties", {})
                state = props.get("state", "")
                if state and "connecticut" not in state.lower():
                    return (None, None)
                return (coords[1], coords[0])
    except Exception:
        pass
    return (None, None)


def _geocode_census(query: str) -> tuple[float | None, float | None]:
    """Geocode via US Census Bureau. Free, no key, fast, no documented rate limit."""
    url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address={urllib.parse.quote(query)}&benchmark=Public_AR_Current&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            matches = data.get("result", {}).get("addressMatches", [])
            if matches:
                c = matches[0]["coordinates"]
                lat, lon = float(c["y"]), float(c["x"])
                if 40.9 < lat < 42.1 and -73.8 < lon < -71.7:
                    return (lat, lon)
    except Exception:
        pass
    return (None, None)


def geocode(address: str, town: str, provider: str = "census") -> tuple[float | None, float | None]:
    """Geocode address. Provider: 'census', 'nominatim', 'photon', or 'auto'."""
    town_clean = town.replace("CT", "").strip()
    import re
    town_clean = re.sub(r'([a-z])([A-Z])', r'\1 \2', town_clean)
    address = _expand_abbrevs(address)
    query = f"{address}, {town_clean}, CT"

    if provider == "census":
        return _geocode_census(query)
    elif provider == "photon":
        return _geocode_photon(query)
    elif provider == "nominatim":
        return _geocode_nominatim(query)
    else:  # auto — census first, strip unit#, then photon fallback
        import re as _re
        clean_query = _re.sub(r'\s*#.*$', '', query)
        lat, lng = _geocode_census(clean_query)
        if lat is not None:
            return (lat, lng)
        return _geocode_photon(clean_query.replace(", CT", ", Connecticut"))


def get_ungeocode_parcels(town: str | None = None, limit: int = 10000) -> list[dict]:
    """Get parcels missing lat/lng."""
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_agent@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            if town:
                cur.execute("""
                    SELECT pid, town, address FROM ct_vision_parcels
                    WHERE lat IS NULL AND address IS NOT NULL AND address != ''
                    AND town = %s
                    ORDER BY pid LIMIT %s
                """, (town, limit))
            else:
                cur.execute("""
                    SELECT pid, town, address FROM ct_vision_parcels
                    WHERE lat IS NULL AND address IS NOT NULL AND address != ''
                    ORDER BY town, pid LIMIT %s
                """, (limit,))
            return [{"pid": r[0], "town": r[1], "address": r[2]} for r in cur.fetchall()]
    finally:
        conn.close()


def update_coords(pid: int, town: str, lat: float, lng: float):
    """Update lat/lng for a parcel."""
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_etl@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ct_vision_parcels SET lat = %s, lng = %s
                WHERE pid = %s AND town = %s AND lat IS NULL
            """, (lat, lng, pid, town))
        conn.commit()
    finally:
        conn.close()


def update_coords_batch(updates: list[tuple]):
    """Batch update lat/lng. Each tuple: (lat, lng, pid, town)."""
    if not updates:
        return
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_etl@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            for lat, lng, pid, town in updates:
                cur.execute("""
                    UPDATE ct_vision_parcels SET lat = %s, lng = %s
                    WHERE pid = %s AND town = %s AND lat IS NULL
                """, (lat, lng, pid, town))
        conn.commit()
    finally:
        conn.close()


def run(town: str | None = None, delay: float = 0.1, batch_size: int = 500,
        limit: int = 50000, dry_run: bool = False, provider: str = "nominatim") -> dict:
    """Geocode parcels missing coordinates."""
    parcels = get_ungeocode_parcels(town, limit)
    print(f"\n=== Geocoding {len(parcels)} parcels {'for ' + town if town else '(all towns)'} (provider={provider}) ===", flush=True)

    total_geocoded = 0
    total_failed = 0
    batch = []
    current_town = None

    for i, p in enumerate(parcels):
        if p["town"] != current_town:
            current_town = p["town"]
            print(f"\n  Town: {current_town}", flush=True)

        lat, lng = geocode(p["address"], p["town"], provider=provider)
        if lat is not None:
            batch.append((lat, lng, p["pid"], p["town"]))
            total_geocoded += 1
        else:
            total_failed += 1

        if len(batch) >= batch_size:
            if not dry_run:
                update_coords_batch(batch)
            print(f"  [{i+1}/{len(parcels)}] geocoded={total_geocoded} failed={total_failed} (batch saved)", flush=True)
            batch = []

        time.sleep(delay)

    # Final batch
    if batch and not dry_run:
        update_coords_batch(batch)
        print(f"  Final batch: {len(batch)} updates saved", flush=True)

    result = {"parcels_processed": len(parcels), "geocoded": total_geocoded,
              "failed": total_failed, "town": town or "all"}
    print(f"\n  Done: {total_geocoded} geocoded, {total_failed} failed out of {len(parcels)}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch geocode parcels")
    parser.add_argument("--town", help="Single town (e.g. StamfordCT)")
    parser.add_argument("--all", action="store_true", help="All towns")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between requests (seconds)")
    parser.add_argument("--batch-size", type=int, default=500, help="DB batch size")
    parser.add_argument("--limit", type=int, default=50000, help="Max parcels to process")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    town = args.town if args.town else (None if args.all else None)
    if not args.town and not args.all:
        parser.print_help()
        sys.exit(1)

    result = run(town=town, delay=args.delay, batch_size=args.batch_size,
                 limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result))
