#!/usr/bin/env python3
"""
Run Cook County ETL: parcel_universe (API), parcel_sales (API), commercial_valuations (CSV).
Schema: schema/cook_county.md. DB: set PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD.
API: set SODA_APP_TOKEN for parcel_universe and parcel_sales.

Usage:
  python scripts/run_etl.py --dataset parcel_universe [--limit 1000] [--dry-run]
  python scripts/run_etl.py --dataset parcel_sales [--limit 1000] [--dry-run]
  python scripts/run_etl.py --dataset commercial_valuations [--csv-path path/to/file.csv] [--dry-run]
  python scripts/run_etl.py --dataset all [--dry-run]
"""

import argparse
import os
import sys

# Project root = parent of scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    p = argparse.ArgumentParser(description="Cook County ETL → PostgreSQL")
    p.add_argument("--dataset", choices=["parcel_universe", "parcel_sales", "commercial_valuations", "all"],
                   default="all", help="Which dataset to load")
    p.add_argument("--limit", type=int, default=None, help="Max rows (API datasets only)")
    p.add_argument("--where", type=str, default=None, help="SoQL $where (API only)")
    p.add_argument("--csv-path", type=str, default=None, help="Commercial CSV path (commercial_valuations only)")
    p.add_argument("--dry-run", action="store_true", help="Fetch/read only, do not write to DB")
    args = p.parse_args()

    datasets = ["parcel_universe", "parcel_sales", "commercial_valuations"] if args.dataset == "all" else [args.dataset]

    for name in datasets:
        print(f"\n--- ETL: {name} ---")
        if name == "parcel_universe":
            from scripts.etl_parcel_universe import run
            stats = run(limit=args.limit, where=args.where, dry_run=args.dry_run)
        elif name == "parcel_sales":
            from scripts.etl_parcel_sales import run
            stats = run(limit=args.limit, where=args.where, dry_run=args.dry_run)
        else:
            from scripts.etl_commercial_valuations import run
            stats = run(csv_path=args.csv_path, dry_run=args.dry_run)
        stats_print = {k: v for k, v in stats.items() if k != "data"}
        print(f"  {name}: {stats_print}")
        if args.dry_run and "data" in stats:
            import pandas as pd

            df = pd.DataFrame(stats["data"]) if not hasattr(stats["data"], "to_string") else stats["data"]
            # Key columns for readable display (API returns 100+ cols; show subset)
            display_cols = {
                "parcel_universe": ["pin", "pin10", "year", "class", "township_name", "zip_code", "cook_municipality_name"],
                "parcel_sales": ["row_id", "pin", "year", "sale_date", "sale_price", "seller_name", "buyer_name", "deed_type"],
                "commercial_valuations": ["keypin", "year", "township", "address", "tot_units", "finalmarketvalue", "caprate", "property_type_use"],
            }
            cols = [c for c in display_cols.get(name, []) if c in df.columns]
            df_show = df[cols].head(3) if cols else df.head(3)

            pd.set_option("display.max_columns", 12)
            pd.set_option("display.width", 120)
            pd.set_option("display.max_colwidth", 30)
            print(f"\n--- {name} ---")
            print(f"  shape: {df.shape}")
            print("  sample (first 3 rows):\n")
            print(df_show.to_string(index=False))
        if not args.dry_run and stats.get("rows_fetched"):
            from utils.db import get_connection, log_refresh
            with get_connection() as conn:
                log_refresh(
                    conn, name, "full",
                    stats["rows_fetched"], stats.get("rows_inserted", 0), stats.get("rows_updated", 0),
                    stats.get("duration_sec", 0), "success",
                )
    print("\nDone.")


if __name__ == "__main__":
    main()
