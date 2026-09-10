# Current operating model

Status: supported work paths and their material limits — not a claim of
end-to-end readiness
Last reconciled: 2026-09-10 against `main` `7e5a243`

## What this file is for

This file describes **what the system actually supports today and where it
stops**. It is a description: it changes in the same pull request as the thing
it describes. For the direction this is heading, see
[`goal-operating-model.md`](goal-operating-model.md). For navigation to
everything else, see [`../README.md`](../README.md).

It distinguishes four things that are routinely confused: code that exists,
a controlled verification, real runtime evidence, and routine daily use. None
of them implies the others. This file approves nothing — not a dispatch, not a
budget, not a merge, not a Proposed ADR.

Daily delivery state is **not** here. What is delivered, in review or blocked
lives on the GitHub issues and in the Atlas maps derived from them. A status
table copied into this file would be stale the day after it was written.

## Authority

Accepted ADRs in [`../adr/`](../adr/README.md) are normative. GitHub Issues hold
durable scope, acceptance criteria, evidence and approval; exactly one
`workflow:*` label carries workflow state (ADR-018). Project 4 is frozen legacy.
Atlas is a derived view over Issues, never a second backlog.

The operator may designate a local implementation plan as current. Such a plan
is untracked and absent from a clean checkout, so nothing required to do the
work depends on it: its delivery boundaries are summarized here. A plan's dated
status table is not a live ledger — consult current issue evidence and Git
history. Where a plan and an Accepted ADR disagree, the ADR wins.

## How the work is coordinated today

The operator coordinates development through agent sessions with branches and
worktrees, GitHub issues, independent review and local handoffs. That is the
reported daily workflow, supported by delivery records; no aggregate usage share
or cost saving has been measured here. A harness used as a coordinator session
does not thereby prove the corresponding Cortxt worker path — work done in an
external session is not a Cortxt-dispatched Run without the durable record that
makes it one.

Cortxt has routing, external runtime adapters and execution controls. Routine
distribution of implementation across several harness/model combinations is not
yet the established daily default.

## Delivery paths (ADR-040)

Three paths are sanctioned; each upholds the label invariant that a merged
delivery pull request never leaves its issue at `workflow:inbox`.

1. **Dispatched runtime build** — dispatcher claim (`ready -> in-progress`),
   isolated worktree, agent runtime, result envelope, then `review -> done` on
   independent review plus operator approval.
2. **Coordinator-direct build** (bounded fix) — build on a feature branch; the
   pull request's CI plus the operator merge are the review and approval gate.
3. **Docs/ADR materialization** — no code; feature branch, pull request,
   operator merge (`review -> done` in step with the merge).

No worker approves, merges, deploys, publishes or closes its own work.

## Product surface

Cortxt is work- and mandate-first (ADR-042): the durable Workstream and its
authorized outcome are the product object, not any one interface.

- **Cortxt OS** is the accepted general shell and first-party app runtime
  (ADR-044). **Work** is its first principal app, not the identity of the OS.
  Both are in active development.
- The **`cortxt` CLI** is the local, automation, bootstrap, diagnostic and
  power-user interface (ADR-015/021), and today the most complete verified one.
- **`cortxt mcp serve`** is the external, mandate-protected integration surface
  (ADR-024/032); a read-only tool slice shipped, SDK integration deferred.
- A thin `cortxt widget` surface (ADR-021/038) supplies declarative views and
  actions consumed by the other surfaces. It is a UI substrate, not a top-level
  interface.

Work Console is retired by ADR-044 with a bounded compatibility migration to
Work. Execution detail (sessions, pipelines, execution maps) is an Execution
Inspector view inside a Workstream, not the default home (ADR-042 amendment D).
The legacy web prototype removed before the first public release (issue #225) is
unrelated history.

## Current execution boundary

The operator-designated plan separates:

- **Milestone A** — start, follow, review and retry **already-approved** work in
  the OS. The first supported execution path is
  **OS -> WorkLauncher -> Dispatcher**. This is the release milestone.
- **Milestone B** — originate, prepare and approve **new** mandates in the OS.
  Planned alongside A, delivered after it. Not implied by finishing A.
- **W15** — adapting Supervisor Daemon dispatch to the mandate-and-Run chain is
  **deferred**, outside Milestone A's acceptance.

Deferring daemon dispatch does **not** defer review-sync. The mechanism that
moves durably submitted reviews to `workflow:review` (ADR-037,
`cortxt daemon sync-review --state-dir <dir>`) remains required by the delivery
path that uses it. Never bypass the Evidence Gate, and never clean up or merge a
`daemon/<issue-id>` branch or worktree without an operator decision.

The supported Milestone A chain:

```text
Operator-approved issue and limits
  -> OS / WorkLauncher eligibility and confirmation
  -> Dispatcher claim and durable Run
  -> registered worker adapter in the approved workspace
  -> result and evidence verification
  -> durable review submission and review-sync
  -> required independent review and operator approval
```

Detailed execution requirements are in
[`../architecture/dispatch-contract.md`](../architecture/dispatch-contract.md).

## Execution paths are not interchangeable

Selecting a runtime does not prove the selected launch path can invoke it. Three
distinct surfaces exist in today's code and they are not the same registry:

- `scripts/worker_adapters.py` serves the WorkLauncher. Its default
  `ADAPTER_REGISTRY` holds `hermes-researcher`, `hermes-coordinator`, `dsh` and
  `hermes-free` — and a registry hit alone is still not launchability, since
  some adapters additionally require environment configuration.
- `agent-platform/runtime/default_engine_context.py` registers runtime adapters
  separately, including `claude` and `codex`. Registration **there** does not
  register them in the WorkLauncher.
- `agent-platform/routing/engine_manifest.py` supplies static task-shape and
  cost/reliability classifications. `claude` is the default fallback and the only
  `verified` engine in the default manifest; the alternatives are `unverified`
  and mainly cover research and background shapes. These are evidence-based
  bootstrap configuration, not a measured optimizer.

### "Profile" today is three conflated things

The code has three separate concepts that current behaviour runs together:

- **runtime identity** (`engine_id`, e.g. `hermes-free`, `hermes`, `dsh`,
  `claude`) — which adapter executes, resolved by `route()`;
- **worker role** (`builder`, `researcher`) — the approved role from the issue;
- **Hermes configuration profile** (`hermes -p <name>`) — the named config the
  Hermes CLI loads.

`HermesFreeAdapter` passes `run.worker_role` as the `-p` profile name and
overrides that profile's model/provider with `CORTXT_FREE_MODEL` /
`CORTXT_FREE_PROVIDER`, read from the host environment at invoke time. Via the OS
eligibility path the only reachable runtime is `hermes-free`, so today "profile"
in an OS launch means *worker role plus host-env override*, not a deliberately
selected named profile. `hermes-researcher` / `hermes-coordinator` (which do bind
a fixed `-p`) are reachable only from the CLI.

Consequences of the current state, all of which the target direction changes:

- `CORTXT_FREE_*` values are **requested** configuration — what the platform asked
  for — not evidence of what executed. The executed model/provider comes only
  from runtime evidence (completion report / `--usage-file`), else `unknown`. A
  runtime fallback (init-time or on a 429) can run a different model than
  requested.
- A profile **name** alone does not fix an immutable effective configuration:
  the profile's model/provider/base-URL/fallback can change between preview,
  confirm and start, and nothing today binds those fields to the confirmed
  revision.
- The live confirm/launch path (`action_host`, `unified_cli`) reads
  `dispatch.request.v1`, whose digest does **not** include provider/model.
  ADR-046 (Accepted 2026-09-10) decided `dispatch.request.v2`, which does, but v2
  is not yet wired into the live claim/launch path. A W13 evidence note that
  reads a changed digest as proof of model/provider binding is therefore
  **not yet supported by the code that path runs**; the reconciliation is open.

So a `claude` routing outcome is **not** evidence of an eligible paid OS launch:
the default WorkLauncher registry has no `claude` adapter, and the launch path
refuses before any claim. Copilot is not integrated into this supported path.
Any new adapter must preserve the dispatch contract and carry its own evidence
for its runtime/model combination and task shape.

The Supervisor Daemon has its own persisted claim tracking, worktree creation,
autonomy checks and review-sync. Its dispatch loop invokes through the runtime
`EngineContext` -- the second registry above, the one that *does* hold `claude`
and `codex` -- and never through the WorkLauncher's `ADAPTER_REGISTRY`. It
imports no Dispatcher and creates no durable Run: the lane it reports carries
`run_id: None`. This is the concrete reason registration in the daemon's runtime
context is not WorkLauncher eligibility, and why the two paths are not
interchangeable. Do not present the daemon as equivalent to the OS path or
require it for routine Milestone A delivery. Diagnostic daemon status is not OS
end-to-end proof.

## What existing evidence establishes

- Dispatcher claim/run identity, worker invocation adapters, the launcher and
  its integration path are exercised by the four `scripts/` suites, which the
  `dispatch-path-tests` CI job runs one process each. Fake-runtime success is a
  controlled verification, not live proof.
- The daemon loop has a proof-of-life record (issue #180); `cortxt mcp serve`
  has a read-only tool slice (PR #192); the provider-neutral InferencePort runs
  behind an L0 synthetic fixture (PR #115); the provider-assurance policy gate
  makes a deterministic L0-L3 decision and fails closed on malformed evidence
  (ADR-016).
- Historical Hermes routing and swarm experiments, and DSH invocation
  experiments, establish the particular cases tested — not general reliability.
  Issue #531 is a worked example of the difference: a DSH runtime that never
  started was reported as a worker that ran and failed.
- The OS path has delivered projections and actions with verification recorded
  on the individual deliveries. The scoped live acceptance proof of Milestone A
  remains a separate gate and has not been run.

Merged UI work, a registered adapter, a passing fixture and requested model
metadata are **not** verified end-to-end capability. Unknown usage or cost stays
unknown, never zero. A requested provider or model value is not an observation
of what executed. A process exit or a worker's own success message is not
sufficient delivery evidence -- [`../findings/`](../findings/README.md) records
a case where a worker that refused to act was classified as a success (#520).

What a specific run was observed doing, and how that was traced to a mechanism,
belongs in a finding, not here. A finding is read at the commit it cites; this
file describes the present and changes with it.

## Selection rules

Use the smallest path that satisfies the approved issue:

- Planning, classification or synthesis: platform routing through the approved
  model gateway.
- Research: the Researcher profile with the configured provider; add workers
  only when the subquestions are genuinely independent (no fixed cap, #136).
- Bounded implementation: a builder runtime in one explicitly approved
  workspace.
- Review: independent and read-only, once per completed work unit, when risk or
  the issue workflow requires it.
- External integration: `cortxt mcp serve` for MCP consumers; the CLI for direct
  use.

## Cost-effective delivery

The objective is **accepted delivery at the lowest total cost** within the
operator's quality, time and policy constraints. That is not cheapest-model-first
and never has been: a more capable, more expensive combination is the better
choice when it avoids rework or reduces review effort.

Weigh the whole delivery — provider charges, subscription quota, latency,
operator attention, coordination, retries and review effort. These are separate
measurements and constraints, not one fabricated figure, and unknown cost stays
explicit. Quality and evidence gates are constraints, not something traded for a
lower price. No measured automatic optimizer exists today.

In practice: give a worker a coherent bounded unit with its acceptance criteria;
use scripts for mechanical checks and status collection rather than a premium
session interpreting every routine event; escalate a concrete blocker or a
budget change instead of re-planning the same work in several sessions.
Required independent review still applies. None of this authorizes additional
workers, paid routes or effects outside an existing mandate.

## Guardrails against common misreadings

Do not:

- treat Hermes, Pi, Codex, DSH, Buzz or any external runtime as the product —
  they are replaceable resources behind Cortxt-owned ports (ADR-014/016);
- treat the removed legacy web prototype as a product surface or the origin of
  Work — it is unrelated history (issues #186 and #225);
- treat Work as the identity of Cortxt OS, call the Work app Workspace, or
  describe the OS or Work as finished (ADR-044);
- invent a second backlog or independent Kanban outside GitHub;
- describe a successful smoke test as a finished production workflow;
- present a Proposed ADR as Accepted;
- add a new entry point before checking that it preserves the dispatch contract
  and existing component ownership;
- bypass the operator's approval over irreversible decisions.

## Authority and reconciliation

For implementation and runtime behavior, this repository and its architecture
contracts are authoritative. Accepted ADRs are the normative record of
decisions. If this file and an ADR disagree, stop and reconcile the conflict
rather than silently selecting one account.
