---
summary: 'Real estate project — Cook County property data, SF rentals, analysis pipelines.'
read_when:
  - Working on real estate data or analysis
  - Adding property data scrapers or pipelines
  - Querying Cook County or SF rental data
---

# Real Estate

## Overview

Real estate data analysis — property taxes, assessments, sales, and rental markets.

## Status

- **Stage:** Early — data exists in `nhl_betting` DB, should be migrated to own DB
- **Discord:** #real-estate (1473074661016338545)
- **Folder:** `real-estate/`

## Existing Data (in `nhl_betting` DB)

| Table | Description |
|---|---|
| `cook_county_appeals` | Cook County property tax appeals |
| `cook_county_assessments` | Property assessments |
| `cook_county_properties` | Property records |
| `cook_county_sales` | Property sales |
| `cook_county_tax_rates` | Tax rates by area |
| `sf_rentals` | San Francisco rental listings |

## Next Steps

1. Migrate tables to a dedicated `real_estate` database
2. Build analysis pipelines
3. Add more data sources
