"""Candidate datamodel for the controlled learning loop (Fas 8, Beslut 9.1 / P0.1 / P2.4).

A ``Candidate`` is an immutable, type-agnostic improvement proposal: a versioned payload that
the loop can evaluate and (if verified) promote. Key design points (from the approved spec):

- ``id`` is a DERIVED property = ``f"{type}@{name}@{version}"`` (Kimi P2.4) — it can never diverge.
- ``manifest_hash`` is a sha256 over the SERIALIZED payload dict (stable under key order via
  sort_keys), NOT over the mutable runtime object (Kimi P0.1).
- ``payload_ref`` holds a locked copy (frozen snapshot), so mutating the caller's dict after
  construction does not change the candidate (P0.1).

The registry (registry.py) is keyed on ``type@name@version``; this class is the contract root.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _payload_hash(payload: dict[str, Any]) -> str:
    """Deterministic sha256 over a JSON-serialized payload (key-order-stable)."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _lock(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a deep-copied, immutable snapshot of the payload (fail-closed on None)."""
    return json.loads(json.dumps(payload or {}, ensure_ascii=False))


@dataclass(frozen=True)
class Candidate:
    type: str
    name: str
    version: str
    payload: dict[str, Any] | None = None
    status: str = "draft"
    proposed_at: str | None = None
    promoted_by: str | None = None
    promoted_at: str | None = None
    rolled_back_at: str | None = None
    # immutable snapshot taken at construction (never the caller's mutable object)
    payload_ref: dict[str, Any] = field(default_factory=dict, init=False)
    manifest_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        locked = _lock(self.payload)
        # frozen dataclass forces object.__setattr__ on init=False / reassigned fields
        # BOTH `payload` and the immutable `payload_ref` snapshot hold the locked copy, so
        # mutating the caller's original dict after construction changes nothing (P0.1).
        object.__setattr__(self, "payload", locked)
        object.__setattr__(self, "payload_ref", locked)
        object.__setattr__(self, "manifest_hash", _payload_hash(locked))

    @property
    def id(self) -> str:  # noqa: A003 - id is the contract name (Beslut 9.1 / P2.4)
        return f"{self.type}@{self.name}@{self.version}"
