# Cortxt Agent Platform

Status: scaffold; no production execution path

This directory is the future product core for Cortxt-owned agent execution and
reasoning. It is introduced alongside the verified Hermes/Pi operating path and
does not replace that path until the target architecture's exit criteria pass.

## Dependency rule

Core packages may depend on internal contracts and other core packages. They
must not import Hermes, Pi, Prime Agent, InferX, or another concrete provider.
Concrete integrations belong in the repository-level `adapters/` directory.

```text
control plane
    -> agent-platform
        -> internal ports
            <- adapters
        -> harness execution/evaluation boundaries
```

## Packages

| Package | Responsibility |
| --- | --- |
| `supervisor/` | Root and child session lifecycle, dependencies, budgets, cancellation, and recovery. |
| `runtime/` | Agent loop, context assembly, tool admission, persistence, and model invocation flow. |
| `reasoning/` | Reasoning kernel, recursive strategies, geometric strategies, and operators. |
| `state/` | Problem State, Reasoning Graph, trajectory events, and state transitions. |
| `memory/` | Session, run, project, skill, and evidence-memory policies. |
| `skills/` | Skill registry, loading, composition, candidate generation, evaluation, and promotion. |
| `tools/` | Tool registry, typed requests, effect declarations, policy admission, and result normalization. |
| `inference/` | Provider-neutral model invocation port and routing semantics. |
| `profiles/` | Versioned combinations of reasoning, tools, permissions, memory, model, and verification policy. |

## First vertical slice

The first implementation should prove one bounded flow rather than populate
every package:

1. accept an approved dispatch fixture;
2. create a persisted session and minimal Problem State;
3. invoke one model through the inference port;
4. execute read-only repository tools through the tool port;
5. return a compatible result envelope and trajectory reference;
6. pass deterministic evaluation.

No directory in this scaffold implies that its interfaces are stable.

See
[`docs/architecture/cortxt-agent-platform-target-architecture.md`](../docs/architecture/cortxt-agent-platform-target-architecture.md).

