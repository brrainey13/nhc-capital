"""
Scrape exact unit counts from VGSI detail pages for parcels with use_code > 104.
Extracts the 'Occupancy' field from the property detail page.
"""

import json
import re
import ssl
import time
import urllib.request

import psycopg2
import psycopg2.extras

DB_RO = "postgresql://nhc_agent@localhost:5432/real_estate"
DB_RW = "postgresql://nhc_etl@localhost:5432/real_estate"


def fetch_occupancy(town: str, pid: int) -> int | None:
    """Fetch occupancy from VGSI detail page."""
    url = f"https://gis.vgsi.com/{town}/Parcel.aspx?pid={pid}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  FETCH ERROR {town} pid={pid}: {e}", flush=True)
        return None

    # Pattern: <td>Occupancy</td><td>VALUE</td> or with colon
    m = re.search(
        r"<td>\s*Occupancy:?\s*</td>\s*<td>\s*([\d.]+)\s*</td>",
        html,
        re.IGNORECASE,
    )
    if m:
        try:
            return int(float(m.group(1)))
        except ValueError:
            return None

    # Try "# of Units" or "Number of Units" pattern
    m = re.search(
        r"(?:#\s*of\s*Units|Number\s*of\s*Units|Total\s*Units):?\s*</td>\s*<td>\s*([\d.]+)",
        html,
        re.IGNORECASE,
    )
    if m:
        try:
            return int(float(m.group(1)))
        except ValueError:
            return None

    return None


def run(town: str = None, delay: float = 0.15, limit: int = 100000):
    """Scrape unit counts for parcels with use_code > 104 missing unit_count."""
    conn_ro = psycopg2.connect(DB_RO)
    conn_rw = psycopg2.connect(DB_RW)

    cur_ro = conn_ro.cursor()

    where_town = "AND town = %s" if town else ""
    params = [town, limit] if town else [limit]
    cur_ro.execute(f"""
        SELECT pid, town, address, use_code, use_desc
        FROM ct_vision_parcels
        WHERE COALESCE(unit_count, occupancy) IS NULL
          AND use_code IN (
            '105','106','107','108','109','110','111','112',
            '800','801','814','861','862'
          )
          {where_town}
        ORDER BY town, pid
        LIMIT %s
    """, params)
    parcels = cur_ro.fetchall()
    total = len(parcels)
    print(f"Found {total} parcels needing unit count audit", flush=True)

    updated = 0
    skipped = 0
    failed = 0
    batch = []

    for i, (pid, t, addr, code, desc) in enumerate(parcels):
        occ = fetch_occupancy(t, pid)
        if occ is not None and occ > 0:
            batch.append((occ, occ, t, pid))
            updated += 1
        elif occ == 0:
            skipped += 1
        else:
            failed += 1

        if len(batch) >= 50:
            cur_rw = conn_rw.cursor()
            psycopg2.extras.execute_batch(
                cur_rw,
                """UPDATE ct_vision_parcels
                   SET unit_count = %s, occupancy = %s
                   WHERE town = %s AND pid = %s""",
                batch,
            )
            conn_rw.commit()
            cur_rw.close()
            print(
                f"  [{i+1}/{total}] saved={updated} skipped={skipped} "
                f"failed={failed} (batch saved)",
                flush=True,
            )
            batch = []

        time.sleep(delay)

    # Final batch
    if batch:
        cur_rw = conn_rw.cursor()
        psycopg2.extras.execute_batch(
            cur_rw,
            """UPDATE ct_vision_parcels
               SET unit_count = %s, occupancy = %s
               WHERE town = %s AND pid = %s""",
            batch,
        )
        conn_rw.commit()
        cur_rw.close()

    conn_ro.close()
    conn_rw.close()

    result = {
        "total": total,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
    }
    print(f"DONE: {json.dumps(result)}", flush=True)
    return result


if __name__ == "__main__":
    import sys
    town = sys.argv[1] if len(sys.argv) > 1 else None
    run(town=town, delay=0.1)
