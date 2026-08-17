# Fas 5 — RLM v1 — Coding-class exit-criterion verification status

Status: **STRUCTURALLY WRITTEN, NOT YET RUN AGAINST A LIVE MODEL** in this
environment (2026-08-17). The structural suite (Tasks 1-12) is green; the
Coding-class exit proof (`test_exit_criterion_coding.py`) is written but
SKIPS because no live-model credentials are configured here. Consistent with
Fas 4's discipline: **a skipped exit proof is NOT a passed exit proof.**

Branch: `ci/adr-doc-currency-gate-clean`. Stage A (Task 1-9) reviewed by Kimi
K2.6 (2026-08-17, 1 critical finding fixed + 1 accepted reservation), Stage B
(Task 10-12) structurally implemented.

## What is verified, and how

| Check | Command | Result |
|---|---|---|
| Full default suite (no Docker, no real inference) | `pytest agent-platform/ -q -m "not docker_required and not real_inference"` | **291 passed, 4 skipped, 0 failed** (Stage A + harness) |
| **Real-inference exit proof (coding class) — MECHANICALLY WRITTEN, NOT YET RUN** | `pytest agent-platform/tests/harness/eval/test_exit_criterion_coding.py -m "real_inference and docker_required"` | **SKIPPED** — `CORTXT_INFERENCE_URL`/`CORTXT_INFERENCE_API_KEY` not set in this environment. Not a pass. |

## What this must prove when run against a live model (spec §23)

- RLM (recursive, `run_node`, `max_depth=2`/`max_total_children=6`) beats a
  truncated-context single-call baseline on the Coding long-context class.
- Pass rule: RLM succeeds in >= 2 of 3 independent fixture-variant rounds.
- Cost cap: RLM total cost <= 5× the baseline cost for the same fixture.
- The baseline is structurally blind when truncated below `constants.py`'s
  offset (it cannot read the correct `THRESHOLD` value), so a correct RLM
  result proves recursion recovered context the baseline could not.

## To run this for real

Requires (per Fas 4's environment facts):
1. `CORTXT_INFERENCE_URL` and `CORTXT_INFERENCE_API_KEY` set (InferX).
2. A real-inference budget > 0 (`FAS2A_INFERENCE_BUDGET_MAX`) — system-managed.
3. Docker daemon running (rlm_child_cli spawns real detached subprocesses).
4. Run under the Python312 interpreter that has `cortxt_resilient_inference`
   installed (Fas 4 found `sys.executable` is inherited by spawned children —
   see Fas 4 checklist, "Interpreter mismatch").
5. `run_rlm_fn` uses a **placeholder unit cost** (`model_invocations × 0.01`)
   — replace with the real per-invocation provider cost once
   `TextInferencePort`'s usage-reporting field name is confirmed. Do NOT guess
   the field name (Task 9 monitor).

## Rounds recorded

Pending live run. When completed, record per-round: fixture seed, baseline
success/cost, RLM success/cost, observed cost multiplier, and the 2-of-3
pass verdict.

## Expected: real bugs surface only at this step

Fas 4 found 2 real bugs only when running the exit proof against a live
model (`ProviderEvidence` missing `provider_id`; interpreter mismatch). The
same is expected here — `provider_evidence`/`BudgetGate`/port wiring in
`test_exit_criterion_coding.py` may need forwarding fixes. Do not weaken the
assertion or the fixture to force a pass.
