import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import requests

from lib.db import get_conn

GAMMA_URL = "https://gamma-api.polymarket.com/events"


def fetch_all_events():
    all_events = []
    offset = 0
    limit = 100

    while True:
        r = requests.get(GAMMA_URL, params={
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset
        })
        r.raise_for_status()
        batch = r.json()

        if not batch:
            break

        all_events.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    return all_events


def parse_outcome_prices(raw):
    if raw is None:
        return None, None
    try:
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw
        yes_price = float(parsed[0]) if len(parsed) > 0 else None
        no_price = float(parsed[1]) if len(parsed) > 1 else None
        return yes_price, no_price
    except (json.JSONDecodeError, ValueError, IndexError, TypeError):
        return None, None


def upsert_market(cur, market, event):
    yes_price, no_price = parse_outcome_prices(market.get("outcomePrices"))
    vol_24h = float(market.get("volume24hr", 0) or 0)
    liq = float(market.get("liquidityNum", 0) or 0)

    tags = event.get("tags", [])
    category = None
    if tags and isinstance(tags, list) and len(tags) > 0:
        if isinstance(tags[0], dict):
            category = tags[0].get("label")
        elif isinstance(tags[0], str):
            category = tags[0]

    market_id = str(market.get("id", ""))

    cur.execute("""
        INSERT INTO markets (
            polymarket_id, question, description, category,
            end_date, yes_price, no_price, volume_24h,
            liquidity, last_updated
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (polymarket_id) DO UPDATE SET
            yes_price = EXCLUDED.yes_price,
            no_price = EXCLUDED.no_price,
            volume_24h = EXCLUDED.volume_24h,
            liquidity = EXCLUDED.liquidity,
            last_updated = NOW()
    """, (
        market_id,
        market.get("question", ""),
        event.get("description", ""),
        category,
        event.get("endDate"),
        yes_price, no_price,
        vol_24h,
        liq,
        datetime.utcnow()
    ))

    # Log price snapshot for historical tracking
    cur.execute("""
        INSERT INTO market_snapshots (market_id, yes_price, no_price, volume_24h, liquidity)
        VALUES (%s, %s, %s, %s, %s)
    """, (market_id, yes_price, no_price, vol_24h, liq))


def main():
    events = fetch_all_events()

    conn = get_conn(db="clawd")
    cur = conn.cursor()

    count = 0
    skipped = 0
    for event in events:
        for market in event.get("markets", []):
            vol = float(market.get("volumeNum", 0) or 0)
            if vol < 1000:
                skipped += 1
                continue
            upsert_market(cur, market, event)
            count += 1

    conn.commit()
    cur.close()
    conn.close()
    print(
        f"[{datetime.utcnow().isoformat()}] Done. "
        f"Upserted {count} markets ({count} snapshots), skipped {skipped} low-volume."
    )


if __name__ == "__main__":
    main()
