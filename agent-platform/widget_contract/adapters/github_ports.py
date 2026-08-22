"""Injected, read-only GitHub adapters."""

import json
import subprocess
import time
from typing import Any, Callable, Mapping

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
        result = runner(command, capture_output=True, text=True, timeout=timeout_seconds)
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

    def read(self, repo: str, *, run_subprocess: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
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
                                      blocker_statuses=blockers)
        validate(model, TYPES["candidates.view.v1"].schema)
        return model


def read_candidates_view(repo: str, *, run_subprocess: Callable[..., Any] = subprocess.run,
                         cache: LastGoodCandidates | None = None) -> dict[str, Any]:
    """Execute the registered candidates read without any GitHub mutation."""
    return (cache or LastGoodCandidates()).read(repo, run_subprocess=run_subprocess)
