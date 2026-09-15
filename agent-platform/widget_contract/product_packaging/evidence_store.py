"""Evidence append with deterministic outcomes (D4 / EVP-A, #606).

- ``idempotency_key = sha256(canon_arr(request_id_stripped, entry_id))`` --
  stored as bare hex. Reference: request_id
  ``sha256:d7f131fb7d9bc94fe5af641d20397c3a432f6507af65639e7e771065ba3a0469``
  + ``ev-0001`` hashes to ``4aa26a51bfb00214011b1df8dfa99b0b06251f5d1e054d726
  18b22f2f7a5582d`` when the input is stripped; the un-normalized prefixed
  variant hashes to ``34334628a3efd50a057be5c4b44dcf2d46b44a4229724e843552ce
  c4277a3e82``.
- Input normalization happens at input, BEFORE hashing and BEFORE comparison.
  Permitted input: 64 lowercase hex chars, or the same with a single
  ``sha256:`` prefix. Uppercase hex, a doubled prefix, wrong length:
  fail-closed rejection.
- Request binding is DIFFERENT: exact whole-string equality between the
  envelope request_id and the payload digest. A correctly prefixed request_id
  is accepted; the same hex WITHOUT its prefix is rejected with
  ``EV-REQUEST_BINDING_MISMATCH``. The normalization rule must NOT leak into
  request binding or any other logic.
- Three deterministic branches: same identity + same payload_digest =
  REDELIVERY (append nothing); same identity + different payload_digest =
  CONFLICT (rendered explicitly, never silently overwritten); new identity =
  NEW-EVIDENCE-VERSION appended under in-process insert-if-absent.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ._digest import canonical_array, sha256_hex

REQUEST_BINDING_MISMATCH = "EV-REQUEST_BINDING_MISMATCH"
OUTCOME_REDELIVERY = "re-delivery"
OUTCOME_CONFLICT = "conflict"
OUTCOME_NEW_VERSION = "new-evidence-version"

_SHA256_PREFIX = "sha256:"
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceError(ValueError):
    """Raised when an evidence input violates the D4/EVP-A rules."""


def normalize_request_digest(value: str, *, field: str = "request_id") -> str:
    """Normalize an evidence digest input to bare 64-char lowercase hex.

    Fail-closed on uppercase hex, a doubled prefix, or a wrong length. This
    normalization applies to evidence digest inputs only -- it is NOT applied
    to request binding.
    """
    if not isinstance(value, str):
        raise EvidenceError(f"{field}: digest input must be a string")
    stripped = value
    if stripped.startswith(_SHA256_PREFIX):
        stripped = stripped[len(_SHA256_PREFIX):]
        if stripped.startswith(_SHA256_PREFIX):
            raise EvidenceError(f"{field}: doubled sha256: prefix is not permitted")
    if not _HEX64_RE.match(stripped):
        raise EvidenceError(
            f"{field}: must be 64 lowercase hex chars, optionally with a "
            "single sha256: prefix"
        )
    return stripped


def evidence_idempotency_key(request_id: str, entry_id: str) -> str:
    """sha256(canon_arr(request_id_stripped, entry_id)) as bare hex."""
    if not isinstance(entry_id, str) or not entry_id:
        raise EvidenceError("entry_id must be a non-empty string")
    stripped = normalize_request_digest(request_id, field="request_id")
    return sha256_hex(canonical_array([stripped, entry_id]))


def check_request_binding(envelope_request_id: str, payload_digest: str) -> None:
    """Exact whole-string equality between envelope request_id and payload digest.

    A correctly prefixed request_id is accepted; the same hex without its
    prefix is rejected with ``EV-REQUEST_BINDING_MISMATCH``. No normalization
    is applied on either side (the digest-input normalization rule never
    leaks into request binding).

    This is a packaging-layer boundary guard: callers (e.g. the dispatch
    path) invoke it explicitly on the envelope BEFORE dispatch. It is
    deliberately NOT applied inside ``EvidenceStore.append`` -- the store's
    deterministic outcome branches are keyed on the idempotency identity and
    the payload digest, and the ACs' conflict branch (same identity,
    different payload_digest) must stay reachable there.
    """
    if envelope_request_id != payload_digest:
        raise EvidenceError(REQUEST_BINDING_MISMATCH)


def validate_evidence_request(request: Mapping[str, Any]) -> None:
    """Fail-closed structural validation of an evidence append request."""
    required = {"request_id", "entry_id", "payload_digest"}
    missing = required - set(request)
    if missing:
        raise EvidenceError(f"evidence request missing fields: {', '.join(sorted(missing))}")
    normalize_request_digest(request["request_id"], field="request_id")
    if not isinstance(request["payload_digest"], str):
        raise EvidenceError("payload_digest must be a string")
    if not isinstance(request["entry_id"], str) or not request["entry_id"]:
        raise EvidenceError("entry_id must be a non-empty string")


class EvidenceStore:
    """In-process evidence store with insert-if-absent semantics (D4 / EVP-A)."""

    def __init__(self) -> None:
        self._entries: dict[str, dict] = {}  # idempotency_key -> entry

    def append(self, request: Mapping[str, Any]) -> dict:
        """Append evidence; returns the deterministic outcome rendering.

        Never silently overwrites: an identical re-delivery appends nothing
        and a conflicting payload digest is rendered explicitly.
        """
        validate_evidence_request(request)
        key = evidence_idempotency_key(request["request_id"], request["entry_id"])
        # Stored and compared BARE (contract 6.2: readers strip before byte
        # comparison), so a prefixed re-delivery of the same digest renders
        # re-delivery, not a false conflict. Request binding stays
        # un-normalized (check_request_binding, deliberately raw).
        payload = normalize_request_digest(request["payload_digest"],
                                           field="payload_digest")
        entry = {
            "idempotency_key": key,
            "request_id": normalize_request_digest(request["request_id"], field="request_id"),
            "entry_id": request["entry_id"],
            "payload_digest": payload,
        }
        existing = self._entries.get(key)
        if existing is None:
            self._entries[key] = entry
            return {
                "outcome": OUTCOME_NEW_VERSION,
                "appended": True,
                "idempotency_key": key,
                "entry_id": entry["entry_id"],
                "payload_digest": payload,
            }
        if existing["payload_digest"] == payload:
            return {
                "outcome": OUTCOME_REDELIVERY,
                "appended": False,
                "idempotency_key": key,
                "entry_id": entry["entry_id"],
                "payload_digest": payload,
            }
        return {
            "outcome": OUTCOME_CONFLICT,
            "appended": False,
            "idempotency_key": key,
            "entry_id": entry["entry_id"],
            "payload_digest": payload,
            "existing_payload_digest": existing["payload_digest"],
        }

    def entries(self) -> list[dict]:
        """Stored entries in insertion order (bare-hex keys and ids only)."""
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


__all__ = [
    "EvidenceError",
    "EvidenceStore",
    "OUTCOME_CONFLICT",
    "OUTCOME_NEW_VERSION",
    "OUTCOME_REDELIVERY",
    "REQUEST_BINDING_MISMATCH",
    "check_request_binding",
    "evidence_idempotency_key",
    "normalize_request_digest",
    "validate_evidence_request",
]
