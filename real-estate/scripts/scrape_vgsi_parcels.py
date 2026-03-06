#!/usr/bin/env python3
"""
Scrape Vision Government Solutions (VGSI) parcel data for CT towns.

Usage:
    python scrape_vgsi_parcels.py --town BridgeportCT --min-units 0 [--dry-run] [--max-pid 40000]

Reconstructed from bytecode (.pyc) — original functions: fetch_parcel, extract_between,
extract_field, extract_span, parse_parcel, save_batch, is_residential, scrape_town.
"""

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

# Disable SSL verification for VGSI (their cert chain is sometimes broken)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Prevent following redirects — VGSI redirects invalid PIDs."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=SSL_CTX))


def geocode_address(address: str, town: str) -> tuple[float | None, float | None]:
    """Geocode an address using Photon (free, OSM-based). Returns (lat, lng) or (None, None)."""
    town_clean = town.replace("CT", "").strip()
    query = f"{address}, {town_clean}, CT"
    url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(query)}&limit=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NHC-Capital-Research/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("features"):
                coords = data["features"][0]["geometry"]["coordinates"]
                return (coords[1], coords[0])  # lat, lng
    except Exception:
        pass
    return (None, None)


def fetch_parcel(town: str, pid: int) -> str | None:
    """Fetch a single parcel page. Returns HTML or None on error/redirect."""
    url = f"https://gis.vgsi.com/{town}/Parcel.aspx?pid={pid}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (NHC Capital Research Bot)"
        })
        resp = _OPENER.open(req, timeout=15)
        if resp.status == 200:
            return resp.read().decode("utf-8", errors="replace")
        return None
    except urllib.error.HTTPError:
        return None  # 302 redirect = invalid PID
    except Exception:
        return None


def extract_between(html: str, start: str, end: str) -> str | None:
    """Extract text between two markers."""
    i = html.find(start)
    if i < 0:
        return None
    i += len(start)
    j = html.find(end, i)
    if j < 0:
        return None
    return html[i:j].strip()


def extract_field(html: str, span_id: str) -> str | None:
    """Extract value from <span id="...">value</span>."""
    pattern = f'id="{span_id}"[^>]*>([^<]*)</span>'
    m = re.search(pattern, html, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_span(html: str, label: str) -> str | None:
    """Extract value from a label: value pattern in the page."""
    pattern = rf'{label}\s*</?\w[^>]*>\s*([^<]+)'
    m = re.search(pattern, html, re.IGNORECASE)
    return m.group(1).strip() if m else None


def parse_parcel(html: str, town: str, pid: int) -> dict | None:
    """Parse a VGSI parcel page into a dict. Returns None if page is invalid."""
    if not html or "Parcel not found" in html or "No data" in html:
        return None

    def parse_money(s: str | None) -> float | None:
        if not s:
            return None
        s = s.replace("$", "").replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None

    def parse_room_field(label: str) -> int | None:
        val = extract_span(html, label)
        if not val:
            return None
        m = re.search(r'\d+', val)
        return int(m.group()) if m else None

    # Core fields from span IDs
    address = extract_field(html, "MainContent_lblLocation")
    owner = extract_field(html, "MainContent_lblOwner")
    co_owner = extract_field(html, "MainContent_lblCoOwner")
    mblu = extract_field(html, "MainContent_lblMblu")
    acct_num = extract_field(html, "MainContent_lblAcctNum")
    use_code = extract_field(html, "MainContent_lblUseCode")
    use_desc = extract_field(html, "MainContent_lblUseCodeDescription")

    # Valuation
    appraisal = parse_money(extract_field(html, "MainContent_lblGenAppraisal") or extract_field(html, "MainContent_lblAppraisal"))
    assessment = parse_money(extract_field(html, "MainContent_lblGenAssessment") or extract_field(html, "MainContent_lblAssessment"))
    val_year_str = extract_field(html, "MainContent_lblValuationYear")
    valuation_year = int(val_year_str) if val_year_str and val_year_str.isdigit() else None

    # Building details
    year_built_m = re.search(r'lblYearBuilt">(\d+)', html)
    year_built = int(year_built_m.group(1)) if year_built_m else None

    living_match = re.search(r'lblBldArea">([^<]+)', html)
    living_area_sqft = None
    if living_match:
        sq = living_match.group(1).replace(",", "").strip()
        try:
            living_area_sqft = int(float(sq))
        except ValueError:
            pass

    style = extract_span(html, "Style")
    grade = extract_span(html, "Grade")
    occupancy_str = extract_span(html, "Occupancy")
    occupancy = None
    if occupancy_str:
        m = re.search(r'\d+', occupancy_str)
        occupancy = int(m.group()) if m else None

    stories_str = extract_span(html, "Stories")
    stories = None
    if stories_str:
        try:
            stories = float(stories_str)
        except ValueError:
            pass

    building_count_str = extract_field(html, "MainContent_lblBldCount") or extract_field(html, "MainContent_lblBldgCount")
    building_count = None
    if building_count_str:
        m = re.search(r'\d+', building_count_str)
        building_count = int(m.group()) if m else None

    total_rooms = parse_room_field("Total Rooms")
    total_bedrooms = parse_room_field("Total Bedrms") or parse_room_field("Total Bedrooms")
    total_bathrooms = parse_room_field("Total Bthrms")
    half_baths = parse_room_field("Total Half Baths")

    # Last sale
    sale_price_m = re.search(r'Sale Price.*?\$([0-9,]+)', html, re.DOTALL)
    last_sale_price = parse_money(sale_price_m.group(1)) if sale_price_m else None
    sale_date_m = re.search(r'Sale Date.*?(\d{2}/\d{2}/\d{4})', html, re.DOTALL)
    last_sale_date = sale_date_m.group(1) if sale_date_m else None

    if not address and not owner:
        return None

    # Geocoding handled separately in batch for speed
    lat, lng = None, None

    return {
        "pid": pid,
        "town": town,
        "address": address,
        "mblu": mblu,
        "acct_num": acct_num,
        "owner": owner,
        "co_owner": co_owner,
        "use_code": use_code,
        "use_desc": use_desc,
        "occupancy": occupancy,
        "appraisal": appraisal,
        "assessment": assessment,
        "valuation_year": valuation_year,
        "year_built": year_built,
        "living_area_sqft": living_area_sqft,
        "style": style,
        "grade": grade,
        "stories": stories,
        "building_count": building_count,
        "total_rooms": total_rooms,
        "total_bedrooms": total_bedrooms,
        "total_bathrooms": total_bathrooms,
        "half_baths": half_baths,
        "last_sale_price": last_sale_price,
        "last_sale_date": last_sale_date,
        "lat": lat,
        "lng": lng,
    }


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ct_vision_parcels (
    id                  SERIAL PRIMARY KEY,
    pid                 INTEGER NOT NULL,
    town                VARCHAR(50) NOT NULL,
    address             TEXT,
    mblu                VARCHAR(100),
    acct_num            VARCHAR(50),
    owner               TEXT,
    co_owner            Text,
    use_code            VARCHAR(20),
    use_desc            VARCHAR(100),
    occupancy           INTEGER,
    appraisal           NUMERIC(14,2),
    assessment          NUMERIC(14,2),
    valuation_year      INTEGER,
    year_built          INTEGER,
    living_area_sqft    INTEGER,
    style               VARCHAR(100),
    grade               VARCHAR(50),
    stories             NUMERIC(4,1),
    building_count      INTEGER,
    total_rooms         INTEGER,
    total_bedrooms      INTEGER,
    total_bathrooms     INTEGER,
    half_baths          INTEGER,
    last_sale_price     NUMERIC(14,2),
    last_sale_date      VARCHAR(20),
    scraped_at          TIMESTAMPTZ DEFAULT NOW(),
    unit_count          INTEGER,
    lat                 DOUBLE PRECISION,
    lng                 DOUBLE PRECISION,
    UNIQUE(town, pid)
);
CREATE INDEX IF NOT EXISTS idx_cvp_town ON ct_vision_parcels(town);
CREATE INDEX IF NOT EXISTS idx_cvp_occupancy ON ct_vision_parcels(occupancy);
CREATE INDEX IF NOT EXISTS idx_cvp_use_code ON ct_vision_parcels(use_code);
CREATE INDEX IF NOT EXISTS idx_cvp_address ON ct_vision_parcels(address);
"""

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

# Residential use codes (4-char and 3-char)
RESIDENTIAL_USE_CODES = set(range(100, 200))
RESIDENTIAL_USE_CODES_4DIGIT = set(range(1000, 2000))


def is_residential(parcel: dict) -> bool:
    """Check if parcel is residential based on use code."""
    code = parcel.get("use_code") or ""
    code_clean = re.sub(r'\D', '', code)
    if not code_clean:
        return True  # default to include if no code
    code_int = int(code_clean)
    return code_int in RESIDENTIAL_USE_CODES or code_int in RESIDENTIAL_USE_CODES_4DIGIT


def save_batch(parcels: list[dict], dry_run: bool = False):
    """Save a batch of parcels to the database."""
    if dry_run or not parcels:
        return
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_etl@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            # Table already exists — skip CREATE to avoid permission issues with nhc_etl
            for p in parcels:
                cur.execute(INSERT_SQL, p)
        conn.commit()
    finally:
        conn.close()


def scrape_town(town: str, min_units: int = 0, max_pid: int = 50000,
                dry_run: bool = False, delay: float = 0.3, batch_size: int = 100,
                start_pid: int = 1) -> dict:
    """Scrape all parcels for a town, filtering by unit count."""
    print(f"\n=== Scraping {town} (pid={start_pid}..{max_pid}, min_units={min_units}) ===", flush=True)

    batch = []
    total_found = 0
    total_saved = 0
    consecutive_errors = 0
    max_consecutive = 200

    for pid in range(start_pid, max_pid + 1):
        html = fetch_parcel(town, pid)
        if not html:
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive:
                print(f"  200 consecutive errors at pid={pid}, stopping.", flush=True)
                break
            continue

        parcel = parse_parcel(html, town, pid)
        if not parcel:
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive:
                print(f"  200 consecutive errors at pid={pid}, stopping.", flush=True)
                break
            continue

        consecutive_errors = 0
        total_found += 1

        # Filter by min units if specified
        occ = parcel.get("occupancy") or 1
        if min_units > 0 and occ < min_units:
            continue

        batch.append(parcel)
        total_saved += 1

        if len(batch) >= batch_size:
            save_batch(batch, dry_run)
            print(f"  pid={pid} | found={total_found} | saved={total_saved} | batch={len(batch)}", flush=True)
            batch = []

        time.sleep(delay)

    # Final batch
    if batch:
        save_batch(batch, dry_run)
        print(f"  Final batch: saved {len(batch)} parcels", flush=True)

    result = {"town": town, "total_found": total_found, "total_saved": total_saved}
    print(f"\n  Done: {total_found} found, {total_saved} saved", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape VGSI parcel data")
    parser.add_argument("--town", required=True, help="Town slug, e.g. BridgeportCT")
    parser.add_argument("--min-units", type=int, default=0, help="Min occupancy/units filter")
    parser.add_argument("--max-pid", type=int, default=50000, help="Max PID to scan")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests (seconds)")
    parser.add_argument("--batch-size", type=int, default=100, help="DB batch size")
    args = parser.parse_args()

    result = scrape_town(
        town=args.town,
        min_units=args.min_units,
        max_pid=args.max_pid,
        dry_run=args.dry_run,
        delay=args.delay,
        batch_size=args.batch_size,
    )
    print(json.dumps(result))
