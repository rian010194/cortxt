"""Candidate datamodel for the controlled learning loop (Phase 8, Decision 9.1 / P0.1 / P2.4).

A ``Candidate`` is an immutable, type-agnostic improvement proposal: a versioned payload that
the loop can evaluate and (if verified) promote. Key design points (from the approved spec,
refined by Kimi checkpoint review):

- ``id`` is a DERIVED property = ``f"{type}@{name}@{version}"`` (Kimi P2.4) — it can never diverge.
- ``manifest_hash`` is a sha256 over the SERIALIZED payload dict (stable under key order via
  sort_keys), NOT over a mutable runtime object (Kimi P0.1).
- ``payload`` is a LOCKED JSON SNAPSHOT (Kimi P1: shallow-frozen dataclass is not immutability; the
  JSON round-trip at construction produces a private *copy*, so the candidate is decoupled from the
  caller's dict, and the top level is read-only via MappingProxyType). NOTE: this is a read-only
  snapshot, NOT recursive deep-immutability — a nested dict inside the payload copy is still technically
  mutable, but it cannot affect the candidate's stored copy or hash (both frozen at construction).

CONTRACT: ``payload`` must be JSON-serializable (json.dumps is used for hashing + locking — any
non-JSON value (datetime, set, custom object) fails closed at construction with TypeError).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _lock(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return a read-only, JSON-based deep snapshot of the payload (fail-closed on None)."""
    return MappingProxyType(json.loads(json.dumps(payload or {}, ensure_ascii=False)))


def _payload_hash(payload: Mapping[str, Any]) -> str:
    """Deterministic sha256 over a JSON-serialized payload (key-order-stable)."""
    return hashlib.sha256(
        json.dumps(dict(payload), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class Candidate:
    type: str
    name: str
    version: str
    payload: Mapping[str, Any] | None = None
    status: str = "draft"
    proposed_at: str | None = None
    promoted_by: str | None = None
    promoted_at: str | None = None
    rolled_back_at: str | None = None
    manifest_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        locked = _lock(self.payload)
        # frozen dataclass forces object.__setattr__ on reassigned init fields.
        object.__setattr__(self, "payload", locked)
        object.__setattr__(self, "manifest_hash", _payload_hash(locked))

    @property
    def id(self) -> str:  # noqa: A003 - id is the contract name (Decision 9.1 / P2.4)
        return f"{self.type}@{self.name}@{self.version}"
