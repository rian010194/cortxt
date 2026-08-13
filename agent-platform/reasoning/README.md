# Reasoning

Status: scaffold; `kernel/` implemented (DM1 vertical slice)

This package will contain the Cortxt-owned Reasoning Kernel.

```text
reasoning/
|-- kernel/       strategy selection and step admission   [DM1: implemented]
|-- recursive/    bounded RLM decomposition and integration [planned DM2]
|-- geometric/    graph/embedding-based exploration and attractor detection [planned DM3]
`-- operators/    typed Problem State transformations       [DM1: kernel/operators.py]
```

Reasoning proposes transformations. Authoritative state transitions, child
creation, tool effects, and budget consumption are validated by their owning
components.

## DM1 — Reasoning Kernel + operator skeleton (vertical slice, 2026-08-14)

Implemented under `kernel/` with **0 model calls** (deterministic only):

- `problem_state.py` — `ProblemState` (id, content, parent/children, confidence,
  applied_operator, transformation_log) + `new_problem()`.
- `strategy.py` — `Strategy` enum (direct / recursive / geometric /
  human_escalation) + `select_strategy()` based on problem structure.
- `operators.py` — `inspect`, `decompose`, `integrate`, `verify` (model-free).
- `engine.py` — `Engine.solve()` drives strategy + operators to a terminal
  `{strategy, value, confidence, steps}` result.

Tests: `tests/reasoning/kernel/` — 10 passed, coverage 90% for `reasoning/kernel/`.
Three fixture variants of the same "compute total sum" problem force
direct (flat), recursive (nested), geometric (constraint-dependencies).

Next: Checkpoint 1.1 review, then DM2 (RLM engine with hard bounds).
