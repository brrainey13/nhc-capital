#!/usr/bin/env python3
"""
Scrape Intercounty Judicial Sales Corporation (intercountyjudicialsales.com)
for IL foreclosure auctions.

Source: https://intercountyjudicialsales.com/sales/

Outputs to Postgres table: il_foreclosures (source='intercounty')
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

TARGET_COUNTIES = {"cook", "dupage", "kane", "kendall", "lake", "mchenry", "will"}

SALES_URL = "https://intercountyjudicialsales.com/sales/"


def get_connection():
    """Write-capable connection using nhc_etl."""
    return psycopg2.connect("postgresql://nhc_etl:nhc_etl_pass@localhost:5432/real_estate")


def curl_get(url, timeout=30):
    """Fetch URL via curl (skip SSL verify for intercounty — has cert issues)."""
    result = subprocess.run(
        ["curl", "-sLk", "--max-time", str(timeout), url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise Exception(f"curl failed ({result.returncode}): {result.stderr}")
    return result.stdout


def geocode_census(address, state="IL"):
    """Geocode via US Census Bureau geocoder."""
    full_addr = f"{address}, {state}" if state.upper() not in address.upper() else address
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
            if 36.9 < lat < 42.5 and -91.5 < lng < -87.0:
                return lat, lng
    except Exception as e:
        print(f"    Census geocoder error: {e}", flush=True)
    return None, None


def parse_intercounty_sales(html):
    """Parse the Intercounty Ninja Tables page.

    Verified column order (from class names):
    0: dateofsale     | 1: continueddate (hidden) | 2: saletime
    3: county         | 4: matternumber (case#)   | 5: clientreferencenumber (file#)
    6: clientname (firm) | 7: commonaddress        | 8: city (hidden)
    9: propertyzip (hidden) | 10: matterstage (status) | 11: bidamount
    12: successfulbidder (hidden, plaintiff/buyer) | 13: practicearea (IJSC/Sheriff)
    """
    listings = []

    # Data rows use: <tr data-row_id="N" class="ninja_table_row_N ..."><td>...</td>...
    row_pattern = re.compile(
        r'<tr\s+data-row_id="(\d+)"[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE
    )
    cell_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)

    for row_match in row_pattern.finditer(html):
        row_html = row_match.group(2)
        cells = cell_pattern.findall(row_html)
        # Strip HTML tags and collapse whitespace
        cells = [re.sub(r'<[^>]+>', ' ', c).strip() for c in cells]
        cells = [re.sub(r'\s+', ' ', c).strip() for c in cells]

        if len(cells) < 8:
            continue

        # Cell 0: Sale date
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', cells[0])
        if not date_match:
            continue

        # Use continued date if present (cell 1), otherwise original
        continued = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', cells[1]) if len(cells) > 1 else None
        sale_date_raw = continued.group(1) if continued else date_match.group(1)

        # Cell 7: commonaddress — includes full address, city, state, zip
        addr_raw = cells[7].strip() if len(cells) > 7 else ""
        address = addr_raw
        city = cells[8].strip() if len(cells) > 8 else None
        zipcode = cells[9].strip() if len(cells) > 9 else None

        # If city is empty, try to parse from address string
        if not city and addr_raw:
            # Pattern: "1234 Street, City, IL 60601"
            m = re.match(r'(.+?),\s*([A-Za-z\s\.]+?),?\s*(?:IL|Illinois)\s*(\d{5})?', addr_raw)
            if m:
                address = m.group(1).strip()
                city = m.group(2).strip()
                if m.group(3):
                    zipcode = m.group(3)

        # Cell 10: status
        status_raw = cells[10].strip().lower() if len(cells) > 10 else ""
        if status_raw in ("cancelled", "canceled"):
            status = "cancelled"
        elif "to plaintiff" in status_raw:
            status = "completed"
        elif "third party" in status_raw:
            status = "completed"
        elif "continued" in status_raw:
            status = "upcoming"  # rescheduled
        elif "intake" in status_raw:
            status = "upcoming"
        else:
            status = "upcoming"

        # Cell 11: bid amount
        bid = None
        if len(cells) > 11:
            bm = re.search(r'\$([0-9,]+(?:\.\d{2})?)', cells[11])
            if bm:
                bid = bm.group(1).replace(",", "")

        # Cell 12: successful bidder / plaintiff
        plaintiff = cells[12].strip() if len(cells) > 12 and cells[12].strip() else None

        # Cell 13: practice area (IJSC Sales / Sheriff Sale)
        sale_type = "foreclosure"
        if len(cells) > 13 and "sheriff" in cells[13].lower():
            sale_type = "sheriff_sale"

        record = {
            "sale_date_raw": sale_date_raw,
            "sale_time": cells[2].strip() if len(cells) > 2 else None,
            "county": cells[3].strip() if len(cells) > 3 else None,
            "case_number": cells[4].strip() if len(cells) > 4 else None,
            "file_number": cells[5].strip() if len(cells) > 5 else None,
            "firm_name": cells[6].strip() if len(cells) > 6 else None,
            "address": address,
            "city": city,
            "zip": zipcode,
            "status": status,
            "opening_bid": bid,
            "plaintiff": plaintiff,
            "sale_type": sale_type,
        }

        if record["case_number"]:
            listings.append(record)

    return listings


def parse_sale_date(raw):
    """Parse date string to date object."""
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
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
            record.get("source", "intercounty"),
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
            "WHERE lat IS NOT NULL AND lng IS NOT NULL AND source = 'intercounty'"
        )
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def main():
    print("=== IL Foreclosure Scraper — Intercounty ===", flush=True)

    conn = get_connection()
    existing_geocodes = {}
    try:
        existing_geocodes = get_existing_geocodes(conn)
        print(f"Loaded {len(existing_geocodes)} existing geocodes", flush=True)
    except Exception:
        pass

    # Fetch the sales page
    print(f"Fetching {SALES_URL}...", flush=True)
    html = curl_get(SALES_URL)
    print(f"  Page size: {len(html):,} bytes", flush=True)

    # Parse listings
    listings = parse_intercounty_sales(html)
    print(f"  Parsed {len(listings)} listings", flush=True)

    # Process and upsert
    scraped = 0
    geocoded_new = 0
    geocode_skipped = 0
    errors = 0
    target_count = 0

    for listing in listings:
        listing["source"] = "intercounty"
        listing["sale_date"] = parse_sale_date(listing.get("sale_date_raw"))

        case = listing.get("case_number", "").strip()
        if not case:
            continue

        county = (listing.get("county") or "").strip()
        if county.lower() in TARGET_COUNTIES:
            target_count += 1

        # Set status if not already set
        if "status" not in listing:
            listing["status"] = "upcoming"

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
                print(f"  Progress: {scraped}/{len(listings)}", flush=True)
        except Exception as e:
            conn.rollback()
            errors += 1
            if errors <= 5:
                print(f"  ✗ {case}: {e}", flush=True)

    conn.close()
    print("\n=== Intercounty DONE ===", flush=True)
    print(f"  Total: {len(listings)} | Target counties: {target_count}", flush=True)
    print(f"  Upserted: {scraped} | Errors: {errors}", flush=True)
    print(f"  New geocodes: {geocoded_new} | Reused: {geocode_skipped}", flush=True)


if __name__ == "__main__":
    main()
