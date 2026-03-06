#!/usr/bin/env bash
# Auto-deploy watcher — polls origin/main for new commits and deploys
# Runs as a LaunchAgent (connorrainey user), NOT through the agent
#
# Flow: git fetch → compare SHA → if new → deploy-dashboard --all → log → notify Discord
#
# Install: launchctl load ~/Library/LaunchAgents/com.nhc.auto-deploy.plist

set -euo pipefail

REPO_ROOT="$HOME/nhc-capital"
DEPLOY_SCRIPT="$REPO_ROOT/scripts/deploy-dashboard"
SHA_FILE="$HOME/.nhc-deploy-sha"
LOG_DIR="/tmp/nhc-deploy-logs"
LOG_FILE="$LOG_DIR/deploy-$(date +%Y%m%d).log"
DISCORD_WEBHOOK="${DISCORD_WEBHOOK:-}"

mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

notify_discord() {
  local msg="$1"
  if [ -n "$DISCORD_WEBHOOK" ]; then
    curl -sf -H "Content-Type: application/json" \
      -d "{\"content\": \"$msg\"}" \
      "$DISCORD_WEBHOOK" >/dev/null 2>&1 || true
  fi
}

# Get current deployed SHA
deployed_sha=""
if [ -f "$SHA_FILE" ]; then
  deployed_sha=$(cat "$SHA_FILE")
fi

# Fetch latest from origin
cd "$REPO_ROOT"
git fetch origin main --quiet 2>/dev/null || {
  log "⚠️ git fetch failed — skipping this cycle"
  exit 0
}

remote_sha=$(git rev-parse origin/main)

# Compare
if [ "$deployed_sha" = "$remote_sha" ]; then
  # No new commits — nothing to do
  exit 0
fi

log "🚀 New commit detected on main: ${remote_sha:0:8}"
log "   Previous deployed: ${deployed_sha:0:8:-none}"

# Pull to main
current_branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$current_branch" != "main" ]; then
  log "⚠️ Not on main branch ($current_branch) — switching"
  git checkout main --quiet
fi

git pull origin main --quiet 2>/dev/null || {
  log "❌ git pull failed"
  notify_discord "❌ **Auto-deploy failed** — git pull error on \`${remote_sha:0:8}\`"
  exit 1
}

# Get commit info for notification
commit_msg=$(git log -1 --format="%s" HEAD)
commit_author=$(git log -1 --format="%an" HEAD)

log "   Commit: $commit_msg (by $commit_author)"
log "   Running deploy-dashboard --all..."

# Deploy
if "$DEPLOY_SCRIPT" --all >> "$LOG_FILE" 2>&1; then
  # Success — save SHA
  echo "$remote_sha" > "$SHA_FILE"
  log "✅ Deploy succeeded: ${remote_sha:0:8}"
  notify_discord "✅ **Auto-deployed** \`${remote_sha:0:8}\` — $commit_msg (by $commit_author)"
else
  log "❌ Deploy FAILED for ${remote_sha:0:8}"
  notify_discord "❌ **Auto-deploy FAILED** for \`${remote_sha:0:8}\` — $commit_msg. Check logs."
  exit 1
fi
