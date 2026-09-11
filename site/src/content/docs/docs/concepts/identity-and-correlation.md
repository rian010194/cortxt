---
title: Identity and correlation
description: Cortxt's identity namespaces — how they are kept distinct, and which identifiers the documented model does not define.
---

This page is documentation, not research and not a decision. It describes the
**documented conceptual model**, not a verified implementation: where a
namespace below is contractual, the table says so. Where this page and the
repository disagree, the repository wins.

## Why namespaces must stay separate

Identity in Cortxt spans layers with different lifetimes and different owners:
the durable unit of work, one attempt at it, the approved configuration that
attempt was launched under, the session a driving agent speaks over, and
identifiers minted inside an external runtime. Correlating records across those
layers is what makes evidence checkable. Conflating them destroys precisely
that: two identifiers that look alike but are minted by different owners cannot
be compared or converted, and a record joined on the wrong one proves nothing.

## Namespaces

| Identifier | Owner and scope | Status |
| --- | --- | --- |
| Workstream | The operator-visible unit of work, normally correlated to one GitHub issue | Controlled term in `CONTEXT.md`; no separate `workstream_id` is defined |
| `issue_id` | Stable GitHub owner/repository/issue reference | Contractual (dispatch contract) |
| `run_id` | One attempt to advance a Workstream; generated outside the model; a retry mints a new one | Contractual (dispatch contract) |
| Claim | One active claim per `issue_id` and workflow attempt | Contractual (dispatch contract) |
| `request_id` | The approved execution configuration, as a server-derived digest of the immutable request snapshot | Contractual (dispatch contract); extended by ADR-046 |
| Request digest | The content-bound identifier of the approved configuration in its immutable revision | ADR-046 (Accepted) |
| Child run identifier | A runtime-created child task carries the same `issue_id` and parent `run_id`, plus its own child run identifier | Contractual (dispatch contract) |
| ACP session ID (`sessionId`) | The platform's session identity for ACP-speaking agents; owned by Cortxt and created via `session/new` | ADR-047 (Accepted) |
| Engine-native `session_id` | Opaque above the adapter boundary; applies only inside non-ACP adapters | ADR-028, amended by ADR-047 |

The last two rows are the sharpest boundary in the model. The ACP `sessionId`
and the engine-native `session_id` **occupy separate namespaces that never
meet**. They are never compared and never converted.

## Identifiers this model does not define

The following appear in general discussion of agent systems, but none is
established as part of Cortxt's identity model in any public authority this
page can cite:

- MCP request and task identifiers;
- A2A context, task, message and artifact identifiers;
- worker process identifiers;
- execution identifiers.

Some of these belong to external protocols; others belong to a runtime's
internal bookkeeping. This page does not invent a meaning for them. If a future
Accepted ADR adopts one of them into Cortxt's identity model, this page changes
with it.
