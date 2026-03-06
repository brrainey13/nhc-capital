#!/usr/bin/env bash
# Sync Polymarket data from Raspberry Pi to Mac Mini
# Usage: polymarket/scrapers/sync_from_pi.sh
#
# The Pi runs hourly scanners that populate the clawd DB.
# This script pulls new data into the local polymarket DB.

set -euo pipefail

PI_HOST="${PI_HOST:?Set PI_HOST env var (e.g. user@tailscale-ip)}"
LOCAL_PSQL="${LOCAL_PSQL:-psql}"
LOCAL_DB="${LOCAL_DB:-polymarket}"

echo "📡 Syncing Polymarket data from Raspberry Pi..."

# Get latest snapshot time locally
LAST_SNAP=$($LOCAL_PSQL -d "$LOCAL_DB" -t -A -c \
  "SELECT COALESCE(MAX(snapshot_time), '2000-01-01') FROM market_snapshots;" 2>/dev/null)
echo "  Last local snapshot: $LAST_SNAP"

# Dump new markets (full upsert — small table)
echo "  Syncing markets..."
MARKETS_COUNT=$(ssh "$PI_HOST" "sudo -u postgres pg_dump -d clawd --data-only -t markets 2>/dev/null" | \
  $LOCAL_PSQL -d "$LOCAL_DB" 2>&1 | grep -c "INSERT" || echo "0")
echo "  ✅ Markets synced"

# Dump only new snapshots (incremental)
echo "  Syncing snapshots since $LAST_SNAP..."
ssh "$PI_HOST" "sudo -u postgres psql -d clawd -c \"\\COPY (SELECT * FROM market_snapshots WHERE snapshot_time > '$LAST_SNAP') TO STDOUT WITH CSV HEADER\" 2>/dev/null" | \
  $LOCAL_PSQL -d "$LOCAL_DB" -c "\\COPY market_snapshots FROM STDIN WITH CSV HEADER" 2>&1

# Count
TOTAL_SNAPS=$($LOCAL_PSQL -d "$LOCAL_DB" -t -A -c "SELECT COUNT(*) FROM market_snapshots;")
TOTAL_MKTS=$($LOCAL_PSQL -d "$LOCAL_DB" -t -A -c "SELECT COUNT(*) FROM markets;")
echo ""
echo "✅ Sync complete: $TOTAL_MKTS markets, $TOTAL_SNAPS snapshots"
