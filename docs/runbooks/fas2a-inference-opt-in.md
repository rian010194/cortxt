# Phase 2A — Real inference (opt-in) runbook

Purpose: connect the reasoning core's mocked `InferencePort` to REAL,
provider-neutral inference (via `cortxt-resilient-inference`) on an L0
fixture, to eliminate the "fixture-gap" risk. This is **opt-in** and
**data class L0 only**.

## Basic principle
- The default suite is always **mocked** and green (0 model calls): `pytest -m "not real_inference"`.
- Real calls run ONLY when you explicitly select `-m real_inference` AND the environment is configured.
- The budget is **system-managed** (no number needs to be set manually by the operator): env
  `FAS2A_INFERENCE_BUDGET_MAX`. If missing → **0 = fail-closed** (no real calls occur).

## Required to run real inference (env)
```bash
export CORTXT_INFERENCE_URL="https://<l0-endpoint>/v1"     # OpenAI-compatible, HTTPS
export CORTXT_INFERENCE_API_KEY="<key>"
export CORTXT_INFERENCE_MODEL="<model>"
export FAS2A_INFERENCE_BUDGET_MAX=3                        # small cap; the system owns the number
```
> Requires `cortxt-resilient-inference` to be installed (see `requirements`/editable install).

## Running
```bash
# from agent-platform/
# 1) Hermetic default suite (no real calls):
pytest -m "not real_inference"

# 2) Opt-in: real L0 calls (respects the budget cap):
pytest -m real_inference
```

## Budget and cost control
- Every real call is logged to the SQLite table `fas2a_inference_spend` (timestamp, task_id,
  cost_status, latency_ms, route_id, selected_route_id) for later analysis.
- `BudgetGate` denies (fail-closed) everything before HTTP once the cap is reached; a failed call
  also counts (no budget bypass via retries).
- Constant: all non-`real_inference` tests are hermetic.

## L0 fixture
`fixtures/l0_synthetic_rlm.json` — only synthetic integers/vectors (Fibonacci numbers, unit vectors),
clearly public/synthetic, with documented provenance. NO personal data/secrets/real documents.

## Why
Verifies that the RLM/Geometric strategies work against GENUINE model inference behind the port, without
`reasoning/` ever importing a provider (the ADR-016 invariant is protected by `test_no_external_deps`).
