# agent-platform/tests/harness/eval/test_baseline_direct.py
from harness.fixtures.coding_longcontext.generator import generate_variant
from harness.eval.baseline_direct import run_baseline


class StubInferenceSeesEverything:
    """A stub that always 'succeeds' — used to prove truncation is what fails
    the baseline, not the stub's own capability."""
    def invoke(self, prompt: str) -> str:
        return "PATCHED"
    def cost_of(self, prompt: str) -> float:
        return len(prompt) * 0.0001


def test_baseline_cannot_see_second_file_when_truncated_below_its_offset():
    fixture = generate_variant(seed=7)
    first_file_len = len(fixture.repo_files["constants.py"])
    result = run_baseline(fixture, StubInferenceSeesEverything(),
                           max_context_chars=first_file_len)  # cuts off before check.py
    assert result.success is False  # structurally cannot have read check.py
    assert result.cost > 0


def test_baseline_result_carries_cost():
    fixture = generate_variant(seed=7)
    result = run_baseline(fixture, StubInferenceSeesEverything(), max_context_chars=10_000)
    assert isinstance(result.cost, float)
