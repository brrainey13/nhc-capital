#!/usr/bin/env python3
"""
Scrape VGSI parcel sales history from parcel pages into ct_vision_sales.

Usage:
    python scrape_vgsi_sales.py --town StamfordCT [--delay 0.2] [--dry-run]
    python scrape_vgsi_sales.py --all [--delay 0.2] [--workers 4]

Extracts ALL sale records from each parcel page's sales history section.
"""

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=SSL_CTX))


def fetch_parcel(town: str, pid: int) -> str | None:
    """Fetch a VGSI parcel page."""
    url = f"https://gis.vgsi.com/{town}/Parcel.aspx?pid={pid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NHC Research)"})
        resp = _OPENER.open(req, timeout=15)
        if resp.status == 200:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def extract_sales(html: str, town: str, pid: int) -> list[dict]:
    """Extract all sale records from a parcel page."""
    sales = []

    # Get living area from the page
    living_match = re.search(r'lblBldArea">([^<]+)', html)
    living_area = None
    if living_match:
        sq = living_match.group(1).replace(",", "").strip()
        try:
            living_area = int(float(sq))
        except ValueError:
            pass

    # Find sales history grid table (works for all VGSI layouts)
    grid_match = re.search(
        r'History</legend>.*?<table class="GridViewStyle"[^>]*>(.*?)</table>',
        html, re.DOTALL,
    )
    if not grid_match:
        # Fallback: try original 5-column regex
        sale_rows = re.findall(
            r'<td[^>]*>([^<]+)</td>\s*<td[^>]*>\$?([\d,]+)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>(\d{2}/\d{2}/\d{4})</td>',
            html,
        )
        for owner, price_str, book_page, instrument, date_str in sale_rows:
            owner = owner.strip()
            if not owner or owner == "&nbsp;":
                continue
            price_clean = price_str.replace(",", "").strip()
            price = float(price_clean) if price_clean else None
            sales.append({
                "town": town, "pid": pid, "owner": owner,
                "sale_price": price, "sale_date": date_str,
                "book_page": book_page.strip() if book_page.strip() != "&nbsp;" else None,
                "instrument": instrument.strip() if instrument.strip() != "&nbsp;" else None,
                "living_area_sqft": living_area,
            })
        return sales

    table_html = grid_match.group(1)

    # Get headers to determine column order
    headers = [h.lower().replace("&amp;", "&") for h in re.findall(r'<th[^>]*>([^<]+)</th>', table_html)]

    # Map header names to indices
    col_map = {}
    for i, h in enumerate(headers):
        if "owner" in h:
            col_map["owner"] = i
        elif "price" in h:
            col_map["price"] = i
        elif "book" in h or "page" in h:
            col_map["book_page"] = i
        elif "instrument" in h:
            col_map["instrument"] = i
        elif "date" in h:
            col_map["date"] = i

    if "owner" not in col_map or "date" not in col_map:
        return sales

    # Parse data rows
    rows = re.findall(r'<tr[^>]*class="(?:Row|Alt)[^"]*"[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.I)
    if not rows:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)

    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if len(cells) <= max(col_map.values()):
            continue

        owner = cells[col_map["owner"]]
        if not owner or owner == "&nbsp;":
            continue

        date_str = cells[col_map.get("date", -1)] if "date" in col_map else ""
        if not re.match(r'\d{2}/\d{2}/\d{4}', date_str):
            continue

        price_str = cells[col_map.get("price", -1)] if "price" in col_map else "0"
        price_str = price_str.replace("$", "").replace(",", "").strip()
        price = None
        try:
            price = float(price_str) if price_str else None
        except ValueError:
            pass

        bp = cells[col_map["book_page"]] if "book_page" in col_map and col_map["book_page"] < len(cells) else None
        if bp and bp == "&nbsp;":
            bp = None
        instr = cells[col_map["instrument"]] if "instrument" in col_map and col_map["instrument"] < len(cells) else None
        if instr and instr == "&nbsp;":
            instr = None

        sales.append({
            "town": town, "pid": pid, "owner": owner,
            "sale_price": price, "sale_date": date_str,
            "book_page": bp, "instrument": instr,
            "living_area_sqft": living_area,
        })

    return sales


INSERT_SQL = """
INSERT INTO ct_vision_sales (town, pid, owner, sale_price, sale_date, book_page, instrument, living_area_sqft)
VALUES (%(town)s, %(pid)s, %(owner)s, %(sale_price)s, %(sale_date)s, %(book_page)s, %(instrument)s, %(living_area_sqft)s)
ON CONFLICT (town, pid, sale_date, sale_price) DO NOTHING
"""


def save_sales(sales: list[dict], dry_run: bool = False):
    """Save sales to database."""
    if dry_run or not sales:
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


def get_town_pids(town: str) -> list[int]:
    """Get all PIDs for a town from ct_vision_parcels."""
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_agent@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pid FROM ct_vision_parcels WHERE town = %s ORDER BY pid", (town,))
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_vgsi_towns() -> list[str]:
    """Get all VGSI towns (those that end with CT and are on gis.vgsi.com)."""
    import psycopg2
    conn = psycopg2.connect("postgresql://nhc_agent@localhost:5432/real_estate")
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT town, COUNT(*) as cnt FROM ct_vision_parcels 
                WHERE town NOT IN (SELECT DISTINCT town FROM ct_vision_sales)
                GROUP BY town HAVING COUNT(*) > 100
                ORDER BY cnt DESC
            """)
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def scrape_town_sales(town: str, delay: float = 0.2, dry_run: bool = False, batch_size: int = 200) -> dict:
    """Scrape all sales for a town by iterating through known PIDs."""
    pids = get_town_pids(town)
    print(f"\n=== Scraping sales for {town} ({len(pids)} parcels) ===", flush=True)

    total_sales = 0
    total_saved = 0
    total_errors = 0
    batch = []

    for i, pid in enumerate(pids):
        html = fetch_parcel(town, pid)
        if not html:
            total_errors += 1
            continue

        sales = extract_sales(html, town, pid)
        if sales:
            batch.extend(sales)
            total_sales += len(sales)

        if len(batch) >= batch_size:
            saved = save_sales(batch, dry_run)
            total_saved += saved
            print(f"  [{i+1}/{len(pids)}] sales={total_sales} saved={total_saved} errors={total_errors}", flush=True)
            batch = []

        if (i + 1) % 500 == 0 and not batch:
            print(f"  [{i+1}/{len(pids)}] sales={total_sales} saved={total_saved} errors={total_errors}", flush=True)

        time.sleep(delay)

    # Final batch
    if batch:
        saved = save_sales(batch, dry_run)
        total_saved += saved

    result = {"town": town, "parcels": len(pids), "total_sales": total_sales,
              "saved": total_saved, "errors": total_errors}
    print(f"\n  Done: {total_sales} sales found, {total_saved} saved, {total_errors} errors", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape VGSI sales history")
    parser.add_argument("--town", help="Single town to scrape (e.g. StamfordCT)")
    parser.add_argument("--all", action="store_true", help="Scrape all towns without sales data")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between requests")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    if args.all:
        towns = get_vgsi_towns()
        print(f"Found {len(towns)} towns without sales data")
        for town in towns:
            try:
                result = scrape_town_sales(town, delay=args.delay, dry_run=args.dry_run,
                                           batch_size=args.batch_size)
                print(json.dumps(result))
            except Exception as e:
                print(f"ERROR scraping {town}: {e}", flush=True)
    elif args.town:
        result = scrape_town_sales(args.town, delay=args.delay, dry_run=args.dry_run,
                                   batch_size=args.batch_size)
        print(json.dumps(result))
    else:
        parser.print_help()
