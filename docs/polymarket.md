---
summary: 'Polymarket project — prediction market data, crypto price feeds, BTC up/down models, Pi scanner infrastructure.'
read_when:
  - Working on Polymarket data or models
  - Adding scrapers or API integrations for Polymarket
  - Querying prediction market data
  - Building trading strategies for Polymarket
  - Working with crypto price data
  - Connecting to Raspberry Pi
---

# Polymarket

## Overview

Prediction market trading — focused on BTC/ETH "Up or Down" short-term markets where quantitative models can find edge.

## Architecture

```
Raspberry Pi (hourly cron)          Mac Mini (models + analysis)
  scanner.py → Gamma API              sync_from_pi.sh ← Pi data
  → clawd DB (markets + snapshots)    → polymarket DB
                                       scrape_crypto_bars.py → Alpaca 5-min bars
                                       → crypto_bars_5min table
```

## Database: `polymarket`

Connection: `postgresql://connorrainey@localhost:5432/polymarket`

### Tables

| Table | Rows | Description |
|---|---|---|
| `markets` | 20,258 | Active Polymarket markets (from Gamma API) |
| `market_snapshots` | 870,717 | Hourly price/volume snapshots (123 MB, since 2026-02-14) |
| `crypto_bars_5min` | 17,183 | BTC/USD + ETH/USD 5-min OHLCV candles (Alpaca, 30 days) |
| `positions` | 0 | Trade tracking (future) |
| `theses` | 0 | Investment theses (future) |
| `agent_log` | 0 | Agent action log (future) |
| `human_notes` | 0 | Team notes (future) |

### Market Categories (top 10 by count)

| Category | Markets |
|---|---|
| Sports | 4,109 |
| Esports | 2,311 |
| Politics | 1,401 |
| Crypto | 758 |
| Tennis | 731 |
| Weather | 709 |
| Culture | 673 |
| Up or Down | 536 |
| NBA | 506 |
| NHL | 321 |

## Data Sources

### Gamma API (Polymarket)
- URL: `https://gamma-api.polymarket.com/events`
- Data: markets, outcomes, prices, volumes, liquidity
- Rate: no auth needed, paginated (limit/offset)
- Scanner filters: `active=true`, `closed=false`, volume > $1,000
- **Note:** This is the "easy" API — provides aggregated data, NOT order book depth
- **Missing:** CLOB (Central Limit Order Book) data — bid/ask spreads, order depth, trade history

### Polymarket CLOB API (TODO)
- Docs: `https://docs.polymarket.com`
- Provides: order book depth, real-time trades, order placement
- Requires: API key + wallet signature
- Needed for: actual trading, spread analysis, market microstructure

### Alpaca Crypto Data (Free)
- URL: `https://data.alpaca.markets/v1beta3/crypto/us/bars`
- Data: OHLCV candles (1min to 1day), quotes, trades, order books
- Auth: **No API key needed for historical bars**
- Symbols: BTC/USD, ETH/USD, 20+ more
- Also available: real-time WebSocket streaming (needs free API key)

## Raspberry Pi Setup

- **Host:** `<user>@<tailscale-ip>` (Tailscale)
- **DB:** `clawd` on local Postgres 15, user `postgres` (peer auth)
- **Crons:**
  - `0 * * * *` — `scanner.py` (Gamma API → markets + snapshots)
  - `5 * * * *` — `hockey_scanner.py` (QuantHockey → reports)
  - `0 9 * * *` — `daily_report.py` (summary to stdout/log)
- **Logs:** `/tmp/polymarket_scan.log`, `/tmp/hockey_scan.log`, `/tmp/daily_report.log`

## Scrapers

### `scrapers/scanner.py` (runs on Pi)
Fetches all active markets from Gamma API, upserts to `markets`, logs price snapshots.
Filters out markets with volume < $1,000.

### `scrapers/hockey_scanner.py` (runs on Pi)
Scrapes QuantHockey for goalie stats, identifies hot goalies and pull candidates.
Writes reports to `/tmp/polymarket_hockey_YYYY-MM-DD.txt`.

### `scrapers/scrape_crypto_bars.py` (runs on Mac Mini)
Fetches 5-min BTC/USD and ETH/USD bars from Alpaca (free, no API key).
```bash
python scrapers/scrape_crypto_bars.py --days 30   # Backfill 30 days
python scrapers/scrape_crypto_bars.py              # Last 24h (default)
```

### `scrapers/sync_from_pi.sh`
Pulls latest market + snapshot data from Pi to Mac Mini's `polymarket` DB.
```bash
polymarket/scrapers/sync_from_pi.sh
```

## Strategy: BTC 5-Min Up/Down

### The Opportunity
Polymarket runs "Bitcoin Up or Down" markets that resolve on hourly/daily timeframes.
These markets have high volume ($500K-$800K per market) and price ~50/50 when created.

### The Edge
- **5-min Alpaca bars** give us real-time price momentum that lags behind Polymarket odds
- **Historical snapshots** let us backtest: when BTC moved X% in 5-min, how did the market resolve?
- **Volume/liquidity patterns** may signal informed trading
- The market makers on Polymarket are good but not perfect — short-term momentum signals can exploit latency

### Next Steps
1. Build feature matrix: 5-min bars → rolling momentum, volatility, volume signals
2. Match crypto bars to Polymarket "Up or Down" market resolution times
3. Backtest: can momentum at time T predict resolution at T+1h or T+24h?
4. Set up CLOB API for actual order placement (needs wallet)
5. Paper trade → live trade on Base chain
