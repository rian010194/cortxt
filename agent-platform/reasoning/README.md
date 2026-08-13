# Reasoning

Status: scaffold; kernel/ (DM1), recursive/ (DM2), geometric/ (DM3), pipeline (DM4) implemented

This package is the Cortxt-owned Reasoning Kernel (target architecture §10–§12).

```text
reasoning/
|-- kernel/       strategy selection + step admission (direct/recursive/geometric) [DM1]
|-- recursive/    bounded RLM decomposition and integration (hard limits)         [DM2]
|-- geometric/    graph/embedding exploration + attractor detection + escape      [DM3]
|-- pipeline.py   integrated ReasoningPipeline (kernel+RLM+geometric)             [DM4]
|-- orchestrator.py  lifecycle: init -> run -> verify -> finalize; human_esc.     [DM4]
`-- tests/        kernel, recursive, geometric, integration, verification,
                  no-external-deps
```

Reasoning proposes transformations. Authoritative state transitions, child
creation, tool effects, and budget consumption are validated by their owning
components. Core packages do not import Hermes/Pi/InferX/provider (guarded by
`tests/reasoning/test_no_external_deps.py`).

## DM4 — Integrated pipeline (done 2026-08-14)
- `ReasoningPipeline.run(problem)`: selects strategy (kernel), dispatches to
  the RLM engine (recursive) or Geometric explorer, folds results and updates
  confidence via a verify step. Hybrid problems (`{recursive, geometric}`)
  switch strategy mid-flight.
- `ReasoningOrchestrator.run(problem, expected)`: lifecycle over the pipeline,
  honours a `human_escalation` marker, classifies the job terminal vs not.
- 0 model calls (inference port is injected/stubbed).

Tests: 57 passed, coverage 93% for `reasoning/`, 0 model calls. Next: CP4.1
(Kimi review) then a PR; main-merge stays an operator gate.
