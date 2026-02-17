#!/usr/bin/env python3
"""
ETL: Parcel Sales from SODA API (wvhk-k5uv) into PostgreSQL.
Schema: schema/cook_county.md — parcel_sales.
"""

import os
import sys
import time
import json
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.db import get_connection, ensure_schema, log_refresh

BASE = "https://datacatalog.cookcountyil.gov/resource"
DATASET_ID = "wvhk-k5uv"
COLS = [
    "row_id", "pin", "year", "township_code", "nbhd", "class", "sale_date",
    "is_mydec_date", "sale_price", "doc_no", "deed_type", "mydec_deed_type",
    "seller_name", "buyer_name", "is_multisale", "num_parcels_sale", "sale_type",
    "sale_filter_same_sale_within_365", "sale_filter_less_than_10k", "sale_filter_deed_type",
]


def fetch_batch(limit: int = 50000, where: str = None, offset: int = 0) -> list:
    token = os.environ.get("SODA_APP_TOKEN", "")
    headers = {"X-App-Token": token} if token else {}
    params = {"$limit": limit, "$offset": offset, "$order": "sale_date DESC"}
    if where:
        params["$where"] = where
    r = requests.get(f"{BASE}/{DATASET_ID}.json", headers=headers, params=params, timeout=300)
    r.raise_for_status()
    return r.json()


def run(limit: int = None, where: str = None, dry_run: bool = False) -> dict:
    start = time.perf_counter()
    fetched = 0
    inserted = 0

    if dry_run:
        data = fetch_batch(limit=limit or 100, where=where)
        fetched = len(data)
        print(f"[dry run] Would upsert {fetched} rows into parcel_sales")
        return {"rows_fetched": fetched, "rows_inserted": 0, "duration_sec": 0, "data": data}

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
                    INSERT INTO parcel_sales ({cols_sql})
                    VALUES %s
                    ON CONFLICT (row_id) DO UPDATE SET
                        pin = EXCLUDED.pin, year = EXCLUDED.year, township_code = EXCLUDED.township_code,
                        nbhd = EXCLUDED.nbhd, class = EXCLUDED.class, sale_date = EXCLUDED.sale_date,
                        is_mydec_date = EXCLUDED.is_mydec_date, sale_price = EXCLUDED.sale_price,
                        doc_no = EXCLUDED.doc_no, deed_type = EXCLUDED.deed_type, mydec_deed_type = EXCLUDED.mydec_deed_type,
                        seller_name = EXCLUDED.seller_name, buyer_name = EXCLUDED.buyer_name,
                        is_multisale = EXCLUDED.is_multisale, num_parcels_sale = EXCLUDED.num_parcels_sale,
                        sale_type = EXCLUDED.sale_type,
                        sale_filter_same_sale_within_365 = EXCLUDED.sale_filter_same_sale_within_365,
                        sale_filter_less_than_10k = EXCLUDED.sale_filter_less_than_10k,
                        sale_filter_deed_type = EXCLUDED.sale_filter_deed_type,
                        raw_json = EXCLUDED.raw_json
                    """,
                    rows,
                    page_size=1000,
                )
                inserted += cur.rowcount
            if len(data) < batch_size:
                break
            offset += len(data)

    duration = time.perf_counter() - start
    return {"rows_fetched": fetched, "rows_inserted": inserted, "duration_sec": duration}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ETL Parcel Sales → PostgreSQL")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--where", type=str, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    stats = run(limit=args.limit, where=args.where, dry_run=args.dry_run)
    if not args.dry_run and stats.get("rows_fetched"):
        with get_connection() as conn:
            log_refresh(
                conn, "parcel_sales", "full",
                stats["rows_fetched"], stats.get("rows_inserted", 0), 0,
                stats.get("duration_sec", 0), "success",
            )
    print("Done:", stats)
