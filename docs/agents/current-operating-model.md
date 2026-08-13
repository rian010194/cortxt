# Current operating model

Status: active operational baseline  
Last reconciled: 2026-08-13

## Why this file exists

Read this file before recommending architecture or choosing a runtime. The
repository contains experiments and future designs alongside verified paths.
No single experiment README describes the whole system.

The durable task record and the execution runtime are deliberately separate.
GitHub Issues hold durable scope and evidence. A planning surface may supply
workflow state only when explicitly designated current; Project 4 is frozen
legacy.

```text
Hermes desktop (primary operator surface; Buzz = remote complement)
  -> GitHub Issue (durable scope and evidence source of truth)
  -> explicitly current planning state, when designated
  -> manual local dispatch for now
     -> Hermes Coordinator/Researcher
     -> Pi Builder for bounded writes
  -> GitHub evidence or pull request
  -> Codex read-only review when the approved workflow requires it
  -> operator approval
```

This is the current usable path, not a claim that every arrow is automated.

Rikard works primarily in Hermes desktop (single coordinator session that routes
to Researcher/Builder as runtime workers). Buzz remains the remote/mobile
complement for monitoring status and approvals, not a per-agent surface.

## Component responsibilities today

| Component | Responsibility | Current constraint |
|---|---|---|
| Buzz | Remote/mobile monitoring, scope clarification, status display, and approvals (compliment to the Hermes desktop primary surface) | It is not the durable task registry or the primary work surface. Buzz-native delegation is not approved for unattended work because delegation handles cannot be polled. |
| GitHub Issues and current planning state | Canonical scope, acceptance criteria, evidence, review, and approval; workflow state only from an explicitly current planning surface | Project 4 is frozen legacy. An issue must be approved and `Ready` in the current workflow before dispatch. |
| Hermes | Agent runtime for Coordinator and Kimi-backed Researcher profiles; profile routing, bounded delegation, Kanban execution ledger, and gateway dispatch for scratch workspaces | Hermes routing and Kanban dispatch work for scratch workspaces. Worktree mode requires correct Windows path setup. The complete Buzz-to-runtime handoff is not automated. |
| Pi Builder | Short-lived, containerized Kimi runtime for bounded file writes | It remains an experiment pending production hardening and a general dispatcher interface. |
| Kimi/Moonshot | Heavy research, analysis, implementation, and tests | Cost and tool limits must be explicit; unknown provider cost must never be treated as zero. |
| OpenRouter | Coordinator model gateway and later fallback/specialized routing | The free Coordinator test model is not approved for confidential material. |
| Codex | High-risk architecture/security input and independent, compact, read-only final review | It is not the default planner, researcher, or builder and should receive only the issue, criteria, diff/artifact, and test evidence needed for review. |
| Operator | Approval of scope, budget, irreversible effects, merge, publication, deploy, and final completion | No agent may approve its own work. |

## Verified capabilities

The following have been demonstrated and must not be described as merely
theoretical:

- Hermes routed explicit tasks to the correct Researcher and Builder profiles.
- Hermes Coordinator decomposition ran two Researcher workers concurrently and
  respected the live concurrency limit of two and delegation depth of one.
- A manual GitHub -> Hermes Researcher -> GitHub workflow completed.
- Hermes Kanban board `cortxt-cp` created with gateway dispatch proven (scratch
  workspace, 36s `ready → running → done`).
- Hermes Kanban swarm-mode demonstrated: parallel workers → verifier → synthesizer.
- Kanban-to-GitHub mirror **script** exists; **no mirror cron is registered**
  (verified 2026-08-09 — `hermes cron list` shows only `kanban-buzz-push`). The
  mirror is a manual/available capability, not an active scheduled function.
- Manual dispatch routine documented with run_id generation, runtime selection,
  result envelope, and operator approval checklist.
- OpenRouter served the Coordinator profile and Kimi served the worker profiles.
- Pi called Kimi through endpoint-restricted egress.
- Pi performed a bounded single-workspace write, followed by a separate Codex
  read-only review and operator acceptance.

Detailed execution requirements live in
`docs/architecture/dispatch-contract.md`. Pi evidence and remaining hardening
gaps live in `experiments/runtime-pi-builder/README.md`.

## Known blockers and incomplete links

- Buzz `delegate_task` can return child handles but cannot query status,
  heartbeat, elapsed time, or result by handle. It is discovery-only.
- Ordinary Hermes ACP text is not reliably published back into Buzz in the
  tested configuration.
- Buzz cannot currently complete the required human edit-approval round trip
  for a writing Hermes Builder. The Buzz Builder therefore remains stopped.
- A 2026-08-02 Buzz workflow experiment verified marker filtering plus trigger
  message ID/text rendering, but the hosted workflow's textual `@Builder` did
  not wake Builder without an operator-added structured mention.
- When manually woken in that experiment, Builder's terminal tool echoed the
  submitted command without returning command output and the session ended in
  `idle_timeout`. This runtime must fail closed and be repaired before another
  implementation dispatch.
  **Status update 2026-08-05:** a plain Hermes ACP subagent probe (2026-08-02)
  returned real output for `pwd`, `echo`, and `ls` (exit 0, genuine filesystem
  data), and the Pi Builder Docker bootstrap returned `0.82.1`. So the terminal
  transport itself is **not** reproducibly broken. The 2026-08-02 failure was
  specific to the Buzz-delegation transport path, not to the Builder runtime. It
  must be re-verified on the *next* Buzz-woken dispatch (fail closed if output is
  missing), and the stale "Builder stopped (terminal output missing)" blocker
  should no longer be read as a general runtime failure.
- There is no completed general dispatcher from a `Ready` GitHub issue to the
  selected Hermes or Pi runtime with the full dispatch result envelope.
  **Partial exception:** Hermes Kanban gateway dispatch works for scratch
  workspaces; worktree mode requires correct Windows path setup (`cygpath -w`).
- Pi Builder is verified as a bounded experiment, not yet promoted to the
  production harness.
- **Hermes Kanban gateway dispatch is limited to scratch-workspace profiles**
  (e.g. `researcher`). Profiles assigned to the terminal lane (e.g.
  `coordinator` for verification/synthesis) are not auto-spawned by the
  gateway; they must be manually claimed and completed by an operator or
  an active Hermes session. This was demonstrated on 2026-08-03 during the
  ticket #9 swarm: three researcher workers auto-completed, but verifier
  and synthesizer tasks remained `ready` until manually claimed.
- n8n/VPS automation is future work, not part of the local operational baseline.

## Selection rules

Use the smallest verified path that matches the approved issue:

- Planning, classification, or synthesis: Hermes Coordinator through the
  approved OpenRouter model.
- Research: Hermes Researcher with Kimi; use at most two workers only when the
  subquestions are genuinely independent.
- Bounded implementation: Pi Builder with Kimi in one explicitly approved
  workspace until Buzz/Hermes write approval is fixed.
- Review: Codex once per completed work unit when risk or the issue workflow
  requires independent review.

Until the general dispatcher exists, handoff is manual. Manual does not mean
that GitHub issue identity, runtime limits, budget, evidence, or approval may be
skipped.

The partial Buzz workflow evidence and exact recovery sequence are recorded in
`docs/wayfinder/handoffs/2026-08-02-buzz-workflow-session.md`.

## Guardrails against common misreadings

Do not:

- conclude that Hermes should be removed or bypassed because Buzz-native
  delegation lacks polling;
- treat Pi as a replacement for Hermes Coordinator or Researcher;
- invent a second backlog or independent Kanban outside GitHub;
- recommend abandoning Buzz as the operator surface merely because it is not
  the writing runtime (keep it as the remote complement);
- describe a successful smoke test as a finished production workflow;
- design a new `buzz-run` or similar entry point before checking whether it
  preserves the dispatch contract and existing component ownership;
- use Codex for routine long-form planning, research, implementation, or
  repeated intermediate reviews.

## Authority and reconciliation

For implementation and runtime behavior, this repository and its architecture
contracts are authoritative. The workspace LLM Wiki records broader rationale,
test history, and decisions. If the Wiki and this file disagree, stop and
reconcile the conflict rather than silently selecting one account or redesigning
the system.
