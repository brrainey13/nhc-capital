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
├── risk-policy.json              ← Machine-readable risk tiers & merge policy
├── scripts/
│   ├── committer                 ← Safe commit helper (USE THIS)
│   ├── docs-list                 ← List docs with summaries — RUN THIS FIRST
│   ├── deploy-dashboard          ← Blue-green deploy (the ONLY way to deploy)
│   ├── risk-classifier           ← Classifies changed files by risk tier
│   └── pr-discord-notify         ← Generates Discord Components v2 PR cards
├── .claude/commands/             ← Slash commands (/build, /commit, /fix, /docs)
├── .gitlab-ci.yml                ← Legacy GitLab CI config kept during migration
├── .github/workflows/            ← GitHub Actions (primary — branch protection enforced)
│   ├── ci.yml                    ← Full CI (infra/shared changes)
│   ├── ci-projects.yml           ← Path-filtered: NHL/Poly/RE only
│   ├── ci-dashboard.yml          ← Path-filtered: dashboard only
│   ├── risk-policy-gate.yml      ← Preflight risk classification on PRs
│   └── pr-review.yml             ← Automated code review on PRs
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

## ⚠️ GIT WORKFLOW — MANDATORY (No Direct Pushes to main)

**ALL changes MUST go through GitHub Pull Requests.** Never push directly to `main`.
**ALWAYS use `scripts/committer`** — never `git add .`, never `git commit` directly.
**ALWAYS push to `origin` remote** — GitHub is the primary remote.

```bash
# 1. Create a feature branch
git checkout main && git pull origin main
git checkout -b feat/your-feature-name

# 2. Do your work (tests first, then code)
# 3. Commit (auto-lints Python files via ruff --fix)
scripts/committer "feat: description" file1 file2 ...

# 4. Push to GitHub
git push origin feat/your-feature-name

# 5. Open a pull request
gh pr create --title "feat: description" --body "What and why"
```

### What happens on PR:
1. **Risk Policy Gate** — classifies your changes as high/medium/low risk
2. **CI runs** — lint + test (path-filtered: only your project's tests run)
3. **Code Review** — NHC reviews high/medium PRs automatically
4. **Team approval** — posted to Discord with approve/reject buttons
5. **Merge** — only after all required checks pass

### Risk tiers (from `risk-policy.json`):
- 🔴 **HIGH** — dashboard, CI workflows, deploy scripts → full gate + review
- 🟡 **MEDIUM** — pipelines, models, scrapers → tests + lint required
- 🟢 **LOW** — docs, markdown → lint only

### Schema protection:
If you modify database schema (CREATE/ALTER/DROP TABLE, migration files), a companion PR
must update the admin dashboard to verify compatibility. The risk gate will flag this.

## Workflow

1. **Run `scripts/docs-list`** — then `cat docs/<name>.md` for every doc whose "Read when" matches your task
2. **`cat` the project's `CLAUDE.md`** in the subfolder you're working in (e.g. `cat nhl-betting/CLAUDE.md`)
3. `git checkout main && git pull origin main` — get latest
4. `git checkout -b feat/your-task` — **always work on a branch**
5. `git status` — check for uncommitted changes
6. Write tests FIRST
7. Write code to pass tests
8. `make ci` (ruff lint + pytest) — must pass
9. `scripts/committer "feat: description" file1 file2 ...` — auto-lints + commits (never `git add .`)
10. `git push origin feat/your-task` — push branch to GitHub
11. `gh pr create` — open pull request, wait for Actions checks
    - Pipeline: gate → code-review (HARD GATE) → test
    - Code review must pass before tests run
    - Direct pushes to `main` are blocked at the platform level

## Deployment — CRITICAL RULE

**ALL deployment MUST go through `scripts/deploy-dashboard`.** This is non-negotiable.

```bash
scripts/deploy-dashboard --all    # Full deploy (CI + build + restart backend + restart tunnel)
scripts/deploy-dashboard          # Frontend-only (no server restart)
scripts/deploy-dashboard --restart-server  # Backend swap only
```

**You MUST NOT:**
- Run `uvicorn` directly
- Run `cloudflared` directly
- Kill server processes manually
- Start servers with `nohup` or any ad-hoc method
- Deploy with arbitrary bash commands

You CAN run `scripts/deploy-dashboard` yourself — that's the whole point. Just always use the script.

**The deploy script handles everything:** CI validation, frontend build, blue-green server swap, Cloudflare tunnel, and health checks. If you bypass it, you WILL break the production dashboard.

If the deploy script itself is broken, fix the script — don't work around it.

## Code Review Tools (Code Factory)

The repo has an automated LLM-powered review system. Key scripts:

- **`scripts/mr-review <PR_NUMBER>`** — Reviews a PR: risk classification + regex checks + LLM deep review. Posts SHA-tagged findings to GitHub.
  - `--auto-resolve` — resolves bot-only threads after clean rerun
  - `--remediate` — outputs findings for coding agent to auto-fix
- **`scripts/llm_review.py`** — LLM engine. Primary: NVIDIA GLM5 (`z-ai/glm5`), fallback: OpenRouter free models.
- **`scripts/risk-classifier`** — Classifies files by risk tier (high/medium/low) per `risk-policy.json`.
- **`scripts/schema-guard`** — Detects DB schema changes, enforces dashboard compatibility.
- **`scripts/docs-guard`** — Validates docs front-matter.

**To run reviews locally:** `source admin-dashboard/.env && scripts/mr-review <PR_NUMBER>`

API keys are in `admin-dashboard/.env` (gitignored): `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`.
`GITHUB_TOKEN` comes from `gh auth login` locally or GitHub Actions in CI.

## Rules

- **Conventional Commits:** `feat|fix|refactor|build|ci|chore|docs|style|perf|test`
- **Keep files < 500 LOC** — split/refactor as needed
- **Python style:** ruff-compliant, type hints preferred
- **Tests:** pytest, `--import-mode=importlib`
- **No secrets in code** — trust auth for Postgres, no API keys in commits
- **No model artifacts in git** — `.pkl`, `.joblib`, `.h5`, `.pt`, etc. are gitignored
- **Read `docs/networking-security.md` before exposing any service** — Cloudflare only, no raw ports
- **Update docs when you change things** — if you add tables, endpoints, scrapers, or change architecture, update the relevant `docs/*.md` and project `CLAUDE.md`

## Infrastructure

- **Machine:** Mac Mini (arm64, macOS), Tailscale network
- **CI:** GitHub Actions → Discord `#general` webhook
- **Dashboard:** `admin-dashboard/`, served via Cloudflare Tunnel + Access
- **Discord:** NHC server, channels map to project folders

## MCP Servers (Available to You)

- **chrome-devtools** — 26 tools: navigate, snapshot, click, fill, network, console, performance traces
- **deepwiki** — Query documentation for open-source projects
- **mcporter** — CLI to call any MCP tool: `mcporter call <server.tool> key=value`

## Skills (skills.sh)

Use **[skills.sh](https://skills.sh)** community skills instead of writing custom guides. These are maintained by the community and stay current.

### Installed Skills
- **[vercel-react-best-practices](https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices)** — 58 React/Next.js performance rules (waterfalls, bundle size, SSR, re-renders). **Use this for ALL frontend work.**
- **[pandas-pro](https://skills.sh/jeffallan/claude-skills/pandas-pro)** — Vectorized pandas patterns, memory optimization, groupby/merge/cleaning. **Use this for ALL data pipeline work.**
- **[find-skills](https://skills.sh/vercel-labs/skills/find-skills)** — Meta-skill: search skills.sh for new capabilities when you hit unfamiliar domains.

### How to Use
1. **Before starting work**, check if a relevant skill exists: `npx skills find <topic>`
2. **Install new skills**: `npx skills add <owner/repo@skill-name>`
3. **Check for updates**: `npx skills check`
4. Browse all skills at: https://skills.sh

### Rule
If a skills.sh community skill exists for your task, **use it** — do not write custom instructions that duplicate what a maintained skill already covers.

## Team

NH Capital — 5-person investment team. You're building tools for quantitative analysis, betting models, and data pipelines.
