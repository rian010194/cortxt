import json
import subprocess
from datetime import datetime, timezone

from daemon.review_sync import sync_review_submissions
from cli.unified_cli import main
from runtime import session_state


FIXED_TIME = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _submission(store, submission_id, issue_id="owner/repo#249"):
    doc = session_state.create(store, "task", issue_id=issue_id)
    session_state.append(store, doc["session_id"], 0, "run.review_submitted", {
        "review_submission_id": submission_id,
        "review_kind": "independent",
        "idempotency_key": "key-" + submission_id,
        "result_status": "succeeded",
        "submitted_at": FIXED_TIME.isoformat(),
        "payload_hash": "secret-payload-hash",
    })


class FakeGh:
    def __init__(self, views, edit_failures=None):
        self.views = list(views)
        self.edit_failures = set(edit_failures or [])
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[2] == "view":
            value = self.views.pop(0)
            if isinstance(value, Exception):
                return subprocess.CompletedProcess(args, 1, "", str(value))
            return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
        submission_number = args[3]
        if submission_number in self.edit_failures:
            return subprocess.CompletedProcess(args, 1, "", "edit denied")
        return subprocess.CompletedProcess(args, 0, "", "")


def _run(store, state, fake):
    return sync_review_submissions(store, state, run_subprocess=fake,
                                   clock=lambda: FIXED_TIME)


def test_finds_submission_derives_issue_and_swaps_current_workflow_labels(tmp_path):
    store, state = tmp_path / "store", tmp_path / "state"
    _submission(store, "review_1")
    fake = FakeGh([{"state": "OPEN", "labels": [{"name": "workflow:in-progress"},
                                                    {"name": "research"}]}])
    report = _run(store, state, fake)
    assert report["synced"] == ["review_1"]
    assert fake.calls[0][:7] == ["gh", "issue", "view", "249", "--repo", "owner/repo", "--json"]
    edit = fake.calls[1]
    assert edit.count("--remove-label") == 1
    assert edit[edit.index("--remove-label") + 1] == "workflow:in-progress"
    assert edit[-2:] == ["--add-label", "workflow:review"]
    markers = json.loads((state / "review_sync.json").read_text(encoding="utf-8"))
    assert markers == {"review_1": {"synced_at": FIXED_TIME.isoformat()}}


def test_no_workflow_label_edits_without_remove_argument(tmp_path):
    store, state = tmp_path / "store", tmp_path / "state"
    _submission(store, "review_2")
    fake = FakeGh([{"state": "OPEN", "labels": [{"name": "research"}]}])
    _run(store, state, fake)
    assert "--remove-label" not in fake.calls[1]
    assert fake.calls[1][-2:] == ["--add-label", "workflow:review"]


def test_marker_dedupes_second_run_without_github_call(tmp_path):
    store, state = tmp_path / "store", tmp_path / "state"
    _submission(store, "review_3")
    first = FakeGh([{"state": "OPEN", "labels": []}])
    _run(store, state, first)
    second = FakeGh([])
    report = _run(store, state, second)
    assert report["skipped"] == [{"review_submission_id": "review_3",
                                  "reason": "already_synced"}]
    assert second.calls == []


def test_crash_recovery_missing_marker_observes_already_review(tmp_path):
    store, state = tmp_path / "store", tmp_path / "state"
    _submission(store, "review_4")
    fake = FakeGh([{"state": "OPEN", "labels": [{"name": "workflow:review"}]}])
    report = _run(store, state, fake)
    assert report["skipped"] == [{"review_submission_id": "review_4",
                                  "reason": "already_review"}]
    assert len(fake.calls) == 1
    assert not (state / "review_sync.json").exists()


def test_closed_done_and_already_review_are_skipped(tmp_path):
    store, state = tmp_path / "store", tmp_path / "state"
    for index in range(3):
        _submission(store, f"review_{index}", f"owner/repo#{index + 1}")
    fake = FakeGh([
        {"state": "CLOSED", "labels": []},
        {"state": "OPEN", "labels": [{"name": "workflow:done"}]},
        {"state": "OPEN", "labels": [{"name": "workflow:review"}]},
    ])
    report = _run(store, state, fake)
    assert sorted(row["reason"] for row in report["skipped"]) == [
        "already_done", "already_done", "already_review"]
    assert all(call[2] == "view" for call in fake.calls)


def test_gh_failure_is_reported_and_later_submission_continues(tmp_path):
    store, state = tmp_path / "store", tmp_path / "state"
    _submission(store, "review_a", "owner/repo#1")
    _submission(store, "review_b", "owner/repo#2")
    fake = FakeGh([RuntimeError("network down"), {"state": "OPEN", "labels": []}])
    report = _run(store, state, fake)
    assert len(report["failed"]) == 1
    assert len(report["synced"]) == 1
    assert report["failed"][0]["review_submission_id"] != report["synced"][0]


def test_report_contains_no_session_payload_content(tmp_path):
    store, state = tmp_path / "store", tmp_path / "state"
    _submission(store, "review_safe")
    report = _run(store, state, FakeGh([{"state": "OPEN", "labels": []}]))
    encoded = json.dumps(report)
    assert "secret-payload-hash" not in encoded
    assert "key-review_safe" not in encoded
    assert set(report) == {"synced", "skipped", "failed"}


def test_sync_review_cli_runs_once_and_returns_content_free_counts(tmp_path, capsys):
    exit_code = main(["daemon", "sync-review", "--repo", "owner/repo",
                      "--store", str(tmp_path / "store"),
                      "--state-dir", str(tmp_path / "state")])
    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["evidence"] == [{"review_sync": {
        "synced": 0, "skipped": 0, "failed": 0}}]
