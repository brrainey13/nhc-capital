#!/usr/bin/env python3
"""
Scrape full sales history from PropertyRecordCards.com property pages.
Reads unique IDs from ct_vision_parcels (acct_num), fetches each page, extracts sales table.

Usage:
    python scrape_prc_sales.py --town WiltonCT --towncode 161 [--delay 0.05]
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# PRC town codes
TOWN_CODES = {
    "WiltonCT": "161", "RidgefieldCT": "118", "WestonCT": "157",
    "SimsburyCT": "128", "NewCanaanCT": "090", "DanburyCT": "034",
}


def fetch_property(towncode: str, uniqueid: str) -> str | None:
    url = f"https://www.propertyrecordcards.com/PropertyResults.aspx?towncode={towncode}&uniqueid={urllib.parse.quote(str(uniqueid))}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def extract_sales(html: str, town: str, pid: int) -> list[dict]:
    """Extract sales from PRC property page. Format: Owner, Book, Page, Date, DeedType, Price."""
    sales = []

    # Get living area
    living_match = re.search(r'Living Area.*?(\d[\d,]+)\s*(?:SF|sq)', html, re.I | re.DOTALL)
    living_area = None
    if living_match:
        try:
            living_area = int(living_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Find sales table — it's the one with Owner, Book, Page, Date, DeedType, Price columns
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
    for table in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL)
        # Check if this looks like a sales table (has $ amounts and dates)
        table_text = re.sub(r'<[^>]+>', ' ', table)
        if '$' not in table_text or not re.search(r'\d{2}/\d{2}/\d{4}', table_text):
            continue

        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if len(cells) < 4:
                continue

            # Find the price cell (contains $)
            price_idx = None
            date_idx = None
            for i, c in enumerate(cells):
                if '$' in c and price_idx is None:
                    price_idx = i
                if re.match(r'\d{2}/\d{2}/\d{4}', c) and date_idx is None:
                    date_idx = i

            if price_idx is None or date_idx is None:
                continue

            # Owner is first cell (before date and price)
            owner = cells[0].strip()
            if not owner or owner == "&nbsp;":
                continue

            price_str = cells[price_idx].replace("$", "").replace(",", "").strip()
            try:
                price = float(price_str)
            except ValueError:
                price = None

            date_str = cells[date_idx]

            # Book/page: cells between owner and date
            book_page = None
            if date_idx > 1:
                book = cells[1].strip() if len(cells) > 1 else ""
                page = cells[2].strip() if len(cells) > 2 else ""
                if book and page and book != "&nbsp;":
                    book_page = f"{book}/{page}"

            sales.append({
                "town": town,
                "pid": pid,
                "owner": owner,
                "sale_price": price,
                "sale_date": date_str,
                "book_page": book_page,
                "instrument": None,
                "living_area_sqft": living_area,
            })

    return sales


INSERT_SQL = """
INSERT INTO ct_vision_sales (town, pid, owner, sale_price, sale_date, book_page, instrument, living_area_sqft)
VALUES (%(town)s, %(pid)s, %(owner)s, %(sale_price)s, %(sale_date)s, %(book_page)s, %(instrument)s, %(living_area_sqft)s)
ON CONFLICT (town, pid, sale_date, sale_price) DO NOTHING
"""


def save_sales(sales: list[dict]) -> int:
    if not sales:
        return 0
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_etl@localhost:5432/real_estate")
    saved = 0
    try:
        with conn.cursor() as cur:
            for s in sales:
                try:
                    cur.execute(INSERT_SQL, s)
                    saved += 1
                except Exception:
                    conn.rollback()
                    continue
        conn.commit()
    finally:
        conn.close()
    return saved


def get_prc_parcels(town: str) -> list[dict]:
    """Get all parcels for a PRC town with their acct_num (unique ID)."""
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_agent@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pid, acct_num FROM ct_vision_parcels
                WHERE town = %s AND acct_num IS NOT NULL
                ORDER BY pid
            """, (town,))
            return [{"pid": r[0], "uniqueid": r[1]} for r in cur.fetchall()]
    finally:
        conn.close()


def scrape_town(town: str, towncode: str, delay: float = 0.05, batch_size: int = 200) -> dict:
    parcels = get_prc_parcels(town)
    print(f"\n=== Scraping PRC sales for {town} (code={towncode}, {len(parcels)} parcels) ===", flush=True)

    total_sales = 0
    total_saved = 0
    total_errors = 0
    batch = []

    for i, p in enumerate(parcels):
        html = fetch_property(towncode, p["uniqueid"])
        if not html:
            total_errors += 1
            continue

        sales = extract_sales(html, town, p["pid"])
        if sales:
            batch.extend(sales)
            total_sales += len(sales)

        if len(batch) >= batch_size:
            saved = save_sales(batch)
            total_saved += saved
            print(f"  [{i+1}/{len(parcels)}] sales={total_sales} saved={total_saved} errors={total_errors}", flush=True)
            batch = []

        time.sleep(delay)

    if batch:
        saved = save_sales(batch)
        total_saved += saved

    result = {"town": town, "parcels": len(parcels), "total_sales": total_sales,
              "saved": total_saved, "errors": total_errors}
    print(f"\n  Done: {total_sales} sales found, {total_saved} saved, {total_errors} errors", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--town", required=True)
    parser.add_argument("--towncode", help="PRC town code (auto-detected if known)")
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    tc = args.towncode or TOWN_CODES.get(args.town)
    if not tc:
        print(f"Unknown town code for {args.town}. Use --towncode.")
        sys.exit(1)

    result = scrape_town(args.town, tc, delay=args.delay, batch_size=args.batch_size)
    print(json.dumps(result))
