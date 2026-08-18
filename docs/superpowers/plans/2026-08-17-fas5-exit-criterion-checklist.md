# Fas 5 — RLM v1 — Coding-class exit-criterion verification status

Status: **EMPIRICALLY VERIFIED against a live InferX model** on 2026-08-17.
Both exit classes (Coding and Research) PASSED against `Qwen3-Coder-Next-FP8`
on InferX under the Python312 interpreter that has
`cortxt_resilient_inference` installed. This is no longer a structural-only
or skipped proof — real model calls were made and logged to
`fas2a_inference_spend`.

Branch: `ci/adr-doc-currency-gate-clean`. Stage A (Task 1-9) reviewed by Kimi
K2.6 (2026-08-17, 1 critical finding fixed + 1 accepted reservation), Stage B
(Task 10-13) structurally and now empirically implemented.

## What is verified, and how

| Check | Command | Result |
|---|---|---|
| Full default suite (no Docker, no real inference) | `pytest agent-platform/ -q -m "not docker_required and not real_inference"` | **308 passed, 4 skipped, 0 failed** (Stage A + harness) |
| **Coding exit proof — LIVE** | `pytest agent-platform/tests/harness/eval/test_exit_criterion_coding.py -m "real_inference and docker_required"` | **PASSED** (30.65s) — real `Qwen3-Coder-Next-FP8` on InferX |
| **Research exit proof — LIVE** | `pytest agent-platform/tests/harness/eval/test_exit_criterion_research.py -m "real_inference and docker_required"` | **PASSED** (29.49s) — real `Qwen3-Coder-Next-FP8` on InferX |

Real-call evidence: `fas2a_inference_spend` in state.db logged 6 new
`attempt_started`+`success` rows across the two exit runs (3 Coding + 3
Research) — genuine model invocations, not skipped/stubbed.

## Environment facts required to reproduce (learned this run)

1. **Interpreter:** `cortxt_resilient_inference` is installed ONLY under
   Python312 (`C:\Users\rikar\AppData\Local\Programs\Python\Python312`), not
   the `hermes-agent` venv. Run exit tests with Python312 (its `sys.executable`
   is inherited by spawned `rlm_child_cli` subprocesses).
2. **Model:** the correct model ID for this repo is **`Qwen3-Coder-Next-FP8`**
   (returns `succeeded`). The value in `ticket-triage/.env`
   (`Qwen3.6-35B-A3B-fp8-no-thinking`) returns **404 `invalid_model_id`**
   against `https://model.inferx.net/endpoints/v1` — do not use it here.
3. **Budget:** set `FAS2A_INFERENCE_BUDGET_MAX` above the existing cumulative
   spend in the shared state.db (which already had 3 historical
   `attempt_started` rows) or the `BudgetGate` fail-closes all new calls. Used
   30/60 for the two runs; spend is system-managed.

## What the pass proves (and its honest limits)

- **Coding class:** RLM recursively decomposed, read both required files, and
  beat the truncated-context baseline in >= 2 of 3 rounds within the 5x cost
  cap — the §23 exit criterion for the Coding class.
- **Research class:** RLM completed all rounds without crashing and the runner
  recorded `status == "succeeded"` in >= 2 of 3 rounds. NOTE (honest limit):
  the research `run_rlm_fn` asserts on RLM's `status`, not on an actual
  `citation_match_v1` text-vs-cite check — the plan declared this text-return
  integration gap (Task 8's `integrate_results` sums ints, research output is
  text). So the research pass proves RLM coordination/robustness on the
  research fixture, but NOT yet that RLM's synthesized text is citation-correct.
- **Cost:** placeholder unit cost (`model_invocations × 0.01`) is still used
  in both `run_rlm_fn`; no real per-invocation cost field was confirmed. The
  5x cap is verified against this placeholder, not real provider cost.

## Rounds recorded

- Coding: `test_rlm_beats_baseline_on_coding_long_context_class` PASSED
  (3 fixture-variants, real model).
- Research: `test_rlm_beats_baseline_on_research_long_context_class` PASSED
  (3 fixture-variants, real model).
Per-round seed/cost/multiplier detail is captured in the test's
`run_eval_class` outcome and the `fas2a_inference_spend` ledger.


