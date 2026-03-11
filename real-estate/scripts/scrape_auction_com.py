#!/usr/bin/env python3
"""
Scrape Auction.com IL listings via their public XML sitemaps.

Auction.com has Incapsula bot protection on all pages, but sitemaps
are publicly accessible. We extract:
  - Property address (from URL slug)
  - Listing ID (from URL)
  - Photo URLs (from image sitemaps)
  - Sale type: REO (bank-owned) vs TPS (foreclosure/third-party sale)

Sitemaps:
  - sitemap-pdp-active-reo-{0,1}.xml      — bank-owned properties
  - sitemap-pdp-active-tps-{0,1,2,3}.xml  — foreclosures (third-party sales)
  - sitemap-pdp-active-reo-{0,1}-image.xml — photos for REO
  - sitemap-pdp-active-tps-{0,1,2,3}-image.xml — photos for TPS

Outputs to Postgres table: il_foreclosures (source='auction_com')
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

SITEMAP_BASE = "https://www.auction.com/sitemaps"

# TPS = third-party sale (foreclosure), REO = bank-owned
SITEMAP_CONFIGS = [
    # (sitemap_file, sale_type, image_sitemap_file)
    ("sitemap-pdp-active-tps-0.xml", "foreclosure", "sitemap-pdp-active-tps-0-image.xml"),
    ("sitemap-pdp-active-tps-1.xml", "foreclosure", "sitemap-pdp-active-tps-1-image.xml"),
    ("sitemap-pdp-active-tps-2.xml", "foreclosure", "sitemap-pdp-active-tps-2-image.xml"),
    ("sitemap-pdp-active-tps-3.xml", "foreclosure", None),
    ("sitemap-pdp-active-reo-0.xml", "reo", "sitemap-pdp-active-reo-0-image.xml"),
    ("sitemap-pdp-active-reo-1.xml", "reo", "sitemap-pdp-active-reo-1-image.xml"),
]


def get_connection():
    return psycopg2.connect("postgresql://nhc_etl:nhc_etl_pass@localhost:5432/real_estate")


def curl_get(url, timeout=30):
    result = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout), url],
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


def parse_sitemap_il_urls(xml_content):
    """Extract IL property URLs from a sitemap XML."""
    # Match URLs containing "-il-" (state indicator in slug)
    urls = re.findall(r'<loc>(https://www\.auction\.com/details/[^<]*-il-[^<]*)</loc>', xml_content)
    return urls


def parse_image_sitemap(xml_content):
    """Extract URL -> first photo URL mapping from image sitemap."""
    photos = {}
    # Each entry: <url><loc>page_url</loc><image:image><image:loc>img_url</image:loc>...
    entries = re.findall(
        r'<loc>(https://www\.auction\.com/details/[^<]+)</loc>\s*<image:image>\s*<image:loc>([^<]+)</image:loc>',
        xml_content,
    )
    for page_url, img_url in entries:
        if page_url not in photos:  # Keep first image only
            photos[page_url] = img_url
    return photos


def parse_url_to_record(url, sale_type, photo_url=None):
    """Extract property data from an Auction.com URL slug.

    URL format: /details/{address-slug}-{state}-{listing_id}
    Example: /details/9151-s-perry-ave-chicago-il-1886907
    """
    # Extract the path
    m = re.search(r'/details/(.+)', url)
    if not m:
        return None

    slug = m.group(1)

    # Extract listing ID (last numeric segment)
    parts = slug.rsplit('-', 1)
    if len(parts) != 2 or not parts[1].isdigit():
        # Try finding the last number
        nums = re.findall(r'-(\d{5,})', slug)
        listing_id = nums[-1] if nums else None
        addr_slug = slug
    else:
        listing_id = parts[1]
        addr_slug = parts[0]

    # Remove state suffix (-il)
    addr_slug = re.sub(r'-il$', '', addr_slug)

    # Extract city — typically last word(s) before state
    # Heuristic: split on hyphens, city is usually last 1-3 segments
    segments = addr_slug.split('-')

    # Try to identify where address ends and city begins
    # Street numbers are at the beginning
    # Common patterns: "9151-s-perry-ave-chicago" → address="9151 S Perry Ave", city="Chicago"
    # "16406-plymouth-dr-markham" → address="16406 Plymouth Dr", city="Markham"

    # Find street type indicators
    street_types = {'st', 'ave', 'rd', 'dr', 'ln', 'ct', 'pl', 'blvd', 'way', 'cir',
                    'pkwy', 'ter', 'trl', 'hwy'}
    street_idx = None
    for i, seg in enumerate(segments):
        if seg.lower() in street_types:
            street_idx = i
            # Don't break — take the LAST street type (handles "ave" in middle)

    if street_idx is not None and street_idx < len(segments) - 1:
        addr_parts = segments[:street_idx + 1]
        city_parts = segments[street_idx + 1:]

        # Handle unit numbers after street type (e.g., "apt-2")
        if city_parts and city_parts[0].lower() in ('apt', 'unit', 'ste', 'suite'):
            if len(city_parts) > 1:
                addr_parts.extend(city_parts[:2])
                city_parts = city_parts[2:]
            else:
                addr_parts.append(city_parts[0])
                city_parts = city_parts[1:]

        address = ' '.join(p.title() for p in addr_parts)
        city = ' '.join(p.title() for p in city_parts)
    else:
        # Fallback: everything is the address
        address = ' '.join(p.title() for p in segments)
        city = None

    # Fix common abbreviations
    address = address.replace(' S ', ' S. ').replace(' N ', ' N. ')
    address = address.replace(' E ', ' E. ').replace(' W ', ' W. ')

    return {
        "source": "auction_com",
        "case_number": f"auc-{listing_id}" if listing_id else None,
        "address": address,
        "city": city,
        "state": "IL",
        "sale_type": sale_type,
        "status": "upcoming",
        "auction_com_id": listing_id,
        "photo_url": photo_url,
    }


def upsert_listing(conn, record):
    """Insert or update an IL foreclosure listing."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO il_foreclosures
                (source, case_number, address, city, county, zip,
                 sale_date, sale_time, sale_type, opening_bid, judgment_amount,
                 status, plaintiff, firm_name, file_number,
                 auction_com_id, photo_url, lat, lng, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (source, case_number) DO UPDATE SET
                address=EXCLUDED.address, city=EXCLUDED.city,
                sale_type=EXCLUDED.sale_type,
                auction_com_id=EXCLUDED.auction_com_id,
                photo_url=COALESCE(EXCLUDED.photo_url, il_foreclosures.photo_url),
                lat=COALESCE(EXCLUDED.lat, il_foreclosures.lat),
                lng=COALESCE(EXCLUDED.lng, il_foreclosures.lng),
                scraped_at=NOW()
        """, (
            record.get("source", "auction_com"),
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT case_number, lat, lng FROM il_foreclosures "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL AND source = 'auction_com'"
        )
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def main():
    print("=== IL Foreclosure Scraper — Auction.com Sitemaps ===", flush=True)

    conn = get_connection()
    existing_geocodes = {}
    try:
        existing_geocodes = get_existing_geocodes(conn)
        print(f"Loaded {len(existing_geocodes)} existing geocodes", flush=True)
    except Exception:
        pass

    total_found = 0
    scraped = 0
    geocoded_new = 0
    geocode_skipped = 0
    errors = 0

    for sitemap_file, sale_type, image_file in SITEMAP_CONFIGS:
        print(f"\nProcessing {sitemap_file} ({sale_type})...", flush=True)

        # Fetch main sitemap
        xml = curl_get(f"{SITEMAP_BASE}/{sitemap_file}")
        il_urls = parse_sitemap_il_urls(xml)
        print(f"  Found {len(il_urls)} IL listings", flush=True)
        total_found += len(il_urls)

        # Fetch image sitemap if available
        photos = {}
        if image_file:
            try:
                img_xml = curl_get(f"{SITEMAP_BASE}/{image_file}")
                photos = parse_image_sitemap(img_xml)
                il_photos = {k: v for k, v in photos.items() if '-il-' in k}
                print(f"  Found {len(il_photos)} IL photos", flush=True)
                photos = il_photos
            except Exception as e:
                print(f"  Image sitemap error: {e}", flush=True)

        time.sleep(0.5)

        # Process each URL
        for url in il_urls:
            photo = photos.get(url)
            record = parse_url_to_record(url, sale_type, photo)
            if not record or not record.get("case_number"):
                continue

            case = record["case_number"]

            # Geocode
            if case in existing_geocodes:
                record["lat"], record["lng"] = existing_geocodes[case]
                geocode_skipped += 1
            elif record.get("address"):
                addr = record["address"]
                city = record.get("city", "")
                full_addr = f"{addr}, {city}, IL" if city else f"{addr}, IL"
                lat, lng = geocode_census(full_addr)
                record["lat"] = lat
                record["lng"] = lng
                if lat:
                    geocoded_new += 1
                time.sleep(0.15)

            try:
                upsert_listing(conn, record)
                scraped += 1
                if scraped % 50 == 0:
                    print(f"  Progress: {scraped} upserted...", flush=True)
            except Exception as e:
                conn.rollback()
                errors += 1
                if errors <= 5:
                    print(f"  ✗ {case}: {e}", flush=True)

    conn.close()
    print("\n=== Auction.com DONE ===", flush=True)
    print(f"  Total IL listings: {total_found}", flush=True)
    print(f"  Upserted: {scraped} | Errors: {errors}", flush=True)
    print(f"  New geocodes: {geocoded_new} | Reused: {geocode_skipped}", flush=True)


if __name__ == "__main__":
    main()
