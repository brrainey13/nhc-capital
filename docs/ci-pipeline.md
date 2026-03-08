---
summary: 'CI/CD pipeline — GitHub Actions (primary). Risk-gated, path-filtered, with Discord notifications.'
read_when:
  - CI is failing or red
  - Adding new tests or linting rules
  - Modifying CI workflows (.github/workflows/)
  - Setting up a new project that needs CI
  - Understanding the risk policy gate
---

# CI Pipeline

## Overview

**GitHub Actions is the primary CI/CD platform.**

Branch protection on GitHub enforces:
- No direct pushes to `main` (blocked at platform level)
- Required checks must pass before merge
- Pull requests are required for changes to land on `main`

## Flow

```
feature branch → git push origin → PR created → GitHub Actions:
  1. risk-policy-gate (classifies risk tier)
  2. code-review (posts SHA-tagged findings + machine output)
  3. auto-fix-review-findings (helper job on CRITICAL review findings)
  4. lint (ruff check)
  5. docs-guard (front-matter validation)
  6. test-projects (path-filtered: NHL/Poly/RE)
  7. test-dashboard (path-filtered: admin-dashboard)
  8. test-full (infra/shared changes)
  → Pipeline passes → Review → Merge
```

## GitHub Actions

Files: `.github/workflows/*.yml`

### Workflow Rules
- PR events → path-filtered CI + policy gate
- Push to `main` → full validation
- Feature branch pushes update the PR checks for the current head SHA

### Jobs

| Job | Stage | Runs When | What |
|-----|-------|-----------|------|
| `risk-policy-gate` | gate | All PRs | Classifies changes by risk tier |
| `code-review` | review | All PRs | Runs `scripts/mr-review`, posts findings, writes `.review-findings.json` |
| `auto-fix-review-findings` | helper | PRs with CRITICAL review findings | Runs `scripts/remediate --ci`, pushes fixes, triggers re-review |
| `lint` | test | Always | `ruff check .` |
| `docs-guard` | test | Always | Validates docs front-matter |
| `test-projects` | test | NHL/Poly/RE changes | `pytest` on project tests |
| `test-dashboard` | test | Dashboard changes | Backend tests + frontend build |
| `test-full` | test | Infra/shared changes | Full test suite |
| `discord-notify` | notify | Main branch only | Posts result to Discord #general |

### Risk Tiers (from `risk-policy.json`)

| Tier | Files | Required Checks |
|------|-------|----------------|
| 🔴 HIGH | Dashboard, CI, deploy scripts | gate + test + lint + review |
| 🟡 MEDIUM | Pipelines, models, scrapers | gate + test + lint |
| 🟢 LOW | Docs, markdown | gate + lint |

## Running Locally

```bash
make ci        # lint + docs-guard + test (must pass before commit)
make lint      # ruff only
make test      # pytest only
```

## Git Workflow

```bash
git checkout -b feat/your-task
# ... work ...
make ci
scripts/committer "feat: description" file1 file2
git push -u origin feat/your-task
gh pr create --title "feat: description"
```

**NEVER push directly to main.** It will be rejected.

## Auto-Remediation Guardrails

- `scripts/mr-review --ci` always writes `.review-findings.json` and `.review-result.json`
- Auto-fix only runs when the review output contains `CRITICAL` findings
- Auto-fix commits include `[skip ci-review]`, so the next pipeline run skips the helper job
- Attempts are capped at 3 per PR SHA and recorded in PR comments

## Reviewers

- **brrainey13** (Blake) — Owner
- **Rainman95** (Ian) — Owner
- **nhccapitalinc** (NHC bot) — Maintainer

## If CI Is Red

1. Run `make ci` locally to reproduce
2. Fix the issue
3. Commit with `fix:` prefix
4. Push to your branch — checks re-run on the PR
5. Never leave main broken
