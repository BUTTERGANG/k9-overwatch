---
vault_lock: false
locked_by: null
lock_reason: null
---

# CLAUDE.md — k9-overwatch Agent Startup

> **Scope:** This SCRUM board covers k9-overwatch only.
> **Central Protocol:** All sprint planning, agent protocol, and Definition of Done live at [BUTTERGANG/SCRUM](https://github.com/BUTTERGANG/SCRUM). This board is for task-level work on this repo.

---

## Quick Start (Every Session)

### 1. Check Vault Lock
Read the frontmatter above. If `vault_lock: true` — STOP. Do not claim anything.

### 2. Read the Sprint Board
Read `SCRUM/Sprint_View.md` in this repo. Find unclaimed tasks (`agent_claimed: null`) with `status: sprint`.

### 3. Check Who's Working on What
Run: `grep -r "agent_claimed:" SCRUM/Working/ SCRUM/Backlog/` to see active claims.

### 4. Pick and Claim a Task
Edit the task file:
```yaml
status: in-progress
agent_claimed: <your-agent-id>
claimed_at: <ISO-8601>
updated: <ISO-8601>
```
Move it: `SCRUM/Backlog/` → `SCRUM/Working/`

---

## Task Lifecycle

| Status | Location |
|--------|----------|
| `backlog` / `sprint` | `SCRUM/Backlog/` |
| `in-progress` / `review` / `blocked` | `SCRUM/Working/` |
| `done` | `SCRUM/Archive/` |

---

## Shutdown Protocol

Before ending a session:
1. Add a Work Log entry to your task file
2. Update frontmatter to reflect true status
3. `git add -A && git commit -m "chore: <agent-id> shutdown — <task-name> <status>" && git push"

---

## Sprint Planning

Sprint planning is managed centrally. Check [BUTTERGANG/SCRUM/05_Dashboards/Sprint_View.md](https://github.com/BUTTERGANG/SCRUM/blob/main/05_Dashboards/Sprint_View.md) for the current sprint goal and allocation.

When a sprint starts, the backlog agent will update `SCRUM/Sprint_View.md` in this repo with the relevant tasks.
