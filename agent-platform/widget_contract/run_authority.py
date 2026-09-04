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
FRESHNESS_INDETERMINATE = "indeterminate"
FRESHNESS_STATES = frozenset({
    FRESHNESS_FRESH, FRESHNESS_STALE, FRESHNESS_STRANDED,
    FRESHNESS_TERMINAL, FRESHNESS_UNAVAILABLE, FRESHNESS_INDETERMINATE,
})

TERMINAL_RUN_STATUSES = frozenset({
    "succeeded", "failed", "timed_out", "budget_exceeded", "blocked",
    "cancelled", "review_submitted",
})
ACTIVE_RUN_STATUSES = frozenset({"in_progress"})
# Statuses that say the authority itself is unresolved rather than saying
# anything about the Run (#507). `conflict` is two stores disagreeing, which is
# deliberately never silently resolved; `unknown` is a status this projection
# could not recognise. Neither used to be distinguishable from a live claim --
# both sat in ACTIVE_RUN_STATUSES and so aged into `stranded_running`, which is
# the state that offers recovery. Unresolved provenance must fail closed, not
# permissively, so they now yield `indeterminate` and no recovery is derived
# from them at all.
UNRESOLVED_RUN_STATUSES = frozenset({"conflict", "unknown"})

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
    ``indeterminate``    a run's provenance is unresolved -- two stores disagree
                         (``conflict``) or a status could not be recognised
                         (``unknown``). Nothing about liveness is established,
                         and the caller fails closed (#507).
    """
    now_epoch = _epoch(now_iso)
    if now_epoch is None:
        return {"status": FRESHNESS_UNAVAILABLE, "age_seconds": 0, "complete": False}

    items = [s for s in (summaries or []) if isinstance(s, Mapping)]
    if not items:
        return {"status": FRESHNESS_FRESH, "age_seconds": 0, "complete": True}

    # Unresolved provenance is decided before any time bound, because a time
    # bound applied to a Run nobody agrees about produces a confident answer
    # out of a disagreement (#507). A recorded `conflict` tail counts even when
    # the merged status itself looks ordinary.
    if any(str(s.get("status")) in UNRESOLVED_RUN_STATUSES or s.get("conflict") is not None
           for s in items):
        return {"status": FRESHNESS_INDETERMINATE, "age_seconds": 0, "complete": False}

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


def _find_session_doc(
    session_docs: Sequence[Mapping[str, Any]], issue_ref: str, run_id: str,
) -> Mapping[str, Any] | None:
    for doc in session_docs or []:
        if not isinstance(doc, Mapping):
            continue
        events = doc.get("events")
        if not isinstance(events, list) or not events:
            continue
        created = events[0] if isinstance(events[0], Mapping) else {}
        payload = created.get("payload") if isinstance(created.get("payload"), Mapping) else {}
        if (str(payload.get("run_id")) == run_id
                and str(_pick(payload, "issue_id", "issue_ref")) == issue_ref):
            return doc
    return None


def _last_event_payload(doc: Mapping[str, Any], event_type: str) -> dict[str, Any]:
    for event in reversed(doc.get("events") or []):
        if isinstance(event, Mapping) and str(event.get("event_type")) == event_type:
            payload = event.get("payload")
            return dict(payload) if isinstance(payload, Mapping) else {}
    return {}


def _safe_reference(value: Any) -> str | None:
    """Accept opaque/stable identifiers, never filesystem-looking paths."""
    if not isinstance(value, str) or not value:
        return None
    if "\\" in value or value.startswith(("/", "./", "../")) or "/../" in value:
        return None
    if len(value) >= 3 and value[1:3] in (":/", ":\\"):
        return None
    return value


def _safe_token(value: Any, fallback: str | None = None) -> str | None:
    if isinstance(value, str) and value and all(
            char.isalnum() or char in "._:-" for char in value):
        return value
    return fallback


def _safe_usage(value: Any) -> dict[str, Any]:
    """Usage is structural numeric telemetry, never provider text."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        safe_key = _safe_token(key)
        if safe_key is None:
            continue
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            result[safe_key] = item
        elif isinstance(item, Mapping):
            result[safe_key] = _safe_usage(item)
    return result


def _safe_evidence_entry(item: Any) -> dict[str, Any]:
    """A content-free projection of one evidence entry: only a kind label and
    an opaque reference/hash survive; free text, log bodies, and reasoning are
    dropped entirely (AC5)."""
    out: dict[str, Any] = {}
    if isinstance(item, Mapping):
        kind = _safe_token(item.get("kind") or item.get("type"))
        if kind is not None:
            out["kind"] = kind
        ref = _safe_reference(item.get("ref") or item.get("id"))
        if ref is not None:
            out["ref"] = ref
        sha = item.get("sha256")
        if isinstance(sha, str) and sha:
            out["sha256"] = sha
    return out or {"kind": "unknown"}


def _safe_artifact_entry(item: Any) -> dict[str, Any] | None:
    ref = _safe_reference(item)
    if ref is not None:
        return {"ref": ref, "sha256": None}
    if isinstance(item, Mapping) and _safe_reference(item.get("ref")) is not None:
        sha = item.get("sha256")
        return {"ref": item["ref"], "sha256": sha if isinstance(sha, str) and sha else None}
    return None


_MESSAGE_MAX = 400


def _safe_message(value: Any) -> str:
    """A short authored explanation, or ``""``.

    The Evidence Gate's ``recovery`` strings are authored constants in
    ``scripts/commit_evidence.py`` -- never model output, never log bodies --
    so they are the one piece of prose this projection may carry. It is still
    filtered rather than trusted: anything that looks like a filesystem path
    (the ``worktree`` a gate failure could otherwise mention) is refused
    outright, on the same rule as ``_safe_reference``, and the result is
    length-capped. A rejected message degrades to ``""``, leaving the stable
    ``category`` as the operator's signal -- never to raw text.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    text = " ".join(value.split())
    if "\\" in text or "://" in text:
        return ""
    for token in text.split(" "):
        if token.startswith(("/", "./", "../")) or "/../" in token:
            return ""
        if len(token) >= 3 and token[1:3] in (":/", ":\\"):
            return ""
    return text[:_MESSAGE_MAX]


def _safe_error(value: Any) -> dict[str, str] | None:
    """Content-free ``{category, message}`` for a terminal Run.

    Before #499 slice 6a ``message`` was the error ``code`` alone, so a Run
    refused by the Evidence Gate -- whose envelope carries ``category``,
    ``recovery`` and ``detail`` but no ``code`` -- rendered as the bare
    ``commit_predates_run:`` with nothing after the colon. The operator could
    see that a refusal happened and not what to do about it. ``recovery`` is
    now preferred, falling back to the prior ``code`` behaviour so existing
    envelope shapes project exactly as they did.
    """
    if not isinstance(value, Mapping):
        return None
    category = _safe_token(value.get("category") or value.get("kind"), "error")
    code = value.get("code")
    message = _safe_message(value.get("recovery"))
    if not message:
        message = str(code) if isinstance(code, str) and code and all(
            char.isalnum() or char in "._:-" for char in code) else ""
    if not message and not value.get("category") and not value.get("kind"):
        return None
    return {"category": str(category), "message": str(message)}


def _safe_sha(value: Any) -> str | None:
    """A git object name, or ``None``. Never anything else."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if 7 <= len(text) <= 64 and all(char in "0123456789abcdefABCDEF" for char in text):
        return text
    return None


def _safe_path_list(value: Any) -> list[str]:
    """Repository-relative paths only, in recorded order, de-duplicated.

    ``_safe_reference`` already refuses absolute, drive-lettered, escaping and
    backslash paths, so an absolute worktree path can never enter the
    projection through this door.
    """
    out: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else ():
        ref = _safe_reference(item)
        if ref is not None and ref not in out:
            out.append(ref)
    return out


def _safe_commit_evidence(value: Any) -> dict[str, Any] | None:
    """Content-free projection of the durable ``commit_evidence`` record.

    Identifiers, repo-relative paths and timestamps survive; the absolute
    ``worktree`` path does not -- only the fact that one was registered, as
    ``worktree_recorded``. Nothing here reads a file, so no run-produced
    content can reach the browser through this projection (#499 slice 6a).
    """
    if not isinstance(value, Mapping):
        return None
    committed_at = value.get("committed_at")
    if not (isinstance(committed_at, int) and not isinstance(committed_at, bool)):
        committed_at = None
    return {
        "commit": _safe_sha(value.get("commit")),
        "branch": _safe_reference(value.get("branch")),
        "base_commit": _safe_sha(value.get("base_commit")),
        "committed_at": committed_at,
        "verified_at": _safe_reference(value.get("verified_at")),
        "contributed_commits": [sha for sha in
                                (_safe_sha(item) for item in
                                 (value.get("contributed_commits") or ()))
                                if sha is not None],
        "contributed_files": _safe_path_list(value.get("contributed_files")),
        "files": _safe_path_list(value.get("files")),
        "policy_paths": _safe_path_list(value.get("policy_paths")),
        "worktree_recorded": bool(value.get("worktree")),
    }


def _safe_evidence_gate(*candidates: Any) -> str | None:
    """The gate verdict from the first source that recorded one.

    An unrecognised value is ``None``: absence of a verdict is never a pass.
    """
    for candidate in candidates:
        if candidate in ("commit_correlated", "commit_correlation_failed"):
            return str(candidate)
    return None


# Per-file and whole-response ceilings for `run.diff.v1`. A review surface has
# to stay readable and the response has to stay a projection, not a file
# transfer; a patch past the ceiling is truncated with `truncated: True` rather
# than dropped, so the operator always sees that more exists.
# Measured in CHARACTERS, not bytes: the response is JSON text and slicing on
# a character boundary is what keeps a patch valid. Multibyte content therefore
# serializes larger than the nominal cap; the cap exists to keep a review
# surface readable, not to bound the socket.
_DIFF_FILE_MAX_CHARS = 60_000
_DIFF_TOTAL_MAX_CHARS = 400_000


def _gate_path_rules():
    """The Evidence Gate's own path rules, imported rather than re-implemented.

    `run.diff.v1` must withhold exactly what the gate would have refused, so it
    calls the gate's functions instead of keeping a second copy that could
    drift. They live in the repository-level `scripts/` directory, which the
    action host puts on `sys.path` lazily; this does the same so the projection
    is importable from a plain test as well.
    """
    import sys
    from pathlib import Path

    scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from commit_evidence import _within, normalize_repo_path
    return _within, normalize_repo_path


def _diff_git(worktree: str):
    """A git runner pinned to one registered worktree.

    Mirrors `scripts/commit_evidence._subprocess_git`: same bounded timeout,
    same `(code, stdout)` contract, and `cwd` is the worktree recorded on the
    durable Run -- never a path that came from the request.
    """
    import subprocess

    def run(args):
        try:
            proc = subprocess.run(["git", *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=30,
                                  cwd=worktree)
        except (OSError, subprocess.SubprocessError):
            # A worktree that has been removed, or a git that cannot run, is a
            # non-zero result like any other -- never an exception escaping into
            # a 500. The caller turns it into a stated reason.
            return 1, ""
        return proc.returncode, proc.stdout
    return run


def _unavailable(issue_ref: str, run_id: str, reason: str) -> dict[str, Any]:
    """The fail-closed answer: a stated reason and no content whatsoever."""
    return {"schema_version": 1, "issue_ref": issue_ref, "run_id": run_id,
            "available": False, "reason": reason, "base_commit": None,
            "commit": None, "branch": None, "contributed_commits": [], "files": []}


def run_diff_projection(
    issue_ref: str,
    run_id: str,
    dispatcher_store: Mapping[str, Any] | None = None,
    *,
    git_factory: Any = None,
) -> "dict[str, Any] | None":
    """The change a Run contributed, read from its own registered worktree (#499).

    The operator's final decision is about a change they did not watch happen.
    Metadata and a SHA are not that change, so this is the one read that returns
    run-produced content -- under every restriction the durable record already
    carries and none the request may relax:

    * The Run must correlate to this EXACT ``issue_ref`` + ``run_id``, like
      every other per-Run read.
    * The Evidence Gate must have ACCEPTED this Run. Only
      ``Dispatcher._gate_commit`` writes ``commit_evidence`` onto the durable
      Run record, and only on a pass. The worker's own result envelope is never
      read for it: a refused Run's envelope is copied forward verbatim
      (``scripts/dispatcher.py``), so a worker that put a ``commit_evidence``
      key in its envelope would otherwise have chosen the worktree this
      function runs git in. That is the whole gate, inverted.
    * ``commit``, ``base_commit``, ``branch`` and ``worktree`` come from that
      record. Nothing is taken from the caller but the pair identifying the Run.
    * The record must name this Run and this Issue. A record missing either is
      refused rather than assumed to match.
    * The commit must still be on the registered branch.
    * A patch is returned only for a file in ``contributed_files`` that is also
      inside the approved artifact policy. Any other file is reported
      ``withheld`` with its reason and no content.

    Every failure returns ``available: False`` with a stable reason rather than
    an empty diff, so "nothing to show" and "not allowed to show" can never be
    read as the same answer.
    """
    within, normalize_repo_path = _gate_path_rules()

    run = _dispatcher_run(dispatcher_store, issue_ref, run_id)
    if run is None:
        return None
    # Durable record only -- see the docstring. There is deliberately no
    # fallback to the result envelope.
    record = run.get("commit_evidence")
    if not isinstance(record, Mapping):
        return _unavailable(issue_ref, run_id, "no_commit_evidence")
    result = run.get("result") if isinstance(run.get("result"), Mapping) else {}
    if result.get("evidence_gate") != "commit_correlated":
        return _unavailable(issue_ref, run_id, "evidence_gate_did_not_pass")
    # A record that does not name this exact Run and Issue is never read for
    # them. Absent is refused too: a missing field must not compare equal.
    if _safe_reference(record.get("run_id")) != run_id:
        return _unavailable(issue_ref, run_id, "evidence_run_mismatch")
    if _safe_reference(record.get("issue_id")) != issue_ref:
        return _unavailable(issue_ref, run_id, "evidence_issue_mismatch")

    commit = _safe_sha(record.get("commit"))
    base_commit = _safe_sha(record.get("base_commit"))
    branch = _safe_reference(record.get("branch"))
    worktree = record.get("worktree")
    if not commit or not base_commit:
        return _unavailable(issue_ref, run_id, "no_correlated_commit")
    if not branch:
        return _unavailable(issue_ref, run_id, "no_registered_branch")
    if not isinstance(worktree, str) or not worktree.strip():
        return _unavailable(issue_ref, run_id, "no_registered_worktree")

    git = (git_factory or _diff_git)(worktree)
    # Separate "the worktree is gone" from "the commit left the branch": both
    # fail closed, but they mean different things to the operator and only one
    # of them is a reason to distrust the Run.
    code, _ = git(["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        return _unavailable(issue_ref, run_id, "worktree_unreadable")
    code, _ = git(["merge-base", "--is-ancestor", commit, "refs/heads/" + branch])
    if code != 0:
        return _unavailable(issue_ref, run_id, "commit_not_on_registered_branch")

    policy = [item for item in (record.get("policy_paths") or ()) if isinstance(item, str)]
    # Read RAW, not through `_safe_path_list`: that helper drops a path it
    # cannot vouch for, and a silently dropped path is exactly the failure this
    # read exists to prevent. An unsafe entry must be visible to the operator as
    # withheld, with its reason, rather than absent from the review.
    raw = record.get("contributed_files") or record.get("files") or ()
    contributed = [item for item in raw if isinstance(item, str) and item.strip()]

    files: list[dict[str, Any]] = []
    permitted: list[str] = []
    for path in contributed:
        normalized = normalize_repo_path(path)
        if normalized is None:
            files.append({"path": path, "withheld": True, "reason": "unsafe_path",
                          "patch": None, "truncated": False})
        # An unparsable or unscoped policy names nothing, which the gate treats
        # as fail-closed -- so it withholds here too, never opens up.
        elif not within(normalized, policy):
            files.append({"path": normalized, "withheld": True,
                          "reason": "outside_artifact_policy", "patch": None,
                          "truncated": False})
        elif normalized not in permitted:
            permitted.append(normalized)

    patches: dict[str, str] = {}
    if permitted:
        # ONE subprocess for the whole review, not one per file: this runs on a
        # single-threaded loopback host, and a Run with many contributed files
        # would otherwise hold it for the sum of their timeouts.
        code, out = git(["diff", base_commit + ".." + commit, "--", *permitted])
        if code != 0:
            for path in permitted:
                files.append({"path": path, "withheld": True,
                              "reason": "diff_unreadable", "patch": None,
                              "truncated": False})
            permitted = []
        else:
            patches = _split_diff(out, permitted)

    budget = _DIFF_TOTAL_MAX_CHARS
    for path in permitted:
        patch = patches.get(path)
        if patch is None:
            files.append({"path": path, "withheld": True,
                          "reason": "no_change_in_contributed_range",
                          "patch": None, "truncated": False})
            continue
        if budget <= 0:
            files.append({"path": path, "withheld": True,
                          "reason": "response_budget_exhausted", "patch": None,
                          "truncated": False})
            continue
        limit = min(_DIFF_FILE_MAX_CHARS, budget)
        truncated = len(patch) > limit
        patch = patch[:limit]
        budget -= len(patch)
        files.append({"path": path, "withheld": False, "reason": None,
                      "patch": patch, "truncated": truncated})

    return {
        "schema_version": 1, "issue_ref": issue_ref, "run_id": run_id,
        "available": True, "reason": None,
        "base_commit": base_commit, "commit": commit, "branch": branch,
        "contributed_commits": [sha for sha in
                                (_safe_sha(item) for item in
                                 (record.get("contributed_commits") or ()))
                                if sha is not None],
        "files": files,
    }


def _split_diff(output: str, permitted: "Sequence[str]") -> "dict[str, str]":
    """Split one ``git diff`` into per-file patches, keyed by permitted path.

    Only a path git names that was ALSO asked for is kept, so a header this
    parser misreads can never attribute content to a file outside the request.
    """
    wanted = list(permitted)
    chunks: dict[str, str] = {}
    current = None
    lines: list[str] = []
    for line in output.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current is not None:
                chunks[current] = "".join(lines)
            current, lines = None, []
            header = line.rstrip("\r\n")
            for path in wanted:
                if header.endswith(" b/" + path):
                    current = path
                    break
        if current is not None:
            lines.append(line)
    if current is not None:
        chunks[current] = "".join(lines)
    return chunks


def run_terminal_projection(
    issue_ref: str,
    run_id: str,
    summaries: Sequence[Mapping[str, Any]],
    session_docs: Sequence[Mapping[str, Any]],
    dispatcher_store: Mapping[str, Any] | None = None,
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

    doc = _find_session_doc(session_docs, issue_ref, run_id)
    dispatcher_run = (dispatcher_store or {}).get(run_id)
    if not (isinstance(dispatcher_run, Mapping)
            and str(dispatcher_run.get("issue_id")) == issue_ref):
        dispatcher_run = {}
    dispatcher_result = dispatcher_run.get("result") if isinstance(
        dispatcher_run.get("result"), Mapping) else {}
    turn = _last_event_payload(doc, "run.engine_turn") if doc else dict(dispatcher_result)
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
    raw_artifacts = turn.get("artifacts")
    for item in raw_artifacts if isinstance(raw_artifacts, list) else []:
        entry = _safe_artifact_entry(item)
        if entry is not None:
            artifacts.append(entry)
    raw_evidence = turn.get("evidence")
    evidence = [_safe_evidence_entry(item)
                for item in (raw_evidence if isinstance(raw_evidence, list) else [])]
    error = _safe_error(turn.get("error"))

    # The Evidence Gate's verdict and record (#499 slice 6a). Both are written
    # by `Dispatcher._gate_commit`: the verdict onto the result envelope, the
    # correlated record onto the durable Run as well. The envelope is read
    # first and the durable Run last, so the most specific source wins and a
    # record that outlives its envelope is still projected.
    evidence_gate = _safe_evidence_gate(turn.get("evidence_gate"),
                                        dispatcher_result.get("evidence_gate"),
                                        dispatcher_run.get("evidence_gate"))
    commit_evidence = _safe_commit_evidence(
        turn.get("commit_evidence")
        or dispatcher_result.get("commit_evidence")
        or dispatcher_run.get("commit_evidence"))

    return {
        "schema_version": 1,
        "issue_ref": issue_ref,
        "run_id": run_id,
        "status": str(summary.get("status")),
        "engine": summary.get("engine") or _iso(turn.get("engine_id")) or _iso(
            turn.get("runtime")) or _iso(created.get("engine_id")),
        "worker_role": summary.get("worker_role"),
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at") or _iso(turn.get("finished_at")),
        "provider": _iso(turn.get("provider")) or _iso(created.get("provider")),
        "model": _iso(turn.get("model")) or _iso(created.get("model")),
        "usage": _safe_usage(turn.get("usage")),
        "cost": cost,
        "cost_currency": "USD",
        "cost_status": cost_status,
        "artifacts": artifacts,
        "evidence": evidence,
        "error": error,
        "incomplete": (not artifacts) or (not evidence) or cost_status == "unknown" or error is not None,
        "conflicting": bool(summary.get("conflict")),
        "evidence_gate": evidence_gate,
        "commit_evidence": commit_evidence,
    }


def _dispatcher_run(dispatcher_store: Mapping[str, Any] | None, issue_ref: str,
                    run_id: str) -> Mapping[str, Any] | None:
    """The dispatcher record for this EXACT issue+run, or None."""
    run = (dispatcher_store or {}).get(run_id)
    if not isinstance(run, Mapping) or str(run.get("issue_id")) != issue_ref:
        return None
    return run


def _dispatcher_activity_items(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive the activity timeline from a durable dispatcher Run record.

    S7d (#473), closing #472 finding 5: the timeline used to read the
    MCP/session-event store only, while the launcher path writes exclusively to
    the dispatcher registry -- so every Run started from Work produced an empty
    activity feed even when it had committed code. These items are DERIVED, not
    durable events, and say so through ``source``; the claim/finish timestamps
    and the terminal result's own counts are the only facts read.
    """
    engine = _safe_token(run.get("runtime"))
    items: list[dict[str, Any]] = [{
        "seq": 0,
        "event_type": "run.created",
        "timestamp": _timestamp(run.get("claimed_at")),
        "detail": {"engine": engine} if engine else {},
        "source": STORE_DISPATCHER,
    }]
    status = str(run.get("status") or RUNNING_STATUS)
    if status not in TERMINAL_RUN_STATUSES:
        return items
    result = run.get("result") if isinstance(run.get("result"), Mapping) else {}
    detail: dict[str, Any] = {"status": status if status in KNOWN_STATUSES else "unknown"}
    cost_status = result.get("cost_status")
    if isinstance(cost_status, str):
        detail["cost_status"] = cost_status
    artifacts, evidence = result.get("artifacts"), result.get("evidence")
    detail["artifact_count"] = len(artifacts) if isinstance(artifacts, list) else 0
    detail["evidence_count"] = len(evidence) if isinstance(evidence, list) else 0
    if engine:
        detail["engine"] = engine
    items.append({
        "seq": 1,
        "event_type": "run.engine_turn",
        "timestamp": _timestamp(run.get("finished_at")),
        "detail": detail,
        "source": STORE_DISPATCHER,
    })
    return items


def run_activity_projection(
    issue_ref: str,
    run_id: str,
    session_docs: Sequence[Mapping[str, Any]],
    dispatcher_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Content-free ``run.activity.v1`` timeline from durable state (AC5).

    Durable session events are preferred when they exist. When they do not --
    the launcher path never writes them -- the timeline is derived from the
    dispatcher Run record instead, so a real Run is never rendered as "nothing
    happened" (#472 finding 5). Every item names the store it came from.

    Only the four durable run event types appear; each item carries an event
    type, a timestamp, and a small whitelist of structural counts/labels.
    Prompts, scope text, reasoning, result bodies, and logs are never read.
    """
    doc = _find_session_doc(session_docs, issue_ref, run_id)
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
                "source": STORE_SESSION,
            })
        return {"schema_version": 1, "issue_ref": issue_ref, "run_id": run_id, "items": items}

    run = _dispatcher_run(dispatcher_store, issue_ref, run_id)
    if run is None:
        return {"schema_version": 1, "issue_ref": issue_ref, "run_id": None, "items": []}
    return {"schema_version": 1, "issue_ref": issue_ref, "run_id": run_id,
            "items": _dispatcher_activity_items(run)}


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


# The dispatcher moves a top-level Run's issue to `workflow:review` on exactly
# these terminal statuses (scripts/dispatcher.py `_sync_github`: cancelled goes
# back to ready, FAILING_STATUSES go to blocked, everything else goes to
# review). `gh_synced` is set only once that label swap actually landed.
_DISPATCHER_REVIEW_STATUSES = frozenset({"succeeded", "review_submitted"})


def review_submissions_from_dispatcher(
    dispatcher_store: Mapping[str, Any] | None, issue_ref: str,
) -> list[dict[str, Any]]:
    """Review submissions the dispatcher's own label sync actually performed.

    S7d (#473), closing #472 findings 4 and 5: `run.review.v1` read the
    session-event store only, so an Issue the dispatcher had genuinely moved to
    `workflow:review` projected zero submissions and the label looked like it
    had moved outside the contract. The dispatcher's label swap IS the
    submission for the launcher path, and `gh_synced` is the durable proof it
    landed -- a run whose swap never happened is not claimed as submitted.
    """
    out: list[dict[str, Any]] = []
    for run in (dispatcher_store or {}).values():
        if not isinstance(run, Mapping) or str(run.get("issue_id")) != issue_ref:
            continue
        if str(run.get("status")) not in _DISPATCHER_REVIEW_STATUSES:
            continue
        if not run.get("gh_synced"):
            continue
        run_id = str(run.get("run_id") or "")
        out.append({
            "review_submission_id": f"dispatcher-sync:{run_id}",
            "review_kind": "dispatcher-label-sync",
            "result_status": str(run.get("status")),
            "submitted_at": _timestamp(run.get("finished_at")),
            "run_id": run_id or None,
            # The swap is guarded by the run's own gh-sync claim lease, which is
            # what makes it single-shot; there is no caller-supplied key.
            "idempotency_key_present": False,
            "source": STORE_DISPATCHER,
        })
    return sorted(out, key=lambda item: str(item["run_id"]))


def run_review_projection(issue_ref: str, session_docs: Sequence[Mapping[str, Any]],
                          dispatcher_store: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Content-free ``run.review.v1`` across every store that can hold one.

    ``sources`` names the stores actually consulted, so an empty result reads
    as "no submission recorded in these stores" rather than "unavailable" --
    the #472 report could not tell those two apart.
    """
    submissions = [dict(item, source=STORE_SESSION)
                   for item in review_submissions_from_sessions(session_docs, issue_ref)]
    sources = [STORE_SESSION]
    if dispatcher_store is not None:
        submissions = review_submissions_from_dispatcher(dispatcher_store, issue_ref) + submissions
        sources = sorted({STORE_DISPATCHER, STORE_SESSION})
    return {
        "schema_version": 1,
        "issue_ref": issue_ref,
        "sources": sources,
        "submissions": submissions,
    }
