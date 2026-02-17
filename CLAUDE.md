# CLAUDE.md — NHC Monorepo

You are a coding agent working inside the NH Capital monorepo. NHC (the orchestrator) spawned you for a specific task. Do the task, commit, and exit.

## ⚠️ MANDATORY FIRST STEP — DO THIS BEFORE ANYTHING ELSE

```bash
scripts/docs-list
```

Read the output. If ANY doc's "Read when" matches your current task, you MUST `cat docs/<that-doc>.md` and read it fully before writing a single line of code. **Do not skip this.** Do not skim. Do not summarize from memory. Actually open and read the file. This is non-negotiable.

Then read the `CLAUDE.md` inside whichever project subfolder you're working in (e.g. `nhl-betting/CLAUDE.md`).

## Repo Layout

```
~/nhc-capital/                    ← monorepo root
├── nhl-betting/                  ← NHL betting models & scrapers
│   ├── scrapers/                 ← Data scrapers (BettingPros, NHL API, etc.)
│   ├── model/                    ← ML models & feature engineering (NOT committed)
│   ├── sql/                      ← Database migrations & schemas
│   └── CLAUDE.md                 ← Project-specific agent instructions
├── admin-dashboard/              ← FastAPI + React dashboard
│   ├── backend/main.py           ← API server (read-only SQL)
│   ├── frontend/                 ← React SPA (Vite + TypeScript)
│   ├── backend/tests/test_api.py ← API tests
│   └── CLAUDE.md                 ← Project-specific agent instructions
├── real-estate/                  ← Real estate analysis
│   └── CLAUDE.md                 ← Project-specific agent instructions
├── polymarket/                   ← Prediction market analysis & trading
│   └── CLAUDE.md                 ← Project-specific agent instructions
├── docs/                         ← Project docs (YAML front-matter)
├── scripts/
│   ├── committer                 ← Safe commit helper (USE THIS)
│   ├── docs-list                 ← List docs with summaries — RUN THIS FIRST
│   └── deploy-dashboard          ← Blue-green deploy (the ONLY way to deploy)
├── .claude/commands/             ← Slash commands (/build, /commit, /fix, /docs)
├── .github/workflows/ci.yml     ← GitHub Actions (ruff + pytest)
├── Makefile                      ← make test, make lint, make ci
└── pyproject.toml                ← pytest config
```

Each project subfolder has its own `CLAUDE.md` with project-specific context. **Read it when you enter that folder.**

## Virtual Environments

**Every project has its own `.venv/`.** Always use the project-specific Python when running code.

| Project | Python Path | Setup |
|---|---|---|
| `nhl-betting/` | `nhl-betting/.venv/bin/python` | `cd nhl-betting && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| `admin-dashboard/` | `admin-dashboard/.venv/bin/python` | `cd admin-dashboard && python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt` |
| `polymarket/` | `polymarket/.venv/bin/python` | `cd polymarket && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| `real-estate/` | `real-estate/.venv/bin/python` | `cd real-estate && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |

**Or set up all at once:** `make setup-venvs`

**⚠️ NEVER use the system Python to run project code.** Always use `<project>/.venv/bin/python`.

If a venv doesn't exist yet, create it before running anything:
```bash
cd <project> && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Database

- **PostgreSQL 17** at `localhost:5432`, user `connorrainey`, trust auth (no password)
- **DB:** `nhl_betting` — 28 tables, ~400K+ rows
- Key tables: `games` (5.9K), `teams` (34), `players` (2.3K), `player_stats` (199K), `goalie_stats` (22K), `goalie_advanced` (9.5K), `goalie_saves_by_strength` (10K), `goalie_starts` (9.2K), `saves_odds` (44K), `standings` (7.6K), `period_scores` (36K), `api_snapshots` (26K), `lineup_absences` (11K), `injuries_live`, `predictions` (empty), `model_runs` (empty)
- psql path: `/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql`

## Workflow

1. **Run `scripts/docs-list`** — then `cat docs/<name>.md` for every doc whose "Read when" matches your task
2. **`cat` the project's `CLAUDE.md`** in the subfolder you're working in (e.g. `cat nhl-betting/CLAUDE.md`)
3. `git pull` — get latest
4. `git status` — check for uncommitted changes
5. Write tests FIRST
6. Write code to pass tests
7. `make ci` (ruff lint + pytest) — must pass
8. `scripts/committer "feat: description" file1 file2 ...` — never `git add .`
9. Push only when all tests pass

## Deployment — CRITICAL RULE

**ALL deployment MUST go through `scripts/deploy-dashboard`.** This is non-negotiable.

```bash
scripts/deploy-dashboard --all    # Full deploy (CI + build + restart backend + restart ngrok)
scripts/deploy-dashboard          # Frontend-only (no server restart)
scripts/deploy-dashboard --restart-server  # Backend swap only
```

**You MUST NOT:**
- Run `uvicorn` directly
- Run `ngrok` directly
- Kill server processes manually
- Start servers with `nohup` or any ad-hoc method

**The deploy script handles everything:** CI validation, frontend build, blue-green server swap, ngrok tunnel, and health checks. If you bypass it, you WILL break the production dashboard.

If the deploy script itself is broken, fix the script — don't work around it.

## Rules

- **Conventional Commits:** `feat|fix|refactor|build|ci|chore|docs|style|perf|test`
- **Keep files < 500 LOC** — split/refactor as needed
- **Python style:** ruff-compliant, type hints preferred
- **Tests:** pytest, `--import-mode=importlib`
- **No secrets in code** — trust auth for Postgres, no API keys in commits
- **No model artifacts in git** — `.pkl`, `.joblib`, `.h5`, `.pt`, etc. are gitignored
- **Read `docs/networking-security.md` before exposing any service** — ngrok only, no raw ports
- **Update docs when you change things** — if you add tables, endpoints, scrapers, or change architecture, update the relevant `docs/*.md` and project `CLAUDE.md`

## Infrastructure

- **Machine:** Mac Mini (arm64, macOS), Tailscale network
- **CI:** GitHub Actions → Discord `#general` webhook
- **Dashboard:** `admin-dashboard/`, served via ngrok with Google OAuth
- **Discord:** NHC server, channels map to project folders

## MCP Servers (Available to You)

- **chrome-devtools** — 26 tools: navigate, snapshot, click, fill, network, console, performance traces
- **deepwiki** — Query documentation for open-source projects

## Team

NH Capital — 5-person investment team. You're building tools for quantitative analysis, betting models, and data pipelines.
