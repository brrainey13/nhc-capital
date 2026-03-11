#!/usr/bin/env python3
"""
Ingest CT Open Data real estate sales into ct_vision_parcels + ct_vision_sales.

Source: data.ct.gov dataset 5mzw-sjtu (Real Estate Sales)
API: Socrata Open Data API (SODA), no key required, 50K limit per request.

Creates minimal parcel records (address, town, lat, lng) and linked sales records
for towns not covered by VGSI or PRC scrapers. The comps engine already handles
missing sqft (skips size filter) so radius-based comps work immediately.

Usage:
    python ingest_ct_opendata_sales.py [--towns Greenwich,Darien,...] [--dry-run]
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import psycopg2
import psycopg2.extras

# All 12 missing Fairfield towns
DEFAULT_TOWNS = [
    "Bethel", "Danbury", "Darien", "Easton", "Greenwich",
    "New Canaan", "Norwalk", "Ridgefield", "Shelton", "Sherman",
    "Weston", "Wilton",
]

SODA_BASE = "https://data.ct.gov/resource/5mzw-sjtu.json"
PAGE_SIZE = 50000  # max SODA allows
DELAY = 0.5  # seconds between API calls

# Map CT Open Data property types to use_code / use_desc for comps compatibility
PROPERTY_TYPE_MAP = {
    "Single Family": ("101", "SINGLE FAMILY"),
    "Two Family": ("102", "TWO FAMILY"),
    "Three Family": ("103", "THREE FAMILY"),
    "Four Family": ("104", "FOUR FAMILY"),
    "Condo": ("295", "CONDO"),
    "Apartments": ("800", "APARTMENTS"),
    "Commercial": ("200", "COMMERCIAL"),
    "Industrial": ("300", "INDUSTRIAL"),
    "Vacant Land": ("900", "VACANT LAND"),
}


def normalize_town_key(town_name: str) -> str:
    """Convert 'New Canaan' -> 'NewCanaanCT' to match ct_vision_parcels format."""
    return town_name.strip().replace(" ", "") + "CT"


def make_pid(town_key: str, address: str, serial: str) -> int:
    """Generate a deterministic PID from town + address + serial number.
    Must fit in PostgreSQL integer (max 2,147,483,647).
    """
    key = f"{town_key}:{address}:{serial}"
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % 2_000_000_000


def normalize_address(addr: str) -> str:
    """Normalize address format: 'ORCHARD STREET 0300' -> '300 ORCHARD STREET'."""
    if not addr:
        return ""
    addr = addr.strip().upper()
    # Pattern: "STREET NAME NUMBER" -> "NUMBER STREET NAME"
    match = re.match(r"^(.+?)\s+0*(\d+)$", addr)
    if match:
        return f"{match.group(2)} {match.group(1)}"
    return addr


def fetch_sales(town: str, offset: int = 0) -> list[dict]:
    """Fetch a page of sales from CT Open Data SODA API."""
    params = urllib.parse.urlencode({
        "$where": f"town='{town}'",
        "$limit": PAGE_SIZE,
        "$offset": offset,
        "$order": "daterecorded DESC",
    })
    url = f"{SODA_BASE}?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_all_sales(town: str) -> list[dict]:
    """Fetch all sales for a town, paginating as needed."""
    all_sales = []
    offset = 0
    while True:
        page = fetch_sales(town, offset)
        if not page:
            break
        all_sales.extend(page)
        print(f"  Fetched {len(all_sales)} sales so far...", flush=True)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(DELAY)
    return all_sales


def get_existing_parcels(conn, town_key: str) -> dict[str, int]:
    """Get existing parcels for a town: address -> pid."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pid, address FROM ct_vision_parcels WHERE town = %s",
            (town_key,),
        )
        return {row[1].upper(): row[0] for row in cur.fetchall() if row[1]}


def get_existing_sales(conn, town_key: str) -> set[tuple]:
    """Get existing sales for dedup: (pid, sale_date, sale_price)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pid, sale_date, sale_price FROM ct_vision_sales WHERE town = %s",
            (town_key,),
        )
        return {(str(row[0]), str(row[1]), str(row[2])) for row in cur.fetchall()}


def ingest_town(conn, town: str, dry_run: bool = False) -> dict:
    """Ingest all sales for a town from CT Open Data."""
    town_key = normalize_town_key(town)
    print(f"\n{'='*60}", flush=True)
    print(f"Processing {town} -> {town_key}", flush=True)

    # Fetch all sales
    sales = fetch_all_sales(town)
    print(f"  Total sales from API: {len(sales)}", flush=True)

    if not sales:
        return {"town": town, "fetched": 0, "parcels_created": 0, "sales_inserted": 0}

    # Get existing data for dedup
    existing_parcels = get_existing_parcels(conn, town_key)
    existing_sales = get_existing_sales(conn, town_key)
    print(f"  Existing parcels: {len(existing_parcels)}, existing sales: {len(existing_sales)}", flush=True)

    # Group sales by normalized address to create parcels
    address_groups = defaultdict(list)
    for sale in sales:
        addr = normalize_address(sale.get("address", ""))
        if addr:
            address_groups[addr].append(sale)

    parcels_created = 0
    sales_inserted = 0
    sales_skipped = 0
    errors = 0

    for addr, addr_sales in address_groups.items():
        # Find or create parcel
        pid = existing_parcels.get(addr)

        if pid is None:
            # Create minimal parcel record
            # Use first sale with geo_coordinates for lat/lng
            lat, lng = None, None
            for s in addr_sales:
                geo = s.get("geo_coordinates")
                if geo and geo.get("coordinates"):
                    coords = geo["coordinates"]
                    lng, lat = float(coords[0]), float(coords[1])
                    # Validate CT bounding box
                    if not (40.9 <= lat <= 42.1 and -73.8 <= lng <= -71.7):
                        lat, lng = None, None
                    else:
                        break

            # Get property type info from first sale
            res_type = addr_sales[0].get("residentialtype", "")
            prop_type = addr_sales[0].get("propertytype", "")
            use_code, use_desc = PROPERTY_TYPE_MAP.get(
                res_type, PROPERTY_TYPE_MAP.get(prop_type, ("999", "UNKNOWN"))
            )

            # Generate PID
            serial = addr_sales[0].get("serialnumber", "0")
            pid = make_pid(town_key, addr, serial)

            if not dry_run:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO ct_vision_parcels
                                (town, pid, address, use_code, use_desc, lat, lng)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (town, pid) DO UPDATE SET
                                lat = COALESCE(EXCLUDED.lat, ct_vision_parcels.lat),
                                lng = COALESCE(EXCLUDED.lng, ct_vision_parcels.lng)
                        """, (town_key, pid, addr, use_code, use_desc, lat, lng))
                    conn.commit()
                    parcels_created += 1
                except Exception as e:
                    conn.rollback()
                    errors += 1
                    if errors <= 5:
                        print(f"  ERROR creating parcel {addr}: {e}", flush=True)
                    continue
            else:
                parcels_created += 1

            existing_parcels[addr] = pid

        # Insert sales for this parcel
        for sale in addr_sales:
            sale_date = sale.get("daterecorded", "")
            if sale_date:
                sale_date = sale_date[:10]  # "2024-09-30T00:00:00.000" -> "2024-09-30"

            sale_price = sale.get("saleamount")
            if not sale_price:
                continue
            try:
                sale_price = float(sale_price)
            except (ValueError, TypeError):
                continue

            # Dedup check
            dedup_key = (str(pid), sale_date, str(sale_price))
            if dedup_key in existing_sales:
                sales_skipped += 1
                continue

            if not dry_run:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO ct_vision_sales
                                (town, pid, sale_date, sale_price)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (town_key, pid, sale_date, sale_price))
                    conn.commit()
                    sales_inserted += 1
                    existing_sales.add(dedup_key)
                except Exception as e:
                    conn.rollback()
                    errors += 1
                    if errors <= 5:
                        print(f"  ERROR inserting sale for {addr}: {e}", flush=True)
            else:
                sales_inserted += 1

    stats = {
        "town": town,
        "town_key": town_key,
        "fetched": len(sales),
        "parcels_created": parcels_created,
        "sales_inserted": sales_inserted,
        "sales_skipped": sales_skipped,
        "errors": errors,
    }
    print(f"  Results: {parcels_created} new parcels, {sales_inserted} new sales, "
          f"{sales_skipped} skipped (existing), {errors} errors", flush=True)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Ingest CT Open Data sales")
    parser.add_argument("--towns", default=",".join(DEFAULT_TOWNS),
                        help="Comma-separated town names")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    towns = [t.strip() for t in args.towns.split(",") if t.strip()]

    conn = psycopg2.connect(
        dbname="real_estate",
        user="nhc_etl",
        password="nhc_etl_pass",
        host="localhost",
        port=5432,
    )

    print("=== CT Open Data Sales Ingester ===", flush=True)
    print(f"Towns: {', '.join(towns)}", flush=True)
    if args.dry_run:
        print("*** DRY RUN — no database writes ***", flush=True)

    all_stats = []
    for town in towns:
        try:
            stats = ingest_town(conn, town, dry_run=args.dry_run)
            all_stats.append(stats)
        except Exception as e:
            print(f"\n  FATAL ERROR for {town}: {e}", flush=True)
            all_stats.append({"town": town, "error": str(e)})

    # Summary
    print(f"\n{'='*60}", flush=True)
    print("=== SUMMARY ===", flush=True)
    total_parcels = sum(s.get("parcels_created", 0) for s in all_stats)
    total_sales = sum(s.get("sales_inserted", 0) for s in all_stats)
    total_fetched = sum(s.get("fetched", 0) for s in all_stats)
    total_errors = sum(s.get("errors", 0) for s in all_stats)
    print(f"  Fetched: {total_fetched} sales from API", flush=True)
    print(f"  Created: {total_parcels} new parcels", flush=True)
    print(f"  Inserted: {total_sales} new sales", flush=True)
    print(f"  Errors: {total_errors}", flush=True)

    conn.close()


if __name__ == "__main__":
    main()
