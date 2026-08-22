---
title: Dispatch contract
description: Observable identity, lifecycle, evidence, and state for every execution path.
---

The dispatch contract keeps GitHub task state independent from the worker runtime. [Read the authoritative source](https://github.com/rian010194/cortxt/blob/main/docs/architecture/dispatch-contract.md).

## Request requirements

Every approved dispatch defines a stable issue reference, workflow, worker role, immutable scope, acceptance criteria, runtime and cost limits, parallelism and delegation limits, artifact policy, and approval evidence.

Secrets, customer content, prompts, and model reasoning do not belong in the request or GitHub evidence.

## Claim and run identity

Before execution, the dispatcher establishes one active claim, a unique externally generated `run_id`, the selected runtime and worker profile, a lease or timeout, and the transition to `workflow:in-progress`.

An adapter must support querying the run for status, timing, heartbeat, and terminal result. Child work preserves the parent issue and run correlation.

## Terminal result envelope

A terminal result reports:

- exact `issue_id` and `run_id` correlation;
- terminal status, runtime, worker role, and timestamps;
- provider and model identity;
- usage and cost with confidence, never a silent zero;
- content-free artifact references and evidence;
- a structured error and recovery suggestion when unsuccessful.

## State transitions

```text
Ready -> In progress -> Review -> Done
                    \-> Blocked
```

Only independent review plus human approval moves work to Done. A retry receives a new `run_id` and never overwrites earlier evidence.
