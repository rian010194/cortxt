# Hermes Kanban — Execution Ledger Guide

## Purpose

Hermes Kanban is **not** a backlog. It is an execution ledger for multi-agent runs that must correlate to a GitHub Issue.

Use it when:
- A single GitHub issue requires **multiple parallel workers**.
- Workers have **dependencies** (e.g. synthesizer must wait for research).
- You need **durability** — recovery if a worker crashes or times out.
- You want **atomic claim** — only one profile executes a task.

Do **not** use it when:
- A single Hermes session with `delegate_task` is enough.
- There is no GitHub issue to correlate against.
- You need strategic planning or prioritization (use GitHub Projects).

## Concepts

| Concept | Meaning |
|---------|---------|
| **Board** | Isolated queue per project/repo. Default is `default`. |
| **Task** | One unit of work, tied to a GitHub issue. Has status, assignee, body, workspace. |
| **Status** | `triage` → `todo` → `ready` → `running` → `done` / `blocked` |
| **Parent/Child** | Hard dependency. A child in `todo` stays blocked until all parents are `done`. |
| **Claim** | Atomic lock. Only one profile can claim a `ready` task. |
| **Workspace** | Each task gets a directory under `kanban/boards/<slug>/workspaces/<task_id>/`. |
| **Dispatcher** | Runs in the gateway. Reclaims stale claims, promotes ready tasks, spawns workers. |

## Demo: Parallel research + synthesis

This demo mirrors GitHub issue #7 (Wayfinder map) with three parallel research tracks and one synthesizer.

### 1. Create the board

```bash
hermes kanban boards create cortxt-cp --name "Cortxt Control Plane" --switch
```

### Windows path note

On Windows (git-bash), project paths must be in native Windows format. Use `cygpath -w`:

```bash
hermes project create "Cortxt CP" --slug cortxt-cp \
  --primary "$(cygpath -w /c/Users/rikar/cortxt/projects/ai-workspace-control-plane)" \
  --board cortxt-cp --use
```

### 2. Create independent research tasks (parallel)

```bash
hermes kanban create "#13: Inventera Hermes skills" \
  --body "Issue: rian010194/ai-workspace-control-plane#13
Scope: Mappa inbyggda och optional skills.
Acceptance: Skills lista, gap-dokument." \
  --assignee researcher --max-runtime 600 --idempotency-key "github-13"

hermes kanban create "#11: Granska Matt Pocock-kandidater" \
  --body "Issue: rian010194/ai-workspace-control-plane#11
Scope: Valj skills for krav, spec, felsokning.
Acceptance: Kohort definierad." \
  --assignee researcher --max-runtime 300 --idempotency-key "github-11"

hermes kanban create "#12: Granska ECC-monster" \
  --body "Issue: rian010194/ai-workspace-control-plane#12
Scope: Anpassa eval-harness, verification-loop.
Acceptance: ECC anpassade." \
  --assignee researcher --max-runtime 300 --idempotency-key "github-12"
```

Result: all three are `ready` and can run in parallel.

### 3. Create synthesis task with dependencies

```bash
hermes kanban create "#7: Synthesize research" \
  --body "Depends on #11, #12, #13.
Scope: Gemensamt skillregister + gap-analys." \
  --assignee coordinator --max-runtime 300 \
  --parent t_29e4e958 --parent t_8fd804c8 --parent t_39c71620
```

Result: `todo` — blocked until all parents are `done`.

### 4. Claim and run a task

```bash
hermes kanban claim t_29e4e958
# Output: Workspace: C:\Users\rikar\...\kanban\boards\cortxt-cp\workspaces\t_29e4e958
```

Inside Hermes (or the spawned worker), the task context is available. Run the work in the provided workspace.

### 5. Complete with result envelope

```bash
hermes kanban complete t_29e4e958 \
  --result "Skills inventory skapat. 47 inbyggda, 12 optional." \
  --summary "Gap: EU-provenance, syntes, schema/evals, run manifests." \
  --metadata '{"skills_found":59,"gaps":4}'
```

### 6. Automatic promotion

When the last parent completes, the synthesis task automatically promotes from `todo` to `ready`:

```
✓ t_29e4e958  done      researcher    #13: Inventera Hermes skills
✓ t_8fd804c8  done      researcher    #11: Granska Matt Pocock-kandidater
✓ t_39c71620  done      researcher    #12: Granska ECC-monster
▶ t_eb6cac92  ready     coordinator   #7: Synthesize research
```

## Automation: Gateway dispatcher

For unattended execution, start the gateway:

```bash
hermes gateway start
```

The embedded dispatcher ticks every 60 seconds (config: `kanban.dispatch_interval_seconds`). It will:

1. Reclaim stale claims (worker died, no heartbeat).
2. Promote `todo` tasks whose parents are all `done`.
3. Spawn the assigned profile for each `ready` task.

Config in `~/.hermes/config.yaml`:

```yaml
kanban:
  dispatch_in_gateway: true
  dispatch_interval_seconds: 60
  failure_limit: 2
```

## Manual dispatch without gateway

If you prefer manual control (current operational baseline):

```bash
# List ready tasks
hermes kanban list

# Claim one
hermes kanban claim <task_id>

# Run Hermes with that profile
hermes -p researcher

# Inside session, reference the task workspace and body

# Mark complete
hermes kanban complete <task_id> --result "..." --summary "..."
```

## Swarm mode (advanced)

For complex parallel → verify → synthesize graphs, use `hermes kanban swarm`:

```bash
hermes kanban swarm "Vertical 01 delivery" \
  --workers researcher:2 --verifier coordinator --synthesizer coordinator \
  --body "Deliver vertical-01-ai-act package"
```

This creates a graph automatically: workers run in parallel, verifier checks, synthesizer integrates.

## Cleanup

```bash
# Archive old tasks
hermes kanban archive t_29e4e958 t_8fd804c8 t_39c71620

# Garbage-collect old workspaces and logs
hermes kanban gc

# Switch back to default board
hermes kanban boards switch default
```

## Rules

- Every Kanban task must correlate to a GitHub issue (use `--idempotency-key "github-N"`).
- Do not create Kanban tasks without a GitHub issue backing them.
- Workers may not approve their own work — result goes to GitHub Review, not Done.
- The board is ephemeral execution state; GitHub is durable truth.
