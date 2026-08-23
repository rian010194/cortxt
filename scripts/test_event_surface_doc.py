#!/usr/bin/env python3
"""Offline checks for the generic event surface design doc (#313, C.4).

Run: python scripts/test_event_surface_doc.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the design doc exists at the expected path, contains the required
section markers (inbound envelope, HMAC, replay, retries, outbound,
C.1-C.3 mapping, ADR-024/029 reconciliation), is English-only with zero
a/o/u-with-diacritics, and contains no secrets/prompt markers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "architecture" / "event-surface.md"

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def main() -> int:
    check("design doc exists at docs/architecture/event-surface.md", DOC.is_file())
    text = DOC.read_text(encoding="utf-8")

    required = [
        "## Inbound events",
        "## Outbound events",
        "HMAC",
        "Replay protection",
        "Retries",
        "idempotency",
        "ADR-024",
        "ADR-029",
        "C.1",
        "C.2",
        "C.3",
        "## Boundaries",
        "## Open questions",
    ]
    for marker in required:
        check(f"doc contains {marker!r}", marker in text)

    check("doc is a design record (no production code claims)",
          "design record" in text.lower()
          and "separate build issues" in re.sub(r"\s+", " ", text))
    check("untrusted-input stance applied", "untrusted" in text.lower())
    check("content-free outbound rule stated", "content-free" in text.lower())
    check("no dispatch-authority grant claimed",
          "never grants dispatch authority" in text or "never claims" in text.lower())

    diacritics = re.findall(r"[åäöÅÄÖ]", text)
    check("zero a/o/u-with-diacritics", not diacritics)
    for marker in ("-----BEGIN", "sk-", "cfat_", "prompt:"):
        check(f"no secret/prompt marker {marker!r}", marker not in text)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
