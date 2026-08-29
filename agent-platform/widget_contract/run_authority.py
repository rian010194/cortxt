"""Provenance-preserving Run-summary authority for the Workstream detail read model.

S7a (#470): the dispatcher `runs.json` (scripts/dispatcher.py) and the
MCP/session-event store (cortxt_mcp/run_lifecycle.py -> runtime/session_state)
both hold Run records for the same issue, and they currently overlap.

This module is the deliberate S7a answer to that overlap: it does NOT pick a
canonical writer (launch is S7b scope and must not be decided by a read-only
slice). It defines a read-only adapter that

- reads summaries from both stores,
- correlates them by exact ``issue_ref``,
- preserves each record's provenance as an explicit ``sources`` list, and
- renders a ``conflict`` instead of silently merging whenever two stores
  disagree on the same ``run_id``'s status or terminal timestamp.

Runs are immutable summaries: a retry creates a new ``run_id`` and never
overwrites an earlier record. No prompt, reasoning, secret, or artifact
content ever enters a summary.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

STORE_DISPATCHER = "dispatcher.runs"
STORE_SESSION = "session.events"
KNOWN_STORES = (STORE_DISPATCHER, STORE_SESSION)

RUNNING_STATUS = "in_progress"
CONFLICT_STATUS = "conflict"
KNOWN_STATUSES = frozenset(
    {"in_progress", "succeeded", "failed", "timed_out", "budget_exceeded",
     "blocked", "cancelled", "conflict", "unknown"}
)


def _iso(value: Any) -> str | None:
    """Return a string value unchanged, or None when absent/non-string."""
    return value if isinstance(value, str) and value else None


def _timestamp(value: Any) -> str | None:
    """Normalize a timestamp (ISO string or epoch number) to an ISO string."""
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        from datetime import datetime, timezone

        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return None


def _pick(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def summary_from_dispatcher(run: Mapping[str, Any], issue_ref: str) -> dict[str, Any] | None:
    """Map one dispatcher Run record (Run.asdict) onto the summary shape.

    The dispatcher's ``issue_id`` is ``owner/repo#N``; only a run whose issue
    matches ``issue_ref`` exactly is returned, so a mismatch never leaks an
    unrelated run into the projection.
    """
    if not isinstance(run, Mapping):
        return None
    if str(run.get("issue_id")) != issue_ref:
        return None
    status = str(run.get("status") or RUNNING_STATUS)
    if status not in KNOWN_STATUSES:
        status = "unknown"
    return {
        "run_id": str(run["run_id"]),
        "issue_ref": issue_ref,
        "status": status,
        "engine": _iso(_pick(run, "runtime")),
        "worker_role": _pick(run, "worker_role"),
        "started_at": _timestamp(run.get("claimed_at")),
        "finished_at": _timestamp(run.get("finished_at")),
        "sources": [STORE_DISPATCHER],
        "conflict": None,
    }


def summaries_from_sessions(session_docs: Sequence[Mapping[str, Any]], issue_ref: str) -> list[dict[str, Any]]:
    """Extract Run summaries from loaded session-event documents.

    A session represents a run when its ``session.created`` payload carries a
    ``run_id`` and an ``issue_id``/``issue_ref`` matching ``issue_ref`` exactly.
    Terminal status comes from the last terminal event payload; an unfinished
    run is ``in_progress``. Fields that are absent stay absent (never guessed).
    """
    summaries: list[dict[str, Any]] = []
    for doc in session_docs:
        if not isinstance(doc, Mapping):
            continue
        events = doc.get("events")
        if not isinstance(events, list) or not events:
            continue
        created = events[0] if isinstance(events[0], Mapping) else {}
        payload = created.get("payload") if isinstance(created.get("payload"), Mapping) else {}
        run_id = payload.get("run_id")
        owner_ref = _pick(payload, "issue_id", "issue_ref")
        if not run_id or str(owner_ref) != issue_ref:
            continue
        status = RUNNING_STATUS
        finished_at: str | None = None
        for event in events:
            if not isinstance(event, Mapping):
                continue
            etype = str(event.get("event_type") or "")
            epayload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            if etype in ("session.terminal", "run.terminal"):
                candidate = epayload.get("status")
                if isinstance(candidate, str) and candidate:
                    status = candidate if candidate in KNOWN_STATUSES else "unknown"
                    finished_at = _iso(event.get("timestamp")) or finished_at
        if status not in KNOWN_STATUSES:
            status = "unknown"
        summaries.append({
            "run_id": str(run_id),
            "issue_ref": issue_ref,
            "status": status,
            "engine": _iso(_pick(payload, "engine_id", "runtime")),
            "worker_role": _pick(payload, "worker_role", "profile"),
            "started_at": _iso(created.get("timestamp")),
            "finished_at": finished_at,
            "sources": [STORE_SESSION],
            "conflict": None,
        })
    return summaries


def _agree(a: dict[str, Any], b: dict[str, Any], field: str) -> bool:
    left, right = a.get(field), b.get(field)
    if left is None or right is None:
        return True  # an unknown side cannot contradict the other
    return left == right


def correlate_run_summaries(
    issue_ref: str,
    dispatcher_runs: Mapping[str, Any],
    session_runs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge the two stores' summaries by exact ``run_id`` without silent merge.

    Returns a list (newest-``run_id`` first, cosmetic) of immutable summaries.
    A run present in one store carries that store in ``sources``; a run present
    in both and in agreement merges ``sources``; a run present in both that
    disagrees on ``status`` is rendered as ``conflict`` with both statuses
    listed, never resolved.
    """
    merged: dict[str, dict[str, Any]] = {}
    for run in dispatcher_runs.values():
        summary = summary_from_dispatcher(run, issue_ref) if isinstance(run, Mapping) else None
        if summary is not None:
            merged[summary["run_id"]] = summary
    for raw in session_runs:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("issue_ref") or "") != issue_ref:
            continue
        run_id = str(raw.get("run_id"))
        existing = merged.get(run_id)
        summary = {
            "run_id": run_id,
            "issue_ref": issue_ref,
            "status": str(raw.get("status") or RUNNING_STATUS),
            "engine": _iso(raw.get("engine")),
            "worker_role": _pick(raw, "worker_role"),
            "started_at": _iso(raw.get("started_at")),
            "finished_at": _iso(raw.get("finished_at")),
            "sources": [STORE_SESSION],
            "conflict": None,
        }
        if summary["status"] not in KNOWN_STATUSES:
            summary["status"] = "unknown"
        if existing is None:
            merged[run_id] = summary
            continue
        if not _agree(existing, summary, "status"):
            merged[run_id] = {
                "run_id": run_id,
                "issue_ref": issue_ref,
                "status": CONFLICT_STATUS,
                "engine": existing.get("engine") if existing.get("engine") is not None else summary.get("engine"),
                "worker_role": existing.get("worker_role") if existing.get("worker_role") is not None else summary.get("worker_role"),
                "started_at": existing.get("started_at") if existing.get("started_at") is not None else summary.get("started_at"),
                "finished_at": existing.get("finished_at") if existing.get("finished_at") is not None else summary.get("finished_at"),
                "sources": sorted({STORE_DISPATCHER, STORE_SESSION}),
                "conflict": {
                    "field": "status",
                    "values": [existing["status"], summary["status"]],
                },
            }
            continue
        # Agreement: merge provenance and prefer the non-null terminal fields.
        merged[run_id] = {
            "run_id": run_id,
            "issue_ref": issue_ref,
            "status": existing["status"],
            "engine": existing.get("engine") if existing.get("engine") is not None else summary.get("engine"),
            "worker_role": existing.get("worker_role") if existing.get("worker_role") is not None else summary.get("worker_role"),
            "started_at": existing.get("started_at") if existing.get("started_at") is not None else summary.get("started_at"),
            "finished_at": existing.get("finished_at") if existing.get("finished_at") is not None else summary.get("finished_at"),
            "sources": sorted({STORE_DISPATCHER, STORE_SESSION}),
            "conflict": None,
        }
    return sorted(merged.values(), key=lambda item: item["run_id"], reverse=True)


def run_summaries_projection(issue_ref: str, summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Wrap correlated summaries in the content-free ``run.summaries.v1`` envelope."""
    items = []
    for summary in summaries:
        items.append({
            "run_id": str(summary["run_id"]),
            "issue_ref": str(summary["issue_ref"]),
            "status": str(summary["status"]),
            "engine": summary.get("engine"),
            "worker_role": summary.get("worker_role"),
            "started_at": summary.get("started_at"),
            "finished_at": summary.get("finished_at"),
            "sources": [str(s) for s in summary.get("sources") or []],
            "conflict": (
                {"field": str(summary["conflict"]["field"]),
                 "values": [v for v in summary["conflict"]["values"]]}
                if summary.get("conflict") else None
            ),
        })
    return {"schema_version": 1, "issue_ref": issue_ref, "runs": items}