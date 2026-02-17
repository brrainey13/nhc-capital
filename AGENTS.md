# AGENTS.md — NHC Monorepo

Coding agent instructions. Read this + `CLAUDE.md`. Do the task, commit, exit.

## ⚠️ STEP ZERO: Run `scripts/docs-list` and read matching docs. Always.

## Quick Ref

- Repo: `~/nhc-capital/` (monorepo, 4 project folders — each has its own `CLAUDE.md`)
- DB: `nhl_betting` @ localhost:5432, user connorrainey, trust auth
- psql: `/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql`
- Commit: `scripts/committer "type: msg" file1 file2` (never `git add .`)
- Test: `make ci` (ruff + pytest, must pass before commit)
- Docs: `scripts/docs-list` (read matching docs before coding)
- Deploy: `scripts/deploy-dashboard` (the ONLY way to deploy dashboard)

## Project Folders

| Folder | Status | Key Files |
|---|---|---|
| `nhl-betting/` | Active — 28 tables, 400K+ rows, scrapers + models | `scrapers/`, `model/`, `CLAUDE.md` |
| `admin-dashboard/` | Live — FastAPI + React, ngrok, NL query | `backend/main.py`, `frontend/`, `CLAUDE.md` |
| `real-estate/` | Early — Cook County + SF data in DB | `CLAUDE.md` |
| `polymarket/` | Placeholder — needs scoping | `CLAUDE.md` |

## Conventions

- Conventional Commits (`feat|fix|refactor|...`)
- Tests first, code second
- Files < 500 LOC
- Python: ruff-compliant, type hints
- No secrets in code, no model artifacts in git
- `docs/networking-security.md` before exposing anything
- **Update docs when you change things** — stale docs waste everyone's time

## Keeping Docs Current

When you add, remove, or change:
- **Tables/columns** → update `docs/nhl-betting.md` (or relevant project doc) + project `CLAUDE.md`
- **API endpoints** → update `docs/admin-dashboard.md` + project `CLAUDE.md`
- **Scrapers** → update `docs/nhl-betting.md` + project `CLAUDE.md`
- **Infrastructure** → update `docs/infrastructure.md`
- **New project** → create `docs/<project>.md` with front-matter + project `CLAUDE.md`
- **Deploy changes** → update `docs/admin-dashboard.md` or `docs/networking-security.md`

Front-matter template for new docs:
```yaml
---
summary: 'One-line description of what this doc covers.'
read_when:
  - When you should read this doc
  - Another trigger condition
---
```
