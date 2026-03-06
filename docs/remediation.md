---
summary: "How to auto-fix review findings and CI failures using coding agents"
read_when:
  - Fixing review findings on a PR
  - CI pipeline failed
  - Auto-remediation workflow
---

# Remediation — Fixing Review Findings

## Current Flow

When `scripts/mr-review` finds critical issues or CI fails:

```bash
# 1. Get the findings
export $(grep -v '^#' admin-dashboard/.env | xargs)
scripts/mr-review <PR_NUMBER> --remediate

# 2. NHC can spawn a coding agent to fix locally
# (or CI can auto-remediate critical findings directly)
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

## CI Auto-Remediation

PR CI now has a helper job after `Review: Code Review Agent`:

- `scripts/mr-review <PR> --ci --machine` writes `.review-findings.json`
- If the current SHA has `CRITICAL` findings, `scripts/remediate <PR> --ci` runs
- CI groups findings by file, uses the NVIDIA NIM → OpenRouter fallback chain to generate direct fixes, commits with `fix: auto-remediate review findings [skip ci-review]`, and pushes to the PR branch
- The push triggers a new pipeline and a fresh review for the new SHA

Loop prevention:

- Auto-remediation exits early if the HEAD commit subject contains `[skip ci-review]`
- Each attempt is recorded in PR comments as `🔧 Auto-remediation attempt X/3`
- After 3 failed attempts on the same SHA, CI posts `Auto-remediation failed after 3 attempts — needs human review`
- `scripts/remediate <PR> --ci --dry-run` parses the current findings without posting comments or pushing

## Rules
- Max 2 remediation attempts per PR (prevent loops)
- Never bypass policy gates
- Pin the model + effort for reproducibility
- Only fix findings matching current HEAD SHA
- Agent must run `make ci` before committing

## Notes

- CI remediation only fixes `CRITICAL` findings. Warnings and info remain review output for humans.
- The auto-fix job is a helper, not a required merge gate.
