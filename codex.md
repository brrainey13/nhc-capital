# Codex Instructions — NHC Monorepo

Same rules as AGENTS.md. Read that first.

## Codex-Specific

- You're running locally on Mac Mini (arm64, macOS)
- All work happens in this repo — don't clone elsewhere
- Use `scripts/committer` for commits (never raw `git add`)
- Run `make ci` before committing
- If you finish, exit cleanly

## If Running in Cloud Mode

- Create a PR instead of pushing to main
- The orchestrator (NHC) will review and merge
- Include test results in PR description
