# Hermes Kanban Swarm Mode

Status: active operational
Authority: runtime operations
Last verified: 2026-08-11

## Purpose

Swarm mode creates a complete multi-agent graph automatically:

```
Parallel workers → Verifier → Synthesizer
```

Use it when a GitHub issue requires:
- Multiple independent research or implementation tracks
- An independent verification step
- A final synthesis/integration step

## Command

```bash
hermes kanban swarm "GOAL" \
  --worker researcher:"Task 1 title" \
  --worker researcher:"Task 2 title" \
  --worker researcher:"Task 3 title" \
  --verifier coordinator \
  --synthesizer coordinator \
  --idempotency-key "swarm-001"
```

## Demo result

Command:

```bash
hermes kanban swarm "Vertical 01 delivery: skills inventory" \
  --worker researcher:"#13: Inventera Hermes skills" \
  --worker researcher:"#11: Granska Matt Pocock" \
  --worker researcher:"#12: Granska ECC" \
  --verifier coordinator \
  --synthesizer coordinator \
  --idempotency-key "swarm-test-001"
```

Output:

```
Swarm root: t_8b1fdd9c
Workers: t_bf18e6fa, t_b2a0087b, t_f20c4a14
Verifier: t_af2b71a2
Synthesizer: t_ed4664b1
```

## Resulting board state

```
✓ t_8b1fdd9c  done      coordinator   Swarm: Vertical 01 delivery: skills inventory
▶ t_bf18e6fa  ready     researcher    #13
▶ t_b2a0087b  ready     researcher    #11
▶ t_f20c4a14  ready     researcher    #12
□ t_af2b71a2  todo      coordinator   Verify swarm outputs
□ t_ed4664b1  todo      coordinator   Synthesize swarm outputs
```

## Execution flow

1. **Root** (`t_8b1fdd9c`) — Planning card, completes immediately. Stores swarm topology as a comment.
2. **Workers** — All three are `ready` and can run in parallel. Each has its own workspace.
3. **Verifier** — `todo`, blocked until all workers are `done`. Checks worker outputs.
4. **Synthesizer** — `todo`, blocked until verifier is `done`. Produces final integrated result.

## Dependencies (auto-created)

```
t_8b1fdd9c (root)
  → t_bf18e6fa (worker)
  → t_b2a0087b (worker)
  → t_f20c4a14 (worker)
  → t_af2b71a2 (verifier) → depends on all workers
t_af2b71a2 (verifier)
  → t_ed4664b1 (synthesizer) → depends on verifier
```

## Running the swarm

### Manual (current baseline)

```bash
# Claim each worker
hermes kanban claim t_bf18e6fa
# ... run researcher profile ...
hermes kanban complete t_bf18e6fa --result "..."

# When all workers done, verifier promotes to ready
hermes kanban claim t_af2b71a2
# ... run coordinator profile ...
hermes kanban complete t_af2b71a2 --result "..."

# Synthesizer promotes to ready
hermes kanban claim t_ed4664b1
# ... run coordinator profile ...
hermes kanban complete t_ed4664b1 --result "..."
```

### Unattended (gateway dispatcher)

```bash
hermes gateway start
```

With `kanban.dispatch_in_gateway: true`, the dispatcher will:
1. Spawn all `ready` workers in parallel (respecting `max_spawn` limit).
2. Auto-promote verifier when all workers complete.
3. Auto-promote synthesizer when verifier completes.

## Cleanup after swarm

```bash
# Archive all swarm tasks
hermes kanban archive t_8b1fdd9c t_bf18e6fa t_b2a0087b t_f20c4a14 t_af2b71a2 t_ed4664b1

# GC
hermes kanban gc
```

## Rules

- Always include `--idempotency-key` to prevent duplicate swarms.
- Root card stores topology — check its comments for the full graph.
- Workers may not approve their own work — verifier + synthesizer provide separation.
- Correlate to a GitHub issue in each worker body for mirror script compatibility.
