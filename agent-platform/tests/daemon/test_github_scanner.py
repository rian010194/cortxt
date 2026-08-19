import json
import subprocess

import pytest

from daemon.github_scanner import list_ready_issues


def _fake_run(returncode=0, stdout="[]", stderr=""):
    def _runner(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)
    return _runner


def test_parses_gh_json_output():
    issues = [{"number": 42, "title": "Fix widget", "labels": [{"name": "workflow:ready"}]}]
    runner = _fake_run(stdout=json.dumps(issues))
    result = list_ready_issues("owner/repo", run_subprocess=runner)
    assert result == issues


def test_passes_correct_gh_args():
    captured = {}

    def _runner(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    list_ready_issues("owner/repo", run_subprocess=_runner)
    assert captured["args"][:3] == ["gh", "issue", "list"]
    assert "--repo" in captured["args"] and "owner/repo" in captured["args"]
    assert "--label" in captured["args"] and "workflow:ready" in captured["args"]


def test_nonzero_exit_raises():
    runner = _fake_run(returncode=1, stderr="gh: authentication required")
    with pytest.raises(RuntimeError, match="authentication required"):
        list_ready_issues("owner/repo", run_subprocess=runner)


def test_custom_label():
    captured = {}

    def _runner(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    list_ready_issues("owner/repo", label="workflow:blocked", run_subprocess=_runner)
    assert "workflow:blocked" in captured["args"]
