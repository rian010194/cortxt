"""#469: a stopped Run must explain itself to the operator, not only to a machine.

The terminal panel used to lead with `blocked` and a raw failure code such as
`commit_predates_run`. Both are true; neither answers the two questions an
operator has in front of a stopped Run -- did my task get done, and what do I do
now. These are source-level contract tests over the renderer, in the same style
as the rest of the widget suite: the JS is served as a static asset, so the
contract is asserted against its source.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "widget" / "app-renderer-work-launch.js"


@pytest.fixture(scope="module")
def source() -> str:
    return RENDERER.read_text(encoding="utf-8")


def test_the_refusal_the_dogfood_actually_produced_has_plain_language(source):
    """`commit_predates_run` is what #519 and every blocked #497 Run reported."""
    assert "commit_predates_run:" in source
    assert "No new commit could be verified for this run" in source


def test_every_outcome_offers_a_next_step(source):
    """A stop the operator cannot act on is a dead end, not an explanation."""
    assert "next:" in source
    assert "data-run-next-step" in source
    assert "run-next-step" in source


def test_the_headline_separates_worker_finishing_from_result_being_accepted(source):
    """A worker can finish perfectly and still land nothing acceptable."""
    assert "Worker finished · change accepted" in source
    assert "Worker finished · result not accepted" in source
    assert "Worker did not finish" in source


def test_a_gate_pass_is_never_presented_as_shipped(source):
    """The Gate verifies a commit on the run's own branch and nothing more."""
    assert "Nothing has been pushed, merged, published or deployed" in source


def test_the_machine_vocabulary_survives_in_a_detail_view(source):
    """Debugging needs the raw code, run id and gate verdict -- one click away."""
    assert '<details class="run-detail">' in source
    assert "data-run-error-code" in source
    assert 'row("Run", term.run_id)' in source
    assert "gateRows(term)" in source


def test_an_unrecognised_failure_code_still_explains_and_directs(source):
    """A code with no entry must not fall through to a blank panel."""
    assert "its result could" in source
    assert "Open the details below for the exact reason" in source


def test_the_evidence_hooks_the_acceptance_matrix_reads_are_unchanged(source):
    for hook in ("data-run-terminal", "data-run-status", "data-run-activity",
                 "data-run-freshness", "data-run-live"):
        assert hook in source


def test_acceptance_is_keyed_on_the_gate_verdict_not_the_status_word(source):
    """The dogfood's one accepted Run reads `review_submitted`, not `succeeded`.

    #515 made the correlation carry the later lifecycle state, so keying the
    accepted headline on `status === "succeeded"` rendered the only Run that
    passed the gate as "outcome not recorded" — found by running the renderer
    against the live `run-14d3cb02c6314a3da6c7a36d2ecc66e1` projection.
    """
    assert 'term.evidence_gate === "commit_correlated"' in source
    assert 'term.evidence_gate === "commit_correlation_failed"' in source
