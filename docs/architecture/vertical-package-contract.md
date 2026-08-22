# Vertical package contract

## Purpose

A vertical package declares domain behavior that a generic harness can load.
It describes **what** should be done and evaluated without embedding the
dispatcher, container implementation, credentials, or global approval policy.

## Intended package shape

```text
verticals/<vertical-id>/
|-- vertical.yaml
|-- README.md
|-- workflows/
|-- schemas/
|-- instructions/
|-- evals/
|   `-- synthetic/
`-- templates/
```

Directories should be created only when the package has real content. A
package-local manifest schema exists for the first vertical
(`verticals/vertical-01-ai-act/schemas/vertical-manifest.schema.json`,
v0.1.0) but it is vertical-specific (`const: vertical-01-ai-act`),
nothing validates against it, and no generic vertical manifest schema is
tracked in `contracts/` yet.

## A vertical may declare

- a stable vertical identifier and package version;
- supported workflows and their domain inputs and outputs;
- domain instructions and reusable templates;
- required capabilities, such as document reading or structured output;
- domain-specific schemas and deterministic assertions;
- synthetic or explicitly redistributable evaluation fixtures;
- expected artifacts and review requirements.

## A vertical must not own

- GitHub, n8n, Kanban, or another dispatcher;
- Docker images, host mounts, sandbox policy, or runtime cleanup;
- provider API keys or customer credentials;
- hard-coded provider selection where a capability declaration is sufficient;
- the platform-wide approval and review state machine;
- real customer documents or production run outputs.

## Harness interaction

The control plane selects an approved task and vertical version. The harness
validates the package, maps declared capabilities to platform policy, creates
the isolated run workspace, executes the workflow, captures evidence, and
returns a result for evaluation and approval.

Implemented-vs-spec markers against the current tree:

- control plane selects an approved task and vertical version — implemented
  in part: dispatch carries a workflow string; version selection and package
  loading are not;
- validates the package — implemented only as a test
  (`tests/runtime/test_vertical_02_fixture.py`); no runtime validation;
- maps declared capabilities to platform policy — spec-only:
  `capability_tags` are read by no code; the only cap rule is
  `min(fixture caps, profile ceiling)` in `coding_loop.py`;
- creates the isolated run workspace — implemented for the coding vertical
  (`run_workspace.py`);
- executes the workflow — implemented for vertical-02's fix-failing-test via
  CodingLoop; `workflows/*.yaml` are never parsed (execution is hard-coded
  Python);
- captures evidence — `harness/eval/runner.py`;
- returns a result for evaluation and approval — no report format yet;
  results are consumed by tests.

Unknown manifest fields, unsupported capabilities, or incompatible contract
versions must fail before model execution (spec-only today; only a test
asserts the forbidden-keys rule).

## Contract stabilization

The first manifests may be documented examples. JSON Schema files belong in
`contracts/` only after at least one real workflow has shown which task, run,
artifact, review, and approval fields are necessary. This avoids encoding the
first vertical's assumptions into the platform contract.

The stabilization trigger has been met: the vertical-02 fix-failing-test
workflow runs end-to-end against real fixtures (opt-in
`tests/runtime/test_coding_loop_real_inference.py`). The deferral of generic
schemas in `contracts/` is now a conscious decision
(`contracts/README.md`) rather than a waiting state; revisit whether to
promote a generic manifest schema.

See also [Runtime and evaluation harness](runtime-and-evaluation-harness.md).
