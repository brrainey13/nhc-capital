# AGENTS.md — NHC Monorepo

Coding agent instructions. Read this + `CLAUDE.md`. Do the task, commit, exit.

## Quick Ref

- Repo: `~/nhc-capital/` (monorepo, 4 project folders)
- DB: `nhl_betting` @ localhost:5432, user connorrainey, trust auth
- psql: `/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql`
- Commit: `scripts/committer "type: msg" file1 file2` (never `git add .`)
- Test: `make ci` (ruff + pytest, must pass before commit)
- Docs: `scripts/docs-list` (read matching docs before coding)

## Project Folders

| Folder | Status | Key Files |
|---|---|---|
| `nhl-betting/` | Active — 330K rows in DB, scrapers running | `scrapers/scrape_saves_odds.py` |
| `admin-dashboard/` | Live — FastAPI + React, ngrok | `backend/main.py`, `frontend/src/App.tsx` |
| `real-estate/` | Placeholder | — |
| `polymarket/` | Active — prediction market analysis | `README.md` |

## Conventions

- Conventional Commits (`feat|fix|refactor|...`)
- Tests first, code second
- Files < 500 LOC
- Python: ruff-compliant, type hints
- No secrets in code
- `docs/networking-security.md` before exposing anything
