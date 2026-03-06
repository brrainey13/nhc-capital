#!/usr/bin/env python3
"""
Resumable ETL for parcel_universe 2025 only.
Picks up from the last loaded PIN so it survives restarts.
Run in a loop: while it exits 42, re-run it.
"""
import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests
from psycopg2.extras import execute_values
from utils.db import ensure_schema, get_connection  # noqa: E402

BASE = "https://datacatalog.cookcountyil.gov/resource/nj4t-kc8j.json"
TOKEN = os.environ.get("SODA_APP_TOKEN", "")
BATCH = 5000  # smaller batches = less memory

COLS = [
    "pin","pin10","year","class","triad_name","triad_code",
    "township_name","township_code","nbhd_code","tax_code","zip_code",
    "lon","lat","cook_municipality_name","row_id",
]

def get_last_pin():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(pin),'0') FROM parcel_universe WHERE year='2025'")
            return cur.fetchone()[0]

def fetch(offset, where):
    headers = {"X-App-Token": TOKEN} if TOKEN else {}
    params = {"$limit": BATCH, "$offset": offset, "$where": where, "$order": "pin"}
    r = requests.get(BASE, headers=headers, params=params, timeout=300)
    r.raise_for_status()
    return r.json()

def main():
    with get_connection() as conn:
        ensure_schema(conn)

    last_pin = get_last_pin()
    where = f"year = 2025 AND pin > '{last_pin}'"
    print(f"Resuming from pin > {last_pin}", flush=True)

    cols_sql = ", ".join(COLS) + ", raw_json"
    upsert_sql = f"""
        INSERT INTO parcel_universe ({cols_sql}) VALUES %s
        ON CONFLICT (pin, year) DO UPDATE SET
            pin10=EXCLUDED.pin10, class=EXCLUDED.class,
            triad_name=EXCLUDED.triad_name, triad_code=EXCLUDED.triad_code,
            township_name=EXCLUDED.township_name, township_code=EXCLUDED.township_code,
            nbhd_code=EXCLUDED.nbhd_code, tax_code=EXCLUDED.tax_code, zip_code=EXCLUDED.zip_code,
            lon=EXCLUDED.lon, lat=EXCLUDED.lat, cook_municipality_name=EXCLUDED.cook_municipality_name,
            row_id=EXCLUDED.row_id, raw_json=EXCLUDED.raw_json, updated_at=NOW()
    """

    total = 0
    offset = 0
    while True:
        data = fetch(offset, where)
        if not data:
            print(f"Done! Loaded {total} new rows this run.", flush=True)
            return 0
        rows = []
        for rec in data:
            row = [rec.get(c) for c in COLS]
            row.append(json.dumps(rec))
            rows.append(tuple(row))
        with get_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, upsert_sql, rows, page_size=1000)
        total += len(rows)
        print(f"  +{len(rows)} rows (run total: {total})", flush=True)
        if len(data) < BATCH:
            print(f"Done! Loaded {total} new rows this run.", flush=True)
            return 0
        offset += BATCH
        del data, rows

if __name__ == "__main__":
    sys.exit(main())
