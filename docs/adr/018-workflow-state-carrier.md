# ADR-018: Workflow-state carrier — GitHub Issue labels

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Rikard (operator)
**Technical Story:** #101 (CORTXT Foundation — Wedge B validation), #117 (Designate workflow-state carrier + state mapping)

## Context

`docs/architecture/dispatch-contract.md` and `docs/agents/issue-tracker.md` have, since the Batch 0 Foundation Authority Freeze, declared that worker dispatch is suspended until the operator explicitly designates a replacement for the frozen GitHub Project 4 as the carrier of the `Inbox`/`Ready`/`In progress`/`Review`/`Blocked`/`Done` states. GitHub Issues themselves do not encode these states (only open/closed).

Two candidates were identified:
1. Existing labels `workflow:inbox`, `workflow:ready`, `workflow:in-progress`, `workflow:review`, `workflow:blocked`, `workflow:done` — already created in the repo, no external infrastructure.
2. Hermes Kanban board `cortxt-cp` — already verified with gateway dispatch (36s `ready → running → done`), but requires a mirror script/cron back to GitHub Issues and introduces a second state source that can drift apart from GitHub.

**Independent review:** not performed in this session (no Codex access available here). Deviates from the pattern in ADR-014/015/016/017. Operator approval registered 2026-08-14; a retroactive review is recommended before the next architectural decision builds on this.

## Decision

**Workflow-state carrier = GitHub Issue labels `workflow:*`.** An issue carries exactly one `workflow:*` label at a time (mutually exclusive); the label *is* the state, no mirroring or external source is required.

**State mapping:** identity mapping — `workflow:inbox` → `Inbox`, `workflow:ready` → `Ready`, `workflow:in-progress` → `In progress`, `workflow:review` → `Review`, `workflow:blocked` → `Blocked`, `workflow:done` → `Done`.

**Claim mechanism:** a claim per `dispatch-contract.md` changes `workflow:ready` → `workflow:in-progress` and posts `run_id`, runtime, claim time, and lease/timeout as a structured comment on the issue. Retry creates a new `run_id` in a new comment; earlier run evidence is never overwritten.

**Consequence for #118:** the mirror-cron ticket becomes unnecessary and is closed — there is nothing to mirror when GitHub Issues is already both the scope source and the state carrier.

## Consequences

### Positive
- No new infrastructure; state and scope/evidence live in the same system.
- Eliminates a whole class of bugs (mirror drift between Kanban and GitHub).
- Label changes are logged automatically by GitHub with timestamp and actor — free audit trail.
- Follows the repo's own principles: "GitHub Issues remain the durable source of truth" and "use the smallest verified path".

### Negative
- No visual Kanban surface for the operator (can be added later as a read-only view on top of the labels, not as a source of truth).
- No built-in lease/heartbeat mechanism in the labels themselves — must be implemented in the dispatcher layer (the same requirement would have existed with Hermes Kanban too).

### Risks
- Concurrent label changes can race if two dispatchers act on the same issue at the same time — the dispatcher must perform an atomic claim (e.g. conditional label swap + comment in the same operation), not the labels alone.

## Alternatives Considered
1. **Hermes Kanban `cortxt-cp`** — rejected as first choice: already proven but requires a mirror cron (extra moving part, double-source-of-truth risk); can be resumed later as a pure visualization on top of the label state if the need arises.
2. **Continued suspended dispatch (no decision)** — rejected: blocks #101's remaining T-tests and all further dispatch development without solving anything.

## Validation
- [x] Operator approval registered (2026-08-14, via #117).
- [ ] Independent review (Codex or equivalent) — outstanding, recommended before the next decision builds on this.
- [x] Documentation updated (this ADR + `dispatch-contract.md` + `issue-tracker.md` + `current-operating-model.md`).
- [ ] Implementation: a dispatcher that actually performs the atomic claim via label swap (tracked in #122).

## Expiry/Review Trigger
- Review by: 2026-11-14
- Trigger: a concurrent-claim race is observed in practice, or a need for a visual Kanban surface becomes acute enough to justify adding Hermes Kanban as a mirror (never as the primary source).
