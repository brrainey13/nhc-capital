---
summary: 'How to spawn and manage coding agents (Claude Code, Codex CLI) — patterns, rules, and the orchestrator model.'
read_when:
  - Spawning a coding agent for a task
  - Running Claude Code or Codex CLI
  - Doing background code work in a project
  - Reviewing PRs with agents
  - Parallel issue fixing
---

# Coding Agents

NHC (the orchestrator) spawns coding agents for code-heavy work. NHC does NOT write code itself — it delegates to agents and monitors output.

## The Model

```
Team (Discord) → NHC (orchestrator) → Coding Agent (tmux/background)
                     ↓                        ↓
                monitors output          writes code, runs tests
                     ↓                        ↓
                reports back             commits via scripts/committer
```

**NHC is the operator, not the coder.** NHC:
1. Receives a task (from Discord, heartbeat, or direct chat)
2. Reads relevant docs (`scripts/docs-list`)
3. Spawns a coding agent pointed at the right `workdir`
4. Monitors output via `process:log`
5. Reports results back to the team
6. Never hand-codes patches — if an agent fails, respawn or escalate

## Spawning Agents

### Claude Code (preferred for complex tasks)

```bash
# One-shot (quick task)
bash pty:true workdir:~/nhc-capital/<project> command:"claude --dangerously-skip-permissions --print 'Your task here'"

# Background (longer work)
bash pty:true workdir:~/nhc-capital/<project> background:true command:"claude --dangerously-skip-permissions 'Your task here'"
```

### Codex CLI (good for focused edits)

```bash
# One-shot
bash pty:true workdir:~/nhc-capital/<project> command:"codex exec --full-auto 'Your task here'"

# Background
bash pty:true workdir:~/nhc-capital/<project> background:true command:"codex --yolo 'Your task here'"
```

### tmux (persistent sessions)

```bash
# Create session
tmux new-session -d -s <name> -c ~/nhc-capital/<project> 'claude --dangerously-skip-permissions'

# Send instructions
tmux send-keys -t <name> "your prompt" Enter

# Read output
tmux capture-pane -t <name> -p

# List / kill
tmux list-sessions
tmux kill-session -t <name>
```

## Rules

1. **Always use `pty:true`** — coding agents are interactive terminal apps
2. **Always set `workdir`** to the project subfolder, NOT the workspace root
3. **Never run agents in `~/.openclaw/`** — they'll read soul docs and go off-rails
4. **Monitor with `process:log`** — check progress without interfering
5. **Be patient** — don't kill sessions just because they're slow
6. **If agent fails, respawn** — don't silently take over and hand-code patches
7. **Commit via `scripts/committer`** — stages only listed files, prevents repo-wide adds

## Progress Updates

When spawning background agents, keep the team in the loop:
- 1 message when you start (what + where)
- Update on milestones (tests pass, build done)
- Update on errors or questions
- Final message when done (what changed + where)

## Wake Trigger (Auto-Notify)

For long-running tasks, append this to the agent prompt so NHC gets pinged immediately:

```
When completely finished, run:
openclaw system event --text "Done: [brief summary]" --mode now
```

## Before Every Commit

Agents should follow this flow:
1. Write tests first
2. Write code to pass tests
3. `make ci` (lint + test)
4. All green → `scripts/committer "feat: description" file1 file2`
5. Push only when ready

## Parallel Work (git worktrees)

```bash
git worktree add -b fix/issue-1 /tmp/issue-1 main
git worktree add -b fix/issue-2 /tmp/issue-2 main

# Spawn agents in each
bash pty:true workdir:/tmp/issue-1 background:true command:"codex --yolo 'Fix issue #1...'"
bash pty:true workdir:/tmp/issue-2 background:true command:"codex --yolo 'Fix issue #2...'"

# Clean up after
git worktree remove /tmp/issue-1
git worktree remove /tmp/issue-2
```
