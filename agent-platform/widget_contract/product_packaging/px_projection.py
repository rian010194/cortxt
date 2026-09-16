"""PX read-only projection over the shared PackagingOpsApi (W-5, #617).

The FIRST extension of the packaging projection surface: a SECOND read-only
consumer of ``PackagingOpsApi.workstream()`` (ops_api.py) plus the W-2 record
views the API already exposes. It maps durable packaging records into PX-001's
neutral projection fields:

- ``source_category`` -- one neutral category per record type, so a PX client
  never learns the internal record-type strings;
- ``observation`` -- the Unknown-vs-Indeterminate distinction: ``unknown``
  marks a field the store cannot answer (the value is None -- absence is
  itself evidence, the store convention), while ``indeterminate`` marks a
  field the store DID answer but whose value does not decide the question
  (e.g. a decision whose verdict is not the one a yes/no reading needs);
- the three staleness axes per record: ``run_freshness`` (a completed
  operation or a delivered decision is fresh; anything pending is not),
  ``revision_status`` (``current`` when the record names the head revision,
  ``superseded`` otherwise), and ``run_provenance`` (``platform`` when the
  store carried the record with its own identity, ``unknown`` when a record
  arrived without one).

ZERO new domain logic: every digest, identity and validation is reused from
the W-2 modules through the API's own views -- this module computes nothing
canonical of its own. ZERO writes: read-only by construction, no store, no
GitHub mutation (ADR-048 -- GitHub is reference-only here), no route changes
(the action host is untouched).
"""

from __future__ import annotations

from typing import Any, Mapping

from .ops_api import (
    DECISION_TYPE,
    EVIDENCE_TYPE,
    OPERATION_TYPE,
    REVISION_TYPE,
)

PX_PROJECTION_SCHEMA_VERSION = 1

#: PX-001 neutral source categories: the record type a PX client sees.
SOURCE_REVISION = "packaging-revision"
SOURCE_OPERATION = "packaging-operation"
SOURCE_DECISION = "packaging-decision"
SOURCE_EVIDENCE = "packaging-evidence"

#: Observation values (Unknown-vs-Indeterminate): ``unknown`` = the store has
#: no answer (None); ``indeterminate`` = the store answered but the value does
#: not decide the projected question.
OBSERVATION_VALUE = "value"
OBSERVATION_UNKNOWN = "unknown"
OBSERVATION_INDETERMINATE = "indeterminate"

#: Staleness axes.
STALE_FRESH = "fresh"
STALE_COMPLETED = "completed"
STALE_PENDING = "pending"
STALE_CURRENT = "current"
STALE_SUPERSEDED = "superseded"
STALE_PLATFORM = "platform"
STALE_UNKNOWN = "unknown"

#: Statuses a committed operation may carry (the W-2 module's closed set).
DECIDED_VERDICTS = ("accepted", "rejected")

_SOURCE_BY_TYPE = {
    REVISION_TYPE: SOURCE_REVISION,
    OPERATION_TYPE: SOURCE_OPERATION,
    DECISION_TYPE: SOURCE_DECISION,
    EVIDENCE_TYPE: SOURCE_EVIDENCE,
}

#: The neutral projection fields every PX record carries.
PX_PROJECTION_FIELDS = (
    "px_record_type", "record_identity", "package_id", "issue_ref",
    "source_category", "observed", "run_freshness", "revision_status",
    "run_provenance",
)


class PXRecordError(ValueError):
    """A record view cannot be projected (never a store or identity error)."""


def _normalize_status(status: Any) -> str | None:
    """The operation status as the W-2 module defines it, or None."""
    if isinstance(status, str) and status:
        return status
    return None


def _normalize_verdict(verdict: Any) -> str | None:
    """The decision verdict as a content field, or None when absent."""
    if isinstance(verdict, str) and verdict:
        return verdict
    return None


def _record_staleness(record_type: str, view: Mapping[str, Any],
                      head_identity: str | None) -> dict:
    """The three staleness axes, derived only from the view's own fields."""
    if record_type == REVISION_TYPE:
        identity = view.get("revision_identity")
        return {"run_freshness": STALE_FRESH,
                "revision_status": (STALE_CURRENT if head_identity is not None
                                    and identity == head_identity
                                    else STALE_SUPERSEDED),
                "run_provenance": STALE_PLATFORM}
    if record_type == OPERATION_TYPE:
        status = _normalize_status(view.get("status"))
        # A completed operation is a fresh, finished run; anything pending is
        # not (the run_freshness axis reads the OPERATION's lifecycle, not a
        # wall clock -- the store carries no freshness timestamps beyond the
        # append order, and inventing one would be new domain logic).
        fresh = status == "committed"
        return {"run_freshness": STALE_COMPLETED if fresh else STALE_PENDING,
                "revision_status": STALE_CURRENT if fresh else STALE_SUPERSEDED,
                "run_provenance": (STALE_PLATFORM if view.get("identity") is not None
                                   else STALE_UNKNOWN)}
    if record_type == DECISION_TYPE:
        verdict = _normalize_verdict(view.get("verdict"))
        decided = verdict in DECIDED_VERDICTS
        return {"run_freshness": STALE_COMPLETED if decided else STALE_PENDING,
                "revision_status": STALE_CURRENT if decided else STALE_SUPERSEDED,
                "run_provenance": (STALE_PLATFORM if view.get("identity") is not None
                                   else STALE_UNKNOWN)}
    # Evidence: the entry exists exactly as appended; freshness is its own
    # presence, and its payload digest is not a revision so the axis is
    # indeterminate rather than a fabricated verdict.
    return {"run_freshness": STALE_COMPLETED,
            "revision_status": STALE_CURRENT,
            "run_provenance": STALE_PLATFORM}


def project_record(view: Mapping[str, Any], *,
                   head_revision_identity: str | None = None) -> dict:
    """Project ONE PackagingOpsApi record view into the neutral PX shape.

    ``view`` is a list/get view from the API (``_envelope_view`` fields plus
    the record-type fields). Nothing here mutates the view, the store, or any
    client surface; the projection adds no identity, digest or schema rules of
    its own -- it renames and annotates what the API already answered.
    """
    record_type = view.get("record_type")
    source_category = _SOURCE_BY_TYPE.get(record_type)
    if source_category is None:
        raise PXRecordError(f"record view is not a packaging record: "
                            f"{record_type!r}")
    observed = view.get("revision") if record_type == REVISION_TYPE else \
        view.get("operation") if record_type == OPERATION_TYPE else \
        view.get("decision") if record_type == DECISION_TYPE else \
        view.get("entry")
    if observed is None:
        # The store could not answer with a record body at all: Unknown, the
        # absence-is-evidence arm, never a fabricated default.
        observation = OBSERVATION_UNKNOWN
    elif record_type == DECISION_TYPE and \
            _normalize_verdict(view.get("verdict")) not in DECIDED_VERDICTS:
        # The store answered, but the verdict does not decide the projected
        # question: Indeterminate, a distinct value -- collapsing it into
        # Unknown would erase an answer the operator can still read.
        observation = OBSERVATION_INDETERMINATE
    else:
        observation = OBSERVATION_VALUE
    projected = {
        "px_record_type": "px-packaging-record",
        "record_identity": view.get("identity"),
        "package_id": (view.get("package_id") or observed.get("package_id")
                       if isinstance(observed, Mapping) else view.get("package_id")),
        "issue_ref": view.get("issue_ref"),
        "source_category": source_category,
        "observed": observation,
    }
    if record_type == OPERATION_TYPE:
        projected["operation_status"] = _normalize_status(view.get("status"))
    if record_type == DECISION_TYPE:
        projected["verdict"] = _normalize_verdict(view.get("verdict"))
    if record_type == EVIDENCE_TYPE:
        projected["entry_id"] = view.get("entry_id")
    projected.update(_record_staleness(record_type, view, head_revision_identity))
    return projected


def project_workstream(ops_api: Any) -> dict:
    """Project the shared workstream plus its records for PX-001.

    ``ops_api`` is a PackagingOpsApi. Reads ONLY: workstream(), the four list
    views and head_revision() -- the same surface the web action host and the
    TUI already consume. The head revision identity anchors the
    ``revision_status`` axis of every projected record.
    """
    workstream = ops_api.workstream()
    revisions = ops_api.list_revisions()
    # head_revision needs a package_id; with no package filter the
    # latest-appended revision is the projection's reference point.
    head = revisions[-1] if revisions else None
    head_identity = head.get("revision_identity") if head else None
    views = [project_record(view, head_revision_identity=head_identity)
             for view in revisions]
    views += [project_record(view, head_revision_identity=head_identity)
              for view in ops_api.list_operations()]
    views += [project_record(view, head_revision_identity=head_identity)
              for view in ops_api.list_decisions()]
    views += [project_record(view, head_revision_identity=head_identity)
              for view in ops_api.list_evidence()]
    return {"schema_version": PX_PROJECTION_SCHEMA_VERSION, "status": "ok",
            "workstream": workstream.get("workstream"),
            "store_backup_status": workstream.get("store_backup_status"),
            "head_revision_identity": head_identity,
            "counts": workstream.get("counts"), "records": views}


__all__ = [
    "DECIDED_VERDICTS",
    "OBSERVATION_INDETERMINATE",
    "OBSERVATION_UNKNOWN",
    "OBSERVATION_VALUE",
    "PXRecordError",
    "PX_PROJECTION_FIELDS",
    "PX_PROJECTION_SCHEMA_VERSION",
    "SOURCE_DECISION",
    "SOURCE_EVIDENCE",
    "SOURCE_OPERATION",
    "SOURCE_REVISION",
    "STALE_COMPLETED",
    "STALE_CURRENT",
    "STALE_FRESH",
    "STALE_PENDING",
    "STALE_PLATFORM",
    "STALE_SUPERSEDED",
    "STALE_UNKNOWN",
    "project_record",
    "project_workstream",
]
