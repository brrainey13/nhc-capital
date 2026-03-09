#!/usr/bin/env python3
"""
Scrape CT Judicial Branch pending foreclosure sales.
Source: https://sso.eservices.jud.ct.gov/foreclosures/Public/PendPostbyTownList.aspx

Outputs to Postgres table: ct_foreclosures
"""
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import psycopg2
from geocode_ct_foreclosures import clean_address, geocode_address


def get_connection():
    """Return a write-capable connection using nhc_etl."""
    return psycopg2.connect("postgresql://nhc_etl@localhost:5432/real_estate")

BASE = "https://sso.eservices.jud.ct.gov/foreclosures/Public"

def curl_get(url, timeout=30):
    """Use curl since requests has SSL issues with this site."""
    result = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout), url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise Exception(f"curl failed ({result.returncode}): {result.stderr}")
    return result.stdout

def get_towns():
    """Parse town list page, return list of (town_name, count)."""
    html = curl_get(f"{BASE}/PendPostbyTownList.aspx")
    # Pattern: <a href="PendPostbyTownDetails.aspx?town=Avon">Avon</a><span> (</span><span>1</span>
    pattern = r'PendPostbyTownDetails\.aspx\?town=([^"]+)">[^<]+</a><span> \(</span><span>(\d+)</span>'
    matches = re.findall(pattern, html)
    return [(name.strip(), int(count)) for name, count in matches]

def get_town_listings(town):
    """Parse town detail page, return list of dicts with basic info + posting IDs."""
    url = f"{BASE}/PendPostbyTownDetails.aspx?town={quote(town)}"
    html = curl_get(url)
    listings = []

    # Find table rows with data
    # Each row has: Sale Date | Docket Number (link) | Type & Address | View Full Notice (link)
    # Docket pattern
    docket_pattern = r'PendPostbyDocketNo\.aspx\?DocketNo=([^"]+)'
    # Posting ID pattern
    posting_pattern = r'PendPostDetailPublic\.aspx\?PostingId=(\d+)'
    # Sale date pattern - in table cells
    date_pattern = r'<span[^>]*>(\w+ \d+, \d{4})</span>'
    # Address/type pattern
    addr_pattern = r'<span[^>]*id="[^"]*Label2"[^>]*>(.*?)</span>'

    dockets = re.findall(docket_pattern, html)
    postings = re.findall(posting_pattern, html)
    dates = re.findall(date_pattern, html)
    addresses_raw = re.findall(addr_pattern, html, re.DOTALL)

    for i in range(len(postings)):
        listing = {
            "town": town,
            "posting_id": postings[i] if i < len(postings) else None,
            "docket_number": dockets[i] if i < len(dockets) else None,
            "sale_date_raw": dates[i] if i < len(dates) else None,
            "type_address_raw": addresses_raw[i] if i < len(addresses_raw) else None,
        }
        listings.append(listing)

    return listings

def parse_full_notice(posting_id):
    """Fetch full notice page and extract check amount + full description."""
    url = f"{BASE}/PendPostDetailPublic.aspx?PostingId={posting_id}"
    html = curl_get(url)

    # Sale date
    sale_date = None
    m = re.search(r'lblSaleDate[^>]*>([^<]+)<', html)
    if m:
        sale_date = m.group(1).strip()

    # Heading (type + address)
    heading = None
    m = re.search(r'lblHeading[^>]*>(.*?)</span>', html, re.DOTALL)
    if m:
        heading = re.sub(r'<[^>]+>', ' ', m.group(1)).strip()
        heading = re.sub(r'\s+', ' ', heading)

    # Parse address from heading
    address = None
    if heading:
        m2 = re.search(r'ADDRESS:\s*(.+)', heading, re.IGNORECASE)
        if m2:
            address = m2.group(1).strip()

    # Sale type from heading
    sale_type = None
    if heading:
        m2 = re.search(r'(PUBLIC AUCTION|COMMITTEE SALE|STRICT FORECLOSURE)', heading, re.IGNORECASE)
        if m2:
            sale_type = m2.group(1).strip()

    # Property type
    property_type = None
    if heading:
        m2 = re.search(r'(?:SALE:|FORECLOSURE SALE:)\s*(\w+)', heading, re.IGNORECASE)
        if m2:
            property_type = m2.group(1).strip()

    # Body text
    body = None
    m = re.search(r'lblBody[^>]*>(.*?)</span>', html, re.DOTALL)
    if m:
        body_html = m.group(1)
        body = re.sub(r'<[^>]+>', '\n', body_html).strip()
        body = re.sub(r'\n{3,}', '\n\n', body)

    # Check amount - look for dollar amount near "check" or "amount of"
    check_amount = None
    search_text = body or html
    m2 = re.search(r'amount of \$([0-9,]+(?:\.\d{2})?)', search_text, re.IGNORECASE)
    if m2:
        check_amount = m2.group(1).replace(',', '')

    # Photo URL
    photo_url = None
    m_photo = re.search(r'src="\.\./?(ForeclosureUploads/[^"]+)"', html)
    if m_photo:
        photo_url = f"https://sso.eservices.jud.ct.gov/foreclosures/{m_photo.group(1)}"

    # Cancellation status
    status = None
    if re.search(r'lblStatus.*?cancel', html, re.IGNORECASE):
        status = "Cancelled"

    return {
        "sale_date": sale_date,
        "heading": heading,
        "address": address,
        "sale_type": sale_type,
        "property_type": property_type,
        "check_amount": check_amount,
        "full_notice": body,
        "photo_url": photo_url,
        "status": status,
    }

def create_table(conn):
    """Create ct_foreclosures table."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ct_foreclosures (
                id SERIAL PRIMARY KEY,
                posting_id INTEGER UNIQUE,
                town VARCHAR(100),
                docket_number VARCHAR(50),
                sale_date VARCHAR(50),
                sale_type VARCHAR(50),
                property_type VARCHAR(50),
                address TEXT,
                check_amount NUMERIC(12,2),
                full_notice TEXT,
                heading TEXT,
                lat DOUBLE PRECISION,
                lng DOUBLE PRECISION,
                scraped_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    conn.commit()

def upsert_listing(conn, data):
    """Upsert a single listing."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ct_foreclosures
                (posting_id, town, docket_number, sale_date, sale_type, property_type,
                 address, check_amount, full_notice, heading, lat, lng, photo_url, status, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (posting_id) DO UPDATE SET
                town=EXCLUDED.town, docket_number=EXCLUDED.docket_number,
                sale_date=EXCLUDED.sale_date, sale_type=EXCLUDED.sale_type,
                property_type=EXCLUDED.property_type, address=EXCLUDED.address,
                check_amount=EXCLUDED.check_amount, full_notice=EXCLUDED.full_notice,
                heading=EXCLUDED.heading, lat=EXCLUDED.lat, lng=EXCLUDED.lng,
                photo_url=EXCLUDED.photo_url, status=EXCLUDED.status, scraped_at=NOW()
        """, (
            data.get("posting_id"), data.get("town"), data.get("docket_number"),
            data.get("sale_date"), data.get("sale_type"), data.get("property_type"),
            data.get("address"),
            float(data["check_amount"]) if data.get("check_amount") else None,
            data.get("full_notice"), data.get("heading"),
            data.get("lat"), data.get("lng"), data.get("photo_url"), data.get("status"),
        ))
    conn.commit()

def _geocode_census(address: str) -> tuple:
    """Geocode via US Census Bureau geocoder. Free, no key, no rate limit.
    Returns (lat, lng) or (None, None).
    Note: `quote` is imported at the top of this file (from urllib.parse import quote).
    """
    encoded = quote(address)  # urllib.parse.quote — imported on line 14
    url = (
        f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        f"?address={encoded}&benchmark=Public_AR_Current&format=json"
    )
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "10", url],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        matches = data.get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0]["coordinates"]
            lat, lng = float(coords["y"]), float(coords["x"])
            # Sanity: must be in CT bounding box
            if 40.9 < lat < 42.1 and -73.8 < lng < -71.7:
                return lat, lng
    except Exception as e:
        print(f"    Census geocoder error: {e}", flush=True)
    return None, None


def _get_existing_geocodes(conn):
    """Load posting_id -> (lat, lng) for already-geocoded listings."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT posting_id, lat, lng FROM ct_foreclosures "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL"
        )
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def main():
    print("=== CT Foreclosure Scraper ===", flush=True)

    # Get town list
    print("Fetching town list...", flush=True)
    towns = get_towns()
    total_listings = sum(c for _, c in towns)
    print(f"Found {len(towns)} towns with {total_listings} total listings", flush=True)

    # Setup DB — table should already exist; skip creation for read-only users
    try:
        with get_connection() as conn:
            create_table(conn)
    except Exception:
        pass  # table already exists

    # Load existing geocodes to skip re-geocoding
    existing_geocodes = {}
    try:
        with get_connection() as conn:
            existing_geocodes = _get_existing_geocodes(conn)
        print(f"Loaded {len(existing_geocodes)} existing geocodes (will skip)", flush=True)
    except Exception:
        pass

    # Scrape each town
    scraped = 0
    errors = 0
    geocoded_new = 0
    geocode_skipped = 0
    for town, count in towns:
        print(f"\n[{town}] ({count} listings)...", flush=True)
        try:
            listings = get_town_listings(town)
            print(f"  Parsed {len(listings)} listings from town page", flush=True)

            for listing in listings:
                posting_id = listing.get("posting_id")
                if not posting_id:
                    print("  SKIP: no posting_id", flush=True)
                    errors += 1
                    continue

                try:
                    time.sleep(0.3)  # be polite
                    notice = parse_full_notice(posting_id)

                    # Reuse existing geocode if available; only geocode new listings
                    lat, lng = None, None
                    pid_int = int(posting_id)
                    if pid_int in existing_geocodes:
                        lat, lng = existing_geocodes[pid_int]
                        geocode_skipped += 1
                    else:
                        addr = notice.get("address")
                        if addr:
                            clean = clean_address(addr, town)
                            # Use Census geocoder (free, no rate limit)
                            lat, lng = _geocode_census(clean)
                            if lat is None:
                                # Fallback to Nominatim
                                lat, lng = geocode_address(clean)
                                time.sleep(1.1)
                            else:
                                time.sleep(0.15)  # Census is fast, minimal delay
                            if lat is not None:
                                geocoded_new += 1

                    record = {
                        "posting_id": pid_int,
                        "town": town,
                        "docket_number": listing.get("docket_number"),
                        "sale_date": notice.get("sale_date"),
                        "sale_type": notice.get("sale_type"),
                        "property_type": notice.get("property_type"),
                        "address": notice.get("address"),
                        "check_amount": notice.get("check_amount"),
                        "full_notice": notice.get("full_notice"),
                        "heading": notice.get("heading"),
                        "lat": lat,
                        "lng": lng,
                        "photo_url": notice.get("photo_url"),
                        "status": notice.get("status"),
                    }
                    with get_connection() as conn:
                        upsert_listing(conn, record)
                    scraped += 1
                    print(f"  ✓ {notice.get('address', 'no addr')[:60]} | ${notice.get('check_amount', '?')} | {notice.get('sale_date', '?')}", flush=True)
                except Exception as e:
                    errors += 1
                    print(f"  ✗ PostingId {posting_id}: {e}", flush=True)

            time.sleep(0.2)  # pause between towns
        except Exception as e:
            errors += 1
            print(f"  ERROR on town {town}: {e}", flush=True)

    print(f"\n=== DONE === Scraped: {scraped} | Errors: {errors} | New geocodes: {geocoded_new} | Reused: {geocode_skipped}", flush=True)

if __name__ == "__main__":
    main()
