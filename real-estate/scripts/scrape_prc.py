#!/usr/bin/env python3
"""
Scrape PropertyRecordCards.com for CT town parcel data.

Usage:
    python scrape_prc.py --towncode 161 --town WiltonCT [--dry-run] [--delay 0.5]

PropertyRecordCards.com is an ASP.NET app serving property record cards for ~59 CT towns.
Data includes: parcel info, building details, owner info, sales history, permits.
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

BASE_URL = "https://www.propertyrecordcards.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch(url: str, data: dict | None = None, timeout: int = 20) -> str:
    """Fetch a URL, optionally POSTing form data."""
    headers = {"User-Agent": UA}
    body = None
    if data:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return resp.read().decode("utf-8", errors="replace")


def get_streets(towncode: str) -> list[str]:
    """Get list of street names from the search page dropdown."""
    url = f"{BASE_URL}/SearchMaster.aspx?towncode={towncode}"
    html = fetch(url)
    match = re.search(r'cbPropertySearchStreetName"(.*?)</select>', html, re.DOTALL)
    if not match:
        print("ERROR: Could not find street dropdown", flush=True)
        return []
    streets = re.findall(r'value="([^"]+)"', match.group(1))
    return [s for s in streets if s.strip()]


def get_aspnet_tokens(html: str) -> dict:
    """Extract ASP.NET form tokens from HTML."""
    vs = re.search(r'id="__VIEWSTATE"[^>]*value="([^"]*)"', html)
    vsg = re.search(r'id="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"', html)
    ev = re.search(r'id="__EVENTVALIDATION"[^>]*value="([^"]*)"', html)
    return {
        "__VIEWSTATE": vs.group(1) if vs else "",
        "__VIEWSTATEGENERATOR": vsg.group(1) if vsg else "",
        "__EVENTVALIDATION": ev.group(1) if ev else "",
    }


def search_street(towncode: str, street: str) -> list[tuple[str, str]]:
    """Search for all properties on a street. Returns list of (uniqueid, address)."""
    url = f"{BASE_URL}/SearchMaster.aspx?towncode={towncode}"
    html = fetch(url)
    tokens = get_aspnet_tokens(html)

    data = {
        **tokens,
        "ctl00$MainContent$tbPropertySearchName": "",
        "ctl00$MainContent$tbPropertySearchStreetNumber": "",
        "ctl00$MainContent$cbPropertySearchStreetName": street,
        "ctl00$MainContent$tbPropertySearchStreetUnit": "",
        "ctl00$MainContent$tbPropertySearchMBL": "",
        "ctl00$MainContent$tbPropertySearchUniqueId": "",
        "ctl00$MainContent$cbPropertySearchCondoComplex": "",
        "ctl00$MainContent$btnPropertySearch": "Property Search",
    }

    result = fetch(url, data)

    # Extract unique IDs and addresses from results table
    # Note: some towns use alphanumeric IDs (e.g. I14433, H13263-1)
    rows = re.findall(
        r'PropertyResults\.aspx\?towncode=\d+&uniqueid=([\w-]+)"[^>]*>([^<]*)</a>'
        r'</td><td>([^<]*)</td>',
        result,
    )
    properties = []
    for uid, street_name, street_num in rows:
        addr = f"{street_num.strip()} {street_name.strip()}".strip()
        properties.append((uid, addr))
    return properties


def parse_money(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"\d+", s.replace(",", ""))
    return int(m.group()) if m else None


def parse_float(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract_text(html: str) -> str:
    """Strip HTML to plain text for easier parsing."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n\s*\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def extract_field_after(text: str, label: str) -> str | None:
    """Extract the value that appears after a label in the text."""
    pattern = rf"{re.escape(label)}:?\s*\n\s*(.+)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def fetch_property(towncode: str, uniqueid: str, town: str) -> dict | None:
    """Fetch and parse a single property page."""
    uid_encoded = urllib.parse.quote(uniqueid)
    url = f"{BASE_URL}/PropertyResults.aspx?towncode={towncode}&uniqueid={uid_encoded}"
    try:
        html = fetch(url)
    except Exception as e:
        print(f"  ERROR fetching uid={uniqueid}: {e}", flush=True)
        return None

    text = extract_text(html)

    # Parcel info
    address = extract_field_after(text, "Location")
    property_use = extract_field_after(text, "Property Use")
    primary_use = extract_field_after(text, "Primary Use")
    mbl = extract_field_after(text, "Map Block Lot")
    extract_field_after(text, "Acres")
    extract_field_after(text, "Zone")

    # Values - parse from the appraised/assessed table
    # Pattern: Total <amount> <amount>
    total_appr = None
    total_assess = None
    total_match = re.search(r"Total\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)", text)
    if total_match:
        total_appr = parse_money(total_match.group(1))
        total_assess = parse_money(total_match.group(2))

    # Owner
    owner_match = re.search(r"Owner's Data\s*\n\s*(.+?)(?:\n\s*(.+?))?\n\s*\d+\s", text)
    owner = None
    co_owner = None
    if owner_match:
        owner = owner_match.group(1).strip()
        if owner_match.group(2):
            co = owner_match.group(2).strip()
            # Check if it's a co-owner (not an address)
            if not re.match(r"\d+\s", co) and "CT" not in co:
                co_owner = co

    # Building info (Building 1 section)
    building_use = extract_field_after(text, "Building Use")
    style = extract_field_after(text, "Style")
    living_area = extract_field_after(text, "Living Area")
    stories = extract_field_after(text, "Stories")
    year_built = extract_field_after(text, "Year Built")
    total_rooms = extract_field_after(text, "Total Rooms")
    bedrooms = extract_field_after(text, "Bedrooms")
    full_baths = extract_field_after(text, "Full Baths")
    half_baths = extract_field_after(text, "Half Baths")

    # Map use_code from property_use/building_use
    use_code = map_use_code(property_use, building_use, primary_use)
    use_desc = building_use or property_use or primary_use

    # Sales history - format: Owner \n Vol \n Page \n MM/DD/YYYY \n DeedType \n $Price
    last_sale_price = None
    last_sale_date = None
    sale_section = text[text.find("Sale Date"):] if "Sale Date" in text else ""
    sale_rows = re.findall(
        r"(\d{2}/\d{2}/\d{4})\s*\n\s*(?:[\w\s]*\n\s*)?\$\s*([\d,]+)",
        sale_section,
    )
    for date_str, price_str in sale_rows:
        price = parse_money(price_str)
        if price and price > 0:
            last_sale_date = date_str
            last_sale_price = price
            break  # First one is most recent

    if not address and not owner:
        return None

    # Generate numeric PID from uniqueid (may be alphanumeric like I14433)
    try:
        pid = int(uniqueid)
    except ValueError:
        # Hash alphanumeric ID to a stable integer (use last 8 digits of hash)
        pid = abs(hash(f"{town}:{uniqueid}")) % 100_000_000

    return {
        "pid": pid,
        "town": town,
        "address": address,
        "mblu": mbl,
        "acct_num": uniqueid,  # Store original unique ID
        "owner": owner,
        "co_owner": co_owner,
        "use_code": use_code,
        "use_desc": use_desc,
        "occupancy": map_occupancy(use_code),
        "appraisal": total_appr,
        "assessment": total_assess,
        "valuation_year": None,
        "year_built": parse_int(year_built),
        "living_area_sqft": parse_int(living_area),
        "style": style,
        "grade": None,
        "stories": parse_float(stories),
        "building_count": None,
        "total_rooms": parse_int(total_rooms),
        "total_bedrooms": parse_int(bedrooms),
        "total_bathrooms": parse_int(full_baths),
        "half_baths": parse_int(half_baths),
        "last_sale_price": last_sale_price,
        "last_sale_date": last_sale_date,
        "lat": None,
        "lng": None,
    }


def map_use_code(property_use: str | None, building_use: str | None, primary_use: str | None) -> str | None:
    """Map PropertyRecordCards use descriptions to VGSI-compatible numeric use codes."""
    bu = (building_use or "").lower().strip()
    pu = (property_use or "").lower().strip()
    pru = (primary_use or "").lower().strip()

    # Check building use first (most specific)
    mapping = {
        "single family": "101",
        "condo": "102",
        "two family": "104",
        "three family": "105",
        "four family": "106",
        "five family": "107",
        "six family": "108",
        "apartment": "111",
        "multi-family": "109",
        "commercial": "400",
        "industrial": "500",
        "retail": "410",
        "office": "420",
        "mixed use": "300",
    }

    for keyword, code in mapping.items():
        if keyword in bu:
            return code
        if keyword in pu:
            return code
        if keyword in pru:
            return code

    # Residential vacant
    if "vacant" in pru or "vacant" in pu:
        if "residential" in pru or "residential" in pu:
            return "190"  # Residential vacant land
        return "900"  # General vacant

    if "residential" in pu or "residential" in pru:
        return "101"  # Default residential to single family

    return None


def map_occupancy(use_code: str | None) -> int | None:
    """Map use code to occupancy/unit count."""
    if not use_code:
        return None
    code_map = {
        "101": 1, "102": 1, "104": 2, "105": 3, "106": 4,
        "107": 5, "108": 6, "109": 4, "111": 10,
    }
    return code_map.get(use_code)


INSERT_SQL = """
INSERT INTO ct_vision_parcels (
    pid, town, address, mblu, acct_num, owner, co_owner,
    use_code, use_desc, occupancy, appraisal, assessment, valuation_year,
    year_built, living_area_sqft, style, grade, stories, building_count,
    total_rooms, total_bedrooms, total_bathrooms, half_baths,
    last_sale_price, last_sale_date, lat, lng
) VALUES (
    %(pid)s, %(town)s, %(address)s, %(mblu)s, %(acct_num)s, %(owner)s, %(co_owner)s,
    %(use_code)s, %(use_desc)s, %(occupancy)s, %(appraisal)s, %(assessment)s, %(valuation_year)s,
    %(year_built)s, %(living_area_sqft)s, %(style)s, %(grade)s, %(stories)s, %(building_count)s,
    %(total_rooms)s, %(total_bedrooms)s, %(total_bathrooms)s, %(half_baths)s,
    %(last_sale_price)s, %(last_sale_date)s, %(lat)s, %(lng)s
)
ON CONFLICT (town, pid) DO UPDATE SET
    address = EXCLUDED.address,
    owner = EXCLUDED.owner,
    co_owner = EXCLUDED.co_owner,
    use_code = EXCLUDED.use_code,
    use_desc = EXCLUDED.use_desc,
    occupancy = EXCLUDED.occupancy,
    appraisal = EXCLUDED.appraisal,
    assessment = EXCLUDED.assessment,
    valuation_year = EXCLUDED.valuation_year,
    year_built = EXCLUDED.year_built,
    living_area_sqft = EXCLUDED.living_area_sqft,
    style = EXCLUDED.style,
    grade = EXCLUDED.grade,
    stories = EXCLUDED.stories,
    building_count = EXCLUDED.building_count,
    total_rooms = EXCLUDED.total_rooms,
    total_bedrooms = EXCLUDED.total_bedrooms,
    total_bathrooms = EXCLUDED.total_bathrooms,
    half_baths = EXCLUDED.half_baths,
    last_sale_price = EXCLUDED.last_sale_price,
    last_sale_date = EXCLUDED.last_sale_date,
    lat = COALESCE(EXCLUDED.lat, ct_vision_parcels.lat),
    lng = COALESCE(EXCLUDED.lng, ct_vision_parcels.lng),
    scraped_at = NOW()
"""


def save_batch(parcels: list[dict], dry_run: bool = False):
    """Save a batch of parcels to the database."""
    if dry_run or not parcels:
        return
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_etl@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            for p in parcels:
                cur.execute(INSERT_SQL, p)
        conn.commit()
    finally:
        conn.close()


def scrape_town(towncode: str, town: str, dry_run: bool = False,
                delay: float = 0.3, batch_size: int = 50) -> dict:
    """Scrape all properties for a town via PropertyRecordCards.com."""
    print(f"\n=== Scraping {town} (towncode={towncode}) from PropertyRecordCards.com ===", flush=True)

    # Step 1: Get all streets
    streets = get_streets(towncode)
    print(f"  Found {len(streets)} streets", flush=True)

    # Step 2: Collect all unique IDs by searching each street
    all_props = {}  # uid -> address
    for i, street in enumerate(streets):
        try:
            props = search_street(towncode, street)
            for uid, addr in props:
                all_props[uid] = addr
            if (i + 1) % 20 == 0 or i == len(streets) - 1:
                print(f"  Searched {i+1}/{len(streets)} streets, {len(all_props)} unique properties found", flush=True)
            time.sleep(delay)
        except Exception as e:
            print(f"  ERROR searching street '{street}': {e}", flush=True)
            time.sleep(1)

    print(f"  Total unique properties: {len(all_props)}", flush=True)

    # Step 3: Fetch each property detail page
    batch = []
    total_parsed = 0
    total_errors = 0

    uids = sorted(all_props.keys())
    for i, uid in enumerate(uids):
        parcel = fetch_property(towncode, uid, town)
        if parcel:
            batch.append(parcel)
            total_parsed += 1
        else:
            total_errors += 1

        if len(batch) >= batch_size:
            save_batch(batch, dry_run)
            print(f"  [{i+1}/{len(uids)}] parsed={total_parsed} errors={total_errors} (batch saved)", flush=True)
            batch = []

        time.sleep(delay)

    # Final batch
    if batch:
        save_batch(batch, dry_run)
        print(f"  Final batch: {len(batch)} parcels saved", flush=True)

    result = {"town": town, "towncode": towncode, "total_found": len(all_props),
              "total_parsed": total_parsed, "total_errors": total_errors}
    print(f"\n  Done: {len(all_props)} properties, {total_parsed} parsed, {total_errors} errors", flush=True)
    return result


# Town codes for our target towns
TOWN_CODES = {
    "RidgefieldCT": "118",
    "SheltonCT": "126",
    "WestonCT": "157",
    "WiltonCT": "161",
    "SimsburyCT": "128",
    "EastonCT": "046",
    "ShermanCT": "127",
    "DanburyCT": "034",
    "New CanaanCT": "090",
    "CheshireCT": "025",
    "FarmingtonCT": "052",
    "GuilfordCT": "060",
    "NorwalkCT": "088",  # Listed as Naugatuck? Need to verify
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape PropertyRecordCards.com")
    parser.add_argument("--towncode", required=True, help="Town code (e.g. 161 for Wilton)")
    parser.add_argument("--town", required=True, help="Town slug for DB (e.g. WiltonCT)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests")
    parser.add_argument("--batch-size", type=int, default=50, help="DB batch size")
    args = parser.parse_args()

    result = scrape_town(
        towncode=args.towncode,
        town=args.town,
        dry_run=args.dry_run,
        delay=args.delay,
        batch_size=args.batch_size,
    )
    print(json.dumps(result))
