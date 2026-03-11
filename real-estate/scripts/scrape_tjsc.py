#!/usr/bin/env python3
"""
Scrape The Judicial Sales Corporation (tjsc.com) for IL foreclosure auctions.

Endpoints:
  - /Sales/UpcomingSales   — future auctions (primary)
  - /Sales/CompletedSales  — past results
  - /Sales/CancelledSales  — withdrawn listings

Outputs to Postgres table: il_foreclosures (source='tjsc')
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import psycopg2
import psycopg2.extras

# --- Target counties (Chicago metro) ---
TARGET_COUNTIES = {"cook", "dupage", "kane", "kendall", "lake", "mchenry", "will"}

BASE_URL = "https://tjsc.com"


def get_connection():
    """Write-capable connection using nhc_etl."""
    return psycopg2.connect("postgresql://nhc_etl:nhc_etl_pass@localhost:5432/real_estate")


def curl_get(url, timeout=30):
    """Fetch URL via curl."""
    result = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout), url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise Exception(f"curl failed ({result.returncode}): {result.stderr}")
    return result.stdout


def geocode_census(address, state="IL"):
    """Geocode via US Census Bureau geocoder. Free, no key, no rate limit."""
    full_addr = f"{address}, {state}" if state not in address.upper() else address
    encoded = quote(full_addr)
    url = (
        f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        f"?address={encoded}&benchmark=Public_AR_Current&format=json"
    )
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "10", url],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        matches = data.get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0]["coordinates"]
            lat, lng = float(coords["y"]), float(coords["x"])
            # IL bounding box: lat 36.9-42.5, lng -91.5 to -87.0
            if 36.9 < lat < 42.5 and -91.5 < lng < -87.0:
                return lat, lng
    except Exception as e:
        print(f"    Census geocoder error: {e}", flush=True)
    return None, None


def parse_tjsc_table(html):
    """Parse TJSC DataTable HTML.

    Verified column order (from <thead>):
    0: Sale Date | 1: Sale Time | 2: File Number | 3: Case Number |
    4: Firm Name | 5: Address | 6: City | 7: County | 8: Zip Code |
    9: Opening Bid | 10: Required % Down | 11: Sale Amount |
    12: Continuance | 13: Sold To
    """
    listings = []

    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
    cell_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)

    # Only parse rows inside <tbody>
    tbody_match = re.search(r'<tbody>(.*?)</tbody>', html, re.DOTALL | re.IGNORECASE)
    if not tbody_match:
        return listings

    rows = row_pattern.findall(tbody_match.group(1))
    for row_html in rows:
        cells = cell_pattern.findall(row_html)
        # Strip HTML tags and whitespace from each cell
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]

        if len(cells) < 9:
            continue

        # Cell 0: Sale Date
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', cells[0])
        if not date_match:
            continue

        # Extract opening bid
        bid = None
        bid_match = re.search(r'\$([0-9,]+(?:\.\d{2})?)', cells[9] if len(cells) > 9 else "")
        if bid_match:
            bid = bid_match.group(1).replace(",", "")

        # Determine sold status
        sold_to = cells[13].strip() if len(cells) > 13 else ""

        record = {
            "sale_date_raw": date_match.group(1),
            "sale_time": cells[1].strip() if len(cells) > 1 else None,
            "file_number": cells[2].strip() if len(cells) > 2 else None,
            "case_number": cells[3].strip() if len(cells) > 3 else None,
            "firm_name": cells[4].strip() if len(cells) > 4 else None,
            "address": cells[5].strip() if len(cells) > 5 else None,
            "city": cells[6].strip() if len(cells) > 6 else None,
            "county": cells[7].strip() if len(cells) > 7 else None,
            "zip": cells[8].strip() if len(cells) > 8 else None,
            "opening_bid": bid,
            "plaintiff": sold_to if sold_to and sold_to.lower() not in ("", "plaintiff") else None,
        }

        if record["case_number"]:
            listings.append(record)

    return listings


def scrape_tjsc_page(endpoint, status_label):
    """Scrape a TJSC sales page."""
    print(f"Fetching TJSC {status_label}...", flush=True)
    html = curl_get(f"{BASE_URL}{endpoint}")
    listings = parse_tjsc_table(html)
    print(f"  Parsed {len(listings)} listings", flush=True)
    return listings


def parse_sale_date(raw):
    """Parse various date formats to a date object."""
    if not raw:
        return None
    # Try common formats
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    # Try extracting from string
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', str(raw))
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))).date()
        except ValueError:
            pass
    return None


def upsert_listing(conn, record):
    """Insert or update a single IL foreclosure listing."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO il_foreclosures
                (source, case_number, address, city, county, zip,
                 sale_date, sale_time, sale_type, opening_bid, judgment_amount,
                 status, plaintiff, firm_name, file_number,
                 auction_com_id, photo_url, lat, lng, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (source, case_number) DO UPDATE SET
                address=EXCLUDED.address, city=EXCLUDED.city, county=EXCLUDED.county,
                zip=EXCLUDED.zip, sale_date=EXCLUDED.sale_date, sale_time=EXCLUDED.sale_time,
                sale_type=EXCLUDED.sale_type, opening_bid=EXCLUDED.opening_bid,
                judgment_amount=EXCLUDED.judgment_amount, status=EXCLUDED.status,
                plaintiff=EXCLUDED.plaintiff, firm_name=EXCLUDED.firm_name,
                file_number=EXCLUDED.file_number, auction_com_id=EXCLUDED.auction_com_id,
                photo_url=EXCLUDED.photo_url,
                lat=COALESCE(EXCLUDED.lat, il_foreclosures.lat),
                lng=COALESCE(EXCLUDED.lng, il_foreclosures.lng),
                scraped_at=NOW()
        """, (
            record.get("source", "tjsc"),
            record.get("case_number"),
            record.get("address"),
            record.get("city"),
            record.get("county"),
            record.get("zip"),
            record.get("sale_date"),
            record.get("sale_time"),
            record.get("sale_type", "foreclosure"),
            float(record["opening_bid"]) if record.get("opening_bid") else None,
            float(record["judgment_amount"]) if record.get("judgment_amount") else None,
            record.get("status", "upcoming"),
            record.get("plaintiff"),
            record.get("firm_name"),
            record.get("file_number"),
            record.get("auction_com_id"),
            record.get("photo_url"),
            record.get("lat"),
            record.get("lng"),
        ))
    conn.commit()


def get_existing_geocodes(conn):
    """Load case_number -> (lat, lng) for already-geocoded listings."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT case_number, lat, lng FROM il_foreclosures "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL AND source = 'tjsc'"
        )
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def main():
    print("=== IL Foreclosure Scraper — TJSC ===", flush=True)

    conn = get_connection()
    existing_geocodes = {}
    try:
        existing_geocodes = get_existing_geocodes(conn)
        print(f"Loaded {len(existing_geocodes)} existing geocodes", flush=True)
    except Exception:
        pass  # table may not exist yet

    # Scrape all three endpoints
    all_listings = []

    # 1. Upcoming sales
    upcoming = scrape_tjsc_page("/Sales/UpcomingSales", "Upcoming Sales")
    for r in upcoming:
        r["status"] = "upcoming"
    all_listings.extend(upcoming)

    time.sleep(1)

    # 2. Completed sales
    completed = scrape_tjsc_page("/Sales/CompletedSales", "Completed Sales")
    for r in completed:
        r["status"] = "completed"
    all_listings.extend(completed)

    time.sleep(1)

    # 3. Cancelled sales
    cancelled = scrape_tjsc_page("/Sales/CancelledSales", "Cancelled Sales")
    for r in cancelled:
        r["status"] = "cancelled"
    all_listings.extend(cancelled)

    print(f"\nTotal records: {len(all_listings)}", flush=True)

    # Filter to target counties (optional — keep all for now but flag)
    il_count = 0
    target_count = 0
    scraped = 0
    geocoded_new = 0
    geocode_skipped = 0
    errors = 0

    for listing in all_listings:
        county = (listing.get("county") or "").strip()

        # Parse date
        listing["sale_date"] = parse_sale_date(listing.get("sale_date_raw"))
        listing["source"] = "tjsc"

        case = listing.get("case_number", "").strip()
        if not case:
            continue

        il_count += 1
        if county.lower() in TARGET_COUNTIES:
            target_count += 1

        # Geocode
        addr = listing.get("address", "")
        city = listing.get("city", "")
        zipcode = listing.get("zip", "")
        if case in existing_geocodes:
            listing["lat"], listing["lng"] = existing_geocodes[case]
            geocode_skipped += 1
        elif addr:
            full_addr = f"{addr}, {city}, IL {zipcode}".strip(", ")
            lat, lng = geocode_census(full_addr)
            listing["lat"] = lat
            listing["lng"] = lng
            if lat:
                geocoded_new += 1
            time.sleep(0.15)

        try:
            upsert_listing(conn, listing)
            scraped += 1
            if scraped % 25 == 0:
                print(f"  Progress: {scraped}/{len(all_listings)}", flush=True)
        except Exception as e:
            conn.rollback()
            errors += 1
            if errors <= 5:
                print(f"  ✗ {case}: {e}", flush=True)

    conn.close()
    print("\n=== TJSC DONE ===", flush=True)
    print(f"  Total: {il_count} | Target counties: {target_count}", flush=True)
    print(f"  Upserted: {scraped} | Errors: {errors}", flush=True)
    print(f"  New geocodes: {geocoded_new} | Reused: {geocode_skipped}", flush=True)


if __name__ == "__main__":
    main()
