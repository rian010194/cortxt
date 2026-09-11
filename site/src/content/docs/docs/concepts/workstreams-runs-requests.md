---
title: Workstreams, runs and requests
description: The durable unit of work, one attempt to advance it, and the approved execution configuration that attempt is launched under.
---

This page is documentation, not research and not a decision. **Workstream** and
**Run** are controlled terms in
[`CONTEXT.md`](https://github.com/rian010194/cortxt/blob/main/CONTEXT.md);
**Request** is defined by the
[dispatch contract](https://github.com/rian010194/cortxt/blob/main/docs/architecture/dispatch-contract.md).
Where this page and the repository disagree, the repository wins.

## Workstream

A Workstream is the operator-visible unit of work, normally correlated to one
GitHub issue and one branch or worktree. It is the durable side of the model:
it holds the goal, the mandate and the history that outlive any single
execution attempt. A Workstream may exist without a Git workspace — for
research-only work there is nothing to check out, and that is a legitimate
shape rather than a degenerate one.

## Run

A Run is one attempt to advance a Workstream, identified by a durable
`run_id`. A retry creates a new Run and never overwrites earlier evidence, so
that the history of attempts stays readable instead of being rewritten. The
`run_id` is generated outside the model, and a claim is established before
model execution begins, so that what a Run is allowed to consume is fixed
before anything is spent. Runs are the replaceable side of the model.

## Request

A Request is the approved execution configuration for a Run. It states what the
Run is allowed to do — scope, worker role, acceptance criteria, runtime and
cost limits, artifact policy — and it carries the approval reference the
dispatch was authorized under, together with a server-derived `request_id`
digest of the immutable request snapshot.

Two boundaries are worth stating plainly:

- A Request is a **configuration, not an execution**. It says what may run
  under which limits. It does not report what happened; outcomes belong to the
  Run and to its evidence.
- **Request** is not a controlled term in `CONTEXT.md`. The dispatch contract
  defines it, and a later vocabulary revision may name it differently.

The operator confirms a Request. The dispatcher binds the claim to it.
