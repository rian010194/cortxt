"""Product packaging: revision, operation-record, decision-slot and evidence
process logic per the frozen 4a contract (#606).

Pure process logic only -- persistent storage is delivered in W-2b
(``agent-platform/state/core_store.py`` is NOT part of this package and must
not be imported by its tests).
"""

from ._digest import (
    DigestError,
    canonical_array,
    canonical_object,
    digest_of_object,
    normalize_digest,
    sha256_hex,
)

__all__ = [
    "DigestError",
    "canonical_array",
    "canonical_object",
    "digest_of_object",
    "normalize_digest",
    "sha256_hex",
]
