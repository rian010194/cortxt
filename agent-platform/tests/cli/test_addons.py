from __future__ import annotations

from cli.unified_cli import main


def _paths(tmp_path):
    return ["--store", str(tmp_path / "sessions"), "--snapshot", str(tmp_path / "snapshot.json")]


def test_addons_submit_with_security_passed_reaches_operator_queue(capsys, tmp_path):
    exit_code = main(["addons", "submit", "--candidate-id", "addon@my-addon", "--codex-security-passed", *_paths(tmp_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "AWAIT_OPERATOR" in out


def test_addons_submit_without_security_passed_is_rejected(capsys, tmp_path):
    exit_code = main(["addons", "submit", "--candidate-id", "addon@my-addon", *_paths(tmp_path)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "REJECT" in out


def test_addons_submit_incomplete_matrix_is_rejected(capsys, tmp_path):
    exit_code = main([
        "addons", "submit", "--candidate-id", "addon@my-addon",
        "--codex-security-passed", "--incomplete", *_paths(tmp_path),
    ])
    assert exit_code == 1


def test_addons_submit_non_addon_candidate_passes_through_unaffected(capsys, tmp_path):
    # No codex_security_passed needed -- AddonReviewGate only intercepts
    # "addon@..." candidates, per learning/addon_review.py's own tests.
    exit_code = main(["addons", "submit", "--candidate-id", "policy@some-policy", *_paths(tmp_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "AWAIT_OPERATOR" in out
