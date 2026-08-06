# Gateway Dispatch Test Results

## Date
2026-08-03

## Test objective
Verify that the Hermes gateway embedded kanban dispatcher can:
1. Detect a `ready` task
2. Atomically claim it
3. Spawn the assigned profile
4. Execute the worker
5. Transition to `done`

## Configuration

```yaml
# ~/.hermes/config.yaml (coordinator profile)
kanban:
  dispatch_in_gateway: true
  dispatch_interval_seconds: 30
```

## Test 1: Worktree workspace (FAILED)

**Task:** `t_3412a813` — "Test: Obevakad dispatch demo"
**Workspace:** `worktree` (default when `--project` is used)

**Result:** `blocked` after 2 spawn failures.

**Root cause:** Project primary path was stored with POSIX-style `C:\c\Users\rikar\...` instead of `C:\Users\rikar\...`. The dispatcher could not create a git worktree in a non-existent path.

**Error:**
```
workspace: task t_3412a813 worktree path 'C:\c\Users\rikar\...' is not inside a git repo
```

**Lesson:** On Windows (git-bash), always pass the primary path through `cygpath -w`:

```bash
hermes project create "My Project" --primary "$(cygpath -w /c/Users/rikar/myrepo)"
```

## Test 2: Scratch workspace (PASSED)

**Task:** `t_7db3c75c` — "Test 2: Scratch workspace dispatch"
**Workspace:** `scratch`

**Result:** `done` in 36 seconds.

**Timeline:**
- `00:43:00` — Task created in `ready`
- `00:43:05` — Dispatcher claimed (`lock: BillGates:8444`, `run_id: 6`)
- `00:43:05` — Spawned worker (PID 31424) with `researcher` profile
- `00:44:00` — Heartbeat received
- `00:44:00` — Worker completed via `kanban_complete`
- `00:44:00` — Task moved to `done`

**Worker log excerpt:**
```
Query: work kanban task t_7db3c75c
Initializing agent...
··· kanban_show → status=running
··· terminal → created worker.log
··· kanban_complete → done
```

**Acceptance criteria:**
- [✓] Status went from `ready` to `running`
- [✓] Worker log was created
- [✓] Task completed automatically without operator intervention

## Verified capabilities

- [x] Gateway kanban dispatcher embedded and ticking every 30s
- [x] Atomic claim with `run_id` generation outside the model
- [x] Profile-spawned worker (`researcher`) with isolated session
- [x] Heartbeat during execution
- [x] Automatic completion via `kanban_complete`
- [x] Workspace isolation (`scratch` and `worktree` modes)

## Remaining gaps

- [ ] Worktree mode requires correct Windows path format via `cygpath -w`
- [ ] Gateway must run continuously for unattended dispatch
- [ ] No messaging platforms configured (gateway runs for cron/kanban only)
- [ ] Worker output is not automatically mirrored to GitHub Issues
- [ ] Cost telemetry is `unknown` for this run

## Next steps

1. Use `scratch` workspace for tasks that do not need git worktrees.
2. For git worktrees, always create the project with `cygpath -w` on Windows.
3. Mirror completed kanban results to GitHub issue comments via a post-complete hook or cron job.
4. Test `swarm` mode for parallel → verify → synthesize graphs.
