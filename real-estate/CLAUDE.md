# CLAUDE.md — Real Estate

Read `docs/real-estate.md` for project status and data sources.

## Quick Context

- **Python:** `real-estate/.venv/bin/python` — **always use this, never system Python**
- **Setup:** `cd real-estate && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- **Stage:** Early — data exists in `nhl_betting` DB (should be migrated to own DB)
- **Discord:** #real-estate
- **Folder:** `real-estate/`

## Existing Data (in `nhl_betting` DB — to be migrated)

| Table | Description |
|---|---|
| `cook_county_appeals` | Cook County property tax appeals |
| `cook_county_assessments` | Property assessments |
| `cook_county_properties` | Property records |
| `cook_county_sales` | Property sales |
| `cook_county_tax_rates` | Tax rates by area |
| `sf_rentals` | San Francisco rental listings |

## Rules

- **Update `docs/real-estate.md`** when you add tables, scrapers, or pipelines
- **`make ci` before commit** — always
