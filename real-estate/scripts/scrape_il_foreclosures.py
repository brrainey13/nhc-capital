#!/usr/bin/env python3
"""
Unified IL Foreclosure Scraper — runs all three sources:
  1. TJSC (tjsc.com) — upcoming, completed, cancelled sales
  2. Intercounty Judicial Sales — IJSC + sheriff sales
  3. Auction.com sitemaps — REO + foreclosure listings

All data goes to il_foreclosures table (separate from CT).
Dedup: (source, case_number) unique constraint.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Import scrapers
sys.path.insert(0, SCRIPT_DIR)

from scrape_auction_com import main as run_auction_com
from scrape_intercounty import main as run_intercounty
from scrape_tjsc import main as run_tjsc


def main():
    print("=" * 60, flush=True)
    print("IL FORECLOSURE SCRAPER — ALL SOURCES", flush=True)
    print("=" * 60, flush=True)

    start = time.time()

    # 1. TJSC
    print("\n[1/3] TJSC...", flush=True)
    try:
        run_tjsc()
    except Exception as e:
        print(f"TJSC ERROR: {e}", flush=True)

    # 2. Intercounty
    print("\n[2/3] Intercounty...", flush=True)
    try:
        run_intercounty()
    except Exception as e:
        print(f"Intercounty ERROR: {e}", flush=True)

    # 3. Auction.com
    print("\n[3/3] Auction.com Sitemaps...", flush=True)
    try:
        run_auction_com()
    except Exception as e:
        print(f"Auction.com ERROR: {e}", flush=True)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}", flush=True)
    print(f"ALL DONE — {elapsed:.0f}s total", flush=True)
    print(f"{'=' * 60}", flush=True)


if __name__ == "__main__":
    main()
