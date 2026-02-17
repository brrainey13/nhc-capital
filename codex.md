# Codex Instructions — NHC Monorepo

Same rules as AGENTS.md. Read that first.

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
- No model artifacts in git (`.pkl`, `.joblib`, `.h5`, `.pt` are gitignored)
- **Update docs when you change things** — stale docs waste everyone's time
- **NEVER run uvicorn or ngrok directly** — use `scripts/deploy-dashboard --all` for ALL deployment
- If you finish, exit cleanly

## If Running in Cloud Mode

- Create a PR instead of pushing to main
- The orchestrator (NHC) will review and merge
- Include test results in PR description
