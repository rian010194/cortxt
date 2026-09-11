---
title: Concepts
description: The core vocabulary of Cortxt's control plane — Workstream, Run, Request, the request digest, the Evidence Gate, and identity correlation.
---

This page is documentation, not research and not a decision. It summarises
repository authority — [`CONTEXT.md`](https://github.com/rian010194/cortxt/blob/main/CONTEXT.md)
for the controlled vocabulary, and the
[dispatch contract](https://github.com/rian010194/cortxt/blob/main/docs/architecture/dispatch-contract.md)
for identity and evidence. Where this page and the repository disagree, the
repository wins.

Cortxt is a control plane for long-running AI work under human mandate. It
keeps durable authority — scope, identity, evidence and approval — separate
from replaceable execution, so that a runtime, provider or engine can be
replaced without moving what the work is or what it was allowed to do. The
short form of that principle is: keep the Workstream, replace the Run.

That separation rests on a small set of concepts. A **Workstream** is the
durable unit of work. A **Run** is one attempt to advance it. A **Request** is
the approved execution configuration a Run is launched under, and a **request
digest** binds an operator's confirmation to that configuration's content
rather than to a name that would survive a change to what it identifies. The
**Evidence Gate** decides whether a claimed result is verifiable before it
reaches a human decision. **Identity and correlation** keep the identifiers
from these layers distinct, so that records can be joined without being
confused.

- [Workstreams, runs and requests](/docs/concepts/workstreams-runs-requests/)
- [Request digests](/docs/concepts/request-digests/)
- [Evidence Gate](/docs/concepts/evidence-gate/)
- [Identity and correlation](/docs/concepts/identity-and-correlation/)

This collection describes the **documented conceptual model**. Each page states
on its own face what is contractual and what is not, and none of them claims
that every part of the model is implemented today.
