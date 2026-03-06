# Real Estate

Cook County property data ETL and investment analysis.

## Status
- **Database**: `cook_county` (Postgres, localhost:5432)
- **Stage**: Cook County ETL ready — parcel_universe, parcel_sales, commercial_valuations

## Layout

- **config/** — API and database config (see `config/database.yml.example`)
- **schema/** — `cook_county.md`: single source of truth for table definitions
- **scripts/** — ETL entrypoints:
  - `run_etl.py` — Orchestrator: run one or all datasets
  - `etl_parcel_universe.py` — SODA API `nj4t-kc8j` → `parcel_universe`
  - `etl_parcel_sales.py` — SODA API `wvhk-k5uv` → `parcel_sales`
  - `etl_commercial_valuations.py` — CSV `Assessor_-_Commercial_Valuation_Data_*.csv` → `commercial_valuations`
- **utils/** — DB connection, CSV normalization
- **docs/** — Cook County dataset documentation

## Setup

```bash
cd real-estate
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

1. **PostgreSQL**: Create a DB and set env: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`
2. **SODA API**: Set `SODA_APP_TOKEN` (from https://datacatalog.cookcountyil.gov/)
3. **Commercial CSV** (optional): Place `Assessor_-_Commercial_Valuation_Data_YYYYMMDD.csv` in project root

## Run ETL

From the **real-estate** project root:

```bash
# Dry run (test API connectivity, no DB writes)
.venv/bin/python scripts/run_etl.py --dataset all --dry-run

# Single dataset
.venv/bin/python scripts/run_etl.py --dataset parcel_universe --limit 1000
.venv/bin/python scripts/run_etl.py --dataset parcel_sales --limit 1000
.venv/bin/python scripts/run_etl.py --dataset commercial_valuations

# Full load
.venv/bin/python scripts/run_etl.py --dataset all
```

Or run scripts directly:

```bash
.venv/bin/python scripts/etl_parcel_universe.py --limit 5000
.venv/bin/python scripts/etl_parcel_sales.py --limit 5000
.venv/bin/python scripts/etl_commercial_valuations.py --csv-path "path/to/Assessor_-_Commercial_Valuation_Data_20260214.csv"
```

Runs are recorded in `data_refresh_log`.

## Stack
- Python
- PostgreSQL
- Discord: #real-estate
