# Current operating model

Status: active operational baseline  
Last reconciled: 2026-08-27 (ADR-042 product-surface reconciliation)

## Why this file exists

For the target state this is building toward, see
[`goal-operating-model.md`](goal-operating-model.md). This file only
describes what is verified now.

Read this file before recommending architecture or choosing a runtime. The
repository contains experiments and future designs alongside verified paths.
No single experiment README describes the whole system.

The durable task record and the execution runtime are deliberately separate.
GitHub Issues hold durable scope and evidence. Workflow state is carried by
`workflow:*` Issue labels (ADR-018); Project 4 is frozen legacy.

```text
Operator (human mandate)
  -> GitHub Issue (durable scope and evidence source of truth)
  -> workflow:* Issue label (ADR-018)
  -> dispatch (scripts/dispatcher.py claim/run identity; daemon + CLI)
     -> external agent runtimes behind Cortxt-owned adapters
        (Hermes, Pi, Codex, DSH, ...) as replaceable resources
  -> GitHub evidence or pull request
  -> independent review when the approved workflow requires it
  -> operator approval (no agent approves its own work)
```

This is the current path. The dispatcher implementation tracked in issue #122
is built and exercised: claim/run identity (`scripts/dispatcher.py`), worker
invocation adapters (`scripts/worker_adapters.py`), the daemon loop
(`agent-platform/daemon/`), and the `cortxt` CLI (including `cortxt mcp serve`
for the external integration surface per ADR-024).

## Product surface

Per **ADR-042** (accepted 2026-08-26), Cortxt is **work- and mandate-first**:
the durable Workstream and its authorized outcome are the primary product
object, not any one interface. The governing principle is durable authority,
replaceable execution. Three interfaces expose that authority today, each
with a distinct role:

- **Cortxt OS** is the accepted general shell and first-party app runtime
  (ADR-044). **Work** is its first principal app, not the identity of the OS.
  Both are in active development — do not describe them as shipped.
- The **`cortxt` CLI** remains an important local, automation, bootstrap,
  diagnostic, and power-user surface (ADR-015/021), and today is the most
  complete verified interface.
- **`cortxt mcp serve`** remains the external, mandate-protected programmable
  integration surface (ADR-024, ADR-032).

The legacy web prototype removed before the first public release (issue
#225) is unrelated history and still not the product surface. Work Console is
retired by ADR-044 with a bounded compatibility migration to Work. A
thin `cortxt widget` surface (ADR-021/038) provides declarative views and
apps consumed by the CLI/TUI, the Widget Host, and Work; it is a UI
substrate, not a top-level interface in its own right. Cockpit/runtime detail
(sessions, pipelines, execution maps) continues as an Execution Inspector
view inside a Workstream, not the default product home (ADR-042, amendment D).

## Component responsibilities today

| Component | Responsibility | Current constraint |
|---|---|---|
| GitHub Issues | Canonical scope, acceptance criteria, evidence, review, approval, and workflow state via `workflow:*` labels (ADR-018) | Project 4 is frozen legacy. An issue must be approved and authoritatively `workflow:ready` before dispatch. |
| Cortxt OS | General shell and first-party app runtime: app lifecycle, windows, navigation, global context, commands, and system surfaces (ADR-044) | Owns presentation only; implementation is in progress. |
| Work | First principal work- and mandate-first app over the selected Workstream (ADR-044) | Not the OS identity and not a source of domain authority; implementation follows the S5.5 gate. |
| `cortxt` CLI | Local, automation, bootstrap, diagnostic, and power-user interface: runtimes, credentials, addons, sessions, dispatcher, MCP server, widget snapshot | Most complete verified interface today (ADR-015/021), no longer the sole product surface after ADR-042. |
| `cortxt mcp serve` | External, mandate-protected programmable integration surface exposing platform capabilities as MCP tools | ADR-024/032; read-only slice shipped, SDK integration deferred (see ADR-024 follow-ups). |
| Dispatcher (`scripts/dispatcher.py`) | Claim/run identity per dispatch contract, workflow label transitions | Single-process; concurrency model documented in ADR-018. |
| Worker adapters (`scripts/worker_adapters.py`) | Invoke external agent runtimes (Hermes, Pi, Codex, DSH, ...) behind Cortxt-owned ports | Each adapter must satisfy the dispatch contract's result envelope. |
| Hermes / Pi / Codex / DSH | External agent runtimes used as replaceable execution resources | Replaceable resources behind Cortxt-owned adapters; not the product itself. |
| Buzz | Legacy remote/mobile complement for monitoring/approvals (pre-#186) | Not the primary surface; delegation handles cannot be polled. |
| Operator | Approval of scope, budget, irreversible effects, merge, publication, deploy, and final completion | No agent may approve its own work. |

## Verified capabilities

The following have been demonstrated and must not be described as merely
theoretical:

- Dispatcher claim/run identity and workflow-label transitions
  (`scripts/dispatcher.py`, exercised against a fake GitHubOps in
  `scripts/test_dispatcher.py`).
- Worker invocation adapters with injected fake subprocess
  (`scripts/worker_adapters.py`, `scripts/test_worker_adapters.py`).
- Daemon loop end-to-end proof-of-life (issue #180).
- `cortxt mcp serve` with a read-only tool slice and tier flags (PR #192).
- Provider-neutral InferencePort behind an L0 synthetic fixture
  (`agent-platform/adapters/inference/`, PR #115).
- Provider-assurance policy gate: deterministic L0-L3 decision, fail-closed
  malformed evidence (ADR-016).
- Hermes routed explicit tasks to the correct Researcher and Builder profiles
  (runtime experiment; Hermes remains a replaceable resource, not the
  product).
- Hermes Kanban swarm-mode demonstrated (parallel workers → verifier →
  synthesizer) as a runtime experiment.

Detailed execution requirements live in
[`docs/architecture/dispatch-contract.md`](../architecture/dispatch-contract.md).

## Known blockers and incomplete links

- The general dispatcher loop is proven end-to-end for the deterministic
  CI fixture path (issue #207: claim -> isolated-worktree commit -> result
  envelope -> workflow:ready -> in-progress -> review, repeatedly green via
  GitHub Actions); the default unattended dispatch path for real build
  issues is not yet exercised.
- External agent runtimes are invoked through adapters, but a fully automated,
  unattended end-to-end dispatch (issue → runtime → review → merge) is not yet
  the default; operator approval remains the final gate.
- The legacy web prototype was removed from the repository before the first
  public release (issue #225); the CLI remains the product surface.

## Selection rules

Use the smallest verified path that matches the approved issue:

- Planning, classification, or synthesis: platform routing through the
  approved model gateway.
- Research: Researcher profile with the configured provider; use additional
  workers only when the subquestions are genuinely independent (no fixed
  worker cap, see #136).
- Bounded implementation: Builder runtime in one explicitly approved
  workspace.
- Review: independent, read-only review once per completed work unit when risk
  or the issue workflow requires it.
- External integration: `cortxt mcp serve` for MCP consumers; the CLI for
  direct use.

## Guardrails against common misreadings

Do not:

- treat Hermes, Pi, Codex, Buzz, or any external runtime as the product — they
  are replaceable resources behind Cortxt-owned ports (ADR-014/016);
- treat the removed legacy web prototype as a product surface or the origin of
  Work — it is unrelated history (issues #186 and #225);
- treat Work as the identity of Cortxt OS, call the Work app Workspace, or
  describe the OS or Work as fully shipped (ADR-044);
- invent a second backlog or independent Kanban outside GitHub;
- describe a successful smoke test as a finished production workflow;
- add a new `buzz-run` or similar entry point before checking whether it
  preserves the dispatch contract and existing component ownership;
- bypass the operator's approval over irreversible decisions.

## Authority and reconciliation

For implementation and runtime behavior, this repository and its architecture
contracts are authoritative. Accepted ADRs in `docs/adr/` are the normative
record of decisions. If this file and an ADR disagree, stop and reconcile the
conflict rather than silently selecting one account.
