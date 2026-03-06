#!/usr/bin/env python3
"""
Check foreclosure auction results by matching against VGSI sales data.

For each foreclosure past its 30-35 day close window, looks up the property
in ct_vision_sales to find if a sale was recorded after the auction date.

Run via cron every Monday/Friday alongside the foreclosure scraper.
"""

import json
import re
from datetime import date

import psycopg2
import psycopg2.extras

DB_RO = "postgresql://nhc_agent@localhost:5432/real_estate"
DB_RW = "postgresql://nhc_etl@localhost:5432/real_estate"


def normalize_address(addr: str) -> str:
    """Normalize address for fuzzy matching."""
    if not addr:
        return ""
    a = addr.upper().strip()
    # Remove unit/apt/building suffixes
    a = re.sub(r'\s*(UNIT|APT|#|BLDG|BUILDING|SUITE)\s*\S+.*$', '', a)
    # Remove city/state/zip
    a = re.sub(r',\s*(CT|CONNECTICUT).*$', '', a)
    a = re.sub(r',\s*\w+\s*,?\s*(CT|CONNECTICUT)?.*$', '', a)
    # Normalize spacing
    a = re.sub(r'\s+', ' ', a).strip()
    return a


def normalize_town(town: str) -> str:
    """Convert 'New Haven' to 'NewHavenCT' format."""
    if not town:
        return ""
    t = town.strip()
    # Already in DB format
    if t.endswith("CT"):
        return t
    # Convert spaces
    t = t.title().replace(" ", "")
    return f"{t}CT"


def check_vgsi_sales(conn_ro, town_db: str, address: str,
                     auction_date: date) -> dict | None:
    """Look up sale in ct_vision_sales after auction date."""
    norm_addr = normalize_address(address)
    if not norm_addr or not town_db:
        return None

    cur = conn_ro.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Extract street number and name for matching
    parts = norm_addr.split(' ', 1)
    if len(parts) < 2:
        return None
    street_num = parts[0]
    street_name = parts[1]

    # Search in ct_vision_parcels first to find matching PID
    cur.execute("""
        SELECT pid, address FROM ct_vision_parcels
        WHERE town = %s AND UPPER(address) LIKE %s
        LIMIT 5
    """, (town_db, f"%{street_num} {street_name}%"))
    parcels = cur.fetchall()

    if not parcels:
        # Try with just street number
        cur.execute("""
            SELECT pid, address FROM ct_vision_parcels
            WHERE town = %s AND UPPER(address) LIKE %s
            LIMIT 5
        """, (town_db, f"{street_num}%{street_name.split()[0]}%"))
        parcels = cur.fetchall()

    if not parcels:
        return None

    # Check sales for matched parcels after auction date
    for parcel in parcels:
        cur.execute("""
            SELECT sale_price, sale_date, owner, book_page, instrument
            FROM ct_vision_sales
            WHERE town = %s AND pid = %s AND sale_date >= %s
            ORDER BY sale_date ASC
            LIMIT 1
        """, (town_db, parcel["pid"], auction_date))
        sale = cur.fetchone()
        if sale and sale["sale_price"] and sale["sale_price"] > 0:
            return {
                "sale_price": float(sale["sale_price"]),
                "sale_date": sale["sale_date"],
                "buyer": sale["owner"],
                "book_page": sale["book_page"],
                "source": "vgsi",
            }

    return None


def run():
    """Check all pending foreclosure results that are past their check date."""
    conn_ro = psycopg2.connect(DB_RO)
    conn_rw = psycopg2.connect(DB_RW)

    cur_ro = conn_ro.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Get pending results ready to check
    cur_ro.execute("""
        SELECT id, foreclosure_id, town, address, auction_date, check_amount
        FROM ct_foreclosure_results
        WHERE status = 'pending'
          AND next_check_date <= CURRENT_DATE
        ORDER BY auction_date
    """)
    pending = cur_ro.fetchall()
    print(f"Found {len(pending)} foreclosures ready to check", flush=True)

    found = 0
    not_found = 0
    errors = 0

    for row in pending:
        town_db = normalize_town(row["town"])
        try:
            result = check_vgsi_sales(
                conn_ro, town_db, row["address"], row["auction_date"]
            )
        except Exception as e:
            print(f"  ERROR {row['address']}: {e}", flush=True)
            errors += 1
            continue

        cur_rw = conn_rw.cursor()
        if result:
            cur_rw.execute("""
                UPDATE ct_foreclosure_results
                SET sale_price = %s, sale_date = %s, buyer = %s,
                    book_page = %s, source = %s, status = 'sold',
                    last_checked_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, (
                result["sale_price"], result["sale_date"],
                result["buyer"], result["book_page"],
                result["source"], row["id"]
            ))
            found += 1
            print(
                f"  ✓ {row['address']} — "
                f"${result['sale_price']:,.0f} on {result['sale_date']}",
                flush=True,
            )
        else:
            # Push check date out another 14 days
            cur_rw.execute("""
                UPDATE ct_foreclosure_results
                SET next_check_date = CURRENT_DATE + 14,
                    last_checked_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, (row["id"],))
            not_found += 1

        conn_rw.commit()
        cur_rw.close()

    conn_ro.close()
    conn_rw.close()

    summary = {
        "checked": len(pending),
        "found": found,
        "not_found": not_found,
        "errors": errors,
    }
    print(f"\nDONE: {json.dumps(summary)}", flush=True)
    return summary


if __name__ == "__main__":
    run()
