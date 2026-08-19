# Tracks 2, 3, 5: Scoping Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the three scoping/research documents the swarm design's backlog calls for on agent-memory (Track 2), ADR-023's external surface (Track 3), and the widget/Rust future (Track 5) — no code in any of the three, per the spec's explicit deferral of all three to document level this round.

**Architecture:** Three independent writing tasks, each producing one document plus (Track 3 only) one ADR draft. No shared code, no shared file — genuinely independent, can run in any order or in parallel. This plan intentionally has no TDD steps: writing-plans' bite-sized/TDD apparatus is for code; a document task's "test" is operator review, which is the explicit last step of each task below.

**Tech Stack:** Markdown, following this repo's existing `docs/adr/` and `docs/superpowers/specs/` conventions.

**Spec:** `docs/superpowers/specs/2026-08-19-v02-swarm-orchestration-model-design.md`

## Global Constraints

- None of these three tasks produce code. If, during research, a task turns up something clearly buildable in isolation, it goes into the findings doc as a recommendation for a *future* plan — it is not built here (this round's backlog table explicitly excludes code for these three tracks).
- Each document ends with an explicit "Open questions for the operator" section — these are scoping documents whose purpose is to inform a future decision, not to make it.

---

### Task 1 (Track 2): Agent-memory scoping document

**Files:**
- Create: `docs/superpowers/specs/2026-08-19-track2-agent-memory-scoping.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-18-v02-vision-admin-surface-and-distribution-design.md` §6 (the prior session's flagged gap — README promises "memory," `runtime/session_state.py` is an audit log, not searchable/consolidated memory).
- Produces: nothing consumed by other tasks in this plan. A future track (not scoped here) would consume this document's recommendation if the operator approves scoping agent-memory as a real phase.

- [ ] **Step 1: Read the flagged gap in full**

Read `docs/superpowers/specs/2026-08-18-v02-vision-admin-surface-and-distribution-design.md` §6 completely (not just the summary in the handoff) to capture the exact wording of the README's "memory" claim and how it was compared against `runtime/session_state.py`'s actual behavior.

- [ ] **Step 2: Read `runtime/session_state.py` end to end**

Confirm precisely what it does today: an event-sourced, hash-chained append log per session, keyed by `task_id`, with no cross-session search, no consolidation, no retrieval by content — only `load`/`append`/`create` by `session_id`. Write a one-paragraph, evidence-based (line-numbered) summary of this in the new document — no paraphrasing from memory of what it "probably" does.

- [ ] **Step 3: Research the comparison point named in the handoff**

The prior session compared this gap against Hindsight (hindsight.vectorize.io), a specialized agent-memory product, and reached a "bidirectional strategy" conclusion formalized in ADR-023. Read ADR-023 in full (`docs/adr/` — find the exact filename via `Get-ChildItem docs/adr/ -Filter "*023*"` or equivalent) to avoid re-deriving a conclusion the repo already reached; this document should build on ADR-023, not duplicate or contradict it without a stated reason.

- [ ] **Step 4: Draft what "memory" would need to mean**

Write a section proposing 2-3 concrete candidate definitions for what "agent-memory" could mean in Cortxt specifically (e.g.: (a) full-text/semantic search over existing session_state event logs, no new storage; (b) a separate consolidated-memory store fed by session events, closer to Hindsight's model; (c) narrower — just cross-session task_id lookup, no content search). For each, note roughly what it would touch (which existing modules) and what it would NOT touch, without designing the implementation — this is scoping, not a spec.

- [ ] **Step 5: Write the "Open questions for the operator" section**

At minimum: which candidate definition (if any) matches the actual intent behind the README's claim; whether this becomes its own wayfinder-style phase sequence or stays folded into a future session's brainstorming; whether the README's current wording should be corrected now (a small, independent, low-risk doc fix) regardless of when/whether the larger memory work happens.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-08-19-track2-agent-memory-scoping.md
git commit -m "docs(spec): agent-memory scoping document (Track 2)"
```

---

### Task 2 (Track 3): ADR-023 external surface spike + ADR draft

**Files:**
- Create: `docs/superpowers/specs/2026-08-19-track3-external-surface-spike.md`
- Create: `docs/adr/024-external-integration-surface-form.md` (opens as Proposed, matching ADR-022/023's own pattern; this session's explicit full-autonomy grant — spec's "Session authorization" section — covers flipping it to Accepted without a synchronous operator round-trip, unlike the standing rule this grant supersedes for the session's duration. State that provenance in the ADR's own header so a future reader isn't confused about why this one was self-accepted.)

**Interfaces:**
- Consumes: ADR-023 (Accepted, prior session) — its "bottom-up-consumable externally" direction is decided; this task chooses a concrete *form* for it (SDK/MCP/REST), which ADR-023 explicitly left open.
- Produces: an ADR the operator can accept or reject; if accepted, its concrete form becomes input to a future implementation plan (not scoped here).

- [ ] **Step 1: Read ADR-023 and ADR-022 in full**

Confirm exactly what ADR-023 decided (direction: yes, bottom-up-consumable) versus what it explicitly deferred (form: SDK language? MCP server? REST?). Also re-read ADR-022 (`docs/adr/022-fas3-capability-manifest-and-engine-selection-criteria.md`) since the capability-manifest pattern it introduced is a plausible foundation for whichever form gets chosen (an external caller querying "what can this engine manifest do" maps naturally onto an MCP tool list or a REST capabilities endpoint).

- [ ] **Step 2: Write the spike doc comparing the three forms**

For each of SDK (name the target language(s) — don't assume Python-only without checking whether the operator's own coding agent or other consumers are polyglot), MCP server, and REST API: what it would mean concretely for Cortxt (e.g. an MCP server wrapping `routing/engine_manifest.py`'s `route()` and `cli/unified_cli.py`'s admin-surface commands as tools), rough implementation cost, and how well it fits the "control plane as a service" framing from ADR-023. Recommend one, with reasoning — this document should have a clear recommendation, not just a neutral comparison, per this project's own "propose approaches, lead with a recommendation" convention (see the brainstorming skill's guidance, which this session's own planning followed).

- [ ] **Step 3: Draft ADR-024**

Follow this repo's existing ADR template (read `docs/adr/023-*.md`'s structure and copy its section headings exactly — Context, Decision, Consequences, etc.). Context section links back to ADR-023 and this spike doc. Decision section states the recommended form from Step 2. Status: `Proposed`.

- [ ] **Step 4: Decide accept/reject under this session's autonomy grant**

The spec's "Session authorization" section explicitly extends this session's autonomy grant to ADR acceptance, superseding the standing "ADR accept is the operator's, never self-approved" rule for this session's duration only. Make the call based on Step 2's recommendation and reasoning, flip the status field to `Accepted` (with today's date) if the reasoning holds, and note in the ADR header that it was accepted under this session's explicit autonomy grant rather than a synchronous operator round-trip — so a future reader (including the operator, reviewing after the fact) can see exactly what authorized it. If Step 2's comparison didn't produce a clear enough recommendation to accept confidently, leave it `Proposed` and flag it in the end-of-session handoff instead of forcing a decision.

- [ ] **Step 5: Commit the spike doc and the ADR (whatever its status ends up being)**

```bash
git add docs/superpowers/specs/2026-08-19-track3-external-surface-spike.md docs/adr/024-external-integration-surface-form.md
git commit -m "docs(adr): ADR-024 external integration surface form (Track 3)"
```

---

### Task 3 (Track 5): Widget/Rust future research document

**Files:**
- Create: `docs/superpowers/specs/2026-08-19-track5-widget-rust-research.md`

**Interfaces:**
- Consumes: `prototype/widget-cli-v02` branch (operator-approved Fluent-design reference, not merged, not deleted per the handoff) and the current `agent-platform/widget/` implementation (`index.html`, `serve.py`).
- Produces: nothing consumed by other tasks in this plan — genuinely an open question staying open, per the backlog table.

- [ ] **Step 1: Diff the current widget against the approved prototype**

Run: `git log prototype/widget-cli-v02 --oneline -5` and `git diff main prototype/widget-cli-v02 -- agent-platform/widget/` (or the prototype's actual file paths if they differ — check with `git show prototype/widget-cli-v02 --stat` first) to get a concrete, current list of what the approved visual direction has that `agent-platform/widget/index.html` (as extended by Track 1's plan, if that's landed by the time this runs) does not.

- [ ] **Step 2: Write the gap section**

List the concrete visual/UX gaps found in Step 1 — not a redesign, just an inventory: what the prototype has that today's widget lacks.

- [ ] **Step 3: Research Rust-native prerequisites**

This is genuinely exploratory, not a recommendation to build in Rust — the handoff is explicit that this is "an open, undecided, larger scope item." Write a short, honest section on what a native (Rust or otherwise) rewrite of the widget would require: packaging/distribution story, whether it would still poll `snapshot.json` (keeping the "one data source, not two independently-fetched views" invariant `widget/index.html`'s docstring establishes) or need a different IPC mechanism, and rough scope relative to the current ~150-line single-file HTML widget.

- [ ] **Step 4: Write the "Open questions for the operator" section**

At minimum: does closing the Fluent-prototype visual gap happen incrementally in the current HTML/JS widget (lower cost, keeps momentum) independently of any native-app decision; is the native-app question worth its own dedicated brainstorming session before any code; what would have to be true (usage pattern, distribution need) for a native rewrite to pay for itself over the current zero-build-step static file.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-19-track5-widget-rust-research.md
git commit -m "docs(spec): widget/Rust future research (Track 5)"
```

---

## Self-review notes

- Spec coverage: Tracks 2, 3, 5 each get exactly the document-level deliverable the backlog table specifies — no code, per the spec's explicit "stays an open question" framing for all three.
- Placeholder scan: no TBD/TODO; every step names the actual files to read and the actual sections to write. This plan differs from Track 0/1's in having no code steps at all — that is a deliberate consequence of the spec's own backlog decomposition, not a planning gap.
- ADR-024's accept/reject decision in Task 2 Step 4 is made under this session's explicit autonomy grant (spec's Session Authorization section), not deferred to a synchronous operator round-trip — consistent with the spec, and with the ADR header recording that provenance so it's never mistaken for a normal self-approval outside this session's scope.
