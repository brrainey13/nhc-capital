---
summary: "How to auto-fix review findings and CI failures using coding agents"
read_when:
  - Fixing review findings on a PR
  - CI pipeline failed
  - Auto-remediation workflow
---

# Remediation — Fixing Review Findings

## Current Flow (Manual)

When `scripts/mr-review` finds critical issues or CI fails:

```bash
# 1. Get the findings
export $(grep -v '^#' admin-dashboard/.env | xargs)
scripts/mr-review <PR_NUMBER> --remediate

# 2. NHC spawns a coding agent to fix
# (NHC does this automatically when it detects failures)
```

## How NHC Auto-Remediates

NHC monitors open PRs via the 6hr autonomous cron. When it finds:
- CI pipeline failures
- Critical review findings on current SHA

It spawns a coding agent with:
- The specific findings as context
- The branch checked out
- Instructions to fix, run tests, commit, push

The push triggers a new pipeline → new review → if clean, auto-approve.

## Rules
- Max 2 remediation attempts per PR (prevent loops)
- Never bypass policy gates
- Pin the model + effort for reproducibility
- Only fix findings matching current HEAD SHA
- Agent must run `make ci` before committing

## TODO
- [ ] Wire auto-trigger in CI or cron
- [ ] Track remediation attempts per PR
- [ ] Auto-spawn coding agent on critical findings
