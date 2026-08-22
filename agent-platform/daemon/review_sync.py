"""Synchronize durable MCP review submissions to GitHub workflow labels."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from daemon.github_scanner import GhRunner
from runtime import session_state

WORKFLOW_REVIEW = "workflow:review"


def resolve_issue_ref(issue_ref: str) -> tuple[str, int]:
    repo, separator, number = issue_ref.rpartition("#")
    if not separator or repo.count("/") != 1 or not number.isdigit():
        raise ValueError(f"invalid issue reference: {issue_ref!r}")
    return repo, int(number)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_markers(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("review sync marker must be an object")
    return value


def _persist_markers(path: Path, markers: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / ".review_sync.json.tmp"
    tmp.write_text(json.dumps(markers, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _submissions(store: Path):
    for path in sorted(store.glob("session_*/session.json")):
        session_id = path.parent.name
        doc = session_state.load(store, session_id)
        created = next((event for event in doc["events"]
                        if event["event_type"] == "session.created"), None)
        issue_ref = created["payload"].get("issue_id") if created else None
        for event in doc["events"]:
            if event["event_type"] == "run.review_submitted":
                yield issue_ref, event["payload"].get("review_submission_id")


def sync_review_submissions(
    store: Path,
    state_dir: Path,
    run_subprocess: GhRunner = subprocess.run,
    clock: Callable[[], datetime] = _now,
    issue_resolver: Callable[[str], tuple[str, int]] = resolve_issue_ref,
    repo: str | None = None,
) -> dict:
    """Apply each unmarked review submission once and return content-free results."""
    report: dict[str, list] = {"synced": [], "skipped": [], "failed": []}
    marker_path = state_dir / "review_sync.json"
    markers = _load_markers(marker_path)
    for issue_ref, submission_id in _submissions(store):
        if not isinstance(submission_id, str) or not submission_id:
            continue
        if submission_id in markers:
            report["skipped"].append({"review_submission_id": submission_id,
                                      "reason": "already_synced"})
            continue
        try:
            if not isinstance(issue_ref, str):
                raise ValueError("session.created has no issue_id")
            issue_repo, issue_number = issue_resolver(issue_ref)
            if repo is not None and issue_repo != repo:
                continue
            view_args = ["gh", "issue", "view", str(issue_number), "--repo", issue_repo,
                         "--json", "state,labels"]
            viewed = run_subprocess(view_args, capture_output=True, text=True, timeout=30)
            if viewed.returncode != 0:
                raise RuntimeError(f"gh issue view failed: {viewed.stderr.strip()}")
            issue = json.loads(viewed.stdout)
            labels = [label["name"] for label in issue.get("labels", [])]
            if str(issue.get("state", "")).upper() == "CLOSED" or "workflow:done" in labels:
                report["skipped"].append({"review_submission_id": submission_id,
                                          "reason": "already_done"})
                continue
            if WORKFLOW_REVIEW in labels:
                report["skipped"].append({"review_submission_id": submission_id,
                                          "reason": "already_review"})
                continue
            edit_args = ["gh", "issue", "edit", str(issue_number), "--repo", issue_repo]
            workflow_labels = [label for label in labels if label.startswith("workflow:")]
            for label in workflow_labels:
                edit_args.extend(["--remove-label", label])
            edit_args.extend(["--add-label", WORKFLOW_REVIEW])
            edited = run_subprocess(edit_args, capture_output=True, text=True, timeout=30)
            if edited.returncode != 0:
                raise RuntimeError(f"gh issue edit failed: {edited.stderr.strip()}")
            markers[submission_id] = {"synced_at": clock().isoformat()}
            _persist_markers(marker_path, markers)
            report["synced"].append(submission_id)
        except Exception as error:
            report["failed"].append({"review_submission_id": submission_id,
                                     "error": str(error)})
    return report


def report_counts(report: dict) -> dict[str, int]:
    return {key: len(report[key]) for key in ("synced", "skipped", "failed")}
