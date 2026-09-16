"""Shared product-packaging operations API over the W-2 domain layer (W-3, #612).

This module is the composition boundary between the pure W-2a packaging
modules (``revision``, ``operation_record``, ``decision_slot``,
``evidence_store`` -- pure process logic, no storage) and the W-2b append-only
Core store (``state/core_store.py``). It adds NO digest logic, NO schema rules
and NO semantics of its own: every digest and validation is imported from the
W-2 modules, and every mutation is a single ``CoreStore.append`` whose
deterministic outcome envelope (``appended`` / ``re-delivery`` / ``conflict``)
is returned to the caller.

Store identities (the CAS key) are deterministic and typed:

    packaging-revision.<revision identity>
    packaging-operation.<operation_id>
    packaging-decision.<decision record identity>
    packaging-evidence.<evidence idempotency key>

Volatile timestamps are never part of a stored payload: the operation's
``recorded_at`` and the decision's ``recorded_at`` are transport-only and the
store envelope's canonical ``appended_at`` is the durable timestamp. This is
what makes a genuine retry deterministic: the same operation_id with the same
candidate content re-appends nothing and renders ``re-delivery``; different
content under the same identity renders an explicit ``conflict`` that is
never merged or overwritten (conflict-not-merge).

Read paths are pure reads over the store; mutation paths route through the
W-2 builders/validators (``build_revision`` is the caller's job, validation
happens here) and persist with the store's insert-if-absent semantics.
Evidence appends enforce the D4 request-binding guard (exact whole-string
equality between ``request_id`` and ``payload_digest``) at this boundary.

No GitHub or network calls: issue references are opaque strings validated by
the store (ADR-048 -- GitHub is reference-only for packaging records; the
store never syncs or reconciles with GitHub).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from state.core_store import CoreError, CoreStore, validate_identity

from ._digest import DigestError, normalize_digest
from .decision_slot import (
    OUTCOME_ACCEPTED,
    DecisionSlotError,
    build_decision_record,
    decision_identity_fields,
    decision_record_identity,
)
from .evidence_store import EvidenceError, check_request_binding, evidence_idempotency_key
from .operation_record import (
    OPERATION_FIELDS,
    STATUS_COMMITTED,
    OperationRecordError,
    make_operation_record,
    operation_outcome_identity,
)
from .revision import (
    REVISION_FIELDS,
    RevisionError,
    candidate_digest,
    revision_identity,
    validate_revision,
)

OPS_API_SCHEMA_VERSION = 1

REVISION_TYPE = "packaging-revision"
OPERATION_TYPE = "packaging-operation"
DECISION_TYPE = "packaging-decision"
EVIDENCE_TYPE = "packaging-evidence"

# The W-3 kriterium-oracle workstream (frozen plan section 3): one Packaging
# Workstream, visible in BOTH clients through this single projection. The
# identity fields (id/issue_id/number/title/outcome/url) reuse the existing
# Workstream model's keys; the W-3 fields carry the mandated
# mandate/objective/scope/non-goals/repo-refs. Client-side read/projection
# only: Workstream creation and workflow:* labels remain the external
# GitHub-mutating flow (ADR-048: GitHub is reference-only here).
PACKAGING_WORKSTREAM: dict[str, Any] = {
    "id": "WS-606",
    "issue_id": "rian010194/cortxt#606",
    "number": 606,
    "title": "Product packaging: revisions, operations, decisions, evidence",
    "outcome": ("A Packaging Workstream whose revisions, operation records, decision "
                "records and evidence are durable in the append-only Core store and "
                "visible in both the web action host and the TUI."),
    "url": "https://github.com/rian010194/cortxt/issues/606",
    "mandate": ("Deliver the shared product-packaging operations API over the merged "
                "W-2 domain layer plus both client surfaces: loopback web routes with "
                "guard-parity to POST /api/action and an interactive TUI lifecycle "
                "(W-3, issue 612)."),
    "objective": ("Every packaging mutation routes through the W-2 modules and returns "
                  "the Core store's insert-if-absent outcome envelope (appended / "
                  "re-delivery / conflict) with no duplicated digest logic and no "
                  "network calls."),
    "scope": [
        "Read: list/get revisions, operations, decisions and evidence over the Core store.",
        "Action: create-revision, record-operation, record-decision and append-evidence "
        "through the W-2 modules with insert-if-absent outcome envelopes.",
        "Clients: loopback web action-host routes (guard-parity with POST /api/action) "
        "and an interactive TUI lifecycle consuming the same API.",
    ],
    "non_goals": [
        "No GitHub mutation from the packaging clients (ADR-048: reference-only).",
        "No workflow:* label changes through the packaging ops-API (ADR-018 unchanged).",
        "No client-side Workstream creation: Workstream creation remains the external "
        "GitHub-mutating flow.",
    ],
    "repo_refs": [
        "rian010194/cortxt#606",
        "rian010194/cortxt#609",
        "rian010194/cortxt#612",
    ],
    "authority": {"source": "GitHub Issue",
                  "note": ("Client-side read/projection only; live workflow state stays "
                           "with the workflow:* labels the /api/workstreams projection "
                           "reads.")},
}


class OpsApiError(ValueError):
    """Fail-closed packaging ops-API rejection with a stable kind."""

    def __init__(self, message: str, *, kind: str = "invalid_input",
                 http_status: int = 400) -> None:
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status


_STATUS_BY_CATEGORY = {
    "invalid_input": 400,
    "unsafe_path": 400,
    "not_found": 404,
    "integrity_error": 503,
    "io_error": 503,
}


def _wrap_core(error: CoreError) -> OpsApiError:
    return OpsApiError(error.message, kind=error.category,
                       http_status=_STATUS_BY_CATEGORY.get(error.category, 400))


def _envelope_view(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """The store envelope fields a read-path caller may see (never the hash)."""
    return {
        "identity": envelope["identity"],
        "record_digest": envelope["record_digest"],
        "appended_at": envelope["appended_at"],
        "issue_ref": envelope["issue_ref"],
        "supersedes": envelope["supersedes"],
    }


def _typed_identity(prefix: str, suffix: str, *, field: str) -> str:
    """Compose and validate a typed store identity (fail-closed)."""
    identity = f"{prefix}.{suffix}"
    try:
        validate_identity(identity)
    except CoreError as exc:
        raise OpsApiError(f"{field}: {exc.message}", kind="invalid_input") from exc
    return identity


def _digest_identity(prefix: str, value: Any, *, field: str) -> str:
    """Typed store identity from a digest input (bare or sha256:-prefixed)."""
    if not isinstance(value, str) or not value:
        raise OpsApiError(f"{field} is required", kind="invalid_input")
    full = f"{prefix}."
    raw = value[len(full):] if value.startswith(full) else value
    try:
        normalized = normalize_digest(raw, field=field)
    except DigestError as exc:
        raise OpsApiError(str(exc), kind="invalid_input") from exc
    return f"{prefix}.{normalized}"


class PackagingOpsApi:
    """Shared read+action surface over the merged W-2 modules and Core store."""

    def __init__(self, store: CoreStore | str | Path) -> None:
        # A caller may hand over either a ready CoreStore or the durable
        # store ROOT (str/Path) to build one against -- both client surfaces
        # use the path form.
        if isinstance(store, (str, Path)):
            store = CoreStore(store)
        if not isinstance(store, CoreStore):
            raise OpsApiError("store must be a CoreStore or a store root path")
        self._store = store

    @property
    def store(self) -> CoreStore:
        return self._store

    # --- shared append helper --------------------------------------------

    def _append(self, payload: dict[str, Any], *, identity: str,
                issue_ref: str | None, subject_field: str,
                subject_value: Any) -> dict[str, Any]:
        try:
            envelope = self._store.append(payload, identity=identity, issue_ref=issue_ref)
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        # The store's outcome envelope, verbatim, plus the domain subject the
        # caller needs to chain further calls (never replacing store fields).
        return {**envelope, "record_type": payload["record_type"],
                subject_field: subject_value}

    # --- read paths (pure reads) -----------------------------------------

    def list_revisions(self, package_id: str | None = None) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        try:
            records = self._store.iter_records()
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        for envelope in records:
            payload = envelope["payload"]
            if payload.get("record_type") != REVISION_TYPE:
                continue
            revision = payload.get("revision")
            if not isinstance(revision, dict):
                raise OpsApiError("stored revision payload is malformed",
                                  kind="integrity_error", http_status=503)
            if package_id is not None and revision.get("package_id") != package_id:
                continue
            views.append(self._revision_view(envelope))
        views.sort(key=lambda view: (view["appended_at"], view["identity"]))
        return views

    def _revision_view(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        revision = envelope["payload"]["revision"]
        try:
            subject = revision_identity(revision)
        except RevisionError as exc:
            raise OpsApiError(f"stored revision is not canonicalizable: {exc}",
                              kind="integrity_error", http_status=503) from exc
        return {**_envelope_view(envelope),
                "record_type": REVISION_TYPE,
                "revision_identity": subject,
                "package_id": revision.get("package_id"),
                "parent_revision_identity": revision.get("parent_revision_identity"),
                "revision": revision}

    def get_revision(self, revision_identity_input: str) -> dict[str, Any] | None:
        identity = _digest_identity(REVISION_TYPE, revision_identity_input,
                                    field="revision_identity")
        try:
            envelope = self._store.get(identity)
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        return self._revision_view(envelope) if envelope is not None else None

    def head_revision(self, package_id: str) -> dict[str, Any] | None:
        """Latest-appended revision for a package (deterministic read order)."""
        revisions = self.list_revisions(package_id)
        return revisions[-1] if revisions else None

    def list_operations(self, package_id: str | None = None) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        try:
            records = self._store.iter_records()
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        for envelope in records:
            payload = envelope["payload"]
            if payload.get("record_type") != OPERATION_TYPE:
                continue
            operation = payload.get("operation")
            if not isinstance(operation, dict):
                raise OpsApiError("stored operation payload is malformed",
                                  kind="integrity_error", http_status=503)
            if package_id is not None and operation.get("package_id") != package_id:
                continue
            views.append(self._operation_view(envelope))
        views.sort(key=lambda view: (view["appended_at"], view["identity"]))
        return views

    def _operation_view(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        operation = envelope["payload"]["operation"]
        return {**_envelope_view(envelope),
                "record_type": OPERATION_TYPE,
                "operation_id": operation.get("operation_id"),
                "status": operation.get("status"),
                "package_id": operation.get("package_id"),
                # Reuse the W-2 helper for the produced identity (or None).
                "result_revision_identity": operation_outcome_identity(operation),
                "operation": operation}

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        identity = _typed_identity(OPERATION_TYPE, str(operation_id or ""),
                                   field="operation_id")
        try:
            envelope = self._store.get(identity)
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        return self._operation_view(envelope) if envelope is not None else None

    def list_decisions(self) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        try:
            records = self._store.iter_records()
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        for envelope in records:
            payload = envelope["payload"]
            if payload.get("record_type") != DECISION_TYPE:
                continue
            decision = payload.get("decision")
            if not isinstance(decision, dict):
                raise OpsApiError("stored decision payload is malformed",
                                  kind="integrity_error", http_status=503)
            try:
                subject = decision_record_identity(decision)
            except DecisionSlotError as exc:
                raise OpsApiError(f"stored decision is not identity-derivable: {exc}",
                                  kind="integrity_error", http_status=503) from exc
            views.append({**_envelope_view(envelope),
                          "record_type": DECISION_TYPE,
                          "decision_record_identity": subject,
                          "verdict": decision.get("verdict"),
                          "package_id": decision.get("package_id"),
                          "decision_scope": decision.get("decision_scope"),
                          "operator": decision.get("operator"),
                          "revision_digest": decision.get("revision_digest"),
                          "supersedes": decision.get("supersedes"),
                          "decision": decision})
        views.sort(key=lambda view: (view["appended_at"], view["identity"]))
        return views

    def get_decision(self, decision_identity_input: str) -> dict[str, Any] | None:
        identity = _digest_identity(DECISION_TYPE, decision_identity_input,
                                    field="decision_record_identity")
        try:
            envelope = self._store.get(identity)
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        if envelope is None:
            return None
        for view in self.list_decisions():
            if view["identity"] == identity:
                return view
        return None

    def list_evidence(self) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        try:
            records = self._store.iter_records()
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        for envelope in records:
            payload = envelope["payload"]
            if payload.get("record_type") != EVIDENCE_TYPE:
                continue
            entry = payload.get("entry")
            if not isinstance(entry, dict):
                raise OpsApiError("stored evidence payload is malformed",
                                  kind="integrity_error", http_status=503)
            views.append({**_envelope_view(envelope),
                          "record_type": EVIDENCE_TYPE,
                          "idempotency_key": entry.get("idempotency_key"),
                          "entry_id": entry.get("entry_id"),
                          "payload_digest": entry.get("payload_digest"),
                          "entry": entry})
        views.sort(key=lambda view: (view["appended_at"], view["identity"]))
        return views

    # --- action paths (mutations return the store's outcome envelope) ----

    def create_revision(self, revision: Mapping[str, Any], *,
                        issue_ref: str | None = None) -> dict[str, Any]:
        """Validate and append a revision; identity is its content identity."""
        try:
            validate_revision(revision)
            subject = revision_identity(revision)
        except RevisionError as exc:
            raise OpsApiError(str(exc), kind="invalid_input") from exc
        identity = _typed_identity(REVISION_TYPE, subject,
                                   field="revision identity")
        payload = {"record_type": REVISION_TYPE, "revision": dict(revision)}
        return self._append(payload, identity=identity, issue_ref=issue_ref,
                            subject_field="revision_identity", subject_value=subject)

    def record_operation(self, *, operation_id: str, package_id: str,
                         original_parent: str | None,
                         candidate_revision: Mapping[str, Any], status: str,
                         issue_ref: str | None = None) -> dict[str, Any]:
        """Build (and validate) an S4-B3 operation record, then append it.

        The volatile ``recorded_at`` stamp stays out of the stored payload so a
        genuine retry is deterministic: same operation_id + same candidate
        content renders ``re-delivery``; different content under the same
        operation_id renders ``conflict`` (never silently overwritten).
        """
        result_identity = (candidate_digest(candidate_revision)
                           if status == STATUS_COMMITTED else None)
        try:
            record = make_operation_record(
                operation_id, package_id, original_parent, candidate_revision,
                status, result_identity)
        except (OperationRecordError, RevisionError) as exc:
            raise OpsApiError(str(exc), kind="invalid_input") from exc
        identity = _typed_identity(OPERATION_TYPE, record["operation_id"],
                                   field="operation_id")
        stored = {field: record[field] for field in OPERATION_FIELDS
                  if field != "recorded_at"}
        payload = {"record_type": OPERATION_TYPE, "operation": stored}
        return self._append(payload, identity=identity, issue_ref=issue_ref,
                            subject_field="operation_id",
                            subject_value=record["operation_id"])

    def record_decision(self, *, package_id: str, revision_digest: str,
                        decision_scope: str, operator: str, verdict: str,
                        supersedes: str | None = None,
                        issue_ref: str | None = None) -> dict[str, Any]:
        """Build (and validate) a D5 decision record, then append it.

        The stored payload is the closed content shape (record minus the
        volatile ``recorded_at``); the identity is the erratum-E4 identity the
        W-2 module computes, so identical content re-delivered at any later
        time renders ``re-delivery`` and a different verdict under the same
        key renders as its own content identity (never a silent no-op).
        """
        try:
            record = build_decision_record(
                package_id, revision_digest, decision_scope, operator, verdict,
                supersedes=supersedes)
            subject = decision_record_identity(record)
        except DecisionSlotError as exc:
            raise OpsApiError(str(exc), kind="invalid_input") from exc
        identity = _typed_identity(DECISION_TYPE, subject,
                                   field="decision record identity")
        payload = {"record_type": DECISION_TYPE,
                   "decision": decision_identity_fields(record)}
        return self._append(payload, identity=identity, issue_ref=issue_ref,
                            subject_field="decision_record_identity",
                            subject_value=subject)

    def append_evidence(self, *, request_id: str, entry_id: str,
                        payload_digest: str,
                        issue_ref: str | None = None) -> dict[str, Any]:
        """Enforce the D4 request-binding guard, then append one evidence entry.

        ``check_request_binding`` is the packaging-layer boundary guard and is
        applied here, BEFORE any store write (never inside the store's
        outcome branches, so the conflict branch stays reachable).
        """
        request = {"request_id": request_id, "entry_id": entry_id,
                   "payload_digest": payload_digest}
        try:
            from .evidence_store import validate_evidence_request
            validate_evidence_request(request)
            check_request_binding(request_id, payload_digest)
        except EvidenceError as exc:
            raise OpsApiError(str(exc), kind="invalid_input") from exc
        payload = {"record_type": EVIDENCE_TYPE, "entry": request}
        # Declared identity = the D4 idempotency key over
        # (request_id stripped, entry_id). This makes the store's
        # insert-if-absent branches implement the D4 outcome branches exactly:
        # same identity + same payload renders ``re-delivery`` (nothing
        # appended), same identity + a different payload digest renders an
        # explicit ``conflict`` (never silently overwritten), and a new
        # identity appends a new evidence version.
        try:
            identity = _typed_identity(EVIDENCE_TYPE,
                                       evidence_idempotency_key(request_id, entry_id),
                                       field="evidence idempotency key")
        except EvidenceError as exc:
            raise OpsApiError(str(exc), kind="invalid_input") from exc
        return self._append(payload, identity=identity, issue_ref=issue_ref,
                            subject_field="entry_id", subject_value=entry_id)

    # --- kriterium-oracle projection (W-3) --------------------------------

    def workstream(self) -> dict[str, Any]:
        """The Packaging Workstream projection both clients render.

        Single source of truth: the web action host and the TUI both consume
        THIS projection, so the oracle can assert the same workstream -- with
        mandate/objective/scope/non-goals/repo-refs -- is visible in both.
        """
        counts = {
            "revisions": len(self.list_revisions()),
            "operations": len(self.list_operations()),
            "decisions": len(self.list_decisions()),
            "evidence": len(self.list_evidence()),
        }
        return {"schema_version": OPS_API_SCHEMA_VERSION, "status": "ok",
                "workstream": dict(PACKAGING_WORKSTREAM), "counts": counts,
                "store_backup_status": self._store.backup_status}


__all__ = [
    "DECISION_TYPE",
    "EVIDENCE_TYPE",
    "OPERATION_FIELDS",
    "OPERATION_TYPE",
    "OPS_API_SCHEMA_VERSION",
    "OUTCOME_ACCEPTED",
    "PACKAGING_WORKSTREAM",
    "REVISION_FIELDS",
    "REVISION_TYPE",
    "OpsApiError",
    "PackagingOpsApi",
]
