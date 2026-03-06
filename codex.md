# Codex Instructions — NHC Monorepo

Same rules as CLAUDE.md. Read that first.

## 🚨 GIT WORKFLOW — CRITICAL

**Primary remote is `origin` (GitHub).** You CANNOT push to `main` — branch protection will reject it.

```bash
git checkout -b feat/your-task    # Always work on a branch
# ... do work ...
make ci                            # Must pass
scripts/committer "feat: msg" files...
git push -u origin feat/your-task  # Push to GitHub
gh pr create --title "feat: msg"   # Open pull request
```

**NEVER:** `git push origin main` — branch protection will reject it.

## ⚠️ MANDATORY FIRST STEP: Run `scripts/docs-list` and read matching docs. Always.

Also read the `CLAUDE.md` in whatever project subfolder you're working in.

## Virtual Environments

**Always use the project's `.venv/bin/python`**, never system Python:
- `nhl-betting/.venv/bin/python`, `polymarket/.venv/bin/python`, etc.
- If venv missing: `cd <project> && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

## Codex-Specific

- You're running locally on Mac Mini (arm64, macOS)
- All work happens in this repo — don't clone elsewhere
- Use `scripts/committer` for commits (never raw `git add`)
- Run `make ci` before committing
- Push to `origin` remote, open PR with `gh pr create`
- No model artifacts in git (`.pkl`, `.joblib`, `.h5`, `.pt` are gitignored)
- **Update docs when you change things** — stale docs waste everyone's time
- **NEVER run uvicorn directly** — use `scripts/deploy-dashboard --all` for ALL deployment
- If you finish, exit cleanly

## Frontend Development

When working on `admin-dashboard/frontend/`:
- **React 18+** with Vite + TypeScript
- **Tailwind CSS** for all styling
- **@tanstack/react-virtual** for large lists/tables
- **Recharts** or **visx** for charts
- Components < 200 LOC, TypeScript interfaces for props + API responses
- `npm run build` must succeed before committing frontend changes

## Available Reference Skills

Best-practice guides are installed at `~/.openclaw/workspace/skills/`:
- `vercel/SKILL.md` — Vercel deployment, domains, env vars
- `react/SKILL.md` — React patterns, hooks, components
- `nextjs/SKILL.md` — Next.js App Router, SSR, API routes
- `pandas/SKILL.md` — Pandas data analysis patterns
- `python-dataviz/SKILL.md` — Python visualization libraries
- `data-analysis/SKILL.md` — Statistical analysis, EDA
- `frontend/SKILL.md` — Frontend design best practices
- `tailwind-v4-shadcn/SKILL.md` — Tailwind v4 + shadcn/ui

Read these when working on relevant tasks.
