#!/bin/bash
# Micro-batch ETL loader — spawns a fresh Python process per batch to avoid OOM.
# Usage: bash scripts/batch_loader.sh <dataset> [where_clause]
# Each batch: fetch 5000 rows from API, upsert to DB, exit. No memory accumulation.

set -e
DATASET="${1:?Usage: batch_loader.sh <dataset> [where]}"
WHERE="${2:-}"
BATCH=5000
OFFSET=0
TOTAL=0
DIR="$(cd "$(dirname "$0")/.." && pwd)"
export SODA_APP_TOKEN="${SODA_APP_TOKEN:-XnpDFYJEjocttnVKiXYYfG9T2}"

while true; do
  echo "[batch] offset=$OFFSET fetching $BATCH rows..."
  COUNT=$(python3 -W ignore -c "
import sys, os
sys.path.insert(0, '$DIR')
os.chdir('$DIR')
from scripts.etl_${DATASET} import fetch_batch
data = fetch_batch(limit=$BATCH, where='$WHERE' if '$WHERE' else None, offset=$OFFSET)
print(len(data))
if not data:
    sys.exit(0)
import json
from scripts.etl_${DATASET} import COLS
try:
    from scripts.etl_${DATASET} import _cast
    has_cast = True
except ImportError:
    has_cast = False
from utils.db import get_connection, ensure_schema
from psycopg2.extras import execute_values
rows = []
for rec in data:
    if has_cast:
        row = [_cast(c, rec.get(c)) for c in COLS]
    else:
        row = [rec.get(c) for c in COLS]
    row.append(json.dumps(rec))
    rows.append(tuple(row))
cols_sql = ', '.join(COLS) + ', raw_json'
with get_connection() as conn:
    ensure_schema(conn)
    with conn.cursor() as cur:
        if '${DATASET}' == 'parcel_universe':
            execute_values(cur, '''INSERT INTO parcel_universe (''' + cols_sql + ''') VALUES %s
                ON CONFLICT (pin, year) DO UPDATE SET
                pin10=EXCLUDED.pin10, class=EXCLUDED.class, triad_name=EXCLUDED.triad_name,
                triad_code=EXCLUDED.triad_code, township_name=EXCLUDED.township_name,
                township_code=EXCLUDED.township_code, nbhd_code=EXCLUDED.nbhd_code,
                tax_code=EXCLUDED.tax_code, zip_code=EXCLUDED.zip_code, lon=EXCLUDED.lon,
                lat=EXCLUDED.lat, cook_municipality_name=EXCLUDED.cook_municipality_name,
                row_id=EXCLUDED.row_id, raw_json=EXCLUDED.raw_json, updated_at=NOW()''', rows, page_size=500)
        else:
            execute_values(cur, '''INSERT INTO parcel_sales (''' + cols_sql + ''') VALUES %s
                ON CONFLICT (row_id) DO UPDATE SET
                pin=EXCLUDED.pin, year=EXCLUDED.year, township_code=EXCLUDED.township_code,
                nbhd=EXCLUDED.nbhd, class=EXCLUDED.class, sale_date=EXCLUDED.sale_date,
                is_mydec_date=EXCLUDED.is_mydec_date, sale_price=EXCLUDED.sale_price,
                doc_no=EXCLUDED.doc_no, deed_type=EXCLUDED.deed_type, mydec_deed_type=EXCLUDED.mydec_deed_type,
                seller_name=EXCLUDED.seller_name, buyer_name=EXCLUDED.buyer_name,
                is_multisale=EXCLUDED.is_multisale, num_parcels_sale=EXCLUDED.num_parcels_sale,
                sale_type=EXCLUDED.sale_type,
                sale_filter_same_sale_within_365=EXCLUDED.sale_filter_same_sale_within_365,
                sale_filter_less_than_10k=EXCLUDED.sale_filter_less_than_10k,
                sale_filter_deed_type=EXCLUDED.sale_filter_deed_type,
                raw_json=EXCLUDED.raw_json''', rows, page_size=500)
" 2>&1)
  
  # Extract the count (first line of output)
  ROW_COUNT=$(echo "$COUNT" | head -1)
  
  if [ -z "$ROW_COUNT" ] || [ "$ROW_COUNT" = "0" ]; then
    echo "[done] No more rows at offset=$OFFSET. Total fetched: $TOTAL"
    break
  fi
  
  TOTAL=$((TOTAL + ROW_COUNT))
  echo "[batch] Got $ROW_COUNT rows (total: $TOTAL)"
  
  if [ "$ROW_COUNT" -lt "$BATCH" ]; then
    echo "[done] Last batch. Total fetched: $TOTAL"
    break
  fi
  
  OFFSET=$((OFFSET + BATCH))
  sleep 1  # brief pause between batches
done
