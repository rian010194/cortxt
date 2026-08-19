# v.02 Swarm Orchestration Model — design

**Date:** 2026-08-19
**Status:** Approved (pending final user sign-off on this file before implementation plan)
**Context:** `C:\Users\rikar\AppData\Local\Temp\2026-08-19-cortxt-orchestrator-handoff.md` (prior session handoff, read for full background)

## Problem

The prior session shipped all 7 wayfinder phases (0–6) plus Orchestrator Dispatch
v0.1, then surfaced six open discussion points for "what's next." The operator
wants more than a discussion: a session where Claude acts as orchestrator over a
larger Hermes/Pi/own-agent swarm, working toward the v.02 vision across several
of those points at once, running as autonomously as possible.

The prior session also surfaced a hard constraint that any swarm design must
answer to: **autonomous Kanban-issue dispatch went 0-for-4** (issues #165, #166,
#174, #175 — wrong surface, invented out-of-scope work, or false "completed"
self-reports with everything left uncommitted). **One-shot dispatch + manual
integration went 2-for-2** (`routing/discovery.py`, two `cortxt dispatch --tags
research` calls). Scaling up autonomy without addressing this gap would be
building on the mechanism that just failed, not the one that worked.

## Non-goals

- Fas 6 pricing — explicitly the operator's business decision, stays out of
  this swarm's backlog entirely.
- Deciding *this session* whether agent-memory or the widget/Rust future become
  full phases — both stay at document/scoping level this round (see Backlog).
- Building a general-purpose multi-agent framework. This is scoped to Cortxt's
  own dispatch mechanism and this session's five tracks.

## Session authorization (explicit, time-boxed)

For this session only, the operator has granted full autonomy: I may commit,
open PRs, merge to `main`, and accept ADRs without a per-step confirmation gate.
This supersedes the standing "never commit/merge/accept an ADR without being
asked" rule **for this session's swarm work only** — it does not carry into
future sessions (per the prior handoff's own note that blanket permission
doesn't automatically carry over; it must be re-granted, and here it has been).

Every code change still goes through the existing test suite and the
`code-review` skill before merge — that check is not part of what was loosened.

## Architecture: proof-step → escalation → checkpoint

Every track (the four content tracks plus Track 0, the orchestrator mechanism
itself) moves through the same staircase:

1. **Decomposition.** I break the track into narrow, isolated deliverables —
   one file or one clearly-bounded document per unit, the same granularity as
   `routing/discovery.py` or last night's research dispatches.
2. **Proof step.** The first 1–2 units in a track run as one-shot dispatch
   (`hermes -z ...`, or the Pi/own-agent equivalent once confirmed — see Track
   0) with me integrating, reviewing, and committing by hand. This is the
   pattern with a 2-for-2 track record; every track must clear it before
   anything more autonomous is trusted with that track's work.
3. **Escalation decision.** Only if the proof step succeeds *and* the track's
   remaining work is genuine multi-file coordination (not just "more isolated
   files") do I escalate the remainder to a Kanban-style autonomous agent run.
4. **Mid-task checkpoint.** An escalated agent run must stop and report after
   its first commit/deliverable. I review the actual diff — not a self-report —
   before it's allowed to continue. This directly targets the failure mode
   behind #174/#175 (self-reported "completed" with nothing committed).
5. **PR → code-review skill → merge.** Same gate as every prior PR this
   project has shipped; merge itself is autonomous this session per the
   authorization above.

### Failure handling

- **Failed proof step** → the track freezes at that step. It becomes an open
  item in the end-of-session handoff, and is *not* escalated to a Kanban agent
  — an engine that can't clear the reliable path doesn't get promoted to the
  unreliable one.
- **Failed mid-task checkpoint** (scope drift, or a false "completed" report)
  → the escalated portion is discarded entirely and falls back to manual
  proof-step decomposition of the same work, the same recovery used for
  #174/#175.

## Engine expansion: Pi and the own coding agent

`routing/engine_manifest.py` currently declares two engines (`claude-direct`,
`hermes`), each with a manifest grounded in actual dispatch attempts —
`reliability_class` is hand-set from evidence, never assumed. Pi and the
operator's own coding agent will be added the same way, not guessed:

- Track 0's first unit is a **spike**: confirm each engine's actual CLI
  invocation shape (flags, whether a one-shot mode like Hermes's `-z` exists)
  before writing an invoker module. Guessing an invocation contract is exactly
  the mistake the prior session explicitly avoided for a headless Claude Code
  CLI path that was never confirmed to exist.
- Once confirmed, each gets its own `*_invoker.py` (mirroring
  `hermes_invoker.py`'s shape: one call, one structured result, no retry logic)
  and an `EngineManifest` entry with `reliability_class="unverified"` until it
  has cleared its own proof step.

## Backlog (this session's five tracks)

| Track | Proof step (one-shot) | Likely escalation |
|---|---|---|
| **0. Orchestrator mechanism** | Pi/own-agent invocation spike + `*_invoker.py` modules + mid-task-checkpoint support in `cortxt dispatch` | None — this track stays at proof-step scale by design |
| **1. Admin-UI wiring** | One widget component per one-shot call (runtimes panel, credentials panel, addons panel) against `widget/` | If the panels need shared state/layout work that can't be isolated per-component |
| **2. Agent-memory** | Scoping document only (what "memory" should mean, boundary against the existing audit log) — **no code** until the operator approves the scope | None this round — still an open question per the prior handoff, not ready for code |
| **3. ADR-023 external surface** | Small spike doc comparing SDK/MCP/REST against ADR-023's direction, plus an ADR draft (one-shot) | The surface implementation itself, only after the ADR is accepted |
| **5. Widget / Rust future** | Research document only (current widget gap vs. the approved Fluent prototype on `prototype/widget-cli-v02`, Rust-native prerequisites) | None this round — scope explicitly undecided, stays an open question / ADR candidate |

Tracks 2 and 5 stay at document/scoping level this round — per the prior
handoff, both are open questions, not phases ready for implementation.

## Reporting

- **Status file**, updated continuously during the run:
  `.hermes/plans/2026-08-19-swarm-status.md` — one section per track, updated
  at every proof-step/escalation/checkpoint/freeze transition. This is the
  detailed record; the operator can open it any time without waiting on chat.
- **Chat pings**, kept short, only on major events: a merge, an ADR acceptance,
  or a track freezing. Not a running commentary on every intermediate step.
- **End-of-session handoff document**, same shape as the one this session
  started from: what shipped per track, what froze and why, what's still open
  for the next session.

## Testing

No change to the existing bar: full test suite plus the `code-review` skill
gates every merge, exactly as it did for every PR in the prior session (#161–
#179). The only thing this design changes is who clicks merge, not what has to
pass first.
