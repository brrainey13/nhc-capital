---
summary: 'CI/CD pipeline — GitHub Actions runs ruff + pytest on push, posts results to Discord #general.'
read_when:
  - CI is failing or red
  - Adding new tests or linting rules
  - Modifying GitHub Actions workflows
  - Setting up a new project that needs CI
---

# CI Pipeline

## Flow

```
git push → GitHub Actions → ruff lint → pytest → Discord webhook
```

## Workflow

File: `.github/workflows/ci.yml`

- **Triggers:** Push to `main`, all PRs
- **Steps:** Install Python → Install deps → `make lint` → `make test`
- **Notification:** Posts ✅/❌ summary to Discord `#general` via webhook

## Running Locally

```bash
make ci        # lint + test
make lint      # ruff only
make test      # pytest only
```

## Adding Tests

- Each project subfolder has `test_smoke.py` for basic import/existence tests
- Put real tests in `tests/` within each project folder
- All test files must start with `test_`
- Use `pytest` conventions (functions starting with `test_`)

## If CI Is Red

1. Run `make ci` locally to reproduce
2. Fix the issue
3. Commit with `fix:` prefix
4. Push — CI re-runs automatically
5. Never leave main broken
