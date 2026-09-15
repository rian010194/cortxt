"""Shared canonicalization and digest helpers for the product-packaging layer.

Implements the frozen 4a contract canonicalization rules (#606):

- Object form (candidate_revision digests, decision_record_identity):
  ``json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
  default=str)`` encoded UTF-8 with no trailing newline.
- Derived-key form (decision_key, idempotency_key): a compact JSON *array*
  whose elements are each serialized canonically, wrapped in ``[...]``.
- Digest-string inputs are normalized to stripped plain hex (a single
  ``sha256:`` prefix is dropped) BEFORE hashing; derived keys, id fields and
  pointers are always stored as bare hex, never prefixed (P1-7).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

SHA256_PREFIX = "sha256:"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class DigestError(ValueError):
    """Raised when a digest input violates the packaging digest rules."""


def canonical_object(obj: Any) -> str:
    """Canonical object form: sorted keys, no whitespace, ASCII, default=str."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def canonical_array(items: Iterable[Any]) -> str:
    """Derived-key form: compact JSON array of canonically serialized elements."""
    return "[" + ",".join(
        json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        for v in items
    ) + "]"


def sha256_hex(text: str) -> str:
    """SHA-256 of a UTF-8 string, as bare lowercase hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_digest(value: str, *, field: str = "digest") -> str:
    """Normalize a digest string to bare 64-char lowercase hex (P1-7).

    Permitted input: exactly 64 lowercase hex characters, optionally with a
    single ``sha256:`` prefix. Uppercase hex, a doubled prefix, or a wrong
    length is a fail-closed rejection.
    """
    if not isinstance(value, str):
        raise DigestError(f"{field}: digest input must be a string")
    stripped = value
    if stripped.startswith(SHA256_PREFIX):
        stripped = stripped[len(SHA256_PREFIX):]
        if stripped.startswith(SHA256_PREFIX):
            raise DigestError(f"{field}: doubled sha256: prefix is not permitted")
    if not HEX64_RE.match(stripped):
        raise DigestError(
            f"{field}: digest must be 64 lowercase hex chars, optionally with "
            "a single sha256: prefix"
        )
    return stripped


def digest_of_object(obj: Any) -> str:
    """sha256(canonical_object(obj)) as bare hex."""
    return sha256_hex(canonical_object(obj))
