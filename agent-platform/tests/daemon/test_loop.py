import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from daemon.autonomy import AutonomyTracker
from daemon.budget import SessionBudget
from daemon.loop import DaemonLoop
from daemon.stop_flag import request_stop
from runtime.engine_registry import EngineContext
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineChoice
from routing.hermes_invoker import HermesInvocationError


def _fake_route(task_tags, manifests, fallback="claude-direct"):
    return EngineChoice(engine_id="hermes", reason="test", matched_tag="research",
                         checkpoint_required=False)


def _fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None):
    return {"status": "succeeded", "profile": profile, "stdout": "", "stderr": ""}


def _context_with_hermes(invoke_fn):
    context = EngineContext()
    context.register("hermes", SimpleNamespace(invoke=invoke_fn))
    return context


def _make_progressing_git_head():
    """A git_head fake that returns a new value each call -- simulates a commit landing."""
    counter = itertools.count()
    def _git_head(workdir):
        return f"commit-{next(counter)}"
    return _git_head


def _static_git_head(workdir):
    """A git_head fake that never changes -- simulates no commit landing."""
    return "same-commit"


def _make_loop(tmp_path: Path, *, list_ready_issues, route=_fake_route,
                engine_context=None, supervised=True,
                git_head=None):
    return DaemonLoop(
        repo="owner/repo",
        state_dir=tmp_path / "state",
        snapshot_path=tmp_path / "snapshot.json",
        budget=SessionBudget(max_cost_usd=100.0, max_wall_clock_seconds=3600.0),
        autonomy=AutonomyTracker(),
        supervised=supervised,
        manifests=DEFAULT_MANIFESTS,
        workdir=tmp_path,
        list_ready_issues=list_ready_issues,
        engine_context=engine_context or _context_with_hermes(_fake_invoke_hermes),
        route=route,
        git_head=git_head or _make_progressing_git_head(),
    )


def test_no_ready_issues_returns_empty(tmp_path):
    def _list(repo, **kwargs):
        return []
    loop = _make_loop(tmp_path, list_ready_issues=_list)
    assert loop.run_once() == []


def test_supervised_default_pauses_even_when_engine_does_not_require_it(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 7, "title": "Fix widget", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    results = loop.run_once()
    assert len(results) == 1
    assert results[0]["issue_id"] == "owner/repo#7"
    assert results[0]["gate_outcome"]["decision"] == "pause"
    assert "owner/repo#7" in loop.claimed_issue_ids


def test_unattended_and_unlocked_class_proceeds(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 7, "title": "Fix widget", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list, supervised=False)
    for _ in range(3):
        loop.autonomy.record_pass("hermes", "research", clean=True)
    results = loop.run_once()
    assert results[0]["gate_outcome"]["decision"] == "proceed"


def test_already_claimed_issue_is_skipped(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 7, "title": "Fix widget", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    loop.run_once()
    second = _make_loop(tmp_path, list_ready_issues=_list)
    assert second.run_once() == []


def test_checkpoint_required_engine_pauses_even_unattended_and_unlocked(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 8, "title": "Refactor core", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    def _route_checkpointed(task_tags, manifests, fallback="claude-direct"):
        return EngineChoice(engine_id="hermes", reason="test", matched_tag="research",
                             checkpoint_required=True)

    loop = _make_loop(tmp_path, list_ready_issues=_list, route=_route_checkpointed, supervised=False)
    for _ in range(3):
        loop.autonomy.record_pass("hermes", "research", clean=True)
    results = loop.run_once()
    assert results[0]["gate_outcome"]["decision"] == "pause"


def test_snapshot_written_after_run_once(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 9, "title": "X", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    loop.run_once()
    doc = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert "daemon" in doc
    assert doc["daemon"]["claimed"] == ["owner/repo#9"]


def test_run_forever_stops_on_stop_flag(tmp_path):
    def _list(repo, **kwargs):
        return []

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    request_stop(loop.state_dir)
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=5)
    assert reason == "stop_requested"


def test_run_forever_stops_on_budget_exhausted(tmp_path):
    def _list(repo, **kwargs):
        return []

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    loop.budget.record_cost(loop.budget.max_cost_usd)
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=5)
    assert reason == "budget_exhausted"


def test_run_forever_hits_max_iterations_when_neither_stop_nor_exhausted(tmp_path):
    def _list(repo, **kwargs):
        return []

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=3)
    assert reason == "max_iterations"


def test_crash_then_restart_does_not_redispatch(tmp_path):
    dispatch_count = {"n": 0}

    def _list(repo, **kwargs):
        return [{"number": 11, "title": "X", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    def _counting_invoke(profile, prompt, *, timeout_seconds, model=None, provider=None):
        dispatch_count["n"] += 1
        return {"status": "succeeded", "profile": profile, "stdout": "", "stderr": ""}

    first = _make_loop(tmp_path, list_ready_issues=_list, engine_context=_context_with_hermes(_counting_invoke))
    first.run_once()
    assert dispatch_count["n"] == 1

    second = _make_loop(tmp_path, list_ready_issues=_list, engine_context=_context_with_hermes(_counting_invoke))
    second.run_once()
    assert dispatch_count["n"] == 1


def test_route_choosing_non_hermes_engine_is_skipped_not_dispatched(tmp_path):
    dispatch_count = {"n": 0}

    def _list(repo, **kwargs):
        return [{"number": 12, "title": "Security review", "labels": [{"name": "workflow:ready"}, {"name": "security-sensitive"}]}]

    def _route_claude_direct(task_tags, manifests, fallback="claude-direct"):
        return EngineChoice(engine_id="claude-direct", reason="test", matched_tag="security-sensitive",
                             checkpoint_required=True)

    def _counting_invoke(profile, prompt, *, timeout_seconds, model=None, provider=None):
        dispatch_count["n"] += 1
        return {"status": "succeeded", "profile": profile, "stdout": "", "stderr": ""}

    loop = _make_loop(tmp_path, list_ready_issues=_list, route=_route_claude_direct, engine_context=_context_with_hermes(_counting_invoke))
    results = loop.run_once()
    assert results == []
    assert dispatch_count["n"] == 0
    assert "owner/repo#12" not in loop.claimed_issue_ids


def test_succeeded_status_with_no_commit_landed_is_treated_as_failed(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 13, "title": "X", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list, git_head=_static_git_head, supervised=False)
    for _ in range(3):
        loop.autonomy.record_pass("hermes", "research", clean=True)
    results = loop.run_once()
    assert results[0]["gate_outcome"]["decision"] == "freeze"
    assert "not 'succeeded'" in results[0]["gate_outcome"]["reason"]


def test_hermes_invocation_error_freezes_that_issue(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 14, "title": "X", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    def _raising_invoke(profile, prompt, *, timeout_seconds, model=None, provider=None):
        raise HermesInvocationError("could not start hermes: [WinError 2]")

    loop = _make_loop(tmp_path, list_ready_issues=_list, engine_context=_context_with_hermes(_raising_invoke))
    results = loop.run_once()
    assert results[0]["gate_outcome"]["decision"] == "freeze"
    assert "owner/repo#14" in loop.claimed_issue_ids


def test_run_forever_stops_on_pause_decision(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 15, "title": "X", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)  # supervised=True default -> pause
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=5)
    assert reason == "paused_for_review"


def test_run_forever_survives_a_transient_run_once_exception(tmp_path):
    call_count = {"n": 0}

    def _flaky_list(repo, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("gh issue list failed: network blip")
        return []

    loop = _make_loop(tmp_path, list_ready_issues=_flaky_list)
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=3)
    assert reason == "max_iterations"
    assert call_count["n"] == 3


def test_autonomy_persists_across_restart(tmp_path):
    def _list(repo, **kwargs):
        return []

    first = _make_loop(tmp_path, list_ready_issues=_list)
    first.autonomy.record_pass("hermes", "research", clean=True)
    first.autonomy.record_pass("hermes", "research", clean=True)
    first._persist_autonomy()

    second = _make_loop(tmp_path, list_ready_issues=_list)
    second.autonomy.record_pass("hermes", "research", clean=True)
    assert second.autonomy.is_unlocked("hermes", "research")
