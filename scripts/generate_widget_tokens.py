#!/usr/bin/env python3
"""Regenerate the web-consumer widget tokens artifact from the platform source.

`site/public/widgets/tokens.json` must be a mechanically generated copy of
the platform-owned `agent-platform/widget/tokens.json` (issue #373
acceptance criteria) -- it must never be hand-edited.

Usage:
    python scripts/generate_widget_tokens.py          # regenerate the copy
    python scripts/generate_widget_tokens.py --check  # verify without writing;
                                                        # exits 1 if the site
                                                        # copy is stale or missing

This intentionally copies the existing visual-tokens.v1 document only. Which
preset (if any) a consuming surface applies is issue #374's/#377's job; this
script's only responsibility is keeping the generated artifact byte-identical
to its platform source.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO / "agent-platform" / "widget" / "tokens.json"
GENERATED_PATH = REPO / "site" / "public" / "widgets" / "tokens.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the generated file matches the source without writing it",
    )
    args = parser.parse_args(argv)

    if not SOURCE_PATH.is_file():
        print(f"source tokens file not found: {SOURCE_PATH}", file=sys.stderr)
        return 1

    source_content = SOURCE_PATH.read_text(encoding="utf-8")

    if args.check:
        if not GENERATED_PATH.is_file():
            print(f"generated file missing: {GENERATED_PATH}", file=sys.stderr)
            return 1
        current_content = GENERATED_PATH.read_text(encoding="utf-8")
        if current_content != source_content:
            print(
                f"{GENERATED_PATH} is stale; run `python scripts/generate_widget_tokens.py` to regenerate",
                file=sys.stderr,
            )
            return 1
        print(f"{GENERATED_PATH} is up to date with {SOURCE_PATH}")
        return 0

    GENERATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_PATH.write_text(source_content, encoding="utf-8")
    print(f"wrote {GENERATED_PATH} from {SOURCE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
