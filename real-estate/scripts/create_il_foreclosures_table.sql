-- IL Foreclosures table
-- Sources: TJSC, Intercounty Judicial Sales, Auction.com
-- Separate from CT (ct_foreclosures) by design
CREATE TABLE IF NOT EXISTS il_foreclosures (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(20) NOT NULL,
    case_number     VARCHAR(200),
    address         TEXT,
    city            VARCHAR(100),
    county          VARCHAR(50),
    state           VARCHAR(2) DEFAULT 'IL',
    zip             VARCHAR(10),
    sale_date       DATE,
    sale_time       VARCHAR(20),
    sale_type       VARCHAR(50),
    opening_bid     NUMERIC(14,2),
    judgment_amount NUMERIC(14,2),
    status          VARCHAR(30) DEFAULT 'upcoming',
    plaintiff       TEXT,
    firm_name       TEXT,
    file_number     VARCHAR(200),
    auction_com_id  VARCHAR(30),
    photo_url       TEXT,
    lat             DOUBLE PRECISION,
    lng             DOUBLE PRECISION,
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, case_number)
);
CREATE INDEX IF NOT EXISTS idx_il_foreclosures_coords ON il_foreclosures (lat, lng) WHERE lat IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_il_foreclosures_status ON il_foreclosures (status);
CREATE INDEX IF NOT EXISTS idx_il_foreclosures_county ON il_foreclosures (county);
CREATE INDEX IF NOT EXISTS idx_il_foreclosures_sale_date ON il_foreclosures (sale_date);
GRANT SELECT ON il_foreclosures TO nhc_agent;
GRANT SELECT ON il_foreclosures TO dashboard_readonly;
GRANT SELECT, INSERT, UPDATE ON il_foreclosures TO nhc_etl;
GRANT USAGE, SELECT ON SEQUENCE il_foreclosures_id_seq TO nhc_etl;
