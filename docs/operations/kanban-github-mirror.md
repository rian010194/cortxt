# Kanban → GitHub Mirror

## Purpose

Post completed Kanban task results as comments on the corresponding GitHub
issues. Keeps GitHub as the durable record while Kanban handles execution.

> **Status (verified 2026-08-09):** **script + wrapper exist; NO cron is
> registered.** `hermes cron list` currently contains only `kanban-buzz-push`
> (every 5 min). There is **no** `mirror-kanban-to-github` cron, and the
> documented id `2279ca7e474f` is **not** registered. The mirror therefore does
> NOT run automatically today. It is a *manual/available* capability, not an
> active scheduled function. History is recorded in the git log; the active
> function column below reflects only what is verifiably wired now.

## Components

| File | Purpose | Active? |
|------|---------|---------|
| `harness/scripts/mirror-kanban-to-github.py` | Reads Kanban DB, posts comments via `gh` CLI | Available (manual) |
| `harness/scripts/mirror-kanban-to-github.bat` | Windows wrapper (Hermes venv Python) | Available (manual) |
| Hermes cron job `mirror-kanban-to-github` | Runs every 10 minutes | **NO — not registered (verified 2026-08-09)** |

## How it works (manual invocation)

1. Run `mirror-kanban-to-github.bat` (or the python directly, see below).
2. Script queries `kanban.db` for `done` tasks not yet mirrored.
3. Extracts `owner/repo#issue` from the task body.
4. Formats a result envelope comment.
5. Posts to GitHub via `gh issue comment`.
6. Tracks mirrored tasks in `.mirrored.json` to avoid duplicates.

> Automatic scheduling is **not** active. Re-activating it (e.g. creating the
> cron job) is tracked and must first demonstrate correct idempotence and
> fail-closed behaviour per the operating model; it is not assumed.

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

## Scheduled (cron) management

**No cron is currently registered**, so these commands are shown for when a
cron is created — do not run them expecting a live job today:

```bash
# View current scheduled jobs (authoritative)
hermes cron list

# When (and only when) the mirror job is registered:
#   hermes cron list            # get the real job id
#   hermes cron pause <id>      # same job id
#   hermes cron resume <id>
#   hermes cron remove <id>
```

> The id `2279ca7e474f` referenced in older revisions was not verifiable as
> registered (checked `hermes cron list` on 2026-08-09). Do not trust that id
> or any other id from documentation — read `hermes cron list` for the live one.

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
