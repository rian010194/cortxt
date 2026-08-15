# Runtime and evaluation harness

## Purpose

The harness is the domain-neutral execution boundary between an approved task
in the control plane and a vertical package. It determines **how** work runs
safely and how evidence is captured; it must not decide **what** a domain
answer should contain.

## Dependency direction

```text
Control plane
    -> starts an approved run
Harness
    -> loads a versioned vertical package
Vertical package
    -> operates on one isolated run workspace
Evaluation harness
    -> returns evidence and a verdict to the control plane
```

Dependencies must not point in the opposite direction. A vertical cannot
start dispatchers, configure containers, access control-plane credentials, or
define the platform-wide approval model.

## Runtime responsibilities

The runtime harness owns:

- sandbox and container policy;
- writable-mount scope and tool permissions;
- model/provider routing supplied by platform policy;
- timeouts, retries, concurrency, and cancellation;
- runtime credential injection without persistence;
- artifact, log, usage, and cost capture;
- deterministic cleanup and run-state reporting.

The runtime harness does not own domain instructions, regulatory conclusions,
customer-specific rules, or vertical output schemas.

## Evaluation responsibilities

The evaluation harness owns reusable assertions, graders, comparison logic,
and reports. A vertical may supply domain-specific fixtures and expected
properties, but the generic runner and report format remain platform-owned.

Evaluations must distinguish:

- structural assertions that can be checked deterministically;
- model-assisted grading that is probabilistic and must identify its model;
- human approval, which remains a separate final gate where required.

## Run workspace

Each run receives one explicitly approved workspace containing only that
case's inputs, intermediate files, and outputs. It is runtime data, not
reusable platform code.

- Real customer or municipal documents must not be committed.
- A workspace must not expose a user's home directory or the Docker socket.
- The harness must record the exact writable scope before execution.
- Cleanup and retained evidence must follow an explicit policy.

## Promotion path

Runtime candidates begin as experiments outside this repository. A candidate
may be promoted into a tracked `harness/runtime/` path only after its
interfaces, isolation, cleanup, observability, and failure behavior are
stable. The Pi Builder remains an unpromoted experiment.

See also [Vertical package contract](vertical-package-contract.md).
