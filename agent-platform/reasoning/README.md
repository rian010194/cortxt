# Reasoning

Status: scaffold; `kernel/` (DM1) and `recursive/` (DM2) implemented

This package will contain the Cortxt-owned Reasoning Kernel.

```text
reasoning/
|-- kernel/       strategy selection and step admission   [DM1: implemented]
|-- recursive/    bounded RLM decomposition and integration [DM2: implemented]
|-- geometric/    graph/embedding-based exploration and attractor detection [planned DM3]
`-- operators/    typed Problem State transformations       [DM1: kernel/operators.py]
```

Reasoning proposes transformations. Authoritative state transitions, child
creation, tool effects, and budget consumption are validated by their owning
components.

## DM1 — Kernel + operator skeleton (done 2026-08-14)
`kernel/`: ProblemState, Strategy selector (direct/recursive/geometric),
deterministic operators (inspect/decompose/integrate/verify), Engine loop.
12 tests, coverage 90%, 0 model calls. Checkpoint 1.1: Kimi GODKÄND.

## DM2 — RLM Engine (done 2026-08-14)
`recursive/` implements the bounded recursive decomposition loop
(target architecture §11):
- `bounds.py` — `RLMConfig` with all hard limits (max_depth, max_branches_per_node,
  max_total_children, max_model_invocations, max_context_reads, max_runtime_seconds,
  max_cost, max_output_size, explicit_stop_policy), validated fail-closed.
- `rlm_engine.py` — `RLMEngine` + `InferencePort` (Protocol; never called directly —
  tests inject a pure stub). Prunes fan-out to per-node + global child budget.
- `decomposer.py` / `integrator.py` / `challenger.py` / `stop_conditions.py`.

Tests: bounds (each + combined), RLM fixture, stop conditions, integrator.
29 tests, coverage 92%, 0 model calls. Next: Checkpoint 2.1 (Kimi review).

Next: DM3 (Geometric Reasoning Engine) then DM4 (integrated pipeline).
