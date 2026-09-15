"""Decision slot: CAS semantics, idempotent re-delivery, supersession (D5, S4-B1, #606).

- ``decision_key = sha256(canon_arr(package_id, revision_digest_stripped,
  decision_scope))`` -- stored as bare hex.
- ``decision_record_identity = sha256(canonical_object(record minus
  ``recorded_at``))`` per contract 5.1 / erratum E4; head, CAS and
  ``supersedes`` all reference THIS identity. The closed record content shape
  (frozen D5 example, ``e4_alt1_win_accept``) is
  ``{package_id, decision_key, revision_digest, decision_scope, operator,
  verdict, supersedes}`` plus the non-normative ``recorded_at``; ``verdict``
  (accepted/rejected) is a CONTENT field and ``outcome`` is not a record
  field at all. Because the verdict is inside the identity, a losing reject
  never collides with the winning acceptance's content identity and its
  re-delivery triggers a fresh CAS evaluation (never a no-op).
- CAS: a write succeeds iff the current head equals the expected head; the
  loser renders an explicit lost-CAS outcome, never changes the head and
  never becomes a supersession.
- Identical re-delivery (same content fields, new ``recorded_at``) is an
  idempotent no-op with the head unchanged. After a supersession the
  re-delivery is still an idempotent no-op whose response marks it stale and
  references the current head.
- A deliberate new record with ``supersedes == current head`` is an ordinary
  supersession (ordinary supersession identity of the previous head:
  ``e5e25a83de2c2a0d480c5d97e512d390277173f259e91ef4473093d9e4963ae7``).
- Prefix tolerance (S4-B5): ``revision_digest`` and ``supersedes`` accept both
  bare hex and ``sha256:``-prefixed forms; normalization applies to these CAS
  operands only.
"""

from __future__ import annotations

from typing import Any, Mapping

from ._digest import (
    SHA256_PREFIX,
    canonical_array,
    digest_of_object,
    normalize_digest,
    sha256_hex,
)

OUTCOME_ACCEPTED = "accepted"
OUTCOME_REJECTED = "rejected"
OUTCOME_LOST_CAS = "lost-CAS"
OUTCOME_REDELIVERY = "re-delivery"
OUTCOME_STALE = "stale"


class DecisionSlotError(ValueError):
    """Raised when a decision-slot operation violates the D5/S4-B1 rules."""


def decision_key(package_id: str, revision_digest: str, decision_scope: str) -> str:
    """sha256 over the derived-key array of (package_id, revision_digest, scope).

    ``revision_digest`` is normalized to bare hex before hashing; the key is
    returned as bare hex (P1-7). Reference (``cortxt-core``, rev1
    ``e0f94e0b...``, ``acceptance``): ``9a3f39f71f3713e9782992789b84445f456cd
    c9868bd0d449f7f882c4a720620``.
    """
    if not isinstance(package_id, str) or not package_id:
        raise DecisionSlotError("package_id must be a non-empty string")
    if not isinstance(decision_scope, str) or not decision_scope:
        raise DecisionSlotError("decision_scope must be a non-empty string")
    stripped = normalize_digest(revision_digest, field="revision_digest")
    return sha256_hex(canonical_array([package_id, stripped, decision_scope]))


def decision_identity_fields(record: Mapping[str, Any]) -> dict:
    """The record minus ``recorded_at`` (contract 5.1, erratum E4).

    The closed record content shape carries ``verdict`` as a CONTENT field
    (frozen D5 example): the verdict participates in the identity, which is
    what keeps a losing reject from ever colliding with the win's identity.
    ``outcome`` is not a record field; a caller-supplied ``outcome`` key
    (e.g. from a re-rendered envelope) is also excluded defensively.
    """
    return {k: v for k, v in record.items()
            if k not in ("recorded_at", "outcome")}


def decision_record_identity(record: Mapping[str, Any]) -> str:
    """sha256(canonical_object(record minus recorded_at minus outcome)).

    S4-B5 prefix tolerance: the CAS operands ``revision_digest`` and
    ``supersedes`` are normalized to bare hex before hashing, so the identity
    reproduces identically with or without the ``sha256:`` prefix. The
    ``decision_key`` field is already a bare-hex derived key.
    """
    fields = decision_identity_fields(record)
    for operand in ("revision_digest", "supersedes"):
        value = fields.get(operand)
        if isinstance(value, str):
            fields[operand] = normalize_digest(value, field=operand)
    return digest_of_object(fields)


def validate_decision_record(record: Mapping[str, Any]) -> None:
    """Fail-closed structural validation of a decision record."""
    required = {"package_id", "decision_key", "revision_digest", "decision_scope",
                "operator", "verdict", "supersedes"}
    missing = required - set(record)
    if missing:
        raise DecisionSlotError(f"decision record missing fields: {', '.join(sorted(missing))}")
    if not isinstance(record["decision_scope"], str) or not record["decision_scope"]:
        raise DecisionSlotError("decision_scope must be a non-empty string")
    if record["verdict"] not in (OUTCOME_ACCEPTED, OUTCOME_REJECTED):
        raise DecisionSlotError(
            f"verdict must be {OUTCOME_ACCEPTED!r} or {OUTCOME_REJECTED!r}"
        )
    # CAS operands accept prefixed forms; validate before normalization.
    normalize_digest(record["revision_digest"], field="revision_digest")
    if record["supersedes"] is not None:
        normalize_digest(record["supersedes"], field="supersedes")
    expected_key = decision_key(
        record["package_id"], record["revision_digest"], record["decision_scope"]
    )
    if record["decision_key"] != expected_key:
        raise DecisionSlotError("decision_key does not match the derived key of the record")


def build_decision_record(
    package_id: str,
    revision_digest: str,
    decision_scope: str,
    operator: str,
    verdict: str,
    supersedes: str | None = None,
    recorded_at: str | None = None,
) -> dict:
    """Build a decision record in the closed content shape (frozen D5 example).

    ``verdict`` (accepted/rejected) is a content field; ``operator`` names the
    deciding operator (frozen example: ``operator-rikard``).
    ``revision_digest``/``supersedes`` are stored bare (S4-B5 normalization
    applies to these CAS operands only).
    """
    if verdict not in (OUTCOME_ACCEPTED, OUTCOME_REJECTED):
        raise DecisionSlotError(f"verdict must be {OUTCOME_ACCEPTED!r} or {OUTCOME_REJECTED!r}")
    if not isinstance(operator, str) or not operator:
        raise DecisionSlotError("operator must be a non-empty string")
    record = {
        "package_id": package_id,
        "decision_key": decision_key(package_id, revision_digest, decision_scope),
        "revision_digest": normalize_digest(revision_digest, field="revision_digest"),
        "decision_scope": decision_scope,
        "operator": operator,
        "verdict": verdict,
        "supersedes": normalize_digest(supersedes, field="supersedes")
        if supersedes is not None
        else None,
    }
    if recorded_at is not None:
        record["recorded_at"] = recorded_at
    validate_decision_record(record)
    return record


def _render(record: Mapping[str, Any], outcome: str, head: str | None, **extra: Any) -> dict:
    # `verdict` is a content field of the record (frozen D5 example shape);
    # `outcome` here is the TRANSPORT/outcome rendering key only and is not
    # part of any identity computation.
    rendered = {
        "decision_key": record["decision_key"],
        "decision_record_identity": decision_record_identity(record),
        "verdict": record["verdict"],
        "outcome": outcome,
        "head": head,
        "governing": outcome in (OUTCOME_ACCEPTED, OUTCOME_REJECTED) or outcome == OUTCOME_REDELIVERY,
        "stale": outcome == OUTCOME_STALE,
    }
    rendered.update(extra)
    return rendered


class DecisionSlot:
    """In-process decision slot implementing D5 CAS + S4-B1 re-delivery rules."""

    def __init__(self) -> None:
        self._records: list[dict] = []
        self._head: str | None = None  # decision_record_identity of the head
        self._seen_identities: dict[str, dict] = {}

    @property
    def head(self) -> str | None:
        return self._head

    def committed_identities(self) -> list[str]:
        """Committed identities per slot, rebuilt deterministically from records.

        Identities are COMPUTED per record (contract 5.1, erratum E4:
        ``decision_record_identity`` is never a stored field); a committed
        record has verdict accepted/rejected.
        """
        return [decision_record_identity(r) for r in self._records
                if r.get("verdict") in (OUTCOME_ACCEPTED, OUTCOME_REJECTED)]

    def _deliver(self, record: dict) -> dict:
        content_key = decision_record_identity(record)
        seen = self._seen_identities.get(content_key)

        if seen is not None and self._head == content_key:
            # Re-delivery of the winning record before any supersession.
            return _render(record, OUTCOME_REDELIVERY, self._head,
                           superseded_by=None)

        if seen is not None and self._head != content_key:
            # Identical content re-delivered after the head moved: still an
            # idempotent no-op, but the rendering marks it stale and
            # references the current head (S4-B1).
            return _render(record, OUTCOME_STALE, self._head,
                           superseded_by=self._head)

        # Deliberate new record. If supersedes names the current head it is
        # an ordinary supersession; otherwise it is a CAS attempt against the
        # expected head (None expected means create the genesis head).
        expected = record.get("supersedes")
        if self._head != expected:
            # Lost compare-and-set: explicit outcome, head unchanged, never a
            # supersession. The verdict is part of the content identity, so a
            # losing reject has its own identity and NEVER matches the win's
            # seen-identity entry here -- a re-delivered loser is always a
            # fresh CAS evaluation, never a no-op (S4-B1).
            return _render(record, OUTCOME_LOST_CAS, self._head,
                           expected_head=expected)
        self._records.append(record)
        self._seen_identities[content_key] = record
        self._head = content_key
        return _render(record, record["verdict"], self._head)

    def deliver(self, record: Mapping[str, Any]) -> dict:
        """Deliver a decision record through CAS + re-delivery evaluation."""
        validate_decision_record(record)
        return self._deliver(dict(record))

    def propose(
        self,
        package_id: str,
        revision_digest: str,
        decision_scope: str,
        verdict: str,
        supersedes: str | None = None,
        recorded_at: str | None = None,
        operator: str = "operator-rikard",
    ) -> dict:
        """Convenience: build a record and deliver it in one step."""
        record = build_decision_record(
            package_id, revision_digest, decision_scope, operator, verdict,
            supersedes=supersedes, recorded_at=recorded_at,
        )
        return self._deliver(record)


__all__ = [
    "DecisionSlot",
    "DecisionSlotError",
    "OUTCOME_ACCEPTED",
    "OUTCOME_LOST_CAS",
    "OUTCOME_REDELIVERY",
    "OUTCOME_REJECTED",
    "OUTCOME_STALE",
    "build_decision_record",
    "decision_identity_fields",
    "decision_key",
    "decision_record_identity",
    "validate_decision_record",
]

# The presentation prefix constant is re-exported for renderers only; it is
# never part of a stored key or identity (P1-7).
_ = SHA256_PREFIX
