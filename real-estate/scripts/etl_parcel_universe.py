#!/usr/bin/env python3
"""
ETL: Parcel Universe from SODA API (nj4t-kc8j) into PostgreSQL.
Schema: schema/cook_county.md — parcel_universe.
"""

import json
import os
import sys
import time

import requests

# Project root = parent of scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.db import ensure_schema, get_connection, log_refresh

BASE = "https://datacatalog.cookcountyil.gov/resource"
DATASET_ID = "nj4t-kc8j"
# Columns we persist as dedicated columns; everything else goes into raw_json.
COLS = [
    "pin", "pin10", "year", "class", "triad_name", "triad_code",
    "township_name", "township_code", "nbhd_code", "tax_code", "zip_code",
    "lon", "lat", "cook_municipality_name", "row_id",
]


def fetch_batch(limit: int = 50000, where: str = None, offset: int = 0) -> list:
    token = os.environ.get("SODA_APP_TOKEN", "")
    headers = {"X-App-Token": token} if token else {}
    params = {"$limit": limit, "$offset": offset, "$order": "pin"}
    if where:
        params["$where"] = where
    r = requests.get(f"{BASE}/{DATASET_ID}.json", headers=headers, params=params, timeout=300)
    r.raise_for_status()
    return r.json()


def run(limit: int = None, where: str = None, dry_run: bool = False) -> dict:
    """Fetch from API and upsert into parcel_universe. Returns stats."""
    start = time.perf_counter()
    fetched = 0
    inserted = 0
    updated = 0

    if dry_run:
        data = fetch_batch(limit=limit or 100, where=where)
        fetched = len(data)
        print(f"[dry run] Would upsert {fetched} rows into parcel_universe")
        return {"rows_fetched": fetched, "rows_inserted": 0, "rows_updated": 0, "data": data}

    with get_connection() as conn:
        ensure_schema(conn)
        offset = 0
        batch_size = 50000
        while True:
            data = fetch_batch(limit=batch_size, where=where, offset=offset)
            if not data:
                break
            fetched += len(data)
            rows = []
            for rec in data:
                row = [rec.get(c) for c in COLS]
                row.append(json.dumps(rec) if isinstance(rec, dict) else None)
                rows.append(tuple(row))
            cols_sql = ", ".join(COLS) + ", raw_json"
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    f"""
                    INSERT INTO parcel_universe ({cols_sql})
                    VALUES %s
                    ON CONFLICT (pin, year) DO UPDATE SET
                        pin10 = EXCLUDED.pin10, class = EXCLUDED.class,
                        triad_name = EXCLUDED.triad_name, triad_code = EXCLUDED.triad_code,
                        township_name = EXCLUDED.township_name, township_code = EXCLUDED.township_code,
                        nbhd_code = EXCLUDED.nbhd_code, tax_code = EXCLUDED.tax_code, zip_code = EXCLUDED.zip_code,
                        lon = EXCLUDED.lon, lat = EXCLUDED.lat, cook_municipality_name = EXCLUDED.cook_municipality_name,
                        row_id = EXCLUDED.row_id, raw_json = EXCLUDED.raw_json, updated_at = NOW()
                    """,
                    rows,
                    page_size=1000,
                )
                inserted += cur.rowcount
            if len(data) < batch_size:
                break
            offset += len(data)

    duration = time.perf_counter() - start
    return {"rows_fetched": fetched, "rows_inserted": inserted, "rows_updated": updated, "duration_sec": duration}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ETL Parcel Universe → PostgreSQL")
    p.add_argument("--limit", type=int, default=None, help="Max rows to fetch")
    p.add_argument("--where", type=str, default=None, help="SoQL $where clause")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    stats = run(limit=args.limit, where=args.where, dry_run=args.dry_run)
    if not args.dry_run and stats.get("rows_fetched"):
        with get_connection() as conn:
            log_refresh(
                conn, "parcel_universe", "full",
                stats["rows_fetched"], stats.get("rows_inserted", 0), stats.get("rows_updated", 0),
                stats.get("duration_sec", 0), "success",
            )
    print("Done:", stats)
