# Track 5: Widget/Rust future research

**Status:** Research only — no decision, no code, no recommendation.
**Date:** 2026-08-19
**Author:** Claude Code (Task 3, Track 5, swarm-track235)
**Consumes:** `prototype/widget-cli-v02` branch (operator-approved Fluent visual
direction, not merged, not deleted); `agent-platform/widget/index.html` and
`agent-platform/widget/serve.py` as they stand on `main` after Track 1
(admin-ui-wiring).
**Produces:** nothing consumed by other tasks in this plan. This stays an open
question, per the backlog table in
`docs/superpowers/plans/2026-08-19-tracks235-scoping-documents.md`.

## 1. What was diffed

`git diff main prototype/widget-cli-v02 -- agent-platform/widget/` returns only
deletions, because the prototype branch predates `agent-platform/widget/`
entirely — it carries the mockup at the repo root instead, under different
filenames. The actual comparison is between:

- `agent-platform/widget/index.html` on `main` (224 lines) — the real
  implementation, extended in Track 1 with `runtimes`/`credentials` panels,
  polling `snapshot.json`.
- `prototype-widget-v02.html` at the tip of `prototype/widget-cli-v02`
  (`git show prototype/widget-cli-v02:prototype-widget-v02.html`, 327 lines) —
  the operator-approved "v04" Fluent mockup, per its own docstring: "PROTOTYPE
  — throwaway, not production... No backend — everything below is static fake
  data." The docstring also records the operator's two v04 corrections
  ("should look like a real Windows app" → Fluent/Win11 chrome; "waterfall
  should look like [an ADW-style pipeline dashboard]" → swimlane Gantt
  replacing a flat event list) and instructs: "Capture the winner, then delete
  this file from main" — it has not yet been deleted, confirmed by
  `git branch -a | grep prototype` still showing
  `prototype/widget-cli-v02` and `remotes/origin/prototype/widget-cli-v02`.

A companion file, `prototype-cli-v02.py` (156 lines at the branch tip), does
the same exercise for a terminal/CLI status view (Windows Terminal Campbell
colors, PowerShell `Format-List`/`Format-Table` shapes). It is out of scope
for this widget-focused document but is worth knowing about if a future
research pass looks at the CLI side.

Also read: `agent-platform/cli/status.py`'s module docstring, which is where
the "one data source, not two independently-fetched views" invariant actually
lives (lines 6–10): "`write_snapshot()` is the CLI↔widget wiring point: the
CLI writes the same `load_sessions()` output the table is rendered from, and
the widget ... polls that file — one data source, not two independently-
fetched views that can drift." `index.html`'s own docstring restates this as
"No independent status logic here (per v.02 vision §3): all of this is read
straight from the snapshot, not recomputed from raw session events."

## 2. Gap inventory: prototype vs. current widget

Concrete, not a redesign brief — what the approved mockup has that today's
widget lacks:

1. **No tabbed navigation.** The prototype uses an underline-tab Pivot
   (`Pipeline` / `Logg` / `Flotta`) with `.tabs button.active::after` drawing
   the accent underline and a click handler swapping `display: none/block`
   per panel. The current widget has no tabs — it stacks three fixed
   `<div class="body">` blocks (sessions, runtimes, credentials) vertically,
   each independently hidden via inline `style.display` when its snapshot key
   is absent.

2. **No real Fluent window chrome.** The prototype's `.titlebar` has working
   caption buttons: `<button>—</button><button>□</button>
   <button class="close">✕</button>` with hover states (`.caption
   button:hover { background: var(--layer-hover) }`, `.close:hover
   { background: #c42b1c }` — the actual Windows close-button red). The
   current widget's titlebar has three empty `<span>` dots with no hover
   state and no functional intent — decorative only, not modeled as caption
   buttons.

3. **No acrylic/Mica backdrop.** The prototype's `.window` uses
   `background: rgba(32,32,32,.7); backdrop-filter: blur(30px) saturate(150%)`
   for a translucent acrylic surface, plus an inset highlight
   (`box-shadow: ... 0 1px 0 rgba(255,255,255,.05) inset`). The current
   widget's `.window` is a flat opaque `background: var(--mica-1)` with a
   single drop shadow — no blur, no translucency, no inset highlight.

4. **No pipeline/swimlane visualization.** The prototype's Pipeline tab
   (`.lanes`, `.axis`, `.lane .track`, `.lane .bar`, `.lane .dot`) renders a
   Gantt-style view: one horizontal lane per agent, time-axis ticks, colored
   bars for completed/running/idle segments, dots for discrete events, and a
   `.now-line` marker. The current widget has no equivalent — no per-agent
   timeline, no visual sequencing of session events at all; it is a flat
   table of current-state rows.

5. **No stat chips / cost-time-token summary row.** The prototype's
   `.pipe-footer .chips` shows `💲0,62 kr`, `⏱1m 58s`, `tok 41,2k` next to a
   timestamp. The current widget has no aggregate cost/duration/token summary
   anywhere — each row shows only `task_id`/`status`/`updated_at`.

6. **No running-state pulse badge.** The prototype's `.badge.running::before`
   animates a pulsing dot (`@keyframes pulse`) for in-progress work. The
   current widget's `.badge` classes (`ok`/`warn`/`error`/`info`) are static
   colored pills with no animation and no distinct "actively running" state.

7. **No log/activity feed tab.** The prototype's `Logg` tab
   (`#tabLogg .item`) renders a timestamped feed of per-agent messages with a
   category tag (`Verkställer`/`Fynd`/`Klart`/`Granskar`). Nothing in the
   current widget shows narrative/event-level detail — only the three
   tabular panels.

8. **No fleet/agent-roster view with budget gauge.** The prototype's
   `Flotta` tab (`#tabFlotta .group .row`) lists each agent with a status
   dot, model name, and running token trail, plus a `.gauge-row` budget bar
   (`142,30 kr · 30%`). The current widget's closest equivalent, the
   `runtimes` panel, is a static installed/path table with no live status
   dot, no per-agent cost, and no budget visualization.

9. **Narrower, fixed-purpose layout vs. tabbed multi-view.** The current
   widget is 520px wide and shows everything at once (three stacked panels);
   the prototype is 460px and shows one tab's content at a time. This is a
   structural consequence of gap 1, not a separate gap, but it means closing
   gap 1 has layout knock-on effects (panel heights, scroll behavior) beyond
   just adding tab buttons.

Not a gap: the prototype's Fluent color tokens (`--mica-1`, `--stroke`,
`--text`, `--success`/`--caution`/`--critical`, the `Segoe UI Variable`/
`Cascadia Mono` font stack) are already present nearly verbatim in the current
widget's `:root` block — Track 1's implementation already carried these over,
per `index.html`'s own docstring: "Fluent/Win11 dark-chrome look carried over
from prototype-widget-v02.html (operator-approved direction), stripped of its
hardcoded fake pipeline data." The token-level visual language is not the gap;
the structural/interaction elements above (tabs, chrome, pipeline view, log
feed, fleet view, stat chips, animation) are.

## 3. Rust-native prerequisites (exploratory, no recommendation)

The operator has floated Rust as a possible longer-term native-app direction.
This is genuinely undecided — the following is an honest inventory of what
that path would require, not an argument for or against it.

**Packaging/distribution.** Today's widget is a zero-build-step static HTML
file plus a 42-line stdlib-only Python loopback server (`serve.py`), run with
`python serve.py`. A native rewrite — Rust or otherwise — trades that for a
compiled-binary distribution problem: something has to produce and hand the
operator an executable (or installer) per target platform. For Rust
specifically that means a toolchain choice (a GUI framework such as Tauri,
egui, iced, or Slint — each with different bundling stories), a build step
that did not exist before, and either a manual build-and-copy step or CI that
cross-compiles and publishes artifacts. Tauri in particular still embeds a
web view and could in principle reuse most of the existing HTML/JS/CSS,
which narrows the gap between "rewrite" and "repackage" — but that is itself
an open design question, not a given.

**Data source / IPC.** The current widget's core invariant, from
`status.py`'s docstring, is "one data source, not two independently-fetched
views that can drift" — the CLI writes `snapshot.json`, the widget polls it,
nothing recomputes status independently. A native app in the same process
model could preserve this exactly: poll the same `snapshot.json` file from
Rust instead of from `fetch()` in a browser context, with no change to
`status.py` or the write side at all. That is the option that changes the
least. The alternative — some other IPC mechanism (a local socket, named pipe,
or an embedded HTTP client hitting `serve.py` instead of reading the file
directly) — would only become necessary if a native app needed push updates
instead of poll, or needed to run detached from a filesystem-shared
environment (e.g., a sandboxed container). Nothing in the current
architecture forces that; polling the same file is the lower-risk option and
is the one that keeps the single-data-source invariant intact by construction
rather than by discipline. Any design that introduces a second read path —
native app parses events directly, widget parses snapshot.json — would
recreate exactly the drift risk the current architecture was built to avoid,
and should be treated as a regression against that invariant, not a neutral
implementation choice.

**Scope, relative to today's ~150-line single file.** `index.html` is 224
lines today (JS + HTML + CSS in one file, no dependencies, no build). Closing
the Fluent gap alone (§2 above) — tabs, chrome interactivity, a swimlane
renderer, a log feed, a fleet view with a gauge — is itself a meaningful
addition in HTML/JS, probably several hundred more lines, but stays inside
the same zero-build-step file. A Rust-native rewrite is a different order of
scope entirely: a GUI framework dependency tree, a build/release pipeline,
platform-specific packaging (Windows-only today, per the Fluent/Win11 direction
— but "native" implicitly raises the question of whether macOS/Linux support
is ever wanted), and ongoing maintenance of compiled-binary distribution
instead of "the file is the artifact." Nothing here estimates a line count
for the Rust side, because the real cost driver is not lines of code but the
new categories of work (build pipeline, packaging, update distribution) that
do not exist in the current model at all.

## 4. Open questions for the operator

- Does closing the Fluent-prototype visual gap (§2) happen incrementally in
  the current HTML/JS widget — lower cost, keeps momentum, no new toolchain —
  independently of any native-app decision? Nothing in §2 requires Rust or
  any native framework; all nine gaps are CSS/JS additions to the existing
  single file.

- Is the native-app question (Rust or otherwise) worth its own dedicated
  brainstorming session before any code gets written, given it's a toolchain
  and distribution decision, not a visual one — separate in kind from closing
  the Fluent gap?

- What would have to be true — usage pattern (is this widget used often
  enough, by enough people, to justify install/update friction?), distribution
  need (does it need to run without Python installed, or outside this
  machine, or packaged for other operators?), or some other requirement not
  yet named — for a native rewrite to pay for itself over the current
  zero-build-step static file plus stdlib-only server?

- If a native app is ever built, should it keep polling `snapshot.json`
  (preserves the one-data-source invariant with the least change) or is there
  a concrete reason (not identified in this research) to want push-based
  updates or a different IPC mechanism instead?

- Is Tauri (or an equivalent web-view-embedding framework) worth evaluating
  first, since it could reuse most of the existing/closed-gap HTML instead of
  a ground-up native rewrite — narrowing this from "two projects" to "one
  project plus a shell"? This document does not evaluate that option in
  depth; it is flagged here as a question worth asking before assuming
  "Rust-native" means "rewrite from scratch."
