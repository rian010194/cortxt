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
    -> loads a versioned vertical package     (not yet implemented: no
                                                runtime code reads
                                                vertical.yaml; see below)
Vertical package
    -> operates on one isolated run workspace
Evaluation harness
    -> returns evidence and a verdict to the control plane
```

Dependencies must not point in the opposite direction. A vertical cannot
start dispatchers, configure containers, access control-plane credentials, or
define the platform-wide approval model.

> Vertical-package loading is spec-only today: `package_version`,
> `contract_version`, and `supported_workflows` are read only by a test
> (`tests/runtime/test_vertical_02_fixture.py`); CodingLoop receives
> fixture_dir/schema/prompt paths directly (`coding_loop_cli.py`).

## Runtime responsibilities

The runtime harness owns:

- sandbox and container policy;
- writable-mount scope and tool permissions;
- model/provider routing supplied by platform policy (the gate is real —
  `inference.provider_policy` per ADR-016; note the run-level
  `provider_evidence` is currently a hardcoded default,
  `{"approved": True, "provider_id": "inferx"}`, in `coding_loop_cli.py`,
  not supplied per approved run);
- timeouts, retries, concurrency, and cancellation — timeouts and
  cancellation are implemented; bounded retries default to
  `max_attempts_total=1` (`text_inference_port.py`); parallel concurrency
  is NOT yet implemented (Coordinator.run_m1 waits sequentially,
  `supervisor/coordinator.py`);
- runtime credential injection without persistence;
- artifact, log, usage, and cost capture;
- deterministic cleanup and run-state reporting.

The runtime harness does not own domain instructions, regulatory conclusions,
customer-specific rules, or vertical output schemas.

## Evaluation responsibilities

The evaluation harness owns reusable assertions, graders, comparison logic,
and reports. A vertical may supply domain-specific fixtures and expected
properties, but the generic runner and report format remain platform-owned.
The generic runner exists (`harness/eval/runner.py`); the report format is
not yet implemented — eval results are dataclasses consumed only by pytest
exit-criterion tests, and nothing outside `harness/` imports it.

Evaluations must distinguish:

- structural assertions — implemented (`harness/eval/citation_match.py`,
  `selfhosted_task_class.py`);
- model-assisted grading — pending (no model-assisted grader exists);
- human approval — the dispatch-contract operator gate
  (`docs/architecture/dispatch-contract.md`), not yet a hook in the eval
  harness.

## Run workspace

Each run receives one explicitly approved workspace containing only that
case's inputs, intermediate files, and outputs. It is runtime data, not
reusable platform code.

- Real customer or municipal documents must not be committed.
- A workspace must not expose a user's home directory or the Docker socket.
- The harness must record the exact writable scope before execution.
  (Currently the scope is computed and enforced — `coding_loop.py`,
  `write_policy.py` — and appears inside the inference-request payload, but
  no explicit pre-execution event records it; the session event records only
  `file_count`, and the declared `artifact_policy.retention_class` is never
  read.)
- Cleanup and retained evidence must follow an explicit policy.

## Promotion path

Runtime candidates begin as experiments outside this repository. A candidate
may be promoted into the tracked runtime path only after its interfaces,
isolation, cleanup, observability, and failure behavior are stable. The
tracked destination today is `agent-platform/runtime/` (sandbox, ports,
coding/research loops, session state); the evaluation side is tracked at
`agent-platform/harness/eval/`. The Pi Builder experiment was archived out of
the repository on 2026-08-15 (commits 93a7a9e, 0b27e2f); no runtime candidate
is currently tracked as an experiment.

See also [Vertical package contract](vertical-package-contract.md).
