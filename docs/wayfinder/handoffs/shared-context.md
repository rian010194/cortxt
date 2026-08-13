# AI Workspace Wayfinder: shared context

Snapshot: 2026-08-02  
Repository: <https://github.com/rian010194/ai-workspace-control-plane>  
Canonical map: <https://github.com/rian010194/ai-workspace-control-plane/issues/7>

## Destination

Build a production-capable AI Workspace where Rikard works from Buzz, GitHub
is the control plane, approved workflows dispatch automatically through
n8n/VPS to observable and recoverable specialist runs, a broad reviewed skill
library is activated per workflow, and results pass evaluations, independent
review, and human approval before real cases are used.

## Standing decisions

- The first milestone is a local end-to-end run of a minimal but real
  `vertical-01-ai-act` package, starting from a Buzz-created GitHub issue and
  using contract-compliant manual dispatch.
- GitHub Issues/Projects are the only durable master record. Runtime cards are
  execution ledgers correlated to the same issue.
- Keep stable responsibility types but allow any justified number of
  workflow-selected specialist profiles.
- Maintain a broad, reviewed, version-locked skill registry. Load only the
  relevant bundle for the current workflow stage; there is no fixed skill cap
  per role.
- Use a common skill registry with runtime-specific adapters for Codex,
  Hermes, and Pi.
- No agent may approve its own work. No secrets, customer documents, full
  prompts, or model reasoning belong in GitHub or committed artifacts.

## Current verified operating model

```text
Buzz (dialog and approval surface)
  -> GitHub Issue/Project (scope and workflow source of truth)
  -> manual local dispatch for now
     -> Hermes Coordinator/Researcher
     -> Pi Builder for bounded writes
  -> GitHub evidence or pull request
  -> Codex read-only review when required
  -> operator approval
```

Verified facts:

- Buzz can create GitHub issues, but Buzz-native delegation is not approved
  for unattended work because returned child handles cannot be polled.
- Hermes routing and two-worker bounded delegation have been demonstrated.
- A manual GitHub-to-Hermes-Researcher-to-GitHub flow has completed.
- Hermes Kanban board `cortxt-cp` created with gateway dispatch proven (scratch workspace, 36s `ready → running → done`).
- Hermes Kanban swarm-mode demonstrated: parallel workers → verifier → synthesizer graph.
- Kanban-to-GitHub mirror script and cron job created (runs every 10 min).
- Pi Builder has completed a bounded synthetic write followed by independent
  Codex review, but remains an experiment rather than the production harness.
- No general dispatcher yet takes a `Ready` issue through claim, observable
  execution, and a complete result envelope.
- n8n/VPS is a later automation stage, not required for the first local run.
- Six Buzz marker-routing workflows now exist under
  `harness/buzz-workflows/`. Trigger message ID/text rendering was verified on
  2026-08-02, but workflow-generated textual mentions did not wake Builder and
  Builder terminal output was unavailable after manual wake. This is partial
  routing evidence, not an unattended dispatcher.

Latest operational evidence and the exact resume order are in
`2026-08-02-buzz-workflow-session.md`.

## Convergence update (2026-08-05)

- **Blocker 2 (Buzz Builder terminal-output) is RESOLVED / not reproducible:** a
  Hermes ACP subagent probe (2026-08-02) returned real output for `pwd`,
  `echo`, `ls`; Pi bootstrap returned `0.82.1`. The 2026-08-02 failure was
  specific to the Buzz-delegation transport path, not the Builder runtime.
- **Blocker 1 (Buzz-native delegation discovery-only) is BY DESIGN:** Buzz is
  the dialog + approval surface, not the dispatcher. See
  `docs/agents/current-operating-model.md`.
- **Real gap:** no functioning Hermes↔Buzz return channel, so Buzz status /
  approvals never flow back. This is the work that makes Buzz useful.
- **Next action:** prove the loop with a real issue #9 dispatch through the
  verified GitHub → Hermes → Review → Operator-approval path (see
  `.hermes/dispatch/RUNBOOK.md`), then build the Buzz return channel.

## Research decisions already made

- Matt Pocock: selectively adapt pinned `diagnosing-bugs`, `tdd`, `to-spec`,
  and read-only `codebase-design`; do not duplicate Cortxt's `grilling` or
  `domain-modeling`.
- ECC: selectively adapt eval, verification, read-only security review, and
  cost-event patterns; do not full-install its orchestration and hooks.
- Hermes: use workflow-selected specialist cohorts and locally owned skills
  for EU legal provenance, synthesis, schemas/evals, and run manifests.
- Factory: adopt durable contract patterns for execution/attempt identity,
  leases, retries, recovery, worktrees, and events; do not introduce a second
  control plane before an isolated Linux evaluation establishes ownership.

## Canonical repository sources

- `AGENTS.md`
- `docs/agents/current-operating-model.md`
- `docs/agents/issue-tracker.md`
- `docs/architecture/dispatch-contract.md`
- `docs/architecture/runtime-and-evaluation-harness.md`
- `docs/architecture/vertical-package-contract.md`

If this snapshot conflicts with those sources or the live Wayfinder map, stop
and return the conflict to Codex for reconciliation.
