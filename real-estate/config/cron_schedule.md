# Cron Schedule — Cook County Data Refresh

## Active Jobs

| Dataset | Frequency | Schedule | Command |
|---------|-----------|----------|---------|
| Parcel Universe | Weekly | Sunday 3:00 AM | `python scripts/run_etl.py --dataset parcel_universe` |
| Parcel Sales | Weekly | Sunday 3:15 AM | `python scripts/run_etl.py --dataset parcel_sales` |
| Commercial Valuation | Annual | Manual trigger | `python scripts/run_etl.py --dataset commercial_valuations --csv-path <path>` |

## Crontab Entries

```crontab
# Cook County Property Data Refresh
# Parcel Universe — weekly Sunday 3:00 AM
0 3 * * 0 cd /path/to/nhc-capital/real-estate && /usr/bin/python3 scripts/run_etl.py --dataset parcel_universe >> /var/log/nhc-capital/cook_county_refresh.log 2>&1

# Parcel Sales — weekly Sunday 3:15 AM (stagger to avoid API contention)
15 3 * * 0 cd /path/to/nhc-capital/real-estate && /usr/bin/python3 scripts/run_etl.py --dataset parcel_sales >> /var/log/nhc-capital/cook_county_refresh.log 2>&1

# Full refresh (both API datasets) — alternative to individual jobs
# 0 3 * * 0 cd /path/to/nhc-capital/real-estate && /usr/bin/python3 scripts/run_etl.py --dataset all >> /var/log/nhc-capital/cook_county_refresh.log 2>&1
```

## Monitoring
- Check `data_refresh_log` table for status after each run
- Alert if any dataset has `status = 'failed'`
- Alert if `rows_fetched = 0` (possible API outage or schema change)
- Monitor log file size and rotate: `logrotate /var/log/nhc-capital/cook_county_refresh.log`

## Manual Triggers
```bash
# Full reload of all API datasets
python scripts/run_etl.py --dataset all

# Reload commercial valuations from new CSV
python scripts/run_etl.py --dataset commercial_valuations \
  --csv-path "Assessor_-_Commercial_Valuation_Data_20260214.csv"

# Dry run (preview without writing)
python scripts/run_etl.py --dataset all --dry-run
```
