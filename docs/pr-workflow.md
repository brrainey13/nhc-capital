---
summary: 'Deterministic PR workflow — Code Factory pattern with risk gating, SHA-disciplined review, and remediation loop'
read_when:
  - Opening or reviewing a pull request
  - Modifying CI/CD workflows or .github/workflows/
  - Understanding the Code Factory review agent
  - Debugging CI pipeline failures
---

# PR Workflow — Code Factory Pattern

Based on Blake Rainey's Code Factory pattern. All code goes through GitHub pull requests.

## The Loop

```
PR opened/synchronized
  → Risk classifier (scripts/risk-classifier)
  → Compute required checks from risk-policy.json
  → Risk policy gate preflight (GitHub Actions: risk-policy-gate)
  → Code review agent (NHC via scripts/mr-review, SHA-disciplined, writes .review-findings.json)
  → Review findings?
    YES → Auto-remediation helper (`scripts/remediate --ci`) fixes CRITICAL issues in-branch → push → loop back
    NO  → Resolve bot-only threads → Start CI test fanout
  → All required checks pass?
    YES → Human review + merge
    NO  → Fix and rerun
```

## CI Pipeline Stages

| Stage | Jobs | Purpose |
|-------|------|---------|
| `gate` | `risk-policy-gate` | Classify risk tier, compute required checks |
| `review` | `code-review`, `auto-fix-review-findings`, `lint`, `docs-guard`, `schema-guard` | Cheap validation + review state check + helper remediation |
| `test` | `test-projects`, `test-dashboard`, `test-full` | Expensive CI (needs review to pass first) |
| `notify` | `discord-notify` | Post result to Discord (main pushes only) |

Test jobs use `needs: [lint, docs-guard, code-review (optional)]` so they only run after cheap checks pass.

## SHA Discipline (Non-Negotiable)

- Every review is tagged with `sha:XXXXXXX`
- Stale reviews (from old SHAs) are ignored
- Rerun requests are deduplicated per SHA
- New pushes trigger new reviews automatically

## Risk Tiers

Defined in `risk-policy.json`:

| Tier | Paths | Required Checks |
|------|-------|----------------|
| HIGH | dashboard, CI, risk-policy.json | risk-policy-gate, ci-test, ci-lint, code-review |
| MEDIUM | pipelines, models, scrapers | risk-policy-gate, ci-test, ci-lint |
| LOW | docs, markdown | risk-policy-gate, ci-lint |

## Review Agent

`scripts/mr-review <PR_NUMBER>` — runs locally via `gh api` or direct GitHub API access.

Checks for:
- Hardcoded secrets/credentials (CRITICAL)
- SQL injection (f-strings in SQL)
- DDL changes without dashboard coordination
- Hardcoded hosts
- Files > 500 LOC
- New Python files without tests

Flags: `--auto-resolve` (resolve bot-only threads), `--remediate` (output for fix agent), `--machine` (write `.review-findings.json`), `--ci` (HTTP mode)

## Auto-Remediation Loop

- The review job uploads `.review-findings.json` and `.review-result.json` as workflow artifacts
- If the current head SHA has CRITICAL findings, CI runs `scripts/remediate <PR> --ci`
- Each attempt is posted back to the PR as `🔧 Auto-remediation attempt X/3`
- Auto-fix commits use `fix: auto-remediate review findings [skip ci-review]`
- The next pipeline run still re-reviews the new SHA, but skips the helper job to avoid loops
- After 3 failed attempts on the same SHA, CI posts a human-review escalation comment and stops

## Branch Protection

- **NHC (Developer):** Can push branches, open PRs, review, approve. CANNOT merge.
- **Humans (Owners):** brrainey13, Rainman95 — only they can merge.
- Required checks must pass before merge.

## Workflow for Coding Agents

1. Create branch: `feat/<description>`
2. Make changes, run `make ci` locally
3. Push to GitHub: `git push origin feat/<branch>`
4. Open PR: `gh pr create --title "type: description"`
5. NHC review agent posts SHA-tagged review
6. If critical findings → fix and push (triggers re-review)
7. If clean → human merges
