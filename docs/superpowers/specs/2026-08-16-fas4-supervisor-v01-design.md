# Fas 4 — Supervisor v0.1 — design

Status: approved (interactive brainstorming dialogue with operator 2026-08-16; independent
review by Kimi K2.7-code via Hermes, same day — see "Independent review" section)
Date: 2026-08-16
Authority: architectural proposal for one bounded vertical slice; does not override
`docs/agents/current-operating-model.md`
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §7 (Cortxt
Supervisor), §23 (Fas 4 — Supervisor v0.1), §24.1 (Hermes replacement criteria), §27
(Öppna beslut #1-3), §28 (Arkitektoniska invariants); ADR-019 (confirms §24.1/Supervisor
replacement path is untouched by the coding-engine permanent-multi-routing decision);
`docs/superpowers/specs/2026-08-15-fas2-agent-runtime-v01-design.md` and
`2026-08-16-fas3-coding-agent-v01-design.md` (the phases this builds directly on)

> **Dependency: Fas 2 is merged to main; Fas 3's implementation is not.** Fas 2
> (`session_state.py` — append-only, hash-chained, atomically-written per-session
> event log with optimistic-concurrency `append()`; `agent_loop.py` — single-threaded
> synchronous `AgentLoop.run()`) is on `main` (PR #143/#146/#147). Fas 3's
> implementation — `runtime/coding/coding_loop.py` (`CodingLoop.run()`), the
> `runtime/tools/` package (`patch.py`, `workspace.py`, `execution.py`, `gate.py`),
> `runtime/execution/` (subprocess sandbox, write policy) — exists only on branch
> `agent/fas3-coding-agent-plan` (14 commits, 220 tests, not yet merged); only Fas 3's
> *design spec* (`2026-08-16-fas3-coding-agent-v01-design.md`) is on `main`.
> **Precondition, resolved 2026-08-16: Fas 3 is merged to `main` via PR before Fas 4
> implementation starts** — Fas 4 branches from `main` once that merge lands, not
> from the still-in-review Fas 3 branch. This is tracked as a separate prerequisite
> (PR review + merge), not a task inside the Fas 4 plan. No `supervisor/` package
> exists on either `main` or the Fas 3 branch — Fas 4 is new code, not a refactor of
> existing modules.

## Purpose

Prove Fas 4's exit criterion from the target-architecture staircase (§23): **two
bounded child runs can be carried out and integrated without Hermes.** Per §7.1,
Supervisor's responsibilities are: create/resume root sessions, create and monitor
child sessions, allocate sub-budget without raising the total, handle dependency
joins, provide queryable status and heartbeat, do cancellation and timeout, recover
sessions after process interruption, and integrate terminal child results into one
result envelope.

This exit criterion is a coordination-capability claim, not a reasoning-capability
claim — Fas 4 does not need either child run to be reasoning-sophisticated; it needs
the *coordination* between them (spawn, monitor, join, integrate, recover, cancel) to
be real and machine-proven, the same way Fas 3 made containment the primary
deliverable and the code fix itself the smaller half.

Per ADR-019, this is unrelated to the coding-engine permanent-multi-routing decision.
§24.1 ("Hermes kan lämna huvudvägen när...") is unaffected by ADR-019 and remains the
correct target for what Fas 4 is building toward — a Supervisor capable enough that
Hermes's *coordinating* role can eventually be replaced. Fas 4 v0.1 does not claim
that replacement; it proves the first slice of the capability the replacement
criteria require.

## Scope decisions

Nine decisions, resolved through an interactive brainstorming dialogue with the
operator, then independently reviewed by Kimi K2.7-code (via Hermes) before being
finalized. Recorded so the "why" is not lost.

### 1. Implementation language — Python, `agent-platform/supervisor/`

**Decision:** Python, consistent with Fas 2/3. No new language.

**Why:** Supervisor v0.1 is I/O-bound orchestration (session status, dispatch,
budget bookkeeping) — not compute-bound, so Python's overhead is not the bottleneck.
Reuses Fas 2/3's `session_state.py`, `agent_loop.py`, and reasoning kernel directly
without a cross-language bridge.

**Deferred, not decided:** a systems language (e.g. Rust) becomes worth evaluating
when a *specific phase* shows a measured bottleneck Python cannot absorb —
candidates flagged now are **Fas 6 (Geometric Reasoning — embedding/vector compute,
GIL-bound)** and **Fas 7 (self-hosted inference server — continuous-uptime, low
footprint)**. This is explicitly not a scheduled migration; re-evaluate when one of
those phases produces evidence, not on a fixed version number.

### 2. Process model — separate, detached OS processes per child run

**Decision:** each child run is its own OS process, spawned **detached** (own
process group/session) so it survives if the Supervisor process crashes.

**Why not in-process async:** simpler to build, but recovery-after-crash (§7.1,
an explicit Fas 4 deliverable) would be nearly vacuous — if Supervisor dies, every
async task dies with it, so "recovery" could only ever mean re-running from scratch,
never genuine reattachment to ongoing work.

**Why not threads:** GIL gives no real CPU parallelism for this workload anyway;
shared mutable state between child runs is exactly the kind of uncontrolled coupling
§28 rules out ("Reasoning och execution är separata trust boundaries"); a crashing
thread can corrupt the whole interpreter's state with no crash containment.

**Kimi's addition (agreed):** this is the largest genuinely *new* engineering
surface in Fas 4 — Fas 3's execution sandbox (`run_tests`) was a blocking subprocess
owned by its parent and never had to survive detachment, console loss, or
cross-platform signal handling. Hidden behind a `ProcessSpawner` abstraction (see
Components) rather than left as ad hoc `subprocess` calls scattered through the
codebase.

### 3. IPC — file-based, `session_state.py` is the only contract

**Decision:** no new communication primitive. Supervisor and child processes
communicate exclusively by writing to and reading from `session_state.py`'s
hash-chained per-session logs.

**Why not sockets/pipes:** the Fas 4 exit criterion is two child runs, not many
concurrent channels needing sub-second coordination or work-stealing. Building a
wire protocol now means guessing its shape before a real workload proves what it
needs to be — the same discipline that kept Fas 3 away from a YAML tool manifest and
a dependency graph until a fixture could falsify a simpler design. Recovery-after-
crash is nearly free with file-based state (atomic writes, no partial-message
framing to reason about); a socket introduces a new failure mode ("child alive but
socket dead") this phase does not need to prove.

**Not a dead end:** Supervisor's internal interface (`status()`, `heartbeat()`,
`cancel()`) is the same regardless of transport. Swapping file-polling for real IPC
later is an implementation change behind that interface, not a redesign of the
state machine or the child-run contract (§7.3).

**Deferred, flagged explicitly:** real IPC becomes worth building when concurrent
child-run volume grows enough that O(n) log-reads and polling latency actually
matter — not scheduled, evaluated against a future fleet's real load.

### 4. Persistence — `session_state.py` stays sole source of truth; Supervisor adds a derived, structurally-unwritable run-tree index

**Decision:** per-session hash-chained logs remain authoritative, exactly as in
Fas 2/3. Supervisor adds a `run_tree.py` index (status, budget allocation, join
state) that is a **pure projection**: `build_index(session_docs) -> RunTreeIndex` is
the only constructor; there is no `update_index` API. The index is always rebuilt
from session-log events, never itself written to as a side effect of any operation.

**Why not a fully separate authoritative store:** a second authoritative store
means a second consistency model to keep in sync with the hash-chained logs. If
Supervisor crashes between writing a `child.spawned` event to a child's log and
updating a separately-authoritative run-tree file, exactly the kind of coordination
bug `session_state.py`'s hash-chaining exists to prevent *within* one session
reappears *across* two files.

**Kimi's addition (adopted):** make "always rebuildable" a structural guarantee,
not an intention — no mutation API exists to violate it, rather than a convention
that must be remembered during implementation.

### 5. Exit scenario — staged: M1 (independent) then M2 (sequential + patch handoff), both required for Fas 4 v0.1 exit

**Decision:** the Fas 4 v0.1 exit criterion is proven by two milestones, executed as
sequential tasks within the same plan (not two separate phases):

- **M1:** two *independent* Fas-3-coding-profile child runs, spawned together,
  integrated by merging their two JSON result envelopes into one. Proves process
  spawning, detachment, heartbeat, and file-based IPC/polling — without workspace
  handoff.
- **M2:** child 2 depends on child 1's *output*. Fas 3's `apply_patch` takes
  whole-file content (`{path, new_content}`), not diff hunks — reconstructing
  whole-file content from `diff_workspace`'s unified-diff text externally would
  require a hunk-applying patch algorithm, reintroducing exactly the fuzzy-match
  risk Fas 3's patch design eliminates (see `tools/patch.py`'s module docstring).
  Instead: a small, purely additive change to `CodingLoop.run()` captures each
  changed file's actual content (`result["file_contents"]`) before its workspace
  context manager disposes it (see "Implementation refinement" below). Supervisor
  reads that from child 1's session log and calls Fas 3's existing `apply_patch`
  directly against child 2's fresh copy-in workspace — no new patch-application
  code. Proves dependency joins and workspace-artifact handoff, which M1 alone
  does not exercise.

**Why staged rather than one scenario from the start:** the un-staged sequential
scenario bundles three new hard problems into one slice (detached-process
mechanics, file-based IPC, workspace handoff). Staging isolates which layer is
responsible if something breaks during implementation — the same value Fas 3 got
from treating boundary enforcement and the code fix as separately-provable halves.

**Why both are required for v0.1 exit, not just M1:** §23's Fas 4 deliverables
explicitly list "dependency joins" — a leverable M1 alone cannot prove, since its
two children never depend on each other. Splitting into M1+M2 changes the
*implementation sequencing*, not the *scope* of what Fas 4 v0.1 must demonstrate.

**Inherited, not resolved, by M2:** Fas 3's execution sandbox on Windows (§27 open
decision #4) is still open. M2's coding fixtures inherit whatever that sandbox's
current state is — verify Docker Desktop/WSL2 availability early in planning, or
provide a `sandbox_degraded: true`-flagged subprocess-only fallback (see Error
handling) rather than silently downgrading isolation.

**Implementation refinement (found while grounding this spec against the actual Fas 3
branch):** `CodingLoop.run()`'s `_inspect_scope` closure already computes
`captured["files_changed"]` via `diff_workspace` before its `with run_workspace(...)
as ws:` block exits. The additive change needed is one line: capture
`{p: (ws.work / p).read_text(encoding="utf-8") for p in captured["files_changed"]}`
into `captured["file_contents"]` at the same point, and include it in the returned
`result` dict under the existing `"succeeded"` return statement. No control flow,
error handling, or existing behavior changes — this is read-only, additive, and adds
no new failure mode to already-tested code, unlike the heartbeat fix's shared-state
concern. `coding_loop_cli.py` (via its `SessionWriter`) then appends the file
contents to child 1's own session log as a `result.available` event once
`CodingLoop.run()` returns, so Supervisor — a separate process, per decision 3's
file-based-IPC-only rule — can read it without any new communication channel.

### 6. Recovery — detached children reattached via PID + process start-time

**Decision:** on Supervisor restart, for each root session not yet terminal:
rebuild the run-tree index from session logs, and for each `child.spawned` event
without a matching terminal event, check whether the recorded PID is still running
**and** whether its process start-time matches what was recorded at spawn time. A
match means genuine reattachment (`session.reattached` event, resume monitoring); a
mismatch (dead process, or a live process with a different start-time — i.e. PID
reuse) means the child is marked terminal with a new status, `lost`.

**Why PID alone is insufficient (Kimi's correction, adopted):** after a long
Supervisor outage, the OS can reassign a dead child's PID to an unrelated process.
Bare-PID reattachment would misread that unrelated process as the still-running
child. PID + start-time makes a false-positive reattach effectively impossible
without adding a new dependency (`psutil`) — `GetProcessTimes` on Windows and
`/proc/<pid>/stat` start-time on Linux are sufficient.

**Why a `lost` status rather than reusing `blocked`/`failed`/`cancelled`:** none of
the existing terminal statuses are honest about what happened — Supervisor
genuinely does not know whether a `lost` child crashed, finished successfully with
no chance to report it, or is still running under circumstances that make
reattachment unsafe to assume. A distinct status keeps that uncertainty visible to
the operator rather than guessing.

### 7. Budget — post-hoc rollover only, no mid-flight borrowing

**Decision:** if a child finishes under its allocated budget, the unused surplus
can roll into the next not-yet-started child's pool before that child spawns.
Events `budget.allocated`, `budget.reclaimed`, `budget.transferred` are written to
the root session log so the run-tree index can reconstruct allocations exactly.

**Why not mid-flight borrowing:** M1's two children run concurrently but are
independent (no reason one would need to borrow from the other); M2's two children
never run concurrently (child 2 only spawns after child 1 is terminal). Neither
scenario in this slice creates a situation where a *running* child needs to draw
against a sibling's pool in real time, so a request/grant protocol for that case
would be unproven complexity — deferred until a future scenario actually needs it.

### 8. Cancellation — operator-initiated (CLI) plus Supervisor auto-cancel

**Decision:** an operator can cancel a root session via CLI, propagating to all
non-terminal children (graceful signal, timeout, then forceful kill). Supervisor
also auto-cancels: in M2, if child 1 terminates as `blocked`/`failed`, its join can
never succeed, so child 2 is never spawned (not cancelled — it never existed) and
the root session terminates as `failed`/`blocked` with a reason pointing at child
1's terminal cause.

**Kimi's correction (adopted):** cross-platform signal handling cannot be a naive
`os.kill(pid, signal.SIGTERM)` call — Windows requires `CTRL_BREAK_EVENT` to a
process group followed by `TerminateProcess`; POSIX uses `killpg(SIGTERM)` then
`killpg(SIGKILL)`. Wrapped inside `ProcessSpawner.terminate_gracefully` (see
Components), never called ad hoc from `coordinator.py`.

### 9. Heartbeat — explicit `heartbeat.ping` event from a child-owned `SessionWriter`

**Decision:** each child process runs a daemon timer thread that periodically
appends a `heartbeat.ping` event to its own session log, using a `SessionWriter`
instance shared with the child's main work thread. Supervisor treats a heartbeat
missing for longer than `N × interval` as a stuck-or-dead child.

**Why not rely on PID-liveness alone:** a process can be alive but hung (e.g. stuck
in a long-running test-execution call) — PID-liveness cannot distinguish "working"
from "wedged." An explicit heartbeat can.

**Kimi's correction (adopted, this was a real bug in the original design):**
`session_state.append()` enforces single-writer optimistic concurrency via
`expected_sequence` — two threads in the same child process calling `append()`
independently (main work + a naive heartbeat thread) would race and produce
`SequenceConflict` errors, silently dropping events. Fix: **do not** lock inside
`session_state.py` itself (it stays a simple single-writer primitive); instead, give
each child process a `SessionWriter` (`runtime/session_writer.py`) holding a
`threading.RLock`, and route *all* writes in that process — main work and heartbeat
alike — through the same instance. Folding heartbeat emission into the main loop's
existing write points instead (avoiding the race by avoiding the second thread) was
considered and rejected: a child stuck in a long blocking call would then emit no
heartbeat during exactly the stall Supervisor most needs to detect.

**Implementation refinement (found while grounding this spec against the actual Fas 3
branch, confirmed with a second Kimi K2.7-code pass):** Fas 3's `CodingLoop.run()`
(on `agent/fas3-coding-agent-plan`, not yet merged) already calls
`runtime.session_state.append()` directly, many times, inline inside nested closures
(`_propose`, `_inspect_scope`, `_verify`), with no exception handling around any of
them — the race is worse than first assumed, because a heartbeat write landing
between one of `CodingLoop`'s own `load()`+`append()` calls would raise an uncaught
`SequenceConflict` and crash the child run entirely, not just drop a heartbeat event.
Editing `CodingLoop`'s ~8 call sites to route through `SessionWriter` explicitly was
rejected as unnecessary risk to already-tested, working Fas 3 code that Fas 4 has no
other reason to touch. A sidecar `heartbeat.json` file outside the hash-chained log
was also rejected — it would violate decisions 3 and 4 (single communication
contract, single source of truth) by giving Supervisor two files to reconcile during
recovery.

**Resolution:** `coding_loop_cli.py` (the child entry point) constructs a
`SessionWriter` for the child's session, starts the heartbeat thread against it, then
monkeypatches `runtime.session_state`'s module-level `create`/`load`/
`latest_sequence`/`append` functions — scoped to a context manager, restored on exit
— so that `CodingLoop`'s unmodified internal calls transparently go through the same
writer and lock as the heartbeat thread. This requires Supervisor to **pre-create**
each child's session (`session_state.create()`, called by Supervisor, before
spawning) and pass the resulting `session_id` to the child via `--session-id`, so
`coding_loop_cli.py`'s patched `state.create` can return the already-existing session
document instead of creating a second one — `CodingLoop.run()`'s `task_id` argument
is still passed through, but no longer produces a new session. The patch is process-
local (each child is a separate OS process per decision 2), so it cannot leak into
Supervisor's or another child's view of `session_state`. `CodingLoop.py` itself is
never modified.

## Independent review

Before finalizing, the nine decisions above and a first internal risk pass were sent
to Kimi K2.7-code (via Hermes, session `20260816_175447_294d2d`, 2026-08-16) for an
independent review. Verdict: the decision set is coherent and correctly scoped for
v0.1, but two of the internally-identified risks (the heartbeat/`session_state`
write race, and cross-platform detached-process spawning) were confirmed as genuine
implementation blockers, not polish — both are resolved above (decisions 9 and 2/8
respectively) rather than left open. Kimi's staged-milestone recommendation for the
exit scenario (decision 5) and its PID-reuse correction (decision 6) were also
adopted. A follow-up question — how to reconcile the heartbeat fix with Fas 3's
already-implemented `CodingLoop` (see decision 9's "Implementation refinement") —
was sent the same day; Kimi recommended the process-local monkeypatch approach over
both editing `CodingLoop`'s call sites and a sidecar heartbeat file. Full review
transcripts: `hermes sessions export --session-id 20260816_175447_294d2d` (initial
review) and the follow-up session (heartbeat/`CodingLoop` question).

## Components

**`agent-platform/supervisor/`** (new package):

| Module | Responsibility |
|---|---|
| `coordinator.py` | Root session lifecycle: maps §7.2's state machine (`ADMITTED → FRAMING → READY_TO_REASON → REASONING → EXECUTING → INTEGRATING → VERIFYING → terminal`) to root-session log events. Spawns children, waits on joins, propagates cancellation, builds the final result envelope. |
| `process_spawner.py` | `ProcessSpawner` — platform-hidden `spawn`/`is_alive`/`terminate_gracefully`. Windows: `CREATE_NEW_PROCESS_GROUP`\|`DETACHED_PROCESS`, `CTRL_BREAK_EVENT`→`TerminateProcess`. POSIX: `start_new_session=True`, `killpg(SIGTERM)`→`killpg(SIGKILL)`. `ChildProcess` dataclass: `pid`, `pgid`, `session_id`, `start_time`. |
| `run_tree.py` | `build_index(session_docs) -> RunTreeIndex` — sole constructor, pure projection, no mutation API. Query functions for status/budget/join state. |
| `budget.py` | Post-hoc rollover: reads `budget.*` events, computes the pool available to the next child. |
| `workspace_handoff.py` | M2 only: reads a `result.available` event's `file_contents` from child 1's session log, reshapes it into Fas 3's `apply_patch` `changes` schema (`[{"path", "new_content"}]`), and calls `apply_patch` (from `runtime.tools`, unmodified) against child 2's freshly copied-in workspace before child 2 starts. No new patch-application logic — a reshape plus a direct call. |

**`agent-platform/runtime/`** (extended — these are runtime primitives usable by
any process, not Supervisor-specific):

| Module | Responsibility |
|---|---|
| `session_writer.py` | `SessionWriter` — `threading.RLock`-guarded wrapper serializing all `append()` calls for one session log. Shared by a child process's main-work thread and its heartbeat thread. |
| `coding_loop_cli.py` | New CLI entry point for a child process (`--session-id`, `--store`, `--config-json`). Constructs a `SessionWriter` for the pre-created session, starts the heartbeat daemon thread against it, then monkeypatches `runtime.session_state`'s module-level `create`/`load`/`latest_sequence`/`append` (via a context manager, restored on exit) so Fas 3's unmodified `CodingLoop.run()` transparently writes through the same writer and lock as the heartbeat thread. The child inherits no Python object graph from Supervisor — only filesystem references and the pre-assigned `session_id`. |

**New event vocabulary** in `session_state.py`'s payload conventions (no schema
change): `child.spawned` (pid, pgid, start_time, allocated_budget),
`heartbeat.ping`, `budget.allocated`, `budget.reclaimed`, `budget.transferred`,
`join.waiting`, `join.satisfied`, `session.reattached`, `result.available`
(`file_contents`, M2 only — written by `coding_loop_cli.py` after `CodingLoop.run()`
returns).

**`runtime/coding/coding_loop.py` — one additive line (M2 only):** `CodingLoop.run()`
captures `captured["file_contents"]` (each changed file's actual content) before its
workspace context manager disposes it, and includes it in the returned `result` dict.
No existing behavior, control flow, or error handling changes.

## Data flow

**M1 — two independent child runs:**

```
Root: ADMITTED → FRAMING (splits task into two independent subtasks)
  → READY_TO_REASON → EXECUTING
    spawn child 1 (ProcessSpawner) — session_id_1, budget_1, child.spawned event
    spawn child 2 (ProcessSpawner) — session_id_2, budget_2, child.spawned event
    [Coordinator polls run_tree.build_index() over both session logs]
    child 1 runs Fas 3 AgentLoop, heartbeat.ping via SessionWriter → terminal
    child 2 runs Fas 3 AgentLoop, heartbeat.ping via SessionWriter → terminal
  → INTEGRATING (both terminal: merges two JSON result envelopes)
  → VERIFYING → root terminal (SUCCEEDED/BLOCKED/FAILED)
```

**M2 — sequential dependency, patch handoff:**

```
Root: ADMITTED → FRAMING (splits into a dependent subtask pair) → READY_TO_REASON
  → EXECUTING
    spawn child 1 only; join.waiting logged for child 2
    child 1 runs → terminal
    IF child 1 SUCCEEDED:
      Coordinator reads result.available's file_contents from child 1's session log
      budget.reclaimed (child 1's unused) → budget.transferred to child 2
      workspace_handoff.py reshapes file_contents into apply_patch's changes
        schema, calls apply_patch against child 2's fresh copy-in workspace
      spawn child 2; child 2 runs → terminal; join.satisfied
    IF child 1 BLOCKED/FAILED:
      child 2 is NEVER spawned (auto-cancel of the join; no wasted process)
      root → FAILED/BLOCKED, reason points at child 1's terminal cause
  → INTEGRATING → VERIFYING → root terminal
```

**Recovery (after a Supervisor process interruption):**

```
Supervisor restarts
  → for each non-terminal root session: rebuild run_tree.build_index()
    from session logs (never a stale cache read)
  → for each child.spawned without a matching terminal event:
    ProcessSpawner.is_alive(pid, start_time)?
      YES → log session.reattached, resume polling/heartbeat monitoring
      NO (dead, OR alive with a mismatched start_time → PID reuse)
        → child marked terminal with status='lost' (distinct from
          blocked/failed/cancelled — genuinely unknown outcome)
        → root cannot reach SUCCEEDED; becomes BLOCKED, reason "child lost
          during supervisor outage"
```

## Error handling

| Case | Handling |
|---|---|
| Child exhausts its allocated sub-budget | `BudgetExhausted` (Fas 2/3 pattern) → child terminal `blocked`. In M2, if it's child 1, this blocks the join — child 2 is never spawned. |
| Heartbeat missing beyond `N × interval` | Child judged stuck/dead. Supervisor auto-cancels via `ProcessSpawner.terminate_gracefully`. Terminal status `blocked`, reason "heartbeat timeout". |
| Join dependency can never succeed (child 1 failed/blocked in M2) | Auto-cancel: child 2 never spawned. Root → `failed`/`blocked`. |
| `ProcessSpawner.spawn()` fails (OS error, resource exhaustion) | No `child.spawned` event is ever written; root logs `spawn_failed` and treats the child as immediately `failed` with no process having existed. |
| Recovery reattach: PID alive but `start_time` mismatched | Treated as dead (PID reuse) — `lost` status. Never reattach on PID alone. |
| `apply_patch` (via `workspace_handoff.py`) fails (M2, e.g. a cap violation on child 2's fresh copy) | Child 2 never spawned; root → `blocked`, reason "patch handoff failed", pointing at child 1's `file_contents` for operator diagnosis. |
| Docker sandbox unavailable (Windows, §27 #4 still open) | If `run_tests` cannot run in a container: subprocess-only fallback with weaker network isolation, flagged in the result envelope as `sandbox_degraded: true` — never a silent downgrade. |
| Operator cancellation (CLI) | Propagates to all non-terminal children via `ProcessSpawner.terminate_gracefully`. Each affected session gets `session.terminal {status: cancelled}`. |

## Testing strategy

- **`SessionWriter` concurrency:** two threads (simulating main work + heartbeat)
  write concurrently to the same session log through the same `SessionWriter`
  instance; assert no events are dropped and no `SequenceConflict` leaks to the
  caller.
- **`run_tree.build_index()` purity:** identical session logs in → identical index
  out, regardless of call order; no mutation API exists to test against (a
  structural guarantee, not just a behavioral one).
- **`ProcessSpawner`:** platform-conditional tests for the spawn → is_alive →
  terminate_gracefully cycle, including verifying a detached child genuinely
  survives its parent's death (spawn, kill the test's own parent process, verify
  the child is still alive).
- **Short-lived-child + cancel integration test:** spawn a short-lived child, wait
  for `session.created` plus at least one `heartbeat.ping`, send cancel, assert
  terminal state. Marked as slower/flakier than unit tests.
- **M1 end-to-end:** two independent Fas 3 fixtures, verify merge into one result
  envelope.
- **M2 end-to-end:** sequential fixture, verify patch handoff, join state, and
  budget-rollover events.
- **Recovery simulation:** start root+child, kill the Supervisor process (not the
  child), restart Supervisor, verify `session.reattached` for a still-live child
  and `lost` for one killed during the outage.
- **PID-reuse scenario:** mock `is_alive` so `start_time` does not match → verify
  `lost`, not an incorrect reattach.

## Out of scope for this slice

- Real IPC (sockets/pipes) between Supervisor and children — file-based only;
  flagged as an open question for when concurrent child-run volume grows (decision
  3).
- More than two children, or recursion depth beyond 1 — §25 caps the first product
  increment at two child runs, recursion depth 1.
- Mid-flight budget borrowing between concurrently-running children — only
  post-hoc rollover (decision 7); this slice's scenarios never need it.
- General N-ary dependency graphs or complex join topologies (fan-in from more than
  two, diamond dependencies) — only the single linear join (M2) is proven.
- Automatic budget salvage from a `lost` child during recovery — a lost child's
  session is simply marked `lost`; no attempt to recover or redistribute its
  remaining allocation.
- Full workspace snapshotting for non-text artifacts — M2 uses whole-file changed-
  content handoff (via `apply_patch`) only; a full-snapshot fallback for binary or
  otherwise non-text-representable fixtures is named as a
  future extension, not built.
- A declarative (YAML) run-tree or event schema — the event vocabulary stays
  Python dict/constant-based, consistent with Fas 3's tool-contract discipline
  (ADR-016/017).
- An operator dashboard or UI for querying status — a CLI/query function only
  (`state_cli`-equivalent), no dashboard.
- Live heartbeat push notifications to a human operator — heartbeat is an internal
  Supervisor liveness signal in v0.1, not surfaced live to a person.
- Resolving Fas 3's open Windows/Linux execution-sandbox decision (§27 #4) — M2
  inherits it and works around it via `sandbox_degraded`, but does not resolve it.

## Deferred decisions (revisit triggers for later phases)

| Decision | Revisit when |
|---|---|
| Implementation language (Python) | A specific phase (likely Fas 6 geometric reasoning or Fas 7 self-hosted inference) shows a measured Python bottleneck — not on a fixed version number. |
| IPC transport (file-based) | Concurrent child-run volume grows enough that O(n) log-reads/polling latency measurably matters. |
| Fas 3's Windows/Linux execution sandbox (§27 #4) | Still open; verify Docker Desktop/WSL2 availability before M2 implementation planning, or accept `sandbox_degraded` as v0.1's answer. |
| Mid-flight budget borrowing | A future scenario has genuinely concurrent, mutually-dependent children — neither M1 nor M2 does. |
| Full workspace snapshot handoff | A future fixture produces non-text artifacts a patch cannot represent. |
