# Tool Platform

Status: scaffold

Tools are typed, versioned operations that observe or affect an environment.
They are distinct from skills and reasoning operators:

- a reasoning operator transforms Problem State;
- a skill composes a reusable workflow;
- a tool performs one declared operation;
- the execution harness enforces the operation's real boundary.

## Required tool metadata

Every promoted tool must declare:

- stable identifier and version;
- input and output schemas;
- effect class;
- filesystem and network needs;
- credential requirements;
- timeout and cancellation behavior;
- idempotency/retry semantics;
- artifact and telemetry policy.

## Effect classes

```text
observe
local_mutation
bounded_execution
external_mutation
irreversible
credential
```

Agents may generate tool candidates, manifests, tests, and fixtures. Executable
tool changes require sandboxed contract, permission, security, failure, and
cleanup tests before promotion. A candidate cannot grant itself new authority.

The existing repository-level `tools/` directory remains the current tool
inventory. This package will contain registry, gateway, policy, and evolution
code rather than duplicate tool implementations.

