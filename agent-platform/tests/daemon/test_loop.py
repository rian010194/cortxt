# agent-platform/tests/daemon/test_loop.py
import json
from pathlib import Path

from daemon.autonomy import AutonomyTracker
from daemon.budget import SessionBudget
from daemon.loop import DaemonLoop
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineChoice


def _fake_route(task_tags, manifests, fallback="claude-direct"):
    return EngineChoice(engine_id="hermes", reason="test", matched_tag="research",
                         checkpoint_required=False)


def _fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None):
    return {"status": "succeeded", "profile": profile, "stdout": "", "stderr": ""}


def _make_loop(tmp_path: Path, *, list_ready_issues, route=_fake_route,
                invoke_hermes=_fake_invoke_hermes, supervised=True):
    return DaemonLoop(
        repo="owner/repo",
        state_dir=tmp_path / "state",
        snapshot_path=tmp_path / "snapshot.json",
        budget=SessionBudget(max_cost_usd=100.0, max_wall_clock_seconds=3600.0),
        autonomy=AutonomyTracker(),
        supervised=supervised,
        manifests=DEFAULT_MANIFESTS,
        list_ready_issues=list_ready_issues,
        invoke_hermes=invoke_hermes,
        route=route,
    )


def test_no_ready_issues_returns_empty():
    def _list(repo, **kwargs):
        return []
    loop = _make_loop(Path("/tmp/unused"), list_ready_issues=_list)
    assert loop.run_once() == []


def test_supervised_default_pauses_even_when_engine_does_not_require_it(tmp_path):
    # supervised=True is DaemonLoop's default -- a clean result still pauses
    # for operator review until this (engine, task_shape) class has earned
    # unattended autonomy, regardless of the engine's own checkpoint_required.
    def _list(repo, **kwargs):
        return [{"number": 7, "title": "Fix widget", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    results = loop.run_once()
    assert len(results) == 1
    assert results[0]["issue_id"] == "owner/repo#7"
    assert results[0]["gate_outcome"]["decision"] == "pause"
    assert "owner/repo#7" in loop.claimed_issue_ids


def test_unattended_and_unlocked_class_proceeds(tmp_path):
    # The only combination that reaches "proceed": supervised=False, the
    # engine itself doesn't require a checkpoint, AND this (engine,
    # task_shape) class has already earned its unattended unlock.
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
    second = _make_loop(tmp_path, list_ready_issues=_list)  # fresh instance, same state_dir
    assert second.run_once() == []  # already in claimed.json -> skipped, no re-dispatch


def test_checkpoint_required_engine_pauses_even_unattended_and_unlocked(tmp_path):
    # Isolates the engine-level checkpoint_required=True from supervised
    # mode: even with supervised=False AND the class already unlocked, the
    # engine's own flag still forces a pause.
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
