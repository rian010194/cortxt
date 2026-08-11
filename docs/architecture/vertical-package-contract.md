# Vertical package contract

Status: active normative
Authority: vertical architecture
Last verified: 2026-08-11

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

Directories should be created only when the package has real content. The
repository does not yet define `vertical.yaml` as a stable machine-readable
schema.

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

Unknown manifest fields, unsupported capabilities, or incompatible contract
versions must fail before model execution.

## Contract stabilization

The first manifests may be documented examples. JSON Schema files belong in
`contracts/` only after at least one real workflow has shown which task, run,
artifact, review, and approval fields are necessary. This avoids encoding the
first vertical's assumptions into the platform contract.

See also [Runtime and evaluation harness](runtime-and-evaluation-harness.md).
