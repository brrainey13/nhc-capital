# CLAUDE.md — Polymarket


> ⚠️ **All changes must go through GitHub pull requests.** Never push to `main` directly. See root `CLAUDE.md` for the full PR workflow.

## Code Review Tools

When your PR is open, NHC runs automated LLM review via `scripts/mr-review`.
- Reviews are SHA-tagged — new pushes invalidate old reviews
- Model chain: Kimi K2.5 → GLM5 → OpenRouter free → DeepSeek V3.2
- Critical findings block approval; warnings/info are advisory
- To run locally: `export $(grep -v '^#' admin-dashboard/.env | xargs) && scripts/mr-review <PR_NUMBER>`
- API keys in `admin-dashboard/.env` (gitignored). GitHub auth comes from `gh auth`.

Read `docs/polymarket.md` for full schema, scraper docs, and project status.

## Quick Context

- **Python:** `polymarket/.venv/bin/python` — **always use this, never system Python**
- **Setup:** `cd polymarket && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- **DB:** `polymarket` @ localhost:5432 (Mac Mini). Separate from `nhl_betting`.
- **psql:** `/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql -d polymarket`
- **Data source (Pi):** Raspberry Pi (`<user>@<tailscale-ip>`) runs hourly crons → `clawd` DB
- **Sync:** `scrapers/sync_from_pi.sh` pulls Pi data to local `polymarket` DB

## Key Tables

| Table | Rows | Source | Notes |
|---|---|---|---|
| `markets` | 20K+ | Pi scanner (Gamma API) | Active Polymarket markets |
| `market_snapshots` | 870K+ | Pi scanner (hourly) | Price/volume history |
| `crypto_bars_5min` | 17K+ | Alpaca (free, no key) | BTC/USD + ETH/USD 5-min candles |
| `positions` | 0 | — | Trade tracking (future) |
| `theses` | 0 | — | Investment theses (future) |
| `agent_log` | 0 | — | Agent action log (future) |
| `human_notes` | 0 | — | Team notes (future) |

## Scrapers

| Script | Runs | Source | Target |
|---|---|---|---|
| `scrapers/scanner.py` | Pi hourly cron | Gamma API | markets + snapshots |
| `scrapers/hockey_scanner.py` | Pi hourly cron | QuantHockey | Reports only |
| `scrapers/daily_report.py` | Pi 9AM UTC cron | Local DB | stdout |
| `scrapers/scrape_crypto_bars.py` | Mac Mini (manual/cron) | Alpaca free API | crypto_bars_5min |
| `scrapers/sync_from_pi.sh` | Manual | Pi → Mac Mini | markets + snapshots |

## Focus: BTC 5-Min Up/Down Markets

Polymarket has high-volume "Bitcoin Up or Down" markets resolving on hourly/daily timeframes.
The edge: combine 5-min Alpaca price bars with Polymarket odds to find mispriced short-term markets.

## Rules

- **Never commit model artifacts** — gitignored
- **Update `docs/polymarket.md`** when you add tables, scrapers, or change schema
- **Pi scripts are the source of truth** — edit on Pi or in this repo (then deploy to Pi)
- **`make ci` before commit** — always
