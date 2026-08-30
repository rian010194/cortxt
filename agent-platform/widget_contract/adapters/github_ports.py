"""Injected, read-only GitHub adapters."""

import json
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

from ..registry import TYPES
from ..validation import validate
from ..candidates import build_candidates_view, dependency_targets


def issue_ready_list(call: Callable[[Mapping[str, Any]], Any], request: Mapping[str, Any]) -> dict[str, Any]:
    issues = call(dict(request))
    if not isinstance(issues, list):
        raise ValueError("issue adapter must return a list")
    allowed = ("number", "title", "state", "workflow")
    result = {"schema_version": 1, "issues": [{key: item[key] for key in allowed if key in item} for item in issues]}
    validate(result, TYPES["issues.ready.list.v1"].schema)
    return result


def registered_transition(call: Callable[[str, Mapping[str, Any]], Any], operation: str, request: Mapping[str, Any]) -> Any:
    return call(operation, dict(request))


class TransitionDenied(RuntimeError):
    kind = "transition_denied"


def gh_issue_workflow_labels(issue_id: str) -> list[str]:
    """Read an issue's workflow labels via gh (injectable for tests)."""
    repo, number = issue_id.rsplit("#", 1)
    proc = subprocess.run(["gh", "issue", "view", number, "-R", repo, "--json", "labels"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=20)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip())
    return [x.get("name", "") for x in json.loads(proc.stdout).get("labels", [])]


def gh_inbox_to_ready(issue_id: str) -> dict:
    """Perform exactly the inbox -> ready label swap via gh (injectable for tests)."""
    repo, number = issue_id.rsplit("#", 1)
    proc = subprocess.run(["gh", "issue", "edit", number, "-R", repo,
                           "--remove-label", "workflow:inbox", "--add-label", "workflow:ready"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=20)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip())
    return {"issue_id": issue_id, "status": "ok"}


def gh_review_to_done(issue_id: str) -> dict:
    """Perform exactly the review -> done label swap via gh (injectable for tests)."""
    repo, number = issue_id.rsplit("#", 1)
    proc = subprocess.run(["gh", "issue", "edit", number, "-R", repo,
                           "--remove-label", "workflow:review", "--add-label", "workflow:done"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=20)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip())
    return {"issue_id": issue_id, "status": "ok"}


def mark_ready_transition(operation: str, request: Mapping[str, Any], *,
                          issue_reader: Callable[[str], Mapping[str, Any]],
                          transition: Callable[[str, Mapping[str, Any]], Any]) -> dict[str, Any]:
    """Exactly one authorized label transition: workflow:inbox -> workflow:ready.

    Re-reads the issue immediately before the write, refuses any target that is
    not currently `workflow:inbox` (fail closed, no write), and never chains to
    a run. Not a general label editor: only the fixed inbox->ready swap is
    issued through the injected transition callable.
    """
    issue = issue_reader(request["issue_id"])
    labels = [x.get("name", "") if isinstance(x, dict) else str(x) for x in issue.get("labels") or []]
    workflow = [x for x in labels if str(x).lower().startswith("workflow:")]
    if workflow != ["workflow:inbox"]:
        raise TransitionDenied(f"issue is not exactly workflow:inbox: {workflow}")
    result = transition(operation, {"issue_id": request["issue_id"]})
    if not isinstance(result, dict):
        raise TransitionDenied("transition result must be an object")
    return result


def record_decision_transition(operation: str, request: Mapping[str, Any], *,
                               issue_reader: Callable[[str], Mapping[str, Any]],
                               transition: Callable[[str, Mapping[str, Any]], Any]) -> dict[str, Any]:
    """Exactly one authorized label transition: workflow:review -> workflow:done.

    Mirrors `mark_ready_transition`: re-reads the issue immediately before the
    write, refuses any target that is not currently `workflow:review` (fail
    closed, no write). This is the one authorized "approve" decision action
    scoped for this plan -- Reject/Return is explicitly out of scope.
    """
    issue = issue_reader(request["issue_id"])
    labels = [x.get("name", "") if isinstance(x, dict) else str(x) for x in issue.get("labels") or []]
    workflow = [x for x in labels if str(x).lower().startswith("workflow:")]
    if workflow != ["workflow:review"]:
        raise TransitionDenied(f"issue is not exactly workflow:review: {workflow}")
    result = transition(operation, {"issue_id": request["issue_id"]})
    if not isinstance(result, dict):
        raise TransitionDenied("transition result must be an object")
    return result


FIELDS = "number,title,body,labels,state,milestone,url"
MAX_ISSUES = 1000


class GitHubReadError(RuntimeError):
    kind = "github_read"


class GitHubExitError(GitHubReadError): kind = "nonzero_exit"
class GitHubTimeoutError(GitHubReadError): kind = "timeout"
class GitHubJSONError(GitHubReadError): kind = "malformed_json"
class GitHubTruncationError(GitHubReadError): kind = "truncation"
class BlockerLookupError(GitHubReadError): kind = "blocker_lookup"


def _run(runner: Callable[..., Any], command: list[str], timeout_seconds: int) -> Any:
    try:
        result = runner(command, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=timeout_seconds)
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        raise GitHubTimeoutError("GitHub read timed out") from exc
    if result.returncode:
        raise GitHubExitError(f"GitHub read failed: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GitHubJSONError("GitHub returned malformed JSON") from exc


def list_all_open_issues(repo: str, *, run_subprocess: Callable[..., Any] = subprocess.run,
                         timeout_seconds: int = 30) -> dict[str, Any]:
    """Read all open issues, failing closed when the bounded result may be truncated."""
    issues = _run(run_subprocess, ["gh", "issue", "list", "--repo", repo, "--state", "open",
        "--limit", str(MAX_ISSUES), "--json", FIELDS], timeout_seconds)
    if not isinstance(issues, list):
        raise GitHubJSONError("GitHub issue result is not a list")
    if len(issues) >= MAX_ISSUES:
        raise GitHubTruncationError(f"GitHub result reached the {MAX_ISSUES}-issue completeness bound")
    required = {"number", "title", "body", "labels", "state", "milestone", "url"}
    if any(not isinstance(item, dict) or not required <= set(item) or not isinstance(item["number"], int)
           for item in issues):
        raise GitHubJSONError("GitHub issue result has malformed fields")
    return {"schema_version": 1, "complete": True, "issues": issues}


def resolve_blocker_status(repo: str, number: int, *, run_subprocess: Callable[..., Any] = subprocess.run,
                           timeout_seconds: int = 10) -> dict[str, Any]:
    try:
        value = _run(run_subprocess, ["gh", "issue", "view", str(number), "--repo", repo,
            "--json", "number,title,state,labels,url"], timeout_seconds)
    except GitHubReadError as exc:
        raise BlockerLookupError(f"blocker #{number} lookup failed: {exc}") from exc
    if not isinstance(value, dict) or value.get("number") != number:
        raise BlockerLookupError(f"blocker #{number} lookup returned invalid data")
    return value


ISSUE_DETAIL_FIELDS = "number,title,body,labels,state,milestone,url"


def read_issue_detail(repo: str, number: int, *, run_subprocess: Callable[..., Any] = subprocess.run,
                      timeout_seconds: int = 20) -> dict[str, Any]:
    """Read one issue with the fields the detail projection needs, fail-closed.

    Malformed/truncated reads raise the same GitHubReadError subclasses as the
    list path, so a caller can render an explicit unavailable state instead of
    guessing a partial issue.
    """
    value = _run(run_subprocess, ["gh", "issue", "view", str(number), "--repo", repo,
                 "--json", ISSUE_DETAIL_FIELDS], timeout_seconds)
    if not isinstance(value, dict) or value.get("number") != number:
        raise GitHubJSONError(f"issue #{number} lookup returned invalid data")
    required = {"number", "title", "body", "labels", "state", "milestone", "url"}
    if not required <= set(value):
        raise GitHubJSONError(f"issue #{number} record has malformed fields")
    return value


class LastGoodIssues:
    """Keeps a process-local last-good projection while making stale status explicit."""
    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock, self.value, self.saved_at = clock, None, None

    def read(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        try:
            self.value = list_all_open_issues(repo, **kwargs)
            self.saved_at = self.clock()
            return {**self.value, "status": "fresh", "age_seconds": 0, "error": None}
        except GitHubReadError as exc:
            if self.value is None:
                raise
            return {**self.value, "complete": False, "status": "stale",
                    "age_seconds": max(0, int(self.clock() - self.saved_at)),
                    "error": {"kind": exc.kind, "message": str(exc)}}


class LastGoodCandidates:
    """Build the normalized candidates model with explicit last-good state."""
    def __init__(self, clock: Callable[[], float] = time.time):
        self.issues = LastGoodIssues(clock=clock)

    def read(self, repo: str, *, run_subprocess: Callable[..., Any] = subprocess.run,
             actions: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        raw = (self.issues.read(repo) if run_subprocess is subprocess.run
               else self.issues.read(repo, run_subprocess=run_subprocess))
        blockers: dict[int, dict[str, Any]] = {}
        try:
            for number in dependency_targets(raw["issues"]):
                blockers[number] = (resolve_blocker_status(repo, number) if run_subprocess is subprocess.run
                                    else resolve_blocker_status(repo, number, run_subprocess=run_subprocess))
        except GitHubReadError as exc:
            raw = {**raw, "complete": False, "status": "stale",
                   "error": {"kind": exc.kind, "message": str(exc)}}
        model = build_candidates_view(raw["issues"], complete=raw["complete"], status=raw["status"],
                                      age_seconds=raw["age_seconds"], error=raw["error"],
                                      blocker_statuses=blockers, actions=actions)
        validate(model, TYPES["candidates.view.v1"].schema)
        return model


def read_candidates_view(repo: str, *, run_subprocess: Callable[..., Any] = subprocess.run,
                         cache: LastGoodCandidates | None = None,
                         actions: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Execute the registered candidates read without any GitHub mutation."""
    return (cache or LastGoodCandidates()).read(repo, run_subprocess=run_subprocess, actions=actions)
