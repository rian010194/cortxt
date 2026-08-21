# ADR-030: Plan-vs-actual divergence tracking — YAML sidecar + explicit-only correlation, ghost markers on the real time axis

**Status:** Proposed (Part 1 implemented; Part 2 spec-only)
**Date:** 2026-08-20
**Deciders:** Rikard Andersson (operator), with the 5 open questions resolved by Codex per operator direction; design reviewed by Hermes (7 issues found and folded in, see spec's Revision note)
**Technical Story:** (internal design archive)

## Context

The operator wants the widget/CLI swimlane view to show a workstream's
*expected* shape — derived from this project's own markdown implementation
plans ((internal design archive)) — next to its *actual* runtime shape
(`cli/status.py`'s session/workstream/lane model), so the view visually
diverges when execution doesn't match the plan.

Two gaps stood in the way, confirmed by reading both sides:

1. **Plan docs are prose, not data.** `## Task N: <title>` markdown
   sections have no stable machine-readable task identity, order,
   dependency, or relative-size signal. Parsing the prose directly
   (regexing headings, inferring order from position) breaks silently the
   moment a plan is edited — renumbered, a task inserted, a heading
   reworded.
2. **No session field references a planned task.** `session_state.create()`
   had no field identifying *which numbered task in which plan document*
   a session is executing.

A colleague (Codex) was consulted before this design was written and
identified it as at least two separate problems — plan modeling, and
reconciliation/presentation — recommending a structured YAML sidecar over
prose-parsing and an explicit-only, never-fuzzy correlation mechanism.
Hermes's subsequent review of the full draft found seven concrete issues
(a `relative_size`/duration contradiction, a silent-fallback baseline gap,
unspecified failure propagation, ambiguous retry semantics, a lost
diagnostic distinction between "broken reference" and "no reference," no
integrity story for `heading_ref`, and a self-defeating separate-strip
render design), all resolved in the spec this ADR formalizes.

## Decision

**Part 1 — Plan modeling (implemented this session).**

Each plan doc that wants divergence tracking gets a colocated YAML
sidecar (`<plan-basename>.tasks.yaml`), optional and additive — a plan
with no sidecar simply has no divergence tracking. Sidecar schema v1:
`plan_id`, `plan_doc`, and a `tasks` list of `{task_id, heading_ref,
title, order, depends_on, relative_size}`. Key constraints:
- `task_id` is author-assigned, **immutable once assigned** — a plan
  revision that changes what a task does gets a new `task_id`, not a
  reused one (mirrors this project's own register/description
  distinction: a recorded decision is never silently edited out from
  under something that referenced it). A `supersedes` field is included
  in v1 (not deferred to v2, per Codex's pushback) so a renamed/split
  `task_id` stays traceable instead of silently reading as
  unplanned/unmatched.
- `heading_ref` is a verbatim pointer back to the plan doc's prose, never
  parsed for identity at runtime. Per Hermes's review, a drift-check
  lint ("does this `heading_ref` still exist verbatim in `plan_doc`?") is
  a **required companion** to using the field at all — a silently
  detached `heading_ref` is worse than none, since it looks trustworthy
  while being wrong. The lint's implementation is left to the
  implementation plan.
- `relative_size` (`s`/`m`/`l`) is a strict ordinal, **never a duration
  proxy** — no cross-size conversion factor exists anywhere in this
  design, per Codex's pushback against fabricating defensible-estimate
  claims no plan in this repo currently makes.
- `plan_id` is workstream-agnostic by design — linkage to a runtime
  workstream is resolved per-session via `plan_task_ref`, not
  hard-coded into the sidecar, since the same plan could be executed more
  than once (a recreated worktree, a resumed plan on a new branch).

`session_state.create()` gains one new optional field,
`plan_task_ref: str | None`, shaped `"<plan_id>#<task_id>"`, stored
verbatim in the `session.created` payload using the existing "include a
key only if supplied" pattern. `cli/status.py:load_sessions()` surfaces
it; `write_snapshot()` carries it through by inheritance, no special-
casing needed. **This threading is implemented** — see
(internal design archive),
executed in this session, all three tasks landed and tested (45 passing
tests across `test_session_state.py` and `test_status.py`).

**Part 2 — Reconciliation & presentation (spec-only, not implemented).**

Correlation is **explicit only, never inferred** — no fuzzy matching on
task text, timing proximity, or workstream similarity. Three named
outcomes: **matched** (`plan_task_ref` resolves against a loaded
sidecar), **unresolvable reference** (present but doesn't resolve — a
distinct, differently-rendered signal from "never meant to reference a
plan," per Hermes's review), and **unplanned** (absent entirely, the
default, non-error case). When multiple sessions share a `plan_task_ref`
(retries), the task's displayed state is driven by whichever session has
the latest `session.created` timestamp, regardless of terminal status;
the full attempt history stays available, never discarded.

Divergence states (not started, plan-blocked, on track, insufficient-
baseline, overrunning, failed, unresolvable reference, unplanned) render
as **ghost markers anchored directly on the existing real time axis**,
not on a separate disconnected strip — the design's original
separate-strip approach was rejected after Hermes's review found it
"buries the divergence the subsystem is meant to surface," requiring
manual cross-referencing. A matched task's ghost marker anchors to its
session's real recorded `started_at`; a not-yet-started task's marker
renders "next," immediately after the axis's current rightmost real
event — never at a fabricated future date. A failed task's blocked state
propagates **transitively** through the full `depends_on` graph (not
just immediate dependents), and an already-`succeeded` task is never
retroactively unmarked if its blocker later fails.

**Overrun threshold (tuning calls, decided per Codex review):** 2x the
self-referential median duration of already-succeeded same-plan,
same-or-smaller-size tasks; minimum 5 completed same-size tasks before a
baseline is trusted (below that, renders `insufficient-baseline`, never
silently `on-track` — the specific gap Hermes's review found in the
draft). Planned-but-not-started tasks get a dedicated fixed lane aligned
to the shared time axis. `plan_task_ref` at session-creation time is
populated via a lightweight interactive picker (with an explicit
"unplanned session" choice), not a bare CLI flag alone.

## Consequences

### Positive
- Correlation is structurally guesswork-free: a session either carries an
  explicit `plan_task_ref` that resolves, or it doesn't — no silent
  mis-linking as plans get edited.
- Part 1's additive-only design (`plan_task_ref` optional everywhere) has
  zero blast radius on existing sessions, snapshot consumers, or
  rendering — confirmed by 45 passing regression tests, including one
  proving `write_snapshot()`'s inheritance claim rather than assuming it.
- The ghost-marker-on-real-axis design (Part 2) gives direct visual
  comparison without inventing dates or durations no plan states.

### Negative
- Part 2 is not yet implemented — the field exists and flows through the
  pipeline (Part 1), but nothing consumes it for reconciliation or
  rendering yet. A `plan_task_ref` set today has no visible effect.
- The sidecar format duplicates a second file per plan doc that wants
  tracking, and nothing enforces every plan doc gets one — the operator
  must remember to retrofit older plans if they want divergence tracking
  applied retroactively (explicitly out of this design's scope).

### Risks
- The `heading_ref` drift-check lint is stated as required but not yet
  built — until it exists, a sidecar's `heading_ref` values can silently
  detach from the plan doc's actual headings with no automated warning.
- The overrun multiplier (2x) and minimum sample size (5) are tuning
  calls with no production data behind them yet; may need revision once
  real plan-execution history accumulates.

## Alternatives Considered
1. **Parse `## Task N` headings directly from plan-doc prose instead of a
   YAML sidecar** — Rejected per Codex's review: markdown is authored for
   humans and produces brittle identities that silently break on any
   edit (renumbering, insertion, rewording).
2. **Fuzzy-match sessions to planned tasks by text similarity or timing
   proximity** — Rejected: reintroduces exactly the guesswork Codex's
   review warned against; explicit-only correlation was adopted instead.
3. **Render planned shape as a separate strip, linked to time-axis lanes
   only by a text-suffix label** — Rejected after Hermes's review: buries
   the divergence signal for anything beyond a handful of tasks, requires
   manual cross-referencing. Replaced with ghost markers anchored to the
   real time axis.
4. **Cross-plan calibrated overrun thresholds from day one** — Rejected
   as premature: no historical duration data exists yet to calibrate
   against; deferred to v2 in favor of a self-referential same-plan
   baseline for v1.

## Validation
- [x] Part 1 implementation matches decision —
      `agent-platform/runtime/session_state.py`,
      `agent-platform/cli/status.py`, both test files; 45 tests passing,
      committed 2026-08-20.
- [ ] Part 2 implementation matches decision — not yet implemented.
- [x] Part 1 tests cover decision boundaries — additive-only regression
      confirmed (`plan_task_ref` omitted preserves exact existing payload
      shape), inheritance through `write_snapshot()` proven, not assumed.
- [ ] Part 2 tests — pending implementation.

## Open Questions (deferred, not blocking this ADR)
- Exact ghost-marker DOM/CSS layout, and whether dense plans need a
  collapsed/summarized view — left to the Part 2 implementation plan.
- Whether cross-plan task dependencies (`depends_on` referencing a task in
  a *different* plan doc) will be needed — no evidence yet to design
  against.
