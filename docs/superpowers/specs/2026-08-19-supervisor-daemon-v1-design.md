# Cortxt Supervisor Daemon v1 — design

Status: approved (interactive brainstorming dialogue with operator, 2026-08-19)
Date: 2026-08-19
Authority: architectural proposal for one bounded sub-project; does not
override `docs/agents/current-operating-model.md`. That file is stale as of
this writing (last reconciled 2026-08-13, predates dispatch v0.1 shipping) —
noted here so a future reader does not treat its dispatcher-not-built claim
as current; reconciling it is out of this spec's scope.
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §6
(Control Plane), §7 (Cortxt Supervisor — state machine, child runs, exit
criteria), §23 Fas 4 (Supervisor v0.1, shipped PR #150);
`docs/architecture/dispatch-contract.md` (claim/run identity, result
envelope, `approval_ref` requirement); `agent-platform/routing/
engine_manifest.py` (`checkpoint_required`, `reliability_class`);
`agent-platform/supervisor/coordinator.py` (§7.2 state machine
implementation this spec builds a loop layer on top of, not a replacement
for); `docs/superpowers/specs/2026-08-19-v02-swarm-orchestration-model-
design.md` (proof-step → escalation → checkpoint pattern, and the 0-for-4
autonomous-dispatch failure history this design must not repeat)

## Problem

Cortxt Supervisor (Fas 4, `agent-platform/supervisor/coordinator.py`) already
implements root/child session lifecycle, budget allocation, and recovery —
but it is invocation-driven, not a running process. It is instantiated only
from `supervisor_cli.py` (a one-shot status query) and `rlm_child_cli.py` (a
per-run child process). Nothing scans for approved work, decides when to
start a run, or stays alive to report live status to an operator-facing
surface. Fas 4's own exit note says as much: "Live heartbeat till en
mänsklig operatör i UI/dashboard-form är explicit out of scope for v0.1."

The operator wants long (5–6 hour) unattended execution sessions, with human
effort concentrated at the start (spec/plan, set ambitiously) and at the end
(review the whole slice) rather than a checkpoint every ~10 minutes. But this
project has direct evidence that unattended autonomous dispatch fails
without safeguards: **fully autonomous Kanban-issue dispatch went 0-for-4**
(issues #165, #166, #174, #175 — wrong surface, invented out-of-scope work,
or false "completed" self-reports with nothing committed), while
**one-shot dispatch with a human integration step went 2-for-2**. This spec
must reconcile "run 5–6 hours unattended" with "don't rebuild the mechanism
that already failed four times."

## Non-goals

- **Security model for unattended credential access.** An always-on daemon
  making decisions without an operator present is a different threat model
  than today's CLI invoked by a logged-in human. This is explicitly deferred
  to a follow-on spec (sub-project 2 of 3, agreed with the operator
  2026-08-19), because its design depends on what this daemon actually needs
  to access and when.
- **Widget swimlane/Gantt pipeline visualization.** The prototype's Fluent
  gap (`docs/superpowers/specs/2026-08-19-track5-widget-rust-research.md`
  §2) is CSS/JS work independent of this daemon; deferred to sub-project 3.
- **Handing `route()`'s decision-making to RLM/Geometric Reasoning.** ADR-022
  makes `route()`'s static pattern-matching a deliberate bootstrap; the
  handoff happens only once Fas 6's exit criterion clears (ADR-025 resolved
  one of its two blockers — §27 #8 — but the exit-criterion evaluation
  itself has not run, and §27 #10's embeddings integration is still
  in-progress). This daemon calls `route()` as it exists today and picks up
  the handoff automatically whenever `route()`'s implementation changes
  underneath it — no daemon-side change needed either way.
- **Rebuilding `Coordinator`.** This spec adds a loop and a gate on top of
  the existing §7.2 state machine; it does not change session lifecycle,
  budget allocation, or recovery logic already implemented there.
- **CLI replacement.** Per the operator's explicit direction (2026-08-19
  dialogue), the CLI remains the primary interface for steering
  agents/harness directly. The daemon and widget serve the background/
  visualization role, not a CLI replacement.

## Architecture

Three new components sit on top of the existing, unchanged `Coordinator`:

### 1. Daemon loop

A long-running process (started explicitly by the operator, not
auto-started at login for v1 — see Open Questions) that, on an interval:

1. Scans GitHub Issues labeled `workflow:ready` (dispatch-contract.md's own
   source of truth — no new queue format, no second backlog per
   `current-operating-model.md`'s explicit guardrail against inventing one).
2. For each issue not already claimed, calls the existing `route()`
   (`agent-platform/routing/engine_manifest.py`) to select an engine, then
   `Coordinator`'s existing session-start path to begin a run.
3. Polls the run's already-querybar status (§7.1) until it reaches a
   terminal state.
4. Hands the terminal result to the Evidence Gate (below).
5. Writes current state (what's running, what's queued, what's gated) to a
   status file the widget can read — same polling-a-file pattern as today's
   `widget/snapshot.json`, no new state source.

The daemon never invents work: it only starts runs for issues a human
already approved and labeled `workflow:ready` upstream. Anything it notices
that looks related but isn't approved is logged as a suggestion, never
dispatched — directly targeting the #174/#175 failure mode (invented
out-of-scope work).

### 2. Evidence Gate

Runs after every run's terminal result, replacing a human's per-commit
review with an automated check:

- Tests pass (the run's own declared test command, or the repo's default
  suite if none given).
- The diff matches the run's declared `artifact_policy` (dispatch-contract.md)
  — no writes outside the allowed locations.
- A complete `ResultEnvelope` exists (dispatch-contract.md's result fields:
  status, evidence, cost, artifacts) — a self-reported "succeeded" with no
  evidence is treated as a gate failure, not a pass. This directly targets
  the #174/#175 false-completion failure mode.

Gate outcomes:
- **Pass, `checkpoint_required=False`** → daemon proceeds to the next
  `workflow:ready` issue automatically.
- **Pass, `checkpoint_required=True`** → daemon pauses that track and
  surfaces it for operator review before continuing.
- **Fail** → that issue's track freezes, gets flagged in the status file and
  widget, and the daemon moves on to other independent issues. A frozen
  track is never silently retried or marked done.

### 3. `checkpoint_required` as a real consumer

`EngineManifest.checkpoint_required` and `EngineChoice.checkpoint_required`
already exist (`agent-platform/routing/engine_manifest.py`) but currently
have no reader that changes behavior based on them. This daemon is that
reader: it consults `checkpoint_required` (backed by `reliability_class`) to
decide whether the Evidence Gate's "pass" is sufficient on its own or needs
an operator's sign-off. This is additive — no existing `route()` behavior
changes.

### Widget as read-only client

The widget gains a new panel polling the daemon's status file, the same
shape as its existing `runtimes`/`credentials` panels
(`agent-platform/cli/unified_cli.py` subcommands feeding
`widget/snapshot.json`). The daemon is the only writer; the widget never
mutates daemon state. This spec does not include the swimlane/Gantt
rendering itself (sub-project 3) — only that the daemon's status file
carries enough structure (per-issue state, timestamps, gate outcomes) for
that future rendering to consume without a daemon-side redesign.

## Data flow

```text
GitHub Issue (workflow:ready)
  -> Daemon loop picks it up (not already claimed)
  -> route() selects engine
  -> Coordinator starts root session (existing §7.2 state machine)
  -> child sessions per Coordinator's existing logic
  -> terminal ResultEnvelope
  -> Evidence Gate
       pass + checkpoint_required=False -> next issue, automatically
       pass + checkpoint_required=True  -> pause, surface for operator
       fail                             -> freeze this track, flag, continue others
  -> status file written continuously
  -> widget polls status file, renders
```

## Autonomy model — earned, not assumed

The daemon must prove itself before it is trusted for a full unattended
5–6 hour pass, the same discipline it will later enforce on
`checkpoint_required` tracks:

- **Supervised mode (default at first use):** the Evidence Gate's "pass"
  always surfaces for operator review regardless of `checkpoint_required` —
  i.e. the daemon runs, but nothing proceeds unattended yet.
- **Unattended mode unlocks per class of work** only after N=3 consecutive
  clean passes of that class in supervised mode — mirroring the N=3
  consecutive-green-runs rule `target-architecture.md` §23 already applies
  to Fas 4+ exit criteria, applied here to the daemon's own track record
  instead of a new invented threshold. "Class" reuses the existing taxonomy
  rather than inventing one: `EngineManifest`'s `task_shapes` × the selected
  engine's `reliability_class` (`agent-platform/routing/engine_manifest.py`)
  — e.g. "hermes engine, coding task_shape" earns its unattended unlock
  independently of "hermes engine, research task_shape."
- This is a bootstrapping property of the daemon itself, not a one-time
  config flag: a class of work that starts failing its gate after being
  unlocked should be capable of falling back to supervised mode for that
  class (mechanism deferred to the implementation plan — flagged here so it
  is not forgotten, not designed in detail in this spec).

## Error handling & safety boundaries

- **Evidence Gate failure** → freeze that track only; other tracks continue
  independently (matches the swarm design's existing "Failed proof step"
  handling — an engine/track that fails the reliable path is not promoted
  to the unreliable one).
- **Daemon process crash** → `Coordinator` already recovers child sessions
  after process interruption (§7.1); the daemon loop itself must be
  resumable too — on restart it reads existing root-session state from disk
  before acting, so a crash never causes a duplicate dispatch of the same
  issue.
- **Session-level budget ceiling** — dispatch-contract.md already requires
  `max_cost_usd`/`max_runtime_seconds` per individual request; this spec
  adds a **daemon-level** total (cost + wall-clock) ceiling that halts the
  entire loop when reached, independent of individual run ceilings.
- **Secrets** — the daemon never handles unlocked credentials directly; all
  access goes through the existing `agent-platform/security/
  credential_broker.py` / DPAPI path unchanged. The full threat model for
  unattended credential access is explicitly out of scope here (Non-goals) —
  this daemon introduces no new path around the broker, full stop.
- **Emergency stop** — a dedicated, always-available CLI command (exact
  name TBD in the implementation plan, e.g. `cortxt supervisor stop`) that
  kills the loop immediately regardless of what it is doing. Non-negotiable
  for an unattended multi-hour pass.

## Testing strategy

- **Loop logic** (work discovery, gate evaluation, checkpoint routing)
  tested in isolation against a mocked `Coordinator` — no real subprocess
  spawns, no model calls, matching `reasoning/geometric`'s existing
  0-model-call testing discipline for deterministic logic.
- **Dry-run fixture**: the full loop runs against fake issues/results,
  verifying gate decisions (proceed/pause/freeze) are correct without any
  real dispatch occurring.
- **Crash-recovery test**: kill the loop process mid-run, restart, assert no
  duplicate dispatch — mirroring `Coordinator`'s existing recovery test
  pattern.
- **Real end-to-end run** (an actual `route()` + dispatch) stays a
  **proof step**, not part of the default suite — run manually once before
  any class of work is allowed to escalate toward unattended mode, same
  discipline as the swarm design's tracks.

## Open questions

1. Exact interval/trigger for the daemon's scan loop (fixed poll interval
   vs. GitHub webhook vs. operator-triggered "start a pass") — left to the
   implementation plan.
2. Whether the daemon auto-starts at login/boot or is explicitly started
   per session — leaning toward explicit start for v1 (matches "you kick off
   a 5–6 hour pass" rather than an always-on background service from day
   one), but not decided here.
3. Exact mechanism for a class of work falling back from unattended to
   supervised mode after a post-unlock failure (flagged in Autonomy model
   above, deferred to the implementation plan).
4. `docs/agents/current-operating-model.md` needs reconciliation — separate
   from this spec, noted so it isn't lost.

## Decomposition note

This spec covers sub-project 1 of 3 (agreed with the operator 2026-08-19):
1. **Background orchestrator daemon** (this spec).
2. Security model for unattended credential access — depends on #1's actual
   design, spec'd next.
3. Widget swimlane/pipeline visualization — independent of #1 and #2,
   scoped whenever.
