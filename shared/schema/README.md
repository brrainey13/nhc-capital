# Shared Schema Contract

This directory contains the **schema contract** between project subfolders and the admin dashboard.

## How It Works

- `tables.json` — auto-generated snapshot of all public tables across all databases the dashboard reads
- The admin dashboard auto-discovers tables at startup, but it relies on column names/types for queries and UI
- If a project changes DB schema (CREATE/ALTER/DROP TABLE), the dashboard may break

## Rules

1. **Before changing schema:** Run `scripts/schema-snapshot --diff` to see what will change
2. **After changing schema:** Run `scripts/schema-snapshot` to update `tables.json`
3. **CI warns** (via `scripts/schema-guard`) when DDL changes are detected in MRs
4. **Column renames/drops** that affect dashboard queries need a companion dashboard MR

## Databases

| Database | Owner Project | Tables |
|----------|--------------|--------|
| `nhl_betting` | nhl-betting/ | 27 |
| `polymarket` | polymarket/ | 7 |
| `cook_county` | real-estate/ | 7 |

## Updating the Snapshot

```bash
# See what changed
scripts/schema-snapshot --diff

# Update the contract
scripts/schema-snapshot
```

## What the Dashboard Reads

The dashboard connects to all 3 databases read-only. It:
- Auto-discovers table names from `pg_tables`
- Reads column info from `information_schema.columns`
- Runs parameterized SELECT queries with server-side filtering/sorting
- Runs NL-to-SQL queries (read-only, with SQL injection guards)

**Safe to add:** new tables, new columns (dashboard auto-discovers them)
**Dangerous:** dropping tables, renaming columns, changing column types
