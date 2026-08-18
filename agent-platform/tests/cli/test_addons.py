from __future__ import annotations

from cli.unified_cli import main


def test_addons_submit_with_security_passed_reaches_operator_queue(capsys):
    exit_code = main(["addons", "submit", "--candidate-id", "addon@my-addon", "--codex-security-passed"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "AWAIT_OPERATOR" in out


def test_addons_submit_without_security_passed_is_rejected(capsys):
    exit_code = main(["addons", "submit", "--candidate-id", "addon@my-addon"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "REJECT" in out


def test_addons_submit_incomplete_matrix_is_rejected(capsys):
    exit_code = main([
        "addons", "submit", "--candidate-id", "addon@my-addon",
        "--codex-security-passed", "--incomplete",
    ])
    assert exit_code == 1


def test_addons_submit_non_addon_candidate_passes_through_unaffected(capsys):
    # No codex_security_passed needed -- AddonReviewGate only intercepts
    # "addon@..." candidates, per learning/addon_review.py's own tests.
    exit_code = main(["addons", "submit", "--candidate-id", "policy@some-policy"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "AWAIT_OPERATOR" in out
