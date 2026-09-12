#!/usr/bin/env python
"""Regenerate the JSON exports of the embedded projection schemas.

The embedded dicts in ``agent-platform/widget_contract/registry.py`` are the
single source of truth (VLT-D-007, operator-adjusted step 1). This script
writes their canonical JSON form to ``contracts/``.

Usage:
    python scripts/export_contracts.py            # (re)write the exports
    python scripts/export_contracts.py --check    # exit 1 if exports drifted
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent-platform"))

from widget_contract.schema_source import (  # noqa: E402
    check_schema_exports,
    write_schema_exports,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify exports match the embedded dicts; exit 1 on drift",
    )
    args = parser.parse_args()

    if args.check:
        problems = check_schema_exports()
        for problem in problems:
            print(f"DRIFT: {problem}", file=sys.stderr)
        return 1 if problems else 0

    for path in write_schema_exports():
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
