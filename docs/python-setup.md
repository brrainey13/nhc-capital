---
title: Python Environment Setup
category: infrastructure
updated: 2026-03-06
summary: 'Python 3.13 pinned, per-project venvs with --copies flag, scripts/setup-venvs for setup'
read_when:
  - Setting up Python venvs for any project
  - Debugging venv or import issues
  - Adding new Python dependencies
  - Creating a new project subfolder
---

# Python Environment Setup

## Python Version

**Pinned to Python 3.13** (Homebrew `python@3.13`).

- `.python-version` at repo root specifies `3.13`
- All venvs use `/opt/homebrew/opt/python@3.13/bin/python3.13`
- Do NOT use Python 3.14 — venv detection is broken on Homebrew

## Per-Project Venvs

Each project has its own `.venv/` directory with isolated dependencies:

| Project | Venv | Requirements |
|---|---|---|
| nhl-betting | `nhl-betting/.venv/` | `nhl-betting/requirements.txt` |
| admin-dashboard | `admin-dashboard/.venv/` | `admin-dashboard/backend/requirements.txt` |
| real-estate | `real-estate/.venv/` | `real-estate/requirements.txt` |
| polymarket | `polymarket/.venv/` | `polymarket/requirements.txt` |

## Creating/Recreating Venvs

```bash
# All projects
scripts/setup-venvs

# Single project
scripts/setup-venvs nhl
scripts/setup-venvs dashboard
scripts/setup-venvs real-estate
scripts/setup-venvs polymarket
```

## CRITICAL: --copies Flag

Venvs **MUST** be created with `--copies` (not `--symlinks`, the default).

Homebrew Python uses multi-level symlinks:
```
.venv/bin/python → python3.13 → /opt/homebrew/opt/python@3.13/bin/python3.13
```

When Python resolves its real path, it looks for `pyvenv.cfg` relative to the
**resolved binary** (in Homebrew's directory), not the venv. This means
`sys.prefix == sys.base_prefix` and the venv's site-packages are invisible.

`--copies` copies the actual binary into `.venv/bin/`, so the resolved path
is inside the venv and `pyvenv.cfg` is found correctly.

## Running Code

```bash
# Always use the project's venv python directly:
nhl-betting/.venv/bin/python -m pipeline.nightly_refresh
admin-dashboard/.venv/bin/python -m uvicorn backend.app:app
real-estate/.venv/bin/python -m scripts.geocode_parcels

# NEVER use system python or python3 directly for project code
# NEVER use `cd && python` — use workdir parameter or full paths
```

## Adding Dependencies

```bash
# 1. Add to requirements.txt
# 2. Install in venv
nhl-betting/.venv/bin/pip install -r nhl-betting/requirements.txt
# 3. Commit requirements.txt via PR
```

## Exec Allowlist (OpenClaw)

The following patterns are allowlisted for agent exec:
- `/opt/homebrew/opt/python@3.13/bin/python3.13` — for venv creation
- `/Users/connorrainey/nhc-capital/*/.venv/bin/python` — running project code
- `/Users/connorrainey/nhc-capital/*/.venv/bin/pip` — installing packages

Compound shell commands (`&&`, `|`) are blocked by the allowlist. Use single
commands with the `workdir` parameter instead of `cd && python ...`.
