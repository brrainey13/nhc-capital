---
summary: 'Sub-agent orchestration — when to use sessions_spawn vs coding agents vs cron, and how to manage them.'
read_when:
  - Deciding whether to use a sub-agent or coding agent
  - Spawning background work
  - Managing multiple parallel tasks
  - Orchestrating work across Discord channels
---

# Sub-Agent Orchestration

NHC has three ways to run background work. Pick the right one.

## Decision Tree

```
Need exact timing?           → cron (systemEvent or agentTurn)
Need to write/modify code?   → coding agent (Claude Code / Codex via tmux/background)
Need to research/analyze?    → sessions_spawn (isolated sub-agent)
Need to check something?     → heartbeat (batch periodic checks)
```

## 1. Coding Agents (Code Tasks)

Use when: writing code, fixing bugs, building features, running tests.

See `docs/coding-agents.md` for full patterns.

Key: NHC is the **watcher**, not the coder. Spawn → monitor → report.

## 2. sessions_spawn (Research / Analysis)

Use when: web research, data analysis, summarization, non-code tasks.

```
sessions_spawn(task="Research current NHL standings and injury reports", label="nhl-research")
```

- Runs in isolated session
- Auto-announces results back to requester
- Don't poll in a loop — completion is push-based

## 3. Cron (Scheduled / Timed)

Use when: reminders, periodic checks, exact-time tasks.

```
cron(action="add", job={
  name: "morning-report",
  schedule: { kind: "cron", expr: "0 9 * * *", tz: "America/New_York" },
  payload: { kind: "agentTurn", message: "Generate morning report..." },
  sessionTarget: "isolated"
})
```

## 4. Heartbeat (Batched Periodic)

Use when: multiple lightweight checks that can batch together.

Edit `HEARTBEAT.md` with a checklist. Runs every ~30 min.

## Discord Channel Sessions

Each Discord channel is an **isolated session**. They don't share context.

- `#nhl-betting` session only knows about `nhc-capital/nhl-betting/`
- `#admin-dashboard` session only knows about `nhc-capital/admin-dashboard/`
- Cross-channel coordination happens in `#general` or via `sessions_send`

## Managing Running Work

```
subagents(action="list")           # See what's running
subagents(action="steer", ...)     # Redirect a sub-agent
subagents(action="kill", ...)      # Stop a sub-agent
process(action="list")             # See background exec sessions
process(action="log", ...)         # Check output
```

## Anti-Patterns

- ❌ Don't poll `subagents list` in a loop — wait for push notification
- ❌ Don't hand-code patches when an agent fails — respawn or escalate
- ❌ Don't run coding agents in `~/.openclaw/` — they read soul docs
- ❌ Don't spawn agents without setting `workdir` to the right project
- ❌ Don't create cron jobs for things that fit in `HEARTBEAT.md`
