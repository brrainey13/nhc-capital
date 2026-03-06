---
title: Sub-Agent Workflow
summary: 'How to spawn and manage Codex / Claude Code sub-agents for coding tasks.'
status: active
owner: nhc
read_when:
  - Spawning coding agents (Codex, Claude Code)
  - Understanding the monorepo structure for agents
---

# Sub-Agent Workflow

NHC is the **orchestrator** — it delegates coding work to sub-agents (Codex CLI, Claude Code) and manages their output.

## Available Agents

| Agent | Command | Best For | Model |
|-------|---------|----------|-------|
| **Codex CLI** | `codex exec --full-auto 'task'` | Focused edits, reviews, refactoring | gpt-5.3-codex |
| **Claude Code** | `claude --dangerously-skip-permissions -p 'task'` | Complex multi-step work, architecture changes | claude-sonnet |

## Spawning Agents — ALWAYS USE TMUX

**⚡ MANDATORY:** Never spawn agents with bare background (`&`) or `exec`. Always use tmux named sessions so you can monitor progress in real-time.

### Naming Convention
- `codex-<task>` — e.g. `codex-dead-code`, `codex-tests`
- `claude-<task>` — e.g. `claude-cleanup`, `claude-migrate`

### One-Shot Tasks

```bash
# Codex — focused edit
tmux new-session -d -s codex-validation -c ~/nhc-capital \
  'codex exec --full-auto "Add input validation to routes/ingest.py"'

# Claude Code — refactor
tmux new-session -d -s claude-pooling -c ~/nhc-capital \
  'claude --dangerously-skip-permissions -p "Refactor lib/db.py to use connection pooling"'
```

### Parallel Tasks

```bash
# Multiple agents at once — each in its own named session
tmux new-session -d -s codex-dead-code -c ~/nhc-capital \
  'codex exec --full-auto "Audit nhl-betting/ for dead code"'

tmux new-session -d -s claude-docs -c ~/nhc-capital \
  'claude --dangerously-skip-permissions -p "Update all CLAUDE.md files for GitHub"'
```

### Monitoring

```bash
# List all running agent sessions
tmux ls

# Capture last 50 lines of output (non-blocking)
tmux capture-pane -t codex-dead-code -p -S -50

# Attach to watch live (Ctrl-B then D to detach)
tmux attach -t claude-docs

# Check if agent is still running
tmux has-session -t codex-dead-code 2>/dev/null && echo "running" || echo "done"
```

### Killing

```bash
tmux kill-session -t codex-dead-code
```

## Rules for Sub-Agents

1. **Always set working directory** to the project subfolder, NOT the openclaw workspace
2. **Use `scripts/committer`** for all commits — never `git add .`, never `git commit`
3. **Push to `origin`** (GitHub)
4. **Never push directly to `main`** — create a branch + PR
5. **Per-project venvs** — use `<project>/.venv/bin/python`, never system python
6. **Never run agents in `~/.openclaw/`** — they read soul docs and go off-rails

## Monorepo Structure

```
~/nhc-capital/                  ← Monorepo root
├── admin-dashboard/            ← FastAPI + React dashboard
│   ├── CLAUDE.md               ← Agent instructions for this project
│   ├── backend/                ← Python FastAPI
│   └── frontend/               ← React + Vite
├── nhl-betting/                ← NHL prop betting
│   ├── CLAUDE.md
│   ├── model/                  ← LightGBM models
│   ├── pipeline/               ← Daily picks pipeline
│   ├── scrapers/               ← Odds scrapers
│   └── strategies/             ← Betting strategies
├── real-estate/                ← CT real estate
│   ├── CLAUDE.md
│   └── scripts/                ← Scrapers + ETL
├── polymarket/                 ← Polymarket scanner
│   ├── CLAUDE.md
│   └── scrapers/
├── scripts/                    ← Shared tooling
│   ├── committer              ← THE commit tool (auto-lints)
│   ├── deploy-dashboard       ← THE deploy tool
│   ├── db-query               ← Read-only DB access
│   ├── db-etl                 ← Write DB access (INSERT/UPDATE only)
│   ├── mr-review              ← Code review agent
│   └── risk-classifier        ← File risk tier classifier
├── lib/                        ← Shared Python libraries
│   ├── db.py                  ← DB helpers
│   ├── ingest.py              ← Bulk insert + validation
│   └── validate.py            ← Data validation
├── tests/                      ← Shared tests
├── docs/                       ← Documentation
├── CLAUDE.md                   ← Top-level agent instructions
├── AGENTS.md                   ← Agent rules (used by OpenClaw)
└── .env.example                ← Template for secrets
```

## Database Access (Agents)

```bash
# READ (SELECT only, connects as nhc_agent)
scripts/db-query nhl_betting "SELECT * FROM nhl_picks LIMIT 5"
scripts/db-query real_estate "SELECT count(*) FROM ct_vision_parcels"

# WRITE (INSERT/UPDATE only, connects as nhc_etl)
scripts/db-etl scripts/load_data.py
```

**NEVER** use `psql` directly. **NEVER** run DROP/DELETE/TRUNCATE/ALTER.

## Git Workflow (Agents)

```bash
# 1. Create branch
git checkout -b feat/my-change

# 2. Make changes...

# 3. Commit (auto-lints Python with ruff)
scripts/committer "feat: add input validation" routes/ingest.py lib/validate.py

# 4. Push to GitHub
git push origin feat/my-change

# 5. Create PR
gh pr create --title "feat: add input validation" --body "Added validation for..."
```

## Infrastructure

- **GitHub:** github.com/nhccapitalinc-gif/nhc-capital (PUBLIC)
- **Dashboard:** dashboard.nhc-capital.com (Cloudflare Tunnel + Access)
- **Database:** PostgreSQL 17 @ localhost:5432
- **CI/CD:** GitHub Actions (gate → review → test → human merge)
