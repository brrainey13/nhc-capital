# Cook County Property Data — Shared Schema Definition

> **Authoritative source.** ETL and agents reference this file for Cook County database structure.

---

## PostgreSQL Table Definitions

### Table: `parcel_universe`
Source: SODA API `nj4t-kc8j` | ~1.8M rows (full) / ~19.5K Class 3 | Weekly refresh

```sql
CREATE TABLE IF NOT EXISTS parcel_universe (
    pin                    VARCHAR(14) PRIMARY KEY,
    pin10                  VARCHAR(10),
    year                   INTEGER,
    class                  VARCHAR(10),
    triad_name             VARCHAR(50),
    triad_code             VARCHAR(10),
    township_name          VARCHAR(50),
    township_code          VARCHAR(10),
    nbhd_code              VARCHAR(10),
    tax_code               VARCHAR(10),
    zip_code               VARCHAR(10),
    lon                    DECIMAL(12, 8),
    lat                    DECIMAL(12, 8),
    cook_municipality_name VARCHAR(100),
    row_id                 VARCHAR(30),
    raw_json               JSONB,
    created_at             TIMESTAMPTZ DEFAULT NOW(),
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pu_class ON parcel_universe(class);
CREATE INDEX IF NOT EXISTS idx_pu_township ON parcel_universe(township_name);
CREATE INDEX IF NOT EXISTS idx_pu_zip ON parcel_universe(zip_code);
CREATE INDEX IF NOT EXISTS idx_pu_municipality ON parcel_universe(cook_municipality_name);
CREATE INDEX IF NOT EXISTS idx_pu_coords ON parcel_universe(lat, lon);
```

**Notes**: The `raw_json` column stores the complete API response (all 124 fields). Core query fields are extracted as dedicated columns with indexes.

---

### Table: `parcel_sales`
Source: SODA API `wvhk-k5uv` | ~2.5M rows (full) / ~44.7K Class 3 | Weekly refresh

```sql
CREATE TABLE IF NOT EXISTS parcel_sales (
    row_id                             VARCHAR(20) PRIMARY KEY,
    pin                                VARCHAR(14),
    year                               INTEGER,
    township_code                      VARCHAR(10),
    nbhd                               VARCHAR(10),
    class                              VARCHAR(10),
    sale_date                          TIMESTAMPTZ,
    is_mydec_date                      BOOLEAN,
    sale_price                         NUMERIC(14, 2),
    doc_no                             VARCHAR(30),
    deed_type                          VARCHAR(50),
    mydec_deed_type                    VARCHAR(50),
    seller_name                        TEXT,
    buyer_name                         TEXT,
    is_multisale                       BOOLEAN,
    num_parcels_sale                   INTEGER,
    sale_type                          VARCHAR(50),
    sale_filter_same_sale_within_365   BOOLEAN,
    sale_filter_less_than_10k          BOOLEAN,
    sale_filter_deed_type              BOOLEAN,
    raw_json                           JSONB,
    created_at                         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ps_pin ON parcel_sales(pin);
CREATE INDEX IF NOT EXISTS idx_ps_sale_date ON parcel_sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_ps_class ON parcel_sales(class);
CREATE INDEX IF NOT EXISTS idx_ps_price ON parcel_sales(sale_price);
CREATE INDEX IF NOT EXISTS idx_ps_township ON parcel_sales(township_code);
```

---

### Table: `commercial_valuations`
Source: CSV file `Assessor_-_Commercial_Valuation_Data_*.csv` | ~109K rows | Annual manual upload

```sql
CREATE TABLE IF NOT EXISTS commercial_valuations (
    id                              SERIAL,
    keypin                          VARCHAR(20),
    keypin_normalized               VARCHAR(14),
    pins                            TEXT,
    year                            INTEGER,
    township                        VARCHAR(50),
    modelgroup                      VARCHAR(20),
    class_es                        VARCHAR(20),
    studiounits                     INTEGER,
    _1brunits                       INTEGER,
    _2brunits                       INTEGER,
    _3brunits                       INTEGER,
    _4brunits                       INTEGER,
    tot_units                       INTEGER,
    address                         TEXT,
    adj_rent_sf                     NUMERIC(12, 4),
    aprx_comm_sf                    NUMERIC(12, 2),
    apt                             INTEGER,
    avgdailyrate                    NUMERIC(10, 2),
    bldgsf                          NUMERIC(12, 2),
    gross_building_area             NUMERIC(12, 2),
    caprate                         NUMERIC(8, 6),
    carwash                         VARCHAR(5),
    category                        INTEGER,
    ceilingheight                   VARCHAR(20),
    cost_day_bed                    NUMERIC(10, 2),
    costapproach_sf                 NUMERIC(12, 4),
    covidadjvacancy                 NUMERIC(8, 4),
    ebitda_pct                      NUMERIC(8, 4),
    egi                             NUMERIC(14, 2),
    excesslandarea                  NUMERIC(12, 2),
    excesslandval                   NUMERIC(14, 2),
    exp                             NUMERIC(8, 6),
    f_r                             VARCHAR(10),
    finalmarketvalue                NUMERIC(16, 2),
    finalmarketvalue_bed            NUMERIC(14, 2),
    finalmarketvalue_key            NUMERIC(14, 2),
    finalmarketvalue_sf             NUMERIC(12, 4),
    finalmarketvalue_unit           NUMERIC(14, 2),
    idphlicense                     VARCHAR(20),
    incomemarketvalue               NUMERIC(16, 2),
    incomemarketvalue_sf            NUMERIC(12, 4),
    investmentrating                VARCHAR(5),
    land_bldg                       NUMERIC(10, 4),
    landsf                          NUMERIC(12, 2),
    model                           VARCHAR(50),
    nbhd                            INTEGER,
    netrentablesf                   NUMERIC(12, 2),
    noi                             NUMERIC(14, 2),
    oiltankvalue_atypicaloby        NUMERIC(14, 2),
    owner                           TEXT,
    parking                         INTEGER,
    parkingsf                       NUMERIC(12, 2),
    pctownerinterest                NUMERIC(8, 4),
    permit_partial_demovalue        TEXT,
    permit_partial_demovalue_reason TEXT,
    pgi                             NUMERIC(14, 2),
    property_name_description       TEXT,
    property_type_use               TEXT,
    reportedoccupancy               NUMERIC(8, 4),
    revenuebed_day                  NUMERIC(10, 2),
    revpar                          NUMERIC(10, 2),
    roomrev_pct                     NUMERIC(8, 4),
    salecompmarketvalue_sf          NUMERIC(12, 4),
    sap                             INTEGER,
    sapdeduction                    NUMERIC(14, 2),
    saptier                         INTEGER,
    stories                         NUMERIC(6, 1),
    subclass2                       TEXT,
    taxdist                         VARCHAR(20),
    taxpayer                        TEXT,
    totalrevreported                NUMERIC(14, 2),
    totalexp                        NUMERIC(14, 2),
    totallandval                    NUMERIC(14, 2),
    totalrev                        NUMERIC(14, 2),
    townregion                      VARCHAR(50),
    vacancy                         NUMERIC(8, 4),
    yearbuilt                       NUMERIC(6, 1),
    created_at                      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (keypin_normalized, year)
);

CREATE INDEX IF NOT EXISTS idx_cv_keypin ON commercial_valuations(keypin_normalized);
CREATE INDEX IF NOT EXISTS idx_cv_township ON commercial_valuations(township);
CREATE INDEX IF NOT EXISTS idx_cv_class ON commercial_valuations(class_es);
CREATE INDEX IF NOT EXISTS idx_cv_year ON commercial_valuations(year);
CREATE INDEX IF NOT EXISTS idx_cv_property_type ON commercial_valuations(property_type_use);
CREATE INDEX IF NOT EXISTS idx_cv_tot_units ON commercial_valuations(tot_units);
```

---

## Operational Tables

### `data_refresh_log` — ETL Run Tracking
```sql
CREATE TABLE IF NOT EXISTS data_refresh_log (
    id              SERIAL PRIMARY KEY,
    dataset_name    VARCHAR(50),
    refresh_type    VARCHAR(20),  -- 'full' or 'incremental'
    rows_fetched    INTEGER,
    rows_inserted   INTEGER,
    rows_updated    INTEGER,
    duration_sec    NUMERIC(10, 2),
    status          VARCHAR(20),  -- 'success', 'partial', 'failed'
    error_message   TEXT,
    refreshed_at    TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Reference

### PIN Format
- **parcel_universe / parcel_sales**: Plain 14-digit (`01022020450000`)
- **commercial_valuations (keypin)**: Dashed (`01-02-202-045-0000`)
- **Normalized join key**: `keypin_normalized` = dashes stripped, zero-padded to 14
