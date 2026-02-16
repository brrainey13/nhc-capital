# CLAUDE.md — NHC Monorepo

You are a coding agent working inside the NH Capital monorepo. NHC (the orchestrator) spawned you for a specific task. Do the task, commit, and exit.

## Repo Layout

```
~/nhc-capital/                    ← monorepo root
├── nhl-betting/                  ← NHL betting models & scrapers
│   ├── scrapers/                 ← Data scrapers (BettingPros, etc.)
│   └── test_smoke.py
├── admin-dashboard/              ← FastAPI + React dashboard
│   ├── backend/main.py           ← API server (read-only SQL)
│   ├── frontend/                 ← React SPA (Vite + TypeScript)
│   └── backend/tests/test_api.py
├── real-estate/                  ← Real estate analysis (placeholder)
├── polymarket/                   ← Prediction market analysis & trading
├── docs/                         ← Project docs (YAML front-matter)
├── scripts/
│   ├── committer                 ← Safe commit helper (USE THIS)
│   └── docs-list                 ← List docs with summaries
├── .claude/commands/             ← Slash commands (/build, /commit, /fix, /docs)
├── .github/workflows/ci.yml     ← GitHub Actions (ruff + pytest)
├── Makefile                      ← make test, make lint, make ci
└── pyproject.toml                ← pytest config
```

## Database

- **PostgreSQL 17** at `localhost:5432`, user `connorrainey`, trust auth (no password)
- **DB:** `nhl_betting` — 23 tables, ~330K rows
- Key tables: `games`, `teams`, `players`, `player_stats` (199K), `goalie_stats` (22K), `saves_odds` (21K), `standings`, `predictions` (empty), `model_runs` (empty)
- psql path: `/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql`

## Before You Start

1. Run `scripts/docs-list` — check if any doc matches your task, read it first
2. `git pull` — get latest
3. `git status` — check for uncommitted changes

## Workflow

1. Write tests FIRST
2. Write code to pass tests
3. `make ci` (ruff lint + pytest) — must pass
4. `scripts/committer "feat: description" file1 file2 ...` — never `git add .`
5. Push only when all tests pass

## Rules

- **Conventional Commits:** `feat|fix|refactor|build|ci|chore|docs|style|perf|test`
- **Keep files < 500 LOC** — split/refactor as needed
- **Python style:** ruff-compliant, type hints preferred
- **Tests:** pytest, `--import-mode=importlib`
- **No secrets in code** — trust auth for Postgres, no API keys in commits
- **Read `docs/networking-security.md` before exposing any service** — ngrok only, no raw ports

## Infrastructure

- **Machine:** Mac Mini (arm64, macOS), Tailscale network
- **CI:** GitHub Actions → Discord `#general` webhook
- **Dashboard:** `admin-dashboard/`, served via ngrok with Google OAuth
- **Discord:** NHC server, channels map to project folders

## MCP Servers (Available to You)

- **chrome-devtools** — 26 tools: navigate pages, take snapshots/screenshots, click/fill elements, inspect network requests, console messages, run performance traces. Use for dashboard testing and debugging.
- **deepwiki** — Query documentation for open-source projects

Call via: `mcporter call chrome-devtools.navigate_page url=http://localhost:8000 type=url`

## Team

NH Capital — 5-person investment team. You're building tools for quantitative analysis, betting models, and data pipelines.
