#!/bin/bash
# Game Day Automation — runs odds scrape + picks pipeline
# Called by launchd at 11 AM ET daily during NHL season
# Outputs picks to JSON for Discord posting

set -euo pipefail
cd "$(dirname "$0")/.."

LOG="scrapers/gameday_$(date +%Y-%m-%d).log"
exec > "$LOG" 2>&1

echo "=== Game Day Pipeline: $(date) ==="

# Run full pipeline
.venv/bin/python pipeline/gameday.py \
    --json-out "pipeline/output/picks_$(date +%Y-%m-%d).json" \
    --dry-run

echo "=== Complete: $(date) ==="
