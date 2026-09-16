# ADR-049: The ACP session identity is issued by the agent, not by Cortxt

**Status:** Proposal
**Date:** 2026-09-16
**Deciders:** Rikard (operator), Claude (draft)
**Amends:** ADR-047 §D4 (the decision text, not the decision's direction)
**Technical Story:** No originating issue. Written because the F0 probe recorded in
`docs/findings/2026-09-16-acp-client-probe-f0.md` observed behaviour that contradicts ADR-047's
own §D4 text.

## Context

ADR-047 is Accepted and adopts the Agent Client Protocol as a client (D1). Its §D4 fixes where
each session identifier lives, and states:

> 1. **The ACP `sessionId` is owned by Cortxt**, created via `session/new`. It is the
>    platform's session identity for ACP-speaking agents.

That sentence is wrong about the protocol.

ADR-047's own decision packet already recorded the correction, nine days before this ADR, in its
primary-source review table:

> sessionId issuer — **CORRECTED in D4** (agent issues the ACP sessionId in response to
> `session/new`)

The two documents have therefore disagreed since 2026-09-11: the packet says the agent issues the
identifier, the ADR text says Cortxt owns and creates it. An accepted ADR outranks a local
decision packet, so the wrong sentence has been the governing text.

### What was observed

The F0 probe (2026-09-16) drove `hermes acp` 0.18.2 from Python with
`agent-client-protocol` 0.9.0, protocol version 1, on Windows. Two independent findings:

**From the schema.** `acp.NewSessionRequest` declares exactly `field_meta`, `cwd`, `mcp_servers`
— there is no session identifier a client could supply. `acp.NewSessionResponse` declares
`session_id`. A client cannot create the identity because the request has nowhere to put it.

**From two live runs.** Sessions `e457a85f-a827-45e0-8c03-bc3df7d79a4d` and
`d0298f9d-45cc-4a7e-aaba-beffdd5d6eda` were both returned by the agent in response to
`session/new`. The second was then loaded by a *different process* after the first had exited,
and the conversation resumed correctly.

## Decision

### D1 — ADR-047 §D4 point 1 is superseded

The ACP `sessionId` is **issued by the agent** in response to `session/new`. Cortxt **holds and
correlates** it; Cortxt does not create it and must not attempt to.

The rest of ADR-047 §D4 is unchanged and remains Accepted:

- the engine-native `session_id` remains ADR-028's and remains opaque above the adapter boundary,
  applying only inside non-ACP adapters;
- the two identifiers never meet: neither is derived from, compared to, or substituted for the
  other, and the boundary is the adapter.

Only the claim of *ownership and creation* changes. The claim of *separation* was always correct
and is reaffirmed.

### D2 — Cortxt correlates the agent's identity to its own durable identities

Because Cortxt does not issue the ACP identifier, the binding between an ACP session and a
Cortxt Workstream, Run or work record is a **recorded correlation**, not a shared key. Cortxt
stores the agent-issued `sessionId` against its own identity and never treats it as a
platform-issued identifier.

This follows the boundary the #561 decision packet already drew: ACP standardises the interactive
session and standardises nothing about Run, Request or Workstream identity, the Evidence Gate,
mandate controls, the request digest, claim ownership, or role-based approval. Cortxt owns all of
those.

### D3 — Resume delivers replayed history, and the surface must say so

`load_session` re-emits the prior conversation as ordinary session notifications —
`UserMessageChunk`, `AgentMessageChunk`, and `ToolCallStart` among them — before the next turn
begins. Observed in the probe: an entire earlier exchange arrived at one timestamp on resume.

Any Cortxt surface that consumes session updates **must distinguish replayed history from live
updates**. Rendering a replay as live makes a resumed conversation look like the agent answering
everything again, which is a false statement about what the agent just did.

ADR-047 does not mention this because no implementation existed when it was written. It is
recorded here because it constrains the dialogue surface, not merely the adapter.

### D4 — No adapter is built on the superseded text

An `AcpAdapter` must not be written against ADR-047 §D4 point 1 as it currently stands. Session
resume is designed around which side owns the identifier; building on the wrong owner produces a
resume path that cannot work and a correlation model that has to be unpicked later.

## Consequences

**Positive.** The governing text matches the protocol and the observed behaviour. The correlation
model is stated once, in the place that decides it. The replay constraint is recorded before a
surface is built against it rather than discovered by a user seeing duplicated answers.

**Negative.** ADR-047 now requires two documents to read correctly: itself and this one. That is
the cost of the repository's rule that an accepted decision is superseded rather than edited, and
the rule is worth the cost — a silently corrected ADR is indistinguishable from one that was
always right.

**Neutral.** Nothing in ADR-026, ADR-027 or ADR-028 changes. ADR-047's D1, D2, D3, D5 and D6 are
untouched, as is its D7.

## Alternatives considered

**Edit ADR-047 §D4 in place.** Rejected. `CONTRIBUTING.md` and the ADR pattern make an accepted
decision a register: it records what was decided when, and editing it destroys the record of
having been wrong. The decision packet's correction has been sitting unenforced for five days
precisely because it lived somewhere that could not supersede.

**Treat the decision packet as sufficient.** Rejected. It is explicitly labelled
"LOCAL decision packet … NOT Accepted, NOT an implementation mandate". A local packet cannot
overrule an accepted ADR, and leaving the conflict unresolved would put the choice in the hands
of whoever writes the adapter.

**Defer until the adapter is built.** Rejected. The adapter's session-resume design is the thing
the contradiction breaks, so deferring guarantees the cost is paid as rework.

## Verification

- `docs/findings/2026-09-16-acp-client-probe-f0.md` — probe environment, timeline, both session
  identifiers, and the schema field lists.
- Reproduce the schema claim without running an agent:
  `python -c "import acp; print(list(acp.NewSessionRequest.model_fields)); print(list(acp.NewSessionResponse.model_fields))"`

## Review trigger

Reconsider if the Agent Client Protocol introduces a client-issued session identity, or if Cortxt
takes up the agent role that ADR-047 D1 deferred — in the agent role Cortxt would be the issuer,
and D1 of this ADR would need restating for that direction.
