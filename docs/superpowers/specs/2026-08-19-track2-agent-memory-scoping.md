# Track 2: Agent-memory scoping

**Status:** Scoping only — no decision, no implementation.
**Date:** 2026-08-19
**Author:** Claude Code (Task 1, Track 2, swarm-track235)
**Builds on:** ADR-023 (Accepted, 2026-08-19); §6 of
`docs/superpowers/specs/2026-08-18-v02-vision-admin-surface-and-distribution-design.md`
(the "agentminne" addition dated 2026-08-19, lines 305–366).

## 1. The gap, as flagged

The vision doc's §6, in the entry added 2026-08-19 (lines 305–330), records two
findings from an operator comparison against
[Hindsight](https://hindsight.vectorize.io/), a specialized agent-memory
product (Retain/Recall/Reflect: stores world-/experience-facts, searches with
four parallel strategies — temporal, semantic, keyword/BM25, graph — and
consolidates overlapping facts into evidence-tracked "observations").

Finding 1, the memory gap (vision doc lines 314–324, quoted in full):

> "Minnesluckan. Repots egen README-tagline ('Users own the work's state,
> **memory**, tools, evidence, and evolution') lovar ett minne som inte finns.
> `runtime/session_state.py` (Fas 2) är en append-only, hash-kedjad
> händelselogg per session — ett revisionsspår av vad som hände, inte ett
> sökbart minne. Ingen semantisk sökning, ingen konsolidering av fakta, ingen
> kontinuitet mellan sessioner. Fas 8:s `learning/`-modul
> (`promotion_gate.py`/`candidate.py`/`evidence.py`) är närmast besläktad men
> löser ett annat problem — den lär sig vilka routing-/skill-beslut som
> fungerar, inte fakta om användaren eller världen."

This is verified independently below (§2) — not restated on trust.

The README's tagline itself, confirmed at `README.md` lines 12–14: "Users own
the work's state, memory, tools, evidence, and evolution; models, inference
providers, and external agent engines remain replaceable resources behind
Cortxt-owned contracts." The word "memory" sits alongside "state," "tools,"
"evidence," and "evolution" as a thing the platform claims to give users
ownership of. Whatever else is true, "state" is arguably covered by
`session_state.py`; "memory" as a distinct noun next to it implies something
`session_state.py` does not provide (see §2).

The vision doc also flags a security implication (lines 325–330): a memory
layer has its own threat surface (memory poisoning, prompt injection via
stored facts, who may write to an agent's memory) distinct from the
credential broker's threat model (`docs/security/credential-broker-threat-model.md`,
Fas 1) — it would need its own threat-model document, not a reuse of the
existing one, if/when built. That scoping requirement is inherited here, not
re-argued.

## 2. What `session_state.py` actually does today

Read in full: `agent-platform/runtime/session_state.py` (137 lines).

The module exposes four public functions — `create(store, task_id)`,
`load(store, session_id)`, `append(store, session_id, expected_sequence,
event_type, payload)`, and `latest_sequence(session)` — plus internal
helpers for canonical JSON encoding, hash-chaining, and atomic file writes.
`create()` (lines 80–90) generates a new `session_id` (a UUID4 hex string
prefixed `session_`) and writes a single JSON document to
`{store}/{session_id}/session.json` containing one seed event,
`session.created`, whose payload holds the caller-supplied `task_id`
(line 87). `append()` (lines 124–132) loads the existing document, checks
an optimistic-concurrency `expected_sequence` against the current event
count, and appends one more event to the `events` array, each event
hash-chained to the previous one via `previous_hash`/`hash` (sha256 over a
canonical JSON encoding, lines 50–61, 93–109). `load()` (lines 112–121)
reads the file back and validates the entire hash chain (`_validate_chain`,
lines 93–109) before returning it — any tampering or corruption anywhere in
the chain raises `SessionError("integrity_error", ...)`.

Two points worth being precise about, since the task brief's own paraphrase
("keyed by `task_id`") is looser than the code: the on-disk key and the sole
lookup parameter for `load`/`append` is `session_id`, not `task_id`.
`task_id` only ever appears as a value inside the first event's payload
(line 87) — there is no index, directory listing, or lookup path from a
`task_id` back to the `session_id`(s) that reference it. Concretely, this
means: there is no function to find "all sessions for task X"; there is no
function to search event payloads by content, keyword, or similarity across
any session; there is no consolidation step that merges or summarizes events
either within or across sessions; and there is no concept of "current
knowledge" derived from the log — only the raw, ordered, tamper-evident event
sequence for one `session_id` at a time. This confirms the vision doc's
characterization: `session_state.py` is an audit log (integrity-focused,
append-only, per-session), not a memory system (retrieval-focused,
queryable, consolidated, cross-session) in any sense Hindsight, or common use
of the word "memory" for an agent, would recognize.

The nearest sibling in the codebase, `agent-platform/learning/` (files
`promotion_gate.py`, `candidate.py`, `evidence.py`, `active_policy.py`,
`registry.py`, `rollback.py`, `skill_candidate.py`, `tool_candidate.py`,
`policy_candidate.py`, `evaluator.py`, `submit.py`, `addon_review.py` —
listed, not individually read for this task), solves a different problem per
the vision doc's own characterization: it tracks which routing/skill
decisions perform well enough to be promoted, not facts about the user or the
world. This document treats that boundary as given, not re-derived.

## 3. What ADR-023 already decided (and what it did not)

Read in full: `docs/adr/023-bottom-up-and-top-down-integration-model.md`
(Accepted, 2026-08-19).

ADR-023's actual decision is about **integration direction**, not about
memory architecture specifically: Cortxt stays top-down internally
(control plane owns routing, mandate, audit over the engines it manages —
ADR-019, ADR-022 unchanged) while becoming *also* intentionally bottom-up
consumable externally — other frameworks (LangGraph/LangChain, CrewAI,
Vercel AI SDK) or other coding agents should eventually be able to call into
Cortxt's control plane as a service, the same way Hindsight itself is
consumed by Claude Code/Cursor/CrewAI today, except with Cortxt as the
service instead of the memory. The ADR explicitly scopes out the concrete
external-facing surface (SDK language, MCP server, REST API) as undecided,
deferring it to Fas 6's "installable package" question (§4.1 of the vision
doc) — see ADR-023 "Decision," third paragraph (lines 53–58).

Why this document builds on ADR-023 rather than re-deriving it: the Hindsight
comparison that produced ADR-023 is the same comparison that produced the
memory-gap finding in §1 above (they are the two things vision-doc §6's
2026-08-19 addition reports "falling out" of one operator discussion —
lines 312–313: "Två saker föll ut av jämförelsen"). ADR-023 answers *how
Cortxt relates to external consumers/frameworks in general* (its Alternative
2, rejected, was literally "rebuild Cortxt as a service others orchestrate" —
lines 95–98). It does not answer, and does not attempt to answer, *what
"agent-memory" should concretely mean inside Cortxt* — that question is out
of ADR-023's scope by its own "Decision" section ("Detta ADR beslutar
riktningen, inte ytan," line 53) and is not listed among its three
Validation checkpoints (lines 103–109), none of which mention memory,
session_state, or Hindsight's specific Retain/Recall/Reflect model.

What this document does inherit from ADR-023, as a constraint on the
candidate definitions in §4: whatever agent-memory design is eventually
scoped should be evaluated against the same question ADR-023 raises for any
future control-plane API — "does this work for an external consumer, not
just the internal CLI?" (ADR-023 Consequences/Positive, lines 68–70). A
memory design that only makes sense wired directly into Cortxt's own
orchestration loop, with no plausible bottom-up-consumable shape, would sit
awkwardly next to a just-adopted ADR that says the opposite pattern
(routing/credential-broker/addon-gate) is meant to stay orthogonal-not-
competing with external consumption. This document does not resolve that
tension — it flags it as a live constraint for whichever candidate the
operator picks in §5.

## 4. Candidate definitions for "agent-memory" in Cortxt

These are scoping candidates, not a recommendation and not a design. Each
notes roughly what it would touch and what it would explicitly not touch.
They are ordered from narrowest to broadest scope, not by preference.

### Candidate A — Cross-session `task_id` lookup only, no content search

**What it means:** Add an index (could be as simple as a flat JSON/SQLite
mapping, or a directory-naming convention) from `task_id` to the
`session_id`(s) whose `session.created` event carries that `task_id`. Given a
`task_id`, an operator or agent could enumerate and `load()` every prior
session for that task — but would still read raw event logs, not a summary
or searchable index of their content.

**Would touch:** A new small index/lookup module alongside
`session_state.py`; possibly a write-time hook in `create()` to register the
mapping. Would not require changing `session_state.py`'s existing on-disk
format or its hash-chain guarantees.

**Would NOT touch:** No semantic/full-text search, no consolidation, no new
storage engine, no embedding pipeline, no cross-`task_id` retrieval (e.g. "what
do we know about this user" spanning multiple unrelated tasks stays
unanswerable). This is the closest reading of the brief's narrowest option
and the smallest possible change — it makes the *existing* per-task
continuity gap answerable without making session_state a memory system in
any sense beyond "resumability across sessions of the same task."

### Candidate B — Full-text/semantic search over existing event logs, no new store of record

**What it means:** Keep `session_state.py`'s files as the sole store of
record (append-only, hash-chained, unchanged), but build a read-side index
over event payloads — full-text (e.g. simple inverted index) and/or semantic
(reusing the Voyage-embeddings path Fas 6 already introduces for capability-
manifest search, per vision-doc §6 lines 260–263) — so an agent or operator
can ask "what did we learn/decide about X" and get back matching events
across sessions, ranked, without a human manually re-reading logs.

**Would touch:** A new indexing/query module that reads `session_state.py`
output as its source of truth and rebuilds/updates a derived index (could
reuse the Voyage-embedding infrastructure Fas 6 is already building for a
different purpose — capability-manifest search). Read path only against
existing files; `session_state.py` itself stays unchanged.

**Would NOT touch:** No consolidation of overlapping/conflicting facts (a
search hit is a raw event, not a synthesized "observation" the way Hindsight
produces one) — two contradictory statements from different sessions would
both surface, with no reconciliation step. No separate memory-of-record; if
the index is lost or rebuilt, it derives entirely from the existing
session-state files, so it carries none of session_state's own integrity
guarantees as a *source* of truth, only as a *derived* view. This is a
middle option: closer to what the README's "memory" word plausibly implies
(you can find things again) without taking on Hindsight's full
retain/consolidate/reflect model.

### Candidate C — Separate consolidated-memory store, Hindsight-shaped

**What it means:** A genuinely new subsystem, fed by `session_state.py`
events (or written to directly by agents) as a source, that performs the
Retain/Recall/Reflect pattern the vision doc describes Hindsight as doing:
extracts and stores discrete facts, runs multiple retrieval strategies
(temporal, semantic, keyword, graph), and periodically consolidates
overlapping/superseded facts into evidence-tracked "observations" that are
themselves queryable and revisable. This is the definition closest to
literally matching Hindsight's own architecture and to what "memory" means
in most other agent frameworks that ship one.

**Would touch:** A new storage subsystem (schema, write path, retrieval
API) — the largest of the three candidates. Plausibly consumes
`session_state.py` events as one input source but is not merely a view over
them; it has its own store of record, its own consolidation logic, and its
own query surface. Per ADR-023's inherited constraint (§3 above), this
candidate is also the one most in need of an explicit answer to "would an
external consumer (LangGraph, Cursor, etc.) plausibly want to call into just
this, the way they call into Hindsight today, without adopting the rest of
Cortxt's control plane?" — because architecturally this is the piece that
most resembles what Hindsight itself is.

**Would NOT touch:** Does not require touching `session_state.py`'s
hash-chain/integrity guarantees, which are a different property (tamper-
evidence of what happened) than what a memory store optimizes for
(retrievability/consolidation of what's true). Explicitly requires — per the
vision doc's own flag (§1 above, lines 325–330) — a new, separate threat-
model document before any implementation; that threat-modeling work is not
in scope for this document either.

## 5. Open questions for the operator

1. **Which candidate (if any) matches the actual intent behind the README's
   "memory" claim?** The tagline was written before this gap was noticed: is
   "memory" there because a Hindsight-shaped subsystem (Candidate C) was
   always the intent and just hasn't been built yet, or was it written more
   loosely, in which case Candidate A or B might already satisfy the
   intended meaning at a fraction of the cost? This document cannot answer
   that from the repo alone — it is a claim about original intent, not
   present behavior.

2. **Does this become its own wayfinder-style phase sequence, or stay folded
   into a future session's brainstorming?** The three candidates differ
   enough in scope (Candidate A is a small addition; Candidate C is a new
   subsystem with its own threat model) that "how big a decision is this"
   is itself unresolved. If Candidate A or B is chosen, it may not warrant a
   dedicated phase at all. If Candidate C is chosen, it likely does, given
   the security-review requirement already flagged in the vision doc.

3. **Should the README's current wording be corrected now, independent of
   when/whether the larger memory work happens?** The tagline currently
   states a capability ("memory") as present tense fact. Softening or
   annotating that single word is a small, low-risk, independent doc fix
   that does not require resolving questions 1–2 first, and arguably
   should not wait on them — the gap between the doc and the code is real
   today regardless of which candidate (if any) eventually closes it.

4. *(Not asked by the brief, but surfaced by ADR-023's scope — worth
   flagging explicitly rather than silently assumed):* if Candidate C is
   ultimately chosen, should it be scoped from the start with the
   bottom-up-consumable question ADR-023 raises (§3 above) — i.e. designed
   so an external framework could plausibly call into it the way it calls
   into Hindsight — or is that premature for a first version, given ADR-023
   itself defers the external-facing surface question to Fas 6 and does not
   require every future subsystem to pre-answer it?

> **STATUS-AMENDMENT (2026-08-19, later same session):** ADR-024
> (`docs/adr/024-external-integration-surface-form.md`) has since chosen MCP
> as that form. This document's characterization of ADR-023 at the time of
> writing is unchanged; the question is no longer open.
