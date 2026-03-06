# Cook County Assessor Open Data — Dataset Documentation

*Last updated: Feb 15, 2026*

## Overview

We are ingesting three Cook County Assessor datasets into our PostgreSQL database for property analysis and prospecting. These datasets are published by the Cook County Assessor's Office on the Socrata (SODA) open data platform.

| # | Dataset | Socrata ID | Portal URL | Ingestion Method | Update Cadence | Approx. Rows |
|---|---------|-----------|------------|------------------|---------------|--------------|
| 1 | **Parcel Universe** | `nj4t-kc8j` | [Link](https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Parcel-Universe/nj4t-kc8j/about_data) | SODA API (JSON) | Weekly | ~1.8M (all); ~19.5K Class 3 |
| 2 | **Parcel Sales** | `wvhk-k5uv` | [Link](https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Parcel-Sales/wvhk-k5uv/about_data) | SODA API (JSON) | Weekly | ~2.5M+ (all); ~44.7K Class 3 |
| 3 | **Commercial Valuation Data** | `csik-bsws` | [Link](https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Commercial-Valuation-Data/csik-bsws/about_data) | **Manual CSV upload** | Annual | ~109K |

> **Note on Commercial Valuation**: The SODA JSON API only returns 23 of 77 columns due to Socrata's null-omission behavior. The full CSV download contains all 77 columns including critical fields like `tot_units`, `stories`, `owner`, `taxpayer`, `parking`, etc. We use the manually downloaded flat file (`Assessor_-_Commercial_Valuation_Data_20260214.csv`) for this dataset.

---

## Dataset 1: Assessor — Parcel Universe (`nj4t-kc8j`)

### Purpose
The **master registry of every parcel in Cook County**. Each row represents one property parcel identified by a unique 14-digit PIN. Contains geographic, jurisdictional, and administrative data — essentially *where* a property is and *what districts/zones* it belongs to.

### Key Facts
- **Primary Key**: `pin` (14-digit, zero-padded, e.g. `"01012020370000"`)
- **Total Columns**: 124 (schema) / 94 returned via API (some sparse)
- **No financial data**: This dataset does NOT contain sale prices, assessed values, or building characteristics. It is purely a geographic/administrative registry.
- **Current year only**: The main `nj4t-kc8j` dataset contains all years. There is also a current-year-only view at `pabr-t5kh`.

---

## Dataset 2: Assessor — Parcel Sales (`wvhk-k5uv`)

### Purpose
**Historical record of every property sale** recorded by the Cook County Assessor. Covers all property classes. Each row is one sale transaction for one PIN on one date.

### Key Facts
- **Primary Key**: `row_id` (unique per sale record)
- **Join Key**: `pin` → joins to Parcel Universe `pin`
- **Total Columns**: 20
- **Multiple rows per PIN**: A property sold 3 times has 3 rows
- **Weekly updates**: New sales are appended regularly

---

## Dataset 3: Assessor — Commercial Valuation Data (`csik-bsws`)

### Purpose
**Detailed valuation and physical characteristics for commercial, multi-family, and special-use properties.** This is the richest dataset — it contains unit counts, building sqft, income/expense data, cap rates, market valuations, and property type classifications.

### Key Facts
- **Primary Key**: Composite of `keypin` + `year`
- **Join Key**: `keypin` → normalize (strip dashes) → joins to Parcel Universe `pin`
- **Total Columns**: 77 (CSV) / only 23 via JSON API
- **Ingestion Method**: **Manual CSV upload only** (API returns too few columns)
- **Annual updates**: Refreshed once per year when new assessment data is published
- **~109K rows** total across all years

---

## SODA API Reference

### Authentication
| Credential | Env Var | Purpose |
|-----------|---------|---------|
| App Token | `SODA_APP_TOKEN` | Read-only rate limit elevation — set for API fetch |

Get your App Token at https://datacatalog.cookcountyil.gov/ (sign up for API token).

### Endpoints
| Dataset | Resource API Endpoint |
|---------|----------------------|
| Parcel Universe | `GET /resource/nj4t-kc8j.json` |
| Parcel Sales | `GET /resource/wvhk-k5uv.json` |
| Commercial Valuation | **Use CSV upload** |

Base: `https://datacatalog.cookcountyil.gov`

### Pagination
- Default limit: 1,000 rows
- Max limit: 50,000 rows per request
- Use `$offset` for pagination, `$order` for deterministic paging

---

## Appendix: Dataset IDs Quick Reference

| Friendly Name | Socrata ID | Status |
|--------------|-----------|--------|
| Parcel Universe (all years) | `nj4t-kc8j` | ✅ Active |
| Parcel Sales | `wvhk-k5uv` | ✅ Active |
| Commercial Valuation Data | `csik-bsws` | ✅ Active (CSV only) |

---

## Quick Start

```bash
# From nhc-capital/real-estate:
export SODA_APP_TOKEN="your-app-token"
python scripts/run_etl.py --dataset parcel_universe --limit 100 --dry-run
python scripts/run_etl.py --dataset parcel_sales --limit 100 --dry-run
```
