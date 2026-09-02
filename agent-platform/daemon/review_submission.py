"""Write the durable review submission that review-sync reads (#493).

`daemon/review_sync.py` derives every `in-progress -> review` transition
exclusively from `run.review_submitted` events in the session store. Nothing
wrote those events for a dispatcher-backed Run, so `Dispatcher._sync_github()`
moved the label itself on nothing more than a terminal worker status -- the
#485 defect: the label moved at 12:16:38 with no `run.review_submitted` event
anywhere in any store.

This module is the missing writer, and the only sanctioned one. It is the
third step of the order #493 mandates:

1. the worker reaches a terminal candidate status;
2. the Evidence Gate verifies the result and the commit correlation (#490);
3. **a complete, idempotent `run.review_submitted` is written here**;
4. `review_sync.sync_review_submissions()` performs `in-progress -> review`.

Idempotence is structural, not incidental. The submission id is derived from
the `run_id`, so a replayed completion, a `resync_pending()` retry and a
restarted host all address the same submission; an existing event with that id
short-circuits before any append. `review_sync`'s own marker file dedupes the
GitHub side on the same id, so a replay never produces a second label edit or
a second submission event.

## Relationship to the MCP lifecycle writer

`cortxt_mcp/run_lifecycle.py` also writes `run.review_submitted`, through the
`cortxt_run_submit_for_review` tool (ADR-034). That is not a duplicate of this
module and neither replaces the other -- they are two different submitters for
two different paths:

| | MCP lifecycle | this module |
| --- | --- | --- |
| Submitter | an agent, through the mandate-protected MCP surface | the dispatcher, after its Evidence Gate |
| Submission id | random per submission | derived from the `run_id` |
| Idempotence key | caller-supplied, conflicts on a changed payload | the derived id; a replay is a no-op |

A caller supplying its own idempotency key can express "this is a *different*
submission of the same run", which the MCP tool needs and the dispatcher does
not: a Run completes once, so its submission is a function of the Run.

`review_sync._submissions()` reads only `review_submission_id`, so it consumes
both. If one Run ever produced a submission on both paths, review-sync applies
whichever it reaches first and skips the other as `already_review`; the
transition still happens exactly once.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from runtime import session_state

REVIEW_EVENT = "run.review_submitted"
REVIEW_KIND = "evidence-gate"


class ReviewSubmissionError(RuntimeError):
    """The durable review submission could not be written.

    Raised, never swallowed: without a durable submission no sanctioned path
    can move the Issue to `workflow:review`, so the caller must see the
    failure rather than leave a Run that looks reviewable and is not.
    """


def review_submission_id(run_id: str) -> str:
    """Deterministic per-Run submission id -- the basis of idempotence."""
    return "review-" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _find_session(store: Path, run_id: str, issue_id: str) -> Optional[str]:
    """The existing session for this Run, preferring an exact `run_id` match.

    A session created by the launcher carries `run_id`; an older one may carry
    only `issue_id`. Matching on `run_id` first keeps two Runs on the same
    Issue from sharing a submission chain.
    """
    by_issue = None
    for path in sorted(store.glob("session_*/session.json")):
        session_id = path.parent.name
        try:
            doc = session_state.load(store, session_id)
        except session_state.SessionError:
            continue
        created = next((event for event in doc["events"]
                        if event["event_type"] == "session.created"), None)
        if created is None:
            continue
        payload = created["payload"]
        if payload.get("run_id") == run_id:
            return session_id
        if by_issue is None and payload.get("issue_id") == issue_id:
            by_issue = session_id
    return by_issue


def _already_submitted(doc: dict, submission_id: str) -> bool:
    return any(event["event_type"] == REVIEW_EVENT
               and event["payload"].get("review_submission_id") == submission_id
               for event in doc["events"])


def submit_review(
    store: Path,
    run,
    result_envelope: dict,
    *,
    commit_evidence: Optional[dict] = None,
    clock: Callable[[], str] = _now,
) -> str:
    """Write `run`'s `run.review_submitted` event once and return its id.

    Content-free by construction: the payload carries identifiers, the
    correlated commit and branch, and a hash of the evidence record -- never
    result text, prompts or model reasoning.
    """
    submission_id = review_submission_id(run.run_id)
    store = Path(store)
    try:
        store.mkdir(parents=True, exist_ok=True)
        session_id = _find_session(store, run.run_id, run.issue_id)
        if session_id is None:
            doc = session_state.create(store, run.run_id, run_id=run.run_id,
                                       issue_id=run.issue_id,
                                       branch=getattr(run, "branch", None),
                                       worker_role=getattr(run, "worker_role", None),
                                       runtime=getattr(run, "runtime", None))
            session_id = doc["session_id"]
        else:
            doc = session_state.load(store, session_id)
        if _already_submitted(doc, submission_id):
            return submission_id
        evidence = dict(commit_evidence or {})
        payload = {
            "review_submission_id": submission_id,
            "review_kind": REVIEW_KIND,
            "idempotency_key": submission_id,
            "result_status": (result_envelope or {}).get("status") or run.status,
            "submitted_at": clock(),
            "payload_hash": hashlib.sha256(
                session_state.canonical_json(evidence)).hexdigest(),
            "run_id": run.run_id,
            "issue_id": run.issue_id,
            "request_id": getattr(run, "request_id", None),
            "commit": evidence.get("commit"),
            "branch": evidence.get("branch") or getattr(run, "branch", None),
        }
        session_state.append(store, session_id,
                             session_state.latest_sequence(doc), REVIEW_EVENT, payload)
    except session_state.SessionError as exc:
        raise ReviewSubmissionError(
            f"could not write {REVIEW_EVENT} for {run.run_id}: {exc}") from exc
    except OSError as exc:
        raise ReviewSubmissionError(
            f"review submission store unwritable for {run.run_id}: {exc}") from exc
    return submission_id


def make_review_submitter(store: Path, *, clock: Callable[[], str] = _now) -> Callable:
    """Bind `submit_review` to a store, for injection into `Dispatcher`."""
    store = Path(store)

    def submitter(run, result_envelope: dict, commit_evidence: Optional[dict] = None) -> str:
        return submit_review(store, run, result_envelope,
                             commit_evidence=commit_evidence, clock=clock)
    return submitter
