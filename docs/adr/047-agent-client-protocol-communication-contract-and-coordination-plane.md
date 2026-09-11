# ADR-047: The three ACPs — client protocol, communication contract, and coordination plane

**Status:** Accepted
**Date:** 2026-09-10
**Amended:** 2026-09-11 (v1/v2 pin closed; §D1 wording corrected to the two-distinct-protocol basis)
**Deciders:** Rikard (operator), Claude Code (draft)
**Technical Story:** No originating issue. This ADR is written because ADR-026's and
ADR-027's own review triggers have fired ahead of their shared 2026-09-19 review date;
see Context §0.

## Context

### §0 — This ADR is written on triggers its predecessors set

ADR-026 named the condition under which its own decision must be reconsidered:

> Trigger: a third/fourth adapter (Deepseek, Codex, or Pi) is registered and reveals
> that the protocol is the wrong format (e.g. **needs streaming or multi-turn state
> the registry did not anticipate**)

`agent-platform/runtime/adapters/codex_adapter.py` exists. What it revealed is exactly the named
shape: streaming and multi-turn state the `EngineAdapter` protocol cannot carry.

ADR-027 named a second condition:

> Trigger: ... OR **a cross-process need arises** (the Supervisor Daemon is split
> across multiple processes) and §6.2's RPC bridge becomes relevant

That need has arisen, and §3 below documents that the current implementation does not
merely lack coordination — it silently destroys data when the need is met.

Both ADRs set `Review by: 2026-09-19`. This ADR is written nine days inside that
window, on the triggers themselves rather than on the calendar. It is a scheduled
reconsideration, not an unplanned reversal.

### §1 — One gap, visible at three levels

The workspace has an invocation contract (ADR-026), a broker to reach it through
(ADR-027), and a resume parameter on it (ADR-028). It has never had a **session**: a
bidirectional, framed, correlated channel in which "I need approval", "I am still
alive", and "I am finished, here is the result" are the same kind of message.

The absence is visible in three places that look like three problems and are one.

**Level 1 — client to agent.** `agent-platform/runtime/engine_adapter.py` defines the whole surface
between the platform and every engine:

```python
def invoke(self, profile, prompt, *, timeout_seconds, model=None,
           provider=None, cwd=None, session_id=None) -> dict
```

One direction, one turn. The adapter cannot say anything to its caller until it is
finished. On the client side the asymmetry is the same: `agent-platform/widget/serve.py` is by its own
docstring a static file server with "no custom endpoint or request-handling logic", and
the widget learns state by polling `snapshot.json` over it. The only write path is the
single `POST /api/action` route in `agent-platform/widget/action_host.py`, mounted solely behind the
explicit `--enable-actions` opt-in (ADR-038). A read half and a write half that do not
know about each other is not a protocol.

The operational consequence has a field designation. **F-6** — workers stall on
interactive input, undetected — is not a defect in any one adapter. An agent that wants
to ask a question has no channel to ask *in*, so it blocks until `timeout_seconds`
expires. The heartbeat field is inert for the same reason: there is no transport for it
to be alive in.

**Level 2 — the result channel is text on stdout.** `agent-platform/routing/worker_contract.py` solves
the right problem and says so: one producer, one version, the grammar stated once. But
the carrier it standardises is `CORTXT-OUTCOME:` on the last non-empty line of stdout.
The strictness this forces is documented at length in `agent-platform/routing/completion_report.py` —
six states, four of them terminally refusing, a no-upgrade invariant, an explicit
`is True` / `is False` / else-invalid ladder because the string `"false"` once read as
success. That module is correct and its reasoning is sound. It is also the cost of
defending a channel that has no frames.

`worker_contract.py`'s own docstring records that `daemon/loop.py` remains a fourth,
unmigrated producer of the same instruction, deferred to W15. Four producers of one
message is what the absence of a protocol looks like from the inside.

**Level 3 — no coordination plane.** `scripts/dispatcher.py` states its own boundary:

> this is a single-process dispatcher. max_parallel_workers (when configured) is
> enforced in-process (a lock + an active-claim count), not via a distributed
> compare-and-swap on GitHub. Two dispatcher processes racing the same repo is the
> concurrent-claim risk flagged in ADR-018 and is **out of scope** for this minimal
> adapter.

`scripts/parallel_dispatch.py` addresses a neighbouring problem by physical isolation —
one git worktree per builder, after the 2026-08-22 incident in which issues #252 and
#253 both wrote into main's working tree. Isolation is not coordination: it works until
two *processes* want the same non-file resource. The 8765/8793 port collision observed
on 2026-09-10 is the same absence in miniature — no component owns resource allocation.

### §2 — What ACP is, and what it is not

The Agent Client Protocol (agentclientprotocol.com) standardises communication between
editors/IDEs and coding agents. Verified 2026-09-10:

- **v1 is stable; v2 is in draft.**
- Transport for local agents is JSON-RPC over stdio (subprocess). Remote transport over
  HTTP/WebSocket is stated by the project to be **work in progress**.
- The message surface covers session lifecycle (new, load, resume, close), prompt flow,
  tool calls, **elicitation — structured user input**, cancellation, filesystem access,
  terminal execution, agent plans, and slash commands.
- SDKs exist for Python, Rust, TypeScript, Kotlin and Java.

Two properties of that list decide the shape of this ADR.

**Elicitation is F-6's missing half.** The stall is not a bug to be hunted per adapter;
it is a message type the platform never had. ACP has it as a first-class primitive with
a shipped implementation.

**ACP is client-to-agent only.** It says nothing about agent-to-agent coordination.
Level 3 therefore cannot be adopted from anywhere and must be designed here. The three
levels are one gap but they are not one decision: one is adopted, one is derived, one
is built.

### §3 — A defect found while writing this ADR

`RunRegistry` (`scripts/dispatcher.py:225`) reads the entire JSON store **once, in
`__init__`**, into an in-memory dict, and `_flush()` writes the whole dict back with
`Path.write_text`. There is no re-read, no file lock, and no atomic replace.

The consequence is stronger than the docstring's "out of scope" implies. Two processes
do not merely fail to coordinate a claim: the second `_flush()` writes a snapshot taken
before the first process existed, and **runs are silently erased**. Loss of another
process's committed state is a different category of failure from a missed claim, and
the current comment does not describe it.

This is recorded here as the concrete evidence for Level 3, not as an incident report.
The field observation of 2026-09-10 — `dispatcher.in_progress` persisting across a
commit that should have cleared it — is consistent with this mechanism, but this ADR
does not claim to have root-caused that observation.

## Decision

### D1 — Cortxt adopts the Agent Client Protocol as an ACP **client**; the agent role is deferred

Cortxt OS drives ACP-speaking agents over the protocol instead of over per-adapter
subprocess conventions. Exposing Cortxt *as* an ACP agent — so that Zed or another
editor could drive it — is a named and intended direction that this ADR does **not**
decide. It is deferred, not rejected.

The ACP adopted here is **Agent Client Protocol** (`agentclientprotocol.com`):
the editor/IDE-to-coding-agent protocol transported over JSON-RPC over stdio for
local agents, with remote HTTP/WebSocket transport still work-in-progress. That
protocol has **no explicit v1/v2 split** — features stabilize per-RFD. It is the ACP
relevant to Cortxt's client role (HIGH relevance).

For clarity on the naming collision that previously existed: a separate, distinct
protocol — **Agent Communication Protocol** (IBM BeeAI, `i-am-bee/acp`,
agent-to-agent and agent-to-human over REST/HTTP + OpenAPI) — is **not** adopted.
Its repository is archived (`archived: true`, latest release v1.0.3) and its README
states "ACP is now part of A2A under the Linux Foundation". It has no v2 under active
development and is out of scope here (LOW relevance).

Consequently there is no "v2 draft" of the adopted protocol to wait on; the two
protocols were previously conflated under the single label "ACP" and the earlier
"v1 stable / v2 draft" framing was incorrect in both directions.

### D2 — `AcpAdapter` implements `EngineAdapter`; the registry is unchanged

A new `AcpAdapter` implements the existing `EngineAdapter` protocol and registers under
its own broker key exactly as `CodexAdapter` does (ADR-028 point 3). Consequently:

- `route()` and `agent-platform/routing/engine_manifest.py` remain untouched. ADR-026's central
  promise — that RLM/Geometric Reasoning is the only intended successor to `route()`'s
  role — is unaffected by this ADR.
- ADR-027's broker and its v1 single-provider passthrough policy are unchanged.
- `agent-platform/runtime/adapters/*` is retained in full for engines that do not speak ACP. This ADR
  deprecates no adapter.

### D3 — `invoke()` gains a second direction, additively and without silent degradation

`EngineAdapter.invoke()` gains one keyword-only parameter, `on_event`, carrying a
callback for session updates. Omitting it — every call site today — behaves identically
to the current signature. This is deliberately the same strictly-additive form ADR-028
used for `session_id`.

The protocol also gains a declared capability, `supports_events: bool`. An adapter that
cannot stream declares so, and a caller that passes `on_event` to such an adapter
receives **an error, never silence**. Silent no-op is rejected explicitly, on the rule
`completion_report.py` already states for itself:

> A route that asked a question and got no answer has not received a yes.

### D4 — Session identity: two namespaces, one boundary, never mixed

ADR-028 point 1 established that the engine-native `session_id` is opaque above the
adapter boundary — a Codex UUID and a Hermes session id are never compared or converted.
ACP has its own `sessionId`, created by the client. Both exist; this ADR fixes where
each lives:

1. **The ACP `sessionId` is owned by Cortxt**, created via `session/new`. It is the
   platform's session identity for ACP-speaking agents.
2. **The engine-native `session_id` remains opaque and remains ADR-028's**, but applies
   only *inside non-ACP adapters*. For an ACP agent there is one session, the ACP one.
3. **The two identifiers never meet.** Neither is derived from, compared to, or
   substituted for the other. The boundary is the adapter, as it already was.

### D5 — `CORTXT-OUTCOME:` is retained, and demoted to the non-ACP path

The attestation channel is **not** retired. It is formally redesignated as the result
carrier for workers that do not speak ACP — Hermes, dsh, and Copilot among them — and
remains correct for them. `worker_contract.py`'s `CONTRACT_VERSION`, `ATTESTATION_PREFIX`
and `ATTESTABLE` are unchanged.

For ACP-speaking agents the result arrives as structured session messages, and no
last-line parsing occurs.

### D6 — `completion_report.py`'s six states are retained unchanged, for both paths

ACP supplies transport. It does not supply judgement. The six-state classification, the
four terminally-refusing states, the no-upgrade invariant and the `_correlated` check
continue to decide what the platform verified about a Run, whether the Run's transport
was ACP or stdout.

This is stated as a decision because the opposite is the tempting error: a better
channel is not evidence, and the strictness in that module was bought with four
confirmed defects. It is not refunded here.

### D7 — Level 3 decides ownership, not policy

A cross-process claim/lease owner exists, and `RunRegistry`'s read-once/write-all store
is replaced by an atomic compare-and-swap:

- Writes go through a temporary file plus `os.replace`, which is atomic on both Windows
  and POSIX. The platform's primary development host is Windows 11; a POSIX-only locking
  scheme is not acceptable.
- The store carries a version field. A writer whose version is stale **fails loudly**
  and does not write. A lost race becomes a visible error rather than silent erasure of
  another process's runs.

**No scheduling policy is written.** No priority, no per-engine quota, no preemption, no
fairness, no budget coupling. This is deliberately the same form ADR-027 chose for
itself — "v1 builds only the broker's skeleton, not its policy layer" — and for the same
reason ADR-022's Alternatives section gave: policy for load that has not been measured
is speculative construction.

### D8 — Amendments to ADR-026, ADR-027 and ADR-028

None of the three is superseded. Each decision in them stands; what changes is stated
per ADR.

**ADR-026** is amended: `EngineAdapter` gains a second direction (D3) and a declared
streaming capability. Its separation of selection from invocation, its non-touching of
`route()`, and the `HermesAdapter` repackaging all stand.

**ADR-027** is amended in one point. Point 4 — "Cross-process invocation (the RPC
bridge in §6.2) is explicitly not part of this decision... no known need today" — is
answered rather than contradicted: the need it anticipated has arrived, and D7 decides
ownership while explicitly still declining the policy layer that point 4's surrounding
paragraphs also declined. The broker pattern, the single-provider v1 passthrough, and
the deferral of multi-provider policy stand unchanged.

**ADR-028** is amended: D4 places its opaque engine-native `session_id` inside the
non-ACP adapters and gives the ACP `sessionId` its own namespace. Points 1 through 6
stand; the `--engine` flag, `/engine` slash command, per-engine session tracking, and
the refusal to silently fall back on a stale resume are all unaffected.

Each of the three receives an `amended by ADR-047` marker in its `Status` line and
nothing else. Their bodies are not edited: a register records why a choice was made at
one moment and is not rewritten when a later moment chooses differently. The status
line is a pointer, not content — the same treatment ADR-026 already carries from its
2026-08-19 amendment for ADR-027.

### Explicitly not decided here

- **Exposing Cortxt as an ACP agent** (D1). Deferred, not rejected.
- **ACP v2.** Draft status; adoption is a later decision on its own evidence.
- **Remote ACP transport** (HTTP/WebSocket). The upstream project calls it work in
  progress; local stdio is what is adopted.
- **Any scheduling policy** (D7).
- **Migrating `daemon/loop.py`'s fourth instruction producer.** Remains W15's scope;
  D5 changes which paths still need it, not the deferral.
- **Retiring any existing adapter.** None is deprecated by this ADR.

## Consequences

### Positive

- F-6 gains a mechanism rather than a workaround: `session/request_permission` and
  elicitation make a waiting agent a visible open request instead of a silent stall,
  and the inert heartbeat field gains a transport in `session/update`.
- Adding an ACP-speaking engine stops requiring an adapter at all — the protocol is the
  adapter. The per-engine subprocess conventions in `agent-platform/runtime/adapters/*` stop growing.
- Cortxt becomes interoperable with the ACP ecosystem as a consumer: any conforming
  agent is drivable by the widget without bespoke code.
- Level 3's atomic store converts a silent data-loss path into a loud failure, which is
  the same direction `completion_report.py` already chose for ambiguous evidence.
- The strictness already paid for in `completion_report.py` is preserved rather than
  rebuilt (D6).

### Negative

- An external dependency on a protocol Cortxt does not control is introduced, at v1,
  while v2 is already in draft. Version drift is now a maintenance obligation.
- Two session namespaces exist (D4). The discipline that keeps them apart is stated in
  prose and must be enforced by test, or it will be violated by someone reaching for the
  "other" id when one is inconvenient.
- Two result paths exist (D5). A worker that speaks ACP and a worker that does not are
  classified through different transports into the same six states, and the equivalence
  of those two paths must be asserted, not assumed.
- More code exists than before: `AcpAdapter`, the capability declaration, and the
  compare-and-swap store are all new surface for a platform whose adapters currently
  work.

### Risks

- **Half-adoption.** Adopting ACP's framing while quietly keeping stdout parsing "just
  in case" for agents that do speak ACP would produce a channel that is neither
  compatible nor simple. D5's boundary is what prevents this and must be enforced
  literally: for an ACP agent, no last-line parsing occurs.
- **The capability flag becoming decorative.** If `supports_events` is declared `True`
  by an adapter that emits no events, D3's error path never fires and the guarantee is
  hollow. The declaration must be asserted against observed behaviour, not trusted.
- **Policy creep into D7.** The coordination plane is the most natural place in this
  design for speculative generality to accumulate — exactly the trap ADR-026's own Risks
  section named for the registry. Ownership without policy must survive review pressure.
- **The deferred agent role hardening by accident.** Building the client half without
  regard for symmetry can make the later agent role expensive. This is accepted, not
  mitigated, and is named so the cost is visible when it is paid.

## Alternatives Considered

1. **Define a proprietary Cortxt session protocol** — rejected: it would require
   building streaming, permission flow and elicitation from scratch, and an adapter
   against every engine that already speaks something else, in exchange for control
   over a surface that has an interoperable standard with a Python SDK.
2. **Adopt ACP's wire format but keep Cortxt-specific semantics** — rejected as the
   worst of both: neither compatible with the ecosystem nor simpler than a proprietary
   design, and dependent on a boundary that is easy to state and hard to hold.
3. **Supersede ADR-026/027/028 with this ADR as the single source** — rejected: those
   decisions are not wrong, and superseding them would discard the reasoning that
   records why `route()` was never touched. Amendment preserves the record.
4. **Three separate ADRs, one per level** — rejected at the operator's direction. The
   three levels share one cause and one set of triggers; splitting them would require
   each to re-derive the same context, and the relationship between the levels — one
   adopted, one derived, one built — is itself part of the decision.
5. **Fix `RunRegistry` as an isolated bug and scope this ADR to levels 1 and 2** —
   rejected: ADR-027's cross-process trigger has fired, and leaving it unanswered would
   leave a future reader with a trigger that went off and produced no record.
6. **Decide the full coordination policy now** — rejected: see D7 and ADR-022's
   Alternatives section on routing policy for load that has not been measured.

## Validation

- [ ] `AcpAdapter` implements `EngineAdapter` and registers through the existing
      `EngineContext`/`EngineBroker` without changes to either
- [ ] `route()` and `agent-platform/routing/engine_manifest.py` show zero diff
- [ ] `invoke()` without `on_event` is behaviourally identical to the pre-amendment
      signature, asserted for every existing adapter
- [ ] Passing `on_event` to an adapter declaring `supports_events = False` raises,
      and the raise is asserted by test — not merely documented
- [ ] An adapter declaring `supports_events = True` is asserted to actually emit
      events, so the declaration cannot be decorative
- [ ] ACP `sessionId` and engine-native `session_id` never cross the adapter boundary,
      asserted by test rather than by comment
- [ ] An ACP-speaking agent's Run is classified into `completion_report`'s six states
      with no `CORTXT-OUTCOME:` parsing on that path
- [ ] A non-ACP worker's Run reaches the same six states through the retained
      attestation channel, and the two paths' classifications are asserted equivalent
- [ ] Two concurrent processes writing `RunRegistry` produce one success and one loud
      failure — never a lost run; asserted by test, on Windows and POSIX
- [ ] ADR-026, ADR-027 and ADR-028 carry an `amended by ADR-047` status marker and
      have no other edit (diff shows the status line only)

## Expiry/Review Trigger

- Review by: 2027-03-10
- Trigger: **ACP v2 leaves draft** and its changes reach the surface adopted here, OR
  the **agent role deferred in D1 is actually needed** (an external editor is asked to
  drive Cortxt) and the client-only build proves to have foreclosed it, OR **measured
  concurrency load** makes D7's declined scheduling policy necessary — at which point
  the policy layer is written against that measurement, not against expectation, OR the
  **two-namespace discipline in D4 is violated in practice**, which would show that one
  session identity should have been chosen over two, OR **remote ACP transport** leaves
  work-in-progress status and makes the local-stdio-only scope of D1 too narrow.
