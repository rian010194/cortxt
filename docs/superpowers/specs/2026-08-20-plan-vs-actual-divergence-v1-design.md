# Plan-vs-actual divergence v1 — design

Status: spec-only, no implementation started — this is sub-project 3 of the
2026-08-19 three-way split ("widget swimlane/pipeline visualization"),
scoped narrowly to the plan-vs-actual linkage question specifically, not the
whole swimlane surface
Date: 2026-08-20
Authority: architectural proposal for one bounded sub-project; does not
override ADR-026 (`EngineAdapter` registry) or ADR-027 (`EngineContext`
service broker), neither of which this spec touches. Does not authorize
implementation — per this project's working rules, linking planning
documents to runtime session state is a new subsystem, not a bounded change
to existing code, and needs a shown-and-approved design before any code
change.
Related:
- `docs/superpowers/specs/2026-08-19-supervisor-daemon-v1-design.md` and
  `docs/superpowers/specs/2026-08-20-unattended-daemon-credential-security-model-v1-design.md`
  (sub-projects 1 and 2 of the same three-way split; this is sub-project 3,
  independent of both — neither daemon design nor credential model is
  touched or assumed here)
- `agent-platform/cli/status.py` (`load_sessions`, `build_workstreams`,
  `write_snapshot` — the existing session→snapshot pipeline this design
  extends, read in full this session)
- `agent-platform/runtime/session_state.py` (`create`, event schema — the
  existing session identity fields this design's correlation mechanism must
  hook into, read in full this session)
- `agent-platform/widget/index.html` (`renderPipeline`, `.lane`/`.segment`/
  `.badge` — the existing time-axis lane rendering this design's presentation
  section extends, read this session)
- `docs/superpowers/plans/2026-08-20-orchestrator-engine-resume-and-codex-adapter.md`
  (representative real plan doc — numbered `## Task N: <title>` sections with
  Files/Interfaces/checkbox-Steps, the prose structure the sidecar format
  below must reference without duplicating)
- `.hermes/dispatch/handoff-20260820c.md` (this session's starting context;
  Codex's pre-spec recommendation, reproduced and resolved below)
- The parallel worktree `agent/lane-metadata` (sub-project 3's "D" slice —
  basic session_id/branch/runtime/timestamp visibility in the widget/CLI —
  is being built there right now, independently; see Non-goals)

## Revision note (2026-08-20, post-draft Hermes review)

Hermes (`researcher` profile) reviewed the full draft (pasted, not read from
disk — the CLI has no file-input flag) and found seven concrete issues, all
folded in below rather than left as findings, plus confirmed the two-part
split and the no-fuzzy-matching correlation rule are sound:

1. **`relative_size` was simultaneously "not a duration estimate" and the
   input to a duration-comparison baseline** — a real contradiction. Fixed:
   Part 1 now defines `relative_size` as an explicit ordinal (`s < m < l`)
   used only for ordinal comparison ("same-or-smaller"), never converted to
   or compared against a time quantity directly.
2. **The self-referential overrun baseline had no fallback for too few
   samples** — Hermes: "a task running 10x long with no peers shows green.
   That is a real silence problem, not just an open question." Fixed: a new,
   explicit `insufficient-baseline` state (Part 2), rendered distinctly from
   `on-track`, not silently defaulted to it.
3. **Failed-task propagation to dependents didn't say direct-vs-transitive,
   nor what happens to an already-succeeded task whose blocker fails
   later.** Fixed: Part 2 now states propagation is transitive through the
   full `depends_on` graph, and names the already-succeeded-then-orphaned
   case explicitly (rendered as-is, never retroactively unmarked).
4. **Retry state was ambiguous** ("most recent attempt" — most recent by
   creation time regardless of status, or most recent terminal one?).
   Fixed: defined precisely in Part 2's Retries section.
5. **`unresolvable-reference` and `unplanned` (no reference at all) were
   folded into one visual treatment**, losing the diagnostic difference
   between "this session's plan reference is broken" and "this session was
   never meant to reference a plan." Fixed: distinct lane markers specified
   for each in Part 2's table.
6. **`heading_ref` had no integrity story** — correlation never uses it for
   identity (by design, Part 1), but nothing enforces it stays accurate
   either, so an editor could silently detach it from the doc it names.
   Fixed: the drift-check lint, previously mentioned only as a "plausible
   good addition" in Non-goals, is now stated as a required companion to
   using `heading_ref` at all (still an implementation-time artifact, not
   built here — but no longer optional).
7. **Architectural pushback on the axis split**, the most substantial
   finding: rendering planned shape as a *separate* discrete strip, linked
   to the time-based lanes only by a text-suffix label, "buries the
   divergence the subsystem is meant to surface" for anything beyond a
   handful of tasks — a reader has to manually cross-reference two
   disconnected visual regions. Hermes's alternative — anchor each planned
   task's marker to its session's *actual* recorded start timestamp (a real
   value, not a fabricated date) directly on the existing time axis, as a
   ghost/outline marker, with the next not-yet-started task's marker placed
   immediately after the axis's current rightmost real event — achieves
   direct visual comparison without inventing any date the plan never
   stated. **Adopted**, replacing the separate-strip design in Part 2 below.

## Problem

The operator wants the widget/CLI swimlane view to show a workstream's
*expected* shape — derived from this project's own markdown implementation
plans under `docs/superpowers/plans/*.md` — next to its *actual* runtime
shape (`cli/status.py`'s session/workstream/lane model, already rendered by
`widget/index.html`'s time-axis lanes), so the view visually diverges when
execution doesn't match the plan: a task runs far longer than expected, a
task fails, a task is blocked on an unfinished dependency, or a session
appears that no task in the plan accounts for.

Two things stand in the way today, confirmed by reading both sides:

1. **Plan docs are prose, not data.** `docs/superpowers/plans/*.md` files
   are numbered `## Task N: <title>` sections written for a human/agent to
   execute step-by-step (Files/Interfaces/checkbox Steps) — there is no
   stable machine-readable task identity, order, dependency, or relative-size
   signal anywhere in them today. Parsing the prose directly (regexing
   `## Task N` headings, inferring order from position) would work only
   until a plan is edited — renumbered, a task inserted, a heading reworded
   — at which point any correlation built against it silently breaks or
   silently mis-links, exactly the "guesswork" a colleague (Codex) flagged
   when consulted on this design.
2. **No session field references a planned task.** `session_state.create()`
   (`agent-platform/runtime/session_state.py`) accepts `task_id`,
   `workstream_id`, `run_id`, `issue_id`, `branch`, `worktree`,
   `worker_role`, `runtime` — none of these identify *which numbered task in
   which plan document* a session is doing. `task_id` today is a free-text
   label (e.g. whatever string the dispatching code passes), not a
   plan-scoped reference. Without an explicit field carrying that reference,
   any session-to-plan-task correlation has to guess from text similarity —
   the exact failure mode Codex's review called out.

A colleague (Codex) was consulted before this spec was written and gave the
following recommendation, incorporated throughout:

> C contains at least two separate problems: (1) Plan modeling: represent
> stable task IDs, order/dependencies, expected duration or relative sizing,
> and workstream linkage. (2) Reconciliation and presentation: associate
> sessions with planned tasks, identify unmatched sessions, and define
> lateness, failure, blocked work, and visual divergence. Specify those
> separately. Without explicit task-to-session correlation, "divergence"
> will be guesswork. Pushback: don't call it an "expected timeline" unless
> plans contain defensible estimates; otherwise show expected shape/order,
> not dates or duration promises. I recommend a structured sidecar rather
> than parsing prose. Markdown is authored for humans and will produce
> brittle identities and estimates. A small YAML file should carry stable
> task IDs and machine-relevant fields, while referencing headings in the
> plan document. Keep it minimal; don't duplicate task prose unnecessarily.
> Treat C+D as one design initiative but at least two implementation
> increments: metadata/correlation first, then planned-shape reconciliation
> and divergence visuals.

This spec is organized as the two separate problems Codex named — Plan
modeling, then Reconciliation & presentation — each with its own concrete
shape, so neither section quietly leans on assumptions from the other.

## Part 1 — Plan modeling

### The sidecar file

Each plan doc that wants divergence tracking gets a structured YAML sidecar,
same directory, same basename, `.tasks.yaml` suffix instead of `.md`:

```
docs/superpowers/plans/2026-08-20-orchestrator-engine-resume-and-codex-adapter.md
docs/superpowers/plans/2026-08-20-orchestrator-engine-resume-and-codex-adapter.tasks.yaml
```

Colocated, not centralized under a separate index directory, so a reader
looking at the plan doc's directory listing sees the sidecar sitting right
next to it — the same "read first" discoverability this project's other docs
already lean on (e.g. handoff files naming "read first" docs by path). A
plan doc with no sidecar simply has no divergence tracking; this is additive
and optional, never required for a plan to be valid.

A sidecar is **not required to exist at plan-authoring time.** It's a
separate artifact, plausibly written after the plan (once task shape has
settled) or retrofitted onto an older plan that predates this design. This
spec does not require every existing plan doc under `docs/superpowers/plans/`
to gain one.

### Sidecar schema (v1)

```yaml
schema_version: 1
plan_id: 2026-08-20-orchestrator-engine-resume-and-codex-adapter
plan_doc: 2026-08-20-orchestrator-engine-resume-and-codex-adapter.md
tasks:
  - task_id: T1
    heading_ref: "## Task 1: `EngineAdapter` protocol gains an additive `session_id` parameter"
    title: EngineAdapter protocol gains session_id
    order: 1
    depends_on: []
    relative_size: s

  - task_id: T2
    heading_ref: "## Task 2: `invoke_hermes()` resumes via `--resume` when given a session id"
    title: invoke_hermes resumes via --resume
    order: 2
    depends_on: [T1]
    relative_size: s

  - task_id: T3
    heading_ref: "## Task 3: Capture a fresh Hermes session's id via `hermes sessions list`"
    title: Capture fresh Hermes session id
    order: 3
    depends_on: [T2]
    relative_size: m

  # ... T4-T8 omitted for brevity in this example; same shape.
```

Field-by-field:

- **`task_id`** — stable, short, author-assigned (`T1`, `T2`, ... by
  convention mirroring the plan doc's own `## Task N` numbering, for human
  readability — but the convention is not enforced and is not load-bearing).
  **Immutable once assigned.** A session created against `T3` must keep
  resolving to the same conceptual task even if the plan doc is later
  edited — a task inserted in the middle, a task renumbered, a heading
  reworded — none of that may change an existing `task_id`. If a plan is
  revised in a way that actually changes what a task does, that's a new
  `task_id` (with the old one's `heading_ref` optionally left in place or
  marked defunct in a future schema revision — see Open questions), not a
  reused one. This mirrors this project's own register/description
  distinction (a decision, once recorded, doesn't get silently edited out
  from under something that referenced it).
- **`heading_ref`** — the exact, verbatim markdown heading text from the
  plan doc (`## Task N: <title>`, copy-pasted, not reconstructed). This is
  how the sidecar *references* the prose instead of duplicating it — a
  human or tool can jump straight to the right section. It is not parsed at
  runtime for identity (that's what `task_id` is for) — it exists so a
  sidecar entry can be checked against its plan doc. **`heading_ref` has no
  integrity guarantee on its own** (Hermes review, Revision note): nothing
  stops a plan doc's heading from being edited, split, or reworded out from
  under a sidecar that still quotes the old text verbatim, and correlation
  never notices because it doesn't use `heading_ref` for identity. This
  design therefore treats a drift-check lint — "does this `heading_ref`
  still exist verbatim in `plan_doc`?" — as a **required companion to using
  `heading_ref` at all**, not an optional nicety: a sidecar whose
  `heading_ref` values silently detached from their plan doc is worse than
  no `heading_ref` at all, since it looks trustworthy while being wrong. The
  lint's implementation (a script, a pre-commit hook, whatever the
  implementation plan chooses) is still out of scope for this spec-only
  document, but the requirement that one exist before this field is relied
  on is not optional.
- **`title`** — a short human label for the reconciliation/presentation
  layer to display without re-reading the plan doc. Deliberately much
  shorter than the full heading text.
- **`order`** — an integer defining the plan's intended sequence. Not a
  timestamp, not a duration offset — purely "this comes before/after that,"
  matching Codex's pushback: the sidecar asserts shape/order, never dates.
- **`depends_on`** — list of `task_id`s that must reach a terminal
  `succeeded` state (per Part 2's correlation) before this task's own
  "not blocked" state applies. Optional, defaults to empty. Only intra-plan
  dependencies are modeled in v1 — a task in one plan depending on a task in
  a *different* plan doc is out of scope (see Non-goals).
- **`relative_size`** — one of `s` / `m` / `l` (small/medium/large), the
  plan author's own subjective call, **not** a duration, not an hour
  estimate, not derived from any formula. This directly implements Codex's
  pushback: "don't call it an expected timeline unless plans contain
  defensible estimates; otherwise show expected shape/order, not dates or
  duration promises." If a specific plan doc genuinely states a real,
  defensible duration for a task (rare — none of the plans read this session
  do), that number belongs in the plan doc's own prose, and the sidecar may
  carry it as a separate, clearly-optional field in a future schema revision
  — v1 does not invent a mechanism for it since no real plan currently
  provides one to design against.

  **Ordinal only, never a duration proxy** (fixed per Hermes review, see
  Revision note): `s < m < l` is a strict ordering with no implied ratio or
  magnitude between steps — `relative_size` is never converted to, or
  compared against, a clock quantity. Part 2's overrun baseline uses it only
  to answer "is this other completed task's size the same or smaller,"
  never "how much longer should this take because it's size `m`." If two
  tasks are both size `m`, they are comparable for baseline purposes; a size
  `s` task is comparable against other `s` tasks and, per "same-or-smaller,"
  against nothing larger than itself. There is no cross-size conversion
  factor anywhere in this design, deliberately — inventing one would smuggle
  back the duration-estimate claim Codex's pushback rejected.
- **`plan_id`** (top-level) — the plan's own stable identity, conventionally
  the plan doc's filename stem. This is how "workstream linkage" (Codex's
  phrase) is satisfied: **not** by embedding a specific runtime
  `workstream_id` value into the sidecar. A plan doc is authored before any
  runtime workstream/branch exists, and the same plan could plausibly be
  executed more than once across its lifetime (a worktree recreated after a
  crash, a plan resumed on a new branch) — hard-coding one `workstream_id`
  into the sidecar would make it wrong the second time. Instead, linkage is
  resolved at runtime, per session, via the correlation field in Part 2
  (`plan_task_ref`, shaped `<plan_id>#<task_id>`) — the plan stays
  workstream-agnostic; whichever session references it, in whichever
  workstream that session happens to run under, is how the two get tied
  together for that execution.

No step-by-step task prose (Files/Interfaces/Steps) is duplicated into the
sidecar — `heading_ref` is the pointer back to that content, per Codex's
"keep it minimal" instruction.

### The new session field this requires (its own implementation increment)

**This does not exist today** — confirmed by reading `session_state.create()`
in full. None of its current parameters (`task_id`, `workstream_id`,
`run_id`, `issue_id`, `branch`, `worktree`, `worker_role`, `runtime`) can
carry a plan-task reference without overloading a field that already means
something else. This spec proposes a **new, optional field**:

```python
def create(
    store: Path,
    task_id: str,
    *,
    workstream_id: str | None = None,
    run_id: str | None = None,
    issue_id: str | None = None,
    branch: str | None = None,
    worktree: str | None = None,
    worker_role: str | None = None,
    runtime: str | None = None,
    plan_task_ref: str | None = None,   # NEW
) -> dict:
```

`plan_task_ref` is a single string, `"<plan_id>#<task_id>"` (e.g.
`"2026-08-20-orchestrator-engine-resume-and-codex-adapter#T5"`), stored
verbatim in the `session.created` event's payload exactly like the other
optional identity fields already are — no new event type, no schema-version
bump (the existing `create()` pattern of "include a key only if the caller
supplied a value" already extends this way, see `optional.update(...)` in
the current code).

`cli/status.py:load_sessions()` needs one corresponding line added to the
dict it builds per session (mirroring how `workstream_id`/`issue_id`/etc.
are already read off `created_payload`), and `write_snapshot()`'s schema
grows the new key by inheritance (it doesn't special-case any per-session
field today — it just carries whatever `load_sessions()` produced through
to the snapshot JSON).

**This field does not exist and must be threaded through session creation
before any correlation in Part 2 can work. That threading — the field
itself, `session_state.create()`, `cli/status.py`, and whatever call site(s)
eventually pass a real `plan_task_ref` at dispatch time (daemon task
selection, or an operator-supplied CLI flag) — is its own implementation
increment, separate from the sidecar format above and separate from Part 2's
reconciliation/rendering logic**, per Codex's explicit "metadata/correlation
first, then reconciliation and divergence visuals" split. This spec does not
implement it; it only specifies the shape it must take.

### Explicitly not this spec's concern: sub-project 3's "D" slice

A parallel, independent piece of work — basic session_id/branch/runtime/
timestamp visibility in the widget/CLI — is being built right now in
`agent/lane-metadata`. It does not read or write `plan_task_ref`, does not
touch plan sidecars, and this spec does not depend on it landing first or
assume anything about its shape. The two are only related by both living
under "sub-project 3" in the 2026-08-19 split; they are separate
implementation increments with no ordering dependency between them.

## Part 2 — Reconciliation & presentation

### Correlation: matching a session to a planned task

Deliberately **explicit only, never inferred.** A session correlates to a
planned task if and only if its `plan_task_ref` (Part 1) resolves to a real
`(plan_id, task_id)` pair found in a loaded sidecar. No fuzzy matching on
`task_id` text, no matching by timing proximity, no matching by
`workstream_id` similarity — any of those reintroduce exactly the guesswork
Codex's review warned against. Three outcomes, each a distinct, named state
rather than a single boolean:

1. **Matched** — `plan_task_ref` parses to `<plan_id>#<task_id>` and both
   halves resolve against a loaded sidecar's `tasks` list. The session is
   this task's current (or a past) attempt.
2. **Unresolvable reference** — `plan_task_ref` is present but doesn't
   resolve (unknown `plan_id`, unknown `task_id` within a known plan, or a
   malformed string). **Rendered distinctly from `unplanned`** (fixed per
   Hermes review, see Revision note — the two were originally folded into
   one treatment, losing a real diagnostic signal): a broken reference means
   something is wrong (a typo, a sidecar edited without updating the
   session, a sidecar that failed to load) and should look different from a
   session that was never meant to reference a plan at all. See the
   rendering table below for the specific marker.
3. **Unplanned** — `plan_task_ref` is absent entirely. This is the default,
   expected case for any session not created against a tracked plan (manual
   `cortxt` invocations, ad hoc debugging sessions, work predating this
   design) — not an error state, just "not part of the tracked plan."

**Retries — resolved precisely** (fixed per Hermes review; the draft's
"most recent attempt" was ambiguous between most-recent-by-creation-time and
most-recent-terminal). More than one session can carry the same
`plan_task_ref` (a task fails, gets retried under a fresh session). The
task's *current* displayed state is driven by whichever session has the
latest `session.created` timestamp among all sessions sharing that
`plan_task_ref`, **regardless of whether that session has reached a
terminal state** — if the latest attempt is still `running`, the task shows
as running/on-track/overrunning per that live session, even though an
earlier attempt against the same task failed; the failed attempt is not
what's displayed once a newer one exists. The full attempt list (every
session that ever carried this `plan_task_ref`, oldest to newest) stays
available for anyone who wants to see prior failures — reconciliation never
discards history, it only picks the newest attempt to drive the primary
display.

### Divergence: what each case means and what changes on screen

**Design revision (Hermes review, see Revision note): planned markers are
anchored to the existing time axis, not drawn on a separate strip.** The
draft's original design kept planned shape off the time axis entirely
(reasoning: `order`/`depends_on` carry no timestamps, so drawing them on a
continuous time axis would either fabricate dates or misrepresent order as
duration) and rendered it as a disconnected strip instead. Hermes's review
correctly identified this as self-defeating for a *divergence* view: a
separate region linked only by a text-suffix label requires manual
cross-referencing and, for anything beyond a handful of tasks, buries
exactly the signal the subsystem exists to surface.

**Adopted resolution:** a planned task's marker uses a *real* timestamp once
one exists — its matched session's actual recorded `started_at` — and is
drawn directly on the same time axis `renderPipeline` already computes from
real segments, as a ghost/outline marker layered behind or alongside that
session's own `.segment` bar (not a fabricated date; it's the same
timestamp the actual segment already uses). A planned task with **no**
session yet has no real timestamp to anchor to — it renders as a ghost
marker positioned immediately after the axis's current rightmost real
event (i.e., "next," visually queued at the leading edge of what's actually
happened so far), not at an invented future date. As earlier tasks
complete and the axis's rightmost real timestamp advances, a not-yet-started
task's ghost marker moves with it — it is always "immediately next," never
pinned to a fixed point in a still-hypothetical future.

This keeps the single-coordinate-system property Hermes's review asked for
(everything shares the real time axis, so planned-vs-actual is a direct
visual comparison, not a cross-reference exercise) while never fabricating
a date or duration the plan doesn't state (a not-started task's position is
derived from *where real work has actually gotten to*, not from a promised
completion time).

Concretely, for a workstream with a linked plan sidecar, each `#lanes` row's
`.track` gains ghost-marker rendering alongside its existing `.segment`
bars, per this table:

| Case | Ghost marker (on the existing time axis) | Existing lane row |
|---|---|---|
| **Not started** — planned task has no session yet, and every task in its `depends_on` is already `done`. | Outlined/dashed marker positioned at the axis's current rightmost real timestamp (the "next" position, advancing as real work progresses), muted/dim styling, label = `title`. No lane row to attach it to yet, so it renders on a shared "planned" track above the per-session lanes. | No corresponding lane row exists yet — nothing to show, there is no session. |
| **Plan-blocked** — planned task has no session yet, and at least one `depends_on` task is not yet `done`. **New state, does not exist today** — distinct from a session self-reporting `status: blocked` (an existing, different concept: a *running* session that reports it's stuck). Presentation-only; computed by reconciliation, never written to any session's own event log. | Same "planned" track and position as "not started," plus a small lock/chain glyph and a tooltip naming which unfinished task(s) it's waiting on — visually distinguishable so an operator can tell "could start any time" from "waiting on something else" without reading logs. | Same as "not started" — no lane row yet. |
| **On track** — matched session `status: running`, elapsed time within the plan's own size-adjusted expectation (see "overrun threshold" below). | Ghost outline anchored at the session's real `started_at`, accent/blue outline, same `pulse` animation `.badge.running` already uses. | Unchanged from today: normal `running` segment, growing blue/accent bar, drawn on top of/adjacent to the ghost outline. Lane name gains a suffix showing the matched task id, e.g. `agent · hermes [T5]`. |
| **Insufficient baseline** — matched session `status: running`, but too few same-or-smaller-size peer tasks have completed in this plan yet to compute an overrun threshold (see below). **New state, does not exist in the draft** — added because the draft's silent fallback to "on track" would show green for a task that could already be running arbitrarily long with nothing to compare it against. | Ghost outline in a neutral/grey tone (not accent-blue "on track," not warn-amber "overrunning") with a small "?" glyph; tooltip states "no baseline yet in this plan." | Unchanged lane segment (still a normal running bar) — the neutral glyph is the only signal that no overrun judgment is being made yet, deliberately different from both "confirmed fine" and "confirmed slow." |
| **Overrunning** — matched session still `running`, elapsed time has crossed the overrun threshold for its `relative_size` bucket (see below). | Ghost outline switches to `--warn` (the existing amber the widget already uses for `blocked`/`stale`), plus a small "⏱" glyph. Tooltip states the multiple over the baseline (e.g. "2.4x baseline"). | Lane segment itself stays a normal running bar (the session hasn't reported anything different — only the plan comparison has), but the `[T5]`-suffixed lane name gets the same `--warn` glyph, so a reader scanning lane names alone still sees the flag. |
| **Failed** — matched session's most recent attempt (Retries, above) reached a terminal `failed`/`timed_out` status. | Ghost outline turns `--bad` (red), "✕" glyph, anchored at the failed attempt's real timestamps. **Propagation is transitive** (fixed per Hermes review — the draft didn't say direct-vs-transitive): every task reachable from the failed task through the `depends_on` graph, at any depth, renders as **plan-blocked**, not just its immediate dependents. **Orphaned success, named explicitly** (fixed per Hermes review): if a dependent task already has a `succeeded` matched session recorded *before* its blocker later fails (e.g. re-run order, or a blocker retried and failed after a dependent had already run against an earlier, since-superseded attempt), that dependent's own `done` marker is **not retroactively changed** — it stays `done`, exactly as recorded; this design does not un-mark a completed task because something upstream later failed, it only prevents *new, not-yet-started* dependents from beginning. | Lane row unchanged (already renders `failed`/`timed_out` segments in `--bad` today) — the ghost marker persists even after the failed session's lane scrolls out of view. |
| **Unresolvable reference** — session's `plan_task_ref` is present but doesn't resolve against any loaded sidecar (Part 2, correlation case 2). | No ghost marker — there is no resolvable task to anchor one to. | Lane row gets a small broken-link glyph before the lane name, distinct from the unplanned marker below, and a tooltip naming the unresolved reference string and why it failed to resolve (unknown plan, unknown task, malformed string) — this is a debugging signal ("something is supposed to be linked and isn't"), different in kind from "nothing was ever supposed to be linked here." |
| **Unplanned** — session's `plan_task_ref` is absent entirely, while its workstream has an active, loaded plan sidecar. | No ghost marker — nothing in the plan corresponds to this session, and inventing one would misrepresent the plan. | Lane row gets a small unfilled-diamond/asterisk marker before the lane name (distinct from the unresolvable-reference glyph above), grouped after all matched lanes under a visual separator/sub-heading ("Unplanned"), so it reads as *additional*, not interleaved as if expected. The footer's existing `.chips` row (today: kostnad/tid/tok) gains a fifth chip, "unplanned `<b>N</b>`," combining both the unplanned and unresolvable-reference counts with the tooltip breaking out the split. |

**Overrun threshold — flagged as an open numeric question, not invented
here.** With `relative_size` deliberately ordinal, not a duration (Part 1),
"far past expected" cannot be computed against an absolute duration on day
one — no plan in this repository states one, and inventing a formula (e.g.
"small = 30 minutes") would fabricate exactly the defensible-estimate claim
Codex's pushback rejected. This spec's recommendation, left for operator
confirmation rather than decided unilaterally:

- **v1 (no history):** compute a **self-referential baseline** — the
  median actual duration of already-`succeeded` tasks *in the same plan, of
  the same or smaller `relative_size`* (ordinal comparison only, per Part
  1's fix) — and flag "overrunning" once a running task's elapsed time
  crosses a configurable multiple of that baseline (a reasonable starting
  point is 2x, but the exact number is an operator call, not a finding).
  **If fewer than some minimum number of same-or-smaller-size tasks have
  completed yet in this plan to form a baseline, the task renders as
  `insufficient-baseline` (above), never silently as `on-track`** — this
  replaces the draft's silent fallback, which Hermes correctly flagged as a
  real problem (a task running arbitrarily long with no peers would have
  shown green).
- **v2 (future, out of scope here):** once enough plan executions
  accumulate size-bucketed duration statistics across multiple plans, a
  cross-plan calibrated baseline could replace the self-referential one.
  Not designed here — no historical data exists yet to design it against.

### What "divergence" means, summarized

Divergence is not a single flag — it is the sum of the per-case states in
the table above, evaluated independently per planned task and per session:
a task overrunning, a task with no baseline yet, a task failed (with its
full transitive dependent chain now plan-blocked), and an unplanned or
unresolvable session appearing are five structurally different situations
that each get their own distinct visual treatment, not a single generic
"something's off" badge. An operator should be able to tell, from the
time-axis lanes alone (ghost markers plus real segments, no separate view to
cross-reference) and without reading any session's raw event log, which of
these is happening and to which task.

## Non-goals

- **Implementing any of the above.** This document is spec-only per
  explicit instruction; no code, no sidecar files, no widget changes
  accompany this commit.
- **The "D" slice** (session_id/branch/runtime/timestamp visibility) —
  being built independently in `agent/lane-metadata`; this spec does not
  depend on it, does not touch the same rendering surface it's adding, and
  makes no assumption about its landing order relative to this design.
- **Retrofitting sidecars onto every existing plan doc.** This spec defines
  the format; deciding which plan docs get one, and writing them, is a
  separate, later act (plausibly per-plan, as needed) — not part of this
  design.
- **Cross-plan task dependencies.** `depends_on` in v1 only references
  `task_id`s within the same sidecar's own `tasks` list. A task in one plan
  blocking on a task in a different plan doc is a real future need but has
  no evidence yet to design its correlation format against.
- **v2 cross-run calibrated overrun thresholds.** Named above as a future
  direction; not designed here — no historical duration data exists yet.
- **Absolute duration/date estimates of any kind.** Deliberately excluded
  per Codex's pushback; `relative_size` and `order` are the only planned-
  shape signals this design specifies.
- **Daemon task-selection logic that would populate `plan_task_ref`
  automatically** when the daemon (sub-project 1) dispatches a plan task.
  This spec specifies the field the daemon *would* need to populate to make
  automatic correlation work, not the daemon-side logic that decides which
  plan task to dispatch next or writes the reference at creation time —
  that's daemon implementation, out of this spec's scope, and depends on
  sub-project 1's own design, already approved separately.
- **A sidecar-authoring tool, and the drift-check lint's implementation.**
  Part 1 states the `heading_ref`-vs-plan-doc drift check is a *required*
  companion to using `heading_ref` at all (not optional, per the Revision
  note) — but the lint's actual mechanism (script, pre-commit hook, CI
  check) is an implementation-time choice, not specified here.

## Open questions (operator decision required)

1. **Overrun multiplier default.** This spec suggests 2x the self-
   referential same-plan/same-or-smaller-size median as a starting point
   but explicitly declines to fix that number — it's a tuning call with no
   evidence yet, not a finding. Needs an explicit operator answer (or an
   explicit "make it configurable, no shipped default" answer) before
   implementation.
2. **Minimum same-plan sample size before a baseline is trusted.** Related
   to #1 — how many same-or-smaller-size tasks must have already succeeded
   in the same plan before "overrunning" is computed at all, versus
   rendering the task as `insufficient-baseline` (Part 2, fixed per Hermes
   review so this never silently defaults to "on track")? *That* a
   sub-threshold sample renders as its own distinct neutral state is now
   decided; the exact minimum count is still a tuning call with no evidence
   yet.
3. **Should a superseded/renumbered `task_id` be representable at all** (a
   plan revision that genuinely changes what a task does, per Part 1's
   "immutable once assigned" rule) — e.g. a `supersedes:`-style field on a
   sidecar task entry, mirroring this project's own register-document
   convention (`supersedes:` on decision notes)? Named as a plausible v2
   schema extension in Part 1 but not designed here; whether it's needed at
   all depends on how often plans actually get restructured after sessions
   have already referenced their tasks, which isn't yet known.
4. **Ghost-marker layout specifics** (exact DOM/CSS shape of a marker layered
   behind or beside a `.segment` bar, how the shared "planned" track for
   not-yet-started tasks sits relative to the per-session lanes, whether
   dense plans need a collapsed/summarized view) — this spec specifies what
   states exist, what visually distinguishes them, and that they share the
   real time axis (Part 2's Revision-note fix), deliberately not exact
   pixel/DOM layout, which belongs in the implementation plan once this
   design is approved.
5. **Who writes `plan_task_ref` at session-creation time for an
   operator-driven (non-daemon) session** — a new `--plan-task` CLI flag on
   whatever command creates the session? Left for the implementation plan
   that builds the correlation-metadata increment (Part 1's "its own
   implementation increment").

## Decisions (Codex review, 2026-08-20, operator-directed)

The operator directed following Codex's recommendations for all 5 open
questions above. These resolve the tuning calls; the implementation plan
should build against them without re-litigating.

1. **Overrun multiplier: 2x the median peer duration** (same-plan,
   same-or-smaller relative_size). Simple to explain, resistant to
   outliers. Revisit once real production data exists.
2. **Minimum baseline sample size: 5 completed same-size tasks** in the
   same plan before "overrunning" is computed. Below that, render
   `insufficient-baseline` rather than a noisy early signal.
3. **Add an explicit `supersedes` field in v1**, not deferred to v2.
   Codex's pushback: silently treating a renamed/split task_id as
   unplanned/unmatched destroys traceability exactly when plans evolve —
   the case this field exists for is common enough to design in now.
4. **Planned-but-not-started tasks get a dedicated fixed lane**, aligned
   to the shared time axis, queued starting after the latest real event.
   Preserves sequence/order without visually competing with real
   activity for the same horizontal space as an active session's bar.
5. **A lightweight interactive picker at session-creation time**, with an
   explicit "unplanned session" choice alongside real plan tasks. Reduces
   mistyped `plan_task_ref` values while keeping operator-driven session
   creation quick (no separate flag to remember/look up).

## Decomposition note

This spec covers a narrow slice of sub-project 3 of 3 (agreed with the
operator 2026-08-19): plan-vs-actual correlation and divergence, split
internally (per Codex's recommendation) into:
1. **Plan modeling** (Part 1) — sidecar format, `plan_task_ref` field shape.
   Not yet implemented.
2. **Reconciliation & presentation** (Part 2) — matching logic, divergence
   states, concrete rendering changes. Not yet implemented; depends on (1)
   landing first, per Codex's explicit increment ordering.

The broader "D" slice (basic session metadata visibility, unrelated to plan
correlation) is being built independently in `agent/lane-metadata` and is
not part of this document's scope.
