---
title: API Reference
summary: 'Dashboard REST API endpoints — ingest, query, tables, comps, usage.'
category: infrastructure
updated: 2026-02-20
read_when:
  - Building or modifying API endpoints
  - Integrating with the dashboard API
---

# NHC Admin Dashboard — API Reference

Base URL: `http://localhost:8000` (or your Cloudflare/deploy URL)

Authentication: Cloudflare Access OR `X-API-Key` header / `?api_key=` query param.

## Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/health` | No | Returns `{"status": "ok"}` |

## Databases & Tables

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/databases` | Yes | List available databases |
| POST | `/api/query` | Yes | Execute read-only SQL. Body: `{"sql": "...", "db": "nhl_betting"}` |
| GET | `/api/tables` | Yes | List all tables with row counts |
| GET | `/api/tables/{name}/schema` | Yes | Column names and types |
| GET | `/api/tables/{name}/data` | Yes | Paginated data. Query: `?limit=100&offset=0&sort=col&order=asc&filter_col=val` |
| GET | `/api/tables/{name}/grouped` | Yes | Group-by aggregation. Query: `?group_by=col` |
| GET | `/api/tables/{name}/distinct` | Yes | Distinct values for a column. Query: `?column=col` |
| GET | `/api/tables/{name}/examples` | Yes | Sample rows with smart formatting |
| GET | `/api/tables/{name}/preview` | Yes | Quick preview (first N rows) |

## Real Estate

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/real-estate/foreclosures` | Yes | CT foreclosure listings. Query: `?limit=500` |
| GET | `/api/real-estate/comp-rules` | Yes | Comp rules for a foreclosure. Query: `?foreclosure_id=123` |
| GET | `/api/real-estate/multifamily-points` | Yes | Multifamily map data. Query: `?bucket=2_4&limit=20000` |
| GET | `/api/real-estate/comps` | Yes | Comparable sales. Query: `?foreclosure_id=123&limit=2000` |

## Usage & Telemetry

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/usage` | Yes | OpenClaw session stats, token usage |
| GET | `/api/usage/claude-limits` | Yes | Claude API usage and rate limits |

## NHL Bankroll

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/nhl/bankroll` | Yes | Current bankroll balance plus recent ledger entries |
| GET | `/api/nhl/bankroll/history` | Yes | End-of-day bankroll balance history |
| POST | `/api/nhl/bankroll/deposit` | Yes | Add a bankroll deposit. Body: `{"amount": 100, "sportsbook": "DraftKings", "notes": "..."}` |
| POST | `/api/nhl/bankroll/withdrawal` | Yes | Add a bankroll withdrawal. Body matches deposit |
| GET | `/api/nhl/bankroll/summary` | Yes | Daily P/L, end-of-day balance series, win rate, ROI |

## Data Ingestion (POST)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/ingest/tables` | Yes | List tables available for ingestion |
| POST | `/api/ingest/rows` | Yes | Insert rows via ETL role |

### POST `/api/ingest/rows`

```json
{
  "db": "nhl_betting",
  "table": "odds_snapshots",
  "rows": [
    {"game_id": "2026020101", "market": "ml", "price": -150, "side": "home"},
    {"game_id": "2026020101", "market": "ml", "price": 130, "side": "away"}
  ],
  "on_conflict": "(game_id, market, side) DO NOTHING"
}
```

**Allowed ingest tables:**
- `nhl_betting`: odds_snapshots, game_results, injuries, goalie_advanced
- `polymarket`: markets, market_snapshots, crypto_bars
- `real_estate`: data_refresh_log

## curl Examples

```bash
# Health check
curl http://localhost:8000/api/health

# List tables (with API key)
curl -H "X-API-Key: $DASHBOARD_API_KEY" http://localhost:8000/api/tables

# Run a query
curl -X POST http://localhost:8000/api/query \
  -H "X-API-Key: $DASHBOARD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT COUNT(*) FROM games", "db": "nhl_betting"}'

# Ingest data
curl -X POST http://localhost:8000/api/ingest/rows \
  -H "X-API-Key: $DASHBOARD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"db": "polymarket", "table": "markets", "rows": [{"condition_id": "abc", "question": "test"}]}'
```
