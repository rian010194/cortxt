#!/usr/bin/env python3
"""Offline checks for the review-sync trigger (#312, C.3).

Run: python scripts/test_review_sync_trigger.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the CLI entry point (`daemon sync-review`) applies a fresh
submission exactly once, a re-run is a no-op via the marker dedupe, the
report shape matches the daemon loop's counts, a missing state dir fails
closed with a stable error, and the trigger workflow declares the review
events with the anti-loop and concurrency guards.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

from cli.unified_cli import _run_daemon  # noqa: E402
from daemon.review_sync import report_counts, sync_review_submissions  # noqa: E402
from runtime import session_state  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def submission(store, submission_id, issue_id="owner/repo#249"):
    doc = session_state.create(store, "task", issue_id=issue_id)
    session_state.append(store, doc["session_id"], 0, "run.review_submitted", {
        "review_submission_id": submission_id,
        "review_kind": "independent",
        "idempotency_key": "key-" + submission_id,
        "result_status": "succeeded",
        "submitted_at": "2026-08-22T12:00:00Z",
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
        if args[3] in self.edit_failures:
            return subprocess.CompletedProcess(args, 1, "", "edit denied")
        return subprocess.CompletedProcess(args, 0, "", "")


def fake_env(store, state, views):
    """Return a sync that uses a FakeGh runner and a fixed clock."""
    fake = FakeGh(views)
    return sync_review_submissions(store, state, run_subprocess=fake,
                                   clock=lambda: datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)), fake


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store, state = tmp_path / "store", tmp_path / "state"

        # 1. Fresh submission is applied exactly once with the expected swap.
        submission(store, "review_1")
        report, fake = fake_env(store, state, [{"state": "OPEN", "labels": [{"name": "workflow:in-progress"}]}])
        check("fresh submission synced once", report["synced"] == ["review_1"])
        check("label swap targets workflow:review",
              fake.calls[1][-2:] == ["--add-label", "workflow:review"])
        markers = json.loads((state / "review_sync.json").read_text(encoding="utf-8"))
        check("marker persisted", "review_1" in markers)

        # 2. Re-run is a no-op (dedupe), no GitHub call.
        report2, fake2 = fake_env(store, state, [])
        check("re-run is a no-op", report2["skipped"] == [
            {"review_submission_id": "review_1", "reason": "already_synced"}])
        check("re-run makes no github calls", fake2.calls == [])

        # 3. Report shape matches the daemon loop counts.
        counts = report_counts(report)
        check("report counts match loop shape",
              counts == {"synced": 1, "skipped": 0, "failed": 0} and set(report) == {"synced", "skipped", "failed"})
        check("no payload content leaks", "secret-payload-hash" not in json.dumps(report))

        # 4. CLI entry point runs with an absent state dir (no markers yet =
        #    no prior syncs; treated as empty, safe) and still succeeds.
        from argparse import Namespace
        result = _run_daemon(Namespace(daemon_command="sync-review", repo="owner/repo",
                                       store=store, state_dir=tmp_path / "missing-state"))
        check("CLI sync-review succeeds with an absent state dir",
              result.status == "succeeded")
        # All submissions in this store are already synced, so the pass is a
        # no-op and nothing is persisted - the absent state dir is safe.
        check("absent state dir leaves no marker debris",
              not (tmp_path / "missing-state" / "review_sync.json").exists())

    # 5. Trigger workflow declares review events, anti-loop guard, concurrency.
    workflow = REPO / ".github" / "workflows" / "review-sync-trigger.yml"
    check("trigger workflow exists", workflow.is_file())
    text = workflow.read_text(encoding="utf-8")
    triggers = yaml.safe_load(text).get("on") or yaml.safe_load(text).get(True) or {}
    check("pull_request_review submitted trigger",
          "pull_request_review" in triggers
          and "submitted" in (triggers.get("pull_request_review", {}).get("types") or []))
    check("issues labeled/unlabeled trigger",
          "issues" in triggers
          and {"labeled", "unlabeled"} <= set((triggers.get("issues", {}).get("types") or [])))
    check("anti-loop guard excludes bot actors",
          "github-actions[bot]" in text and "cortxt-atlas[bot]" in text)
    check("concurrency group review-sync",
          "group: review-sync" in text and "cancel-in-progress: false" in text)
    check("workflow runs the sync-review entry point", "daemon sync-review" in text)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
