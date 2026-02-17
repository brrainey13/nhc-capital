# Polymarket

Prediction market data & trading — focused on BTC/ETH short-term "Up or Down" markets.

## Setup

```bash
cd polymarket
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Database (Mac Mini)
psql -d polymarket -f sql/schema.sql
psql -d polymarket -f sql/crypto_prices.sql

# Sync data from Raspberry Pi
scrapers/sync_from_pi.sh

# Backfill crypto prices (Alpaca, free)
.venv/bin/python scrapers/scrape_crypto_bars.py --days 30
```

## Data

- **20K+ markets** from Polymarket Gamma API (hourly via Pi scanner)
- **870K+ price snapshots** (hourly, 123 MB, since 2026-02-14)
- **17K+ crypto bars** (5-min BTC/USD + ETH/USD from Alpaca)

## Architecture

- **Raspberry Pi** (`brainey@100.111.154.65`): hourly scanners → `clawd` DB
- **Mac Mini**: `polymarket` DB, models, analysis
- **Sync**: `scrapers/sync_from_pi.sh` pulls Pi data to Mac Mini

See `docs/polymarket.md` for full details.
