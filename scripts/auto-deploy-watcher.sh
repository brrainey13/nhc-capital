#!/usr/bin/env bash
# Auto-deploy watcher — polls origin/main for new commits and deploys
# Runs as a LaunchAgent (host user), NOT through the agent
#
# Flow: git fetch → compare SHA → if new → deploy-dashboard --all → log → notify Discord
#
# Install: launchctl load ~/Library/LaunchAgents/com.nhc.auto-deploy.plist

set -euo pipefail

SELF="$(realpath "$0")"
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

# ── GATE: Verify commit came from an approved, CI-passed merged PR ──
# Uses GitHub API to check that the commit is associated with a merged PR
# that was approved and passed all required status checks.

pr_json=$(curl -sf \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/brrainey13/nhc-capital/commits/${remote_sha}/pulls" 2>/dev/null || echo "[]")

# Check: at least one merged PR is associated with this commit
merged_pr=$(echo "$pr_json" | python3 -c "
import json, sys
try:
    prs = json.load(sys.stdin)
    merged = [p for p in prs if p.get('merged_at') and p.get('base',{}).get('ref') == 'main']
    if merged:
        print(f'PR #{merged[0][\"number\"]}: {merged[0][\"title\"]}')
    else:
        print('')
except:
    print('')
" 2>/dev/null)

if [ -z "$merged_pr" ]; then
  log "🚫 DEPLOY BLOCKED — commit ${remote_sha:0:8} is NOT from an approved merged PR"
  log "   Only merged PRs trigger auto-deploy. Direct pushes are rejected."
  notify_discord "🚫 **Auto-deploy BLOCKED** — \`${remote_sha:0:8}\` not from a merged PR. Skipping."
  exit 0
fi

log "   ✅ Verified: $merged_pr"

# Check: CI check runs passed on this commit (GitHub Actions uses check runs, not statuses)
ci_result=$(curl -sf \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/brrainey13/nhc-capital/commits/${remote_sha}/check-runs" 2>/dev/null || echo "{}")

ci_verdict=$(echo "$ci_result" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    runs = data.get('check_runs', [])
    if not runs:
        print('none')
    elif all(r.get('conclusion') == 'success' for r in runs):
        print('success')
    elif any(r.get('status') != 'completed' for r in runs):
        print('pending')
    else:
        failed = [r['name'] for r in runs if r.get('conclusion') != 'success']
        print(f'failed:{','.join(failed)}')
except:
    print('unknown')
" 2>/dev/null)

if [ "$ci_verdict" = "none" ]; then
  log "⚠️ No CI check runs found for ${remote_sha:0:8} — skipping (will retry next cycle)"
  exit 0
fi

if [ "$ci_verdict" = "pending" ]; then
  log "⏳ CI still running for ${remote_sha:0:8} — will retry next cycle"
  exit 0
fi

if [ "$ci_verdict" != "success" ]; then
  log "🚫 DEPLOY BLOCKED — CI checks: $ci_verdict for ${remote_sha:0:8}"
  notify_discord "🚫 **Auto-deploy BLOCKED** — CI checks \`$ci_verdict\` for \`${remote_sha:0:8}\`. Need all green."
  exit 0
fi

log "   ✅ CI checks: all passed"

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

# Self-update: if this script changed in the pull, re-exec with the new version
if ! cmp -s "$SELF" "$REPO_ROOT/scripts/auto-deploy-watcher.sh" 2>/dev/null; then
  log "🔄 Watcher script updated — re-executing with new version"
  cp "$REPO_ROOT/scripts/auto-deploy-watcher.sh" "$SELF"
  exec "$SELF" "$@"
fi

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
