# agent-platform/tests/harness/eval/test_runner.py
from harness.eval.runner import run_eval_class, EvalRoundResult


def _fake_generator(seed):
    class _F: pass
    f = _F(); f.seed = seed
    return f


def test_rlm_pass_requires_at_least_two_of_three_rounds():
    def run_rlm(fixture):
        return EvalRoundResult(success=fixture.seed != 2, cost=1.0)  # fails only on seed=2

    def run_baseline(fixture):
        return EvalRoundResult(success=False, cost=0.5)

    result = run_eval_class(_fake_generator, n_variants=3, run_rlm_fn=run_rlm,
                             run_baseline_fn=run_baseline)
    assert result.rlm_pass is True  # 2 of 3 succeed


def test_rlm_fail_when_only_one_of_three_succeeds():
    def run_rlm(fixture):
        return EvalRoundResult(success=fixture.seed == 1, cost=1.0)

    def run_baseline(fixture):
        return EvalRoundResult(success=False, cost=0.5)

    result = run_eval_class(_fake_generator, n_variants=3, run_rlm_fn=run_rlm,
                             run_baseline_fn=run_baseline)
    assert result.rlm_pass is False


def test_cost_cap_exceeded_flags_round_as_budget_exhausted_not_a_crash():
    def run_rlm(fixture):
        return EvalRoundResult(success=True, cost=100.0)  # way over 5x

    def run_baseline(fixture):
        return EvalRoundResult(success=False, cost=1.0)

    result = run_eval_class(_fake_generator, n_variants=1, run_rlm_fn=run_rlm,
                             run_baseline_fn=run_baseline)
    assert result.rounds[0].budget_exhausted is True
    assert result.rounds[0].rlm_success_for_pass_purposes is False
