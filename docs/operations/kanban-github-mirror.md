# Kanban → GitHub Mirror

## Purpose

Automatically post completed Kanban task results as comments on the corresponding GitHub issues. Keeps GitHub as the durable record while Kanban handles execution.

## Components

| File | Purpose |
|------|---------|
| `harness/scripts/mirror-kanban-to-github.py` | Polls Kanban DB, posts comments via `gh` CLI |
| `harness/scripts/mirror-kanban-to-github.bat` | Windows wrapper (Hermes venv Python) |
| Hermes cron job `mirror-kanban-to-github` | Runs every 10 minutes |

## How it works

1. Cron job runs `mirror-kanban-to-github.bat` every 10 minutes.
2. Script queries `kanban.db` for `done` tasks not yet mirrored.
3. Extracts `owner/repo#issue` from the task body.
4. Formats a result envelope comment.
5. Posts to GitHub via `gh issue comment`.
6. Tracks mirrored tasks in `.mirrored.json` to avoid duplicates.

## Task body format for auto-linking

Include a GitHub issue reference in the task body:

```
Issue: rian010194/ai-workspace-control-plane#13
```

Or a full URL:

```
https://github.com/rian010194/ai-workspace-control-plane/issues/13
```

## Manual run

```bash
# From repo root
harness/scripts/mirror-kanban-to-github.bat
```

Or with Python directly:

```bash
"/c/Users/rikar/AppData/Local/hermes/hermes-agent/venv/Scripts/python" \
  "$(cygpath -w harness/scripts/mirror-kanban-to-github.py)"
```

## Cron job management

```bash
# View status
hermes cron list

# Pause
hermes cron pause 2279ca7e474f

# Resume
hermes cron resume 2279ca7e474f

# Remove
hermes cron remove 2279ca7e474f
```

## Comment format

```markdown
## 📋 Kanban Run Complete

**Task:** `t_7db3c75c` — Test 2: Scratch workspace dispatch
**Assignee:** researcher
**Started:** 2026-08-03 00:43:00
**Finished:** 2026-08-03 00:44:00

### Result
Worker log skapad.

### Summary
Dispatcher claim + spawn fungerade.

### Metadata
- cost_usd: 0.23
- input_tokens: 4200

---
*Mirrored automatically from Hermes Kanban `cortxt-cp`.*
```

## Rules

- Never mirror tasks without a GitHub issue reference.
- Never post secrets, prompts, or customer data in the result envelope.
- `.mirrored.json` is local state; it can be reset if needed (tasks will not be re-mirrored if already commented).
