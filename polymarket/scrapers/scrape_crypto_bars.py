
#!/usr/bin/env python3
"""Scrape 5-minute BTC/USD and ETH/USD bars from Alpaca (free, no API key).

Usage:
    python scrapers/scrape_crypto_bars.py                    # Last 24h
    python scrapers/scrape_crypto_bars.py --days 7           # Last 7 days
    python scrapers/scrape_crypto_bars.py --start 2026-01-01 # From date

Stores data in polymarket.crypto_bars_5min on localhost.
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.db import get_conn

BASE_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
SYMBOLS = ["BTC/USD", "ETH/USD"]
TIMEFRAME = "5Min"
LIMIT = 10000  # max per request


def fetch_bars(symbol: str, start: str, end: str, page_token: str | None = None):
    """Fetch bars from Alpaca API."""
    params = f"symbols={symbol}&timeframe={TIMEFRAME}&start={start}&end={end}&limit={LIMIT}"
    if page_token:
        params += f"&page_token={page_token}"
    url = f"{BASE_URL}?{params}"

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def scrape_symbol(cur, symbol: str, start_dt: datetime, end_dt: datetime):
    """Scrape all bars for a symbol in the date range."""
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    total = 0
    page_token = None

    while True:
        data = fetch_bars(symbol, start_str, end_str, page_token)
        bars = data.get("bars", {}).get(symbol, [])

        if not bars:
            break

        for bar in bars:
            cur.execute(
                """
                INSERT INTO crypto_bars_5min
                    (symbol, ts, open, high, low, close, volume, vwap, trade_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, ts) DO UPDATE SET
                    open = EXCLUDED.open, high = EXCLUDED.high,
                    low = EXCLUDED.low, close = EXCLUDED.close,
                    volume = EXCLUDED.volume, vwap = EXCLUDED.vwap,
                    trade_count = EXCLUDED.trade_count
                """,
                (
                    symbol, bar["t"],
                    bar["o"], bar["h"], bar["l"], bar["c"],
                    bar["v"], bar["vw"], bar["n"],
                ),
            )
            total += 1

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return total


def main():
    parser = argparse.ArgumentParser(description="Scrape Alpaca crypto 5-min bars")
    parser.add_argument("--days", type=int, default=1, help="Days of history (default: 1)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    args = parser.parse_args()

    end_dt = datetime.now(timezone.utc)
    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start_dt = end_dt - timedelta(days=args.days)

    conn = get_conn(db="polymarket")
    cur = conn.cursor()

    for symbol in SYMBOLS:
        count = scrape_symbol(cur, symbol, start_dt, end_dt)
        print(f"[{datetime.now(timezone.utc).isoformat()}] {symbol}: {count} bars")

    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
