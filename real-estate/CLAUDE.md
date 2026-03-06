# CLAUDE.md — Real Estate


> ⚠️ **All changes must go through GitHub pull requests.** Never push to `main` directly. See root `CLAUDE.md` for the full PR workflow.

## Code Review Tools

When your PR is open, NHC runs automated LLM review via `scripts/mr-review`.
- Reviews are SHA-tagged — new pushes invalidate old reviews
- Model chain: Kimi K2.5 → GLM5 → OpenRouter free → DeepSeek V3.2
- Critical findings block approval; warnings/info are advisory
- To run locally: `export $(grep -v '^#' admin-dashboard/.env | xargs) && scripts/mr-review <PR_NUMBER>`
- API keys in `admin-dashboard/.env` (gitignored). GitHub auth comes from `gh auth`.

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
