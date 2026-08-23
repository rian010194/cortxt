"""Bounded polling policy and result-size defaults for widget host (issue #326).

Provides deterministic functions and defaults for:
- Exponential backoff on consecutive poll failures (never exceeding cap_ms)
- Result-size truncation for table and list rendering
- Artifact size boundary checking
"""
from __future__ import annotations

from typing import Any, Sequence

# Default timing bounds in milliseconds
DEFAULT_BASE_MS: int = 3000
DEFAULT_MAX_BACKOFF_MS: int = 30000
DEFAULT_CAP_MS: int = 60000

# Default result volume bounds
DEFAULT_ROW_CAP: int = 500

# Default artifact size bound in bytes (1 MiB)
MAX_ARTIFACT_BYTES: int = 1024 * 1024


def next_interval(
    failures: int,
    base_ms: int = DEFAULT_BASE_MS,
    max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS,
    cap_ms: int = DEFAULT_CAP_MS,
) -> int:
    """Calculate the next poll interval in milliseconds given consecutive failures.

    Applies exponential backoff on consecutive failures (failures > 0):
      interval = min(base_ms * 2^failures, max_backoff_ms, cap_ms)
    When failures <= 0 (success or initial poll), returns min(base_ms, cap_ms).
    The returned interval is guaranteed never to exceed cap_ms.
    """
    effective_cap = min(max_backoff_ms, cap_ms)
    if failures <= 0:
        return min(base_ms, cap_ms)
    # Exponential backoff factor (clamped exponent to prevent overflow)
    backoff = base_ms * (2 ** min(failures, 30))
    return min(backoff, effective_cap)


def truncate_rows(
    rows: Sequence[Any],
    cap: int = DEFAULT_ROW_CAP,
) -> tuple[list[Any], bool]:
    """Truncate a sequence of rows to the specified cap.

    Returns:
        tuple[list[Any], bool]: (rows[:cap], True) if len(rows) > cap else (list(rows), False).
    """
    row_list = list(rows)
    if len(row_list) > cap:
        return row_list[:cap], True
    return row_list, False


def artifact_size_exceeded(
    byte_length: int,
    max_bytes: int = MAX_ARTIFACT_BYTES,
) -> bool:
    """Check whether an artifact byte length exceeds the maximum allowed bytes."""
    return byte_length > max_bytes
