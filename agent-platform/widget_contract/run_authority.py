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
  disagree on the same ``run_id``'s status OR terminal timestamp.

Runs are immutable summaries: a retry creates a new ``run_id`` and never
overwrites an earlier record. No prompt, reasoning, secret, or artifact
content ever enters a summary.

The MCP/session-event run shape mirrors ``cortxt_mcp/run_lifecycle.py``:
``run.running`` carries ``started_at``; the terminal result is the last
``run.engine_turn`` (payload ``status``); ``run.review_submitted`` is the
post-terminal review state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

STORE_DISPATCHER = "dispatcher.runs"
STORE_SESSION = "session.events"
KNOWN_STORES = (STORE_DISPATCHER, STORE_SESSION)

RUNNING_STATUS = "in_progress"
CONFLICT_STATUS = "conflict"
KNOWN_STATUSES = frozenset(
    {"in_progress", "succeeded", "failed", "timed_out", "budget_exceeded",
     "blocked", "cancelled", "review_submitted", "conflict", "unknown"}
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
        "heartbeat_at": _timestamp(_pick(run, "heartbeat_at", "finished_at", "claimed_at")),
        "sources": [STORE_DISPATCHER],
        "conflict": None,
    }


def summaries_from_sessions(session_docs: Sequence[Mapping[str, Any]], issue_ref: str) -> list[dict[str, Any]]:
    """Extract Run summaries from loaded session-event documents.

    A session represents a run when its ``session.created`` payload carries a
    ``run_id`` and an ``issue_id``/``issue_ref`` matching ``issue_ref`` exactly.
    ``started_at`` comes from ``run.running``; terminal status is the last
    ``run.engine_turn`` status, or ``review_submitted`` after review sync. An
    unfinished run is ``in_progress``. Fields that are absent stay absent.
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

        started_at = _iso(created.get("timestamp"))
        for event in events:
            if not isinstance(event, Mapping):
                continue
            if str(event.get("event_type") or "") == "run.running":
                epayload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
                started_at = _iso(epayload.get("started_at")) or started_at
                break

        status = RUNNING_STATUS
        finished_at = None
        for event in reversed(events):
            if not isinstance(event, Mapping):
                continue
            etype = str(event.get("event_type") or "")
            epayload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            if etype == "run.review_submitted":
                status = "review_submitted"
                finished_at = _iso(event.get("timestamp"))
                break
            if etype == "run.engine_turn":
                candidate = epayload.get("status")
                status = candidate if (isinstance(candidate, str) and candidate in KNOWN_STATUSES) else "unknown"
                finished_at = _iso(event.get("timestamp"))
                break
            if etype == "run.running":
                break

        last_event_ts = None
        for event in reversed(events):
            if isinstance(event, Mapping) and _iso(event.get("timestamp")):
                last_event_ts = _iso(event.get("timestamp"))
                break

        summaries.append({
            "run_id": str(run_id),
            "issue_ref": issue_ref,
            "status": status,
            "engine": _iso(_pick(payload, "runtime", "engine_id")),
            "worker_role": _pick(payload, "worker_role", "profile"),
            "started_at": started_at,
            "finished_at": finished_at,
            "heartbeat_at": finished_at or last_event_ts or started_at,
            "sources": [STORE_SESSION],
            "conflict": None,
        })
    return summaries


def _epoch(value: Any) -> float | None:
    """Best-effort parse of an ISO-8601 string (or epoch number) to a POSIX
    timestamp. Returns None when the value is absent or unparseable -- a
    caller treating None as 'no fresh signal' fails closed, never guesses."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                parsed = datetime.strptime(value.rstrip("Z"), fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _newest(*values: Any) -> str | None:
    """The ISO string among `values` with the largest parsed timestamp."""
    best_iso: str | None = None
    best_epoch: float | None = None
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        epoch = _epoch(value)
        if epoch is None:
            continue
        if best_epoch is None or epoch > best_epoch:
            best_epoch, best_iso = epoch, value
    return best_iso


def _agree(a: dict[str, Any], b: dict[str, Any], field: str) -> bool:
    left, right = a.get(field), b.get(field)
    if left is None or right is None:
        return True  # an unknown side cannot contradict the other
    return left == right


def _merged_tail(existing: dict[str, Any], summary: dict[str, Any], *,
                 status: str, conflict: dict[str, Any] | None) -> dict[str, Any]:
    """The fields shared by agreement and conflict outcomes, with provenance resolved."""
    return {
        "run_id": existing["run_id"],
        "issue_ref": existing["issue_ref"],
        "status": status,
        "engine": existing.get("engine") if existing.get("engine") is not None else summary.get("engine"),
        "worker_role": existing.get("worker_role") if existing.get("worker_role") is not None else summary.get("worker_role"),
        "started_at": existing.get("started_at") if existing.get("started_at") is not None else summary.get("started_at"),
        "finished_at": existing.get("finished_at") if existing.get("finished_at") is not None else summary.get("finished_at"),
        "heartbeat_at": _newest(existing.get("heartbeat_at"), summary.get("heartbeat_at")),
        "sources": sorted({STORE_DISPATCHER, STORE_SESSION}),
        "conflict": conflict,
    }


def _conflict_tail(existing: dict[str, Any], summary: dict[str, Any],
                   field: str, values: list[str]) -> dict[str, Any]:
    return _merged_tail(existing, summary, status=CONFLICT_STATUS,
                        conflict={"field": field, "values": values})


def correlate_run_summaries(
    issue_ref: str,
    dispatcher_runs: Mapping[str, Any],
    session_runs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge the two stores' summaries by exact ``run_id`` without silent merge.

    Returns a list (newest-``run_id`` first, cosmetic) of immutable summaries.
    A run present in one store carries that store in ``sources``; a run present
    in both and in agreement merges ``sources``; a run present in both that
    disagrees on ``status`` or on a shared terminal ``finished_at`` is rendered
    as ``conflict`` with both values listed, never resolved.
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
            "heartbeat_at": _iso(raw.get("heartbeat_at")) or _iso(raw.get("finished_at")) or _iso(raw.get("started_at")),
            "sources": [STORE_SESSION],
            "conflict": None,
        }
        if summary["status"] not in KNOWN_STATUSES:
            summary["status"] = "unknown"
        if existing is None:
            merged[run_id] = summary
            continue
        if not _agree(existing, summary, "status"):
            merged[run_id] = _conflict_tail(existing, summary, "status",
                                            [existing["status"], summary["status"]])
            continue
        if (existing.get("finished_at") is not None and summary.get("finished_at") is not None
                and existing["finished_at"] != summary["finished_at"]):
            merged[run_id] = _conflict_tail(existing, summary, "finished_at",
                                            [existing["finished_at"], summary["finished_at"]])
            continue
        merged[run_id] = _merged_tail(existing, summary, status=existing["status"], conflict=None)
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
            "heartbeat_at": summary.get("heartbeat_at"),
            "sources": [str(s) for s in summary.get("sources") or []],
            "conflict": (
                {"field": str(summary["conflict"]["field"]),
                 "values": [v for v in summary["conflict"]["values"]]}
                if summary.get("conflict") else None
            ),
        })
    return {"schema_version": 1, "issue_ref": issue_ref, "runs": items}


# --- S7c (#472): freshness, terminal, activity, and review projections -----
#
# All of the below are content-free: they read durable summaries and durable
# session events only, and never copy a prompt, model reasoning, secret, raw
# log line, or artifact body into an output. Every rendered result is bound to
# an exact ``issue_ref`` + ``run_id``; a caller that cannot find that exact
# pair must fail closed rather than fall back to an unrelated run.

FRESHNESS_FRESH = "fresh"
FRESHNESS_STALE = "stale"
FRESHNESS_STRANDED = "stranded_running"
FRESHNESS_TERMINAL = "terminal"
FRESHNESS_UNAVAILABLE = "unavailable"
FRESHNESS_STATES = frozenset({
    FRESHNESS_FRESH, FRESHNESS_STALE, FRESHNESS_STRANDED,
    FRESHNESS_TERMINAL, FRESHNESS_UNAVAILABLE,
})

TERMINAL_RUN_STATUSES = frozenset({
    "succeeded", "failed", "timed_out", "budget_exceeded", "blocked",
    "cancelled", "review_submitted",
})
ACTIVE_RUN_STATUSES = frozenset({"in_progress", "conflict", "unknown"})

_ACTIVITY_EVENT_TYPES = ("run.created", "run.running", "run.engine_turn", "run.review_submitted")

# A running claim with no signal newer than this is stale; older than the
# stranded bound it is a stranded-running claim (claims to run, nothing moved).
DEFAULT_RUNNING_STALE_SECONDS = 30
DEFAULT_RUNNING_STRANDED_SECONDS = 900


def compute_run_freshness(
    summaries: Sequence[Mapping[str, Any]],
    *,
    now_iso: str,
    running_stale_seconds: int = DEFAULT_RUNNING_STALE_SECONDS,
    running_stranded_seconds: int = DEFAULT_RUNNING_STRANDED_SECONDS,
) -> dict[str, Any]:
    """Classify the live-ness of an issue's correlated Run summaries (AC3).

    ``fresh``            no runs, or a running claim with a recent signal.
    ``stale``            a running claim whose newest signal is past the stale
                         bound but not yet stranded.
    ``stranded_running`` a claim that says ``in_progress`` but has produced no
                         signal for longer than the stranded bound (or none at
                         all).
    ``terminal``         every run for the issue has reached a terminal state.
    ``unavailable``      ``now`` could not be resolved (caller fails closed).
    """
    now_epoch = _epoch(now_iso)
    if now_epoch is None:
        return {"status": FRESHNESS_UNAVAILABLE, "age_seconds": 0, "complete": False}

    items = [s for s in (summaries or []) if isinstance(s, Mapping)]
    if not items:
        return {"status": FRESHNESS_FRESH, "age_seconds": 0, "complete": True}

    active = [s for s in items if str(s.get("status")) in ACTIVE_RUN_STATUSES]
    if active:
        signals: list[float] = []
        for s in active:
            for key in ("heartbeat_at", "started_at"):
                epoch = _epoch(s.get(key))
                if epoch is not None:
                    signals.append(epoch)
                    break
        if not signals:
            return {"status": FRESHNESS_STRANDED, "age_seconds": 0, "complete": False}
        age = max(0, int(now_epoch - max(signals)))
        if age <= running_stale_seconds:
            status = FRESHNESS_FRESH
        elif age <= running_stranded_seconds:
            status = FRESHNESS_STALE
        else:
            status = FRESHNESS_STRANDED
        return {"status": status, "age_seconds": age, "complete": False}

    finishes = [e for e in (_epoch(s.get("finished_at")) for s in items) if e is not None]
    age = max(0, int(now_epoch - max(finishes))) if finishes else 0
    return {"status": FRESHNESS_TERMINAL, "age_seconds": age, "complete": True}


def _find_session_doc(session_docs: Sequence[Mapping[str, Any]], run_id: str) -> Mapping[str, Any] | None:
    for doc in session_docs or []:
        if not isinstance(doc, Mapping):
            continue
        events = doc.get("events")
        if not isinstance(events, list) or not events:
            continue
        created = events[0] if isinstance(events[0], Mapping) else {}
        payload = created.get("payload") if isinstance(created.get("payload"), Mapping) else {}
        if str(payload.get("run_id")) == run_id:
            return doc
    return None


def _last_event_payload(doc: Mapping[str, Any], event_type: str) -> dict[str, Any]:
    for event in reversed(doc.get("events") or []):
        if isinstance(event, Mapping) and str(event.get("event_type")) == event_type:
            payload = event.get("payload")
            return dict(payload) if isinstance(payload, Mapping) else {}
    return {}


def _safe_evidence_entry(item: Any) -> dict[str, Any]:
    """A content-free projection of one evidence entry: only a kind label and
    an opaque reference/hash survive; free text, log bodies, and reasoning are
    dropped entirely (AC5)."""
    out: dict[str, Any] = {}
    if isinstance(item, Mapping):
        kind = item.get("kind") or item.get("type")
        if isinstance(kind, str) and kind:
            out["kind"] = kind
        ref = item.get("ref") or item.get("path") or item.get("name") or item.get("id")
        if isinstance(ref, str) and ref:
            out["ref"] = ref
        sha = item.get("sha256")
        if isinstance(sha, str) and sha:
            out["sha256"] = sha
    return out or {"kind": "unknown"}


def _safe_artifact_entry(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str) and item:
        return {"ref": item, "sha256": None}
    if isinstance(item, Mapping) and isinstance(item.get("ref"), str) and item["ref"]:
        sha = item.get("sha256")
        return {"ref": item["ref"], "sha256": sha if isinstance(sha, str) and sha else None}
    return None


def _safe_error(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    category = value.get("category") or value.get("kind") or "error"
    message = value.get("message") or value.get("detail") or ""
    if not message and not value.get("category") and not value.get("kind"):
        return None
    return {"category": str(category), "message": str(message)}


def run_terminal_projection(
    issue_ref: str,
    run_id: str,
    summaries: Sequence[Mapping[str, Any]],
    session_docs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Content-free ``run.terminal.v1`` for one exact issue+run (AC4).

    Returns None when no correlated summary matches ``issue_ref``+``run_id``
    exactly (the caller fails closed). Missing cost is ``unknown`` with a null
    amount -- never ``0`` by assumption.
    """
    summary = next(
        (s for s in summaries or []
         if isinstance(s, Mapping)
         and str(s.get("run_id")) == run_id
         and str(s.get("issue_ref")) == issue_ref),
        None,
    )
    if summary is None:
        return None

    doc = _find_session_doc(session_docs, run_id)
    turn = _last_event_payload(doc, "run.engine_turn") if doc else {}
    created = _last_event_payload(doc, "run.created") if doc else {}

    cost_status = turn.get("cost_status")
    if cost_status not in ("actual", "estimated", "unknown"):
        cost_status = "unknown"
    raw_cost = turn.get("cost")
    if cost_status in ("actual", "estimated") and isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool):
        cost: float | None = float(raw_cost)
    else:
        cost, cost_status = None, "unknown"

    artifacts = []
    for item in turn.get("artifacts") or []:
        entry = _safe_artifact_entry(item)
        if entry is not None:
            artifacts.append(entry)
    evidence = [_safe_evidence_entry(item) for item in turn.get("evidence") or []]
    error = _safe_error(turn.get("error"))

    return {
        "schema_version": 1,
        "issue_ref": issue_ref,
        "run_id": run_id,
        "status": str(summary.get("status")),
        "engine": summary.get("engine") or _iso(turn.get("engine_id")) or _iso(created.get("engine_id")),
        "worker_role": summary.get("worker_role"),
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at") or _iso(turn.get("finished_at")),
        "provider": _iso(turn.get("provider")) or _iso(created.get("provider")),
        "model": _iso(turn.get("model")) or _iso(created.get("model")),
        "usage": turn.get("usage") if isinstance(turn.get("usage"), Mapping) else {},
        "cost": cost,
        "cost_currency": "USD",
        "cost_status": cost_status,
        "artifacts": artifacts,
        "evidence": evidence,
        "error": error,
        "incomplete": (not artifacts) or (not evidence) or cost_status == "unknown" or error is not None,
        "conflicting": bool(summary.get("conflict")),
    }


def run_activity_projection(
    issue_ref: str,
    run_id: str,
    session_docs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Content-free ``run.activity.v1`` timeline from durable events (AC5).

    Only the four durable run event types appear; each item carries an event
    type, a timestamp, and a small whitelist of structural counts/labels.
    Prompts, scope text, reasoning, result bodies, and logs are never read.
    """
    doc = _find_session_doc(session_docs, run_id)
    items: list[dict[str, Any]] = []
    if doc is not None:
        for index, event in enumerate(doc.get("events") or []):
            if not isinstance(event, Mapping):
                continue
            etype = str(event.get("event_type"))
            if etype not in _ACTIVITY_EVENT_TYPES:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            detail: dict[str, Any] = {}
            if etype == "run.engine_turn":
                if isinstance(payload.get("status"), str):
                    detail["status"] = payload["status"]
                if isinstance(payload.get("cost_status"), str):
                    detail["cost_status"] = payload["cost_status"]
                arts = payload.get("artifacts")
                detail["artifact_count"] = len(arts) if isinstance(arts, list) else 0
                evs = payload.get("evidence")
                detail["evidence_count"] = len(evs) if isinstance(evs, list) else 0
                if isinstance(payload.get("engine_id"), str):
                    detail["engine"] = payload["engine_id"]
            elif etype == "run.review_submitted":
                if isinstance(payload.get("review_kind"), str):
                    detail["review_kind"] = payload["review_kind"]
                if isinstance(payload.get("result_status"), str):
                    detail["result_status"] = payload["result_status"]
            seq = event.get("sequence")
            items.append({
                "seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else index,
                "event_type": etype,
                "timestamp": _iso(event.get("timestamp")),
                "detail": detail,
            })
    return {"schema_version": 1, "issue_ref": issue_ref, "run_id": run_id if doc is not None else None,
            "items": items}


def review_submissions_from_sessions(
    session_docs: Sequence[Mapping[str, Any]],
    issue_ref: str,
) -> list[dict[str, Any]]:
    """Content-free facts about durable ``run.review_submitted`` events for an
    exact issue. The OS renders these; it never creates them and never marks
    an issue done."""
    out: list[dict[str, Any]] = []
    for doc in session_docs or []:
        if not isinstance(doc, Mapping):
            continue
        events = doc.get("events")
        if not isinstance(events, list) or not events:
            continue
        created = events[0] if isinstance(events[0], Mapping) else {}
        payload = created.get("payload") if isinstance(created.get("payload"), Mapping) else {}
        if str(_pick(payload, "issue_id", "issue_ref")) != issue_ref:
            continue
        run_id = payload.get("run_id")
        for event in events:
            if not isinstance(event, Mapping) or str(event.get("event_type")) != "run.review_submitted":
                continue
            ep = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            out.append({
                "review_submission_id": str(ep.get("review_submission_id") or ""),
                "review_kind": str(ep.get("review_kind") or "independent"),
                "result_status": _iso(ep.get("result_status")),
                "submitted_at": _iso(ep.get("submitted_at")) or _iso(event.get("timestamp")),
                "run_id": str(run_id) if run_id else None,
                "idempotency_key_present": bool(ep.get("idempotency_key")),
            })
    return out


def run_review_projection(issue_ref: str, session_docs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "issue_ref": issue_ref,
        "submissions": review_submissions_from_sessions(session_docs, issue_ref),
    }