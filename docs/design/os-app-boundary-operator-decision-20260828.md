# Operator decision: Cortxt OS and the first Work app

Date: 2026-08-28  
Status: Accepted by operator 2026-08-28  
Related: ADR-042, proposed ADR-044, S5 PR #446, and the S5.5 execution brief

## Decision requested

Decide whether Cortxt OS is a general first-party app runtime with Work as its
first principal app, rather than Work Console being the identity and mandatory
default of the OS.

The recommendation is to accept proposed ADR-044 with the following canonical
language:

| Concept | Canonical term | Meaning |
| --- | --- | --- |
| Product | Cortxt | The complete product and platform |
| Shell | Cortxt OS | System chrome, lifecycle, navigation, context, and presentation |
| First principal app | Work | Work- and mandate-first surface over a selected Workstream |
| Durable work object | Workstream | Outcome, mandate, state, evidence, and continuity |
| Execution resource | Workspace | Optional Git branch and worktree attached to a Workstream |
| Cross-app attention surface | Activity Center | Read-only attention projections and validated navigation |

## Decisions

Record each answer explicitly. Acceptance of ADR-044 does not merge S5 or
start S5.5.

| ID | Decision | Recommendation | Operator answer |
| --- | --- | --- | --- |
| A1 | Accept ADR-044's OS, system-surface, app, and Core boundary | Yes | Accepted |
| A2 | Name the first principal app `Work` with app ID `work` | Yes | Accepted |
| A3 | Preserve `Workspace` exclusively for the execution resource | Yes | Accepted |
| A4 | Retire Work Console with a one-release `work-console` to `work` alias | Yes | Accepted |
| A5 | Make Activity Center a shell-owned consumer of typed attention projections | Yes | Accepted |
| A6 | Require apps to use capabilities, commands, context bindings, projections, and authorized action ports | Yes | Accepted |
| A7 | Keep third-party plugins, marketplace, remote app code, and a new UI framework out of S5.5 | Yes | Accepted |

## S5 and S5.5 gate

If A1-A7 are accepted, use this sequence:

1. Complete the independent S5 operator gate. If approved, merge PR #446,
   move issue #445 to `workflow:done`, and synchronize the integration branch.
2. Accept ADR-044 through the docs/ADR delivery path and reconcile the
   controlled vocabulary and current operating documentation.
3. Revise the S5.5 brief from `workspace` app identity to `work`; preserve
   Workspace's existing domain meaning.
4. Create or approve the four bounded S5.5 slices with separate acceptance
   criteria, ownership, cost limits, and review gates.
5. Start S5.5a only after the operator explicitly approves its issue and
   authoritative workflow state.

## Required S5.5 contract checks

The revised brief must prove:

- registering Work does not add Work-specific branches to the shell core;
- an app without a Workstream binding can register and open;
- Activity Center cannot call decision or workflow mutations;
- an attention item navigates through a validated command and record reference;
- shell, app-local, presentation, and authoritative state remain distinct;
- v2 sessions and `#app=work-console` links migrate to `work` without losing
  the selected Workstream or other open apps; and
- synthetic mode exposes no authoritative mutations.

## Deferred decisions

This decision does not select a third-party app model, app SDK distribution,
signing, sandboxing, marketplace, event bus technology, or frontend framework.
Those require a real consumer and a separate decision.
