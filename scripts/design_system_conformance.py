#!/usr/bin/env python3
"""Validate the cross-surface design-system ownership contract."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANONICAL_V1 = REPO / "agent-platform/widget/tokens.json"
CANONICAL_PRESETS = REPO / "agent-platform/widget/presets/visual-tokens.v2.json"
GENERATED_WEB = REPO / "site/public/widgets/tokens.json"
WEB_CONSUMERS = {
    REPO / "site/src/styles/landing.css": "--token-",
    REPO / "site/src/styles/custom.css": "--token-",
    REPO / "site/src/styles/atlas.css": "--token-",
}
PRIVATE_TOKEN_DEFINITION = re.compile(r"(?<![\w-])(--token-[\w-]+)\s*:")


def validate() -> None:
    v1 = json.loads(CANONICAL_V1.read_text(encoding="utf-8"))
    presets = json.loads(CANONICAL_PRESETS.read_text(encoding="utf-8"))
    generated = json.loads(GENERATED_WEB.read_text(encoding="utf-8"))
    if generated != v1:
        raise ValueError("generated web tokens are stale")
    if presets.get("schema_version") != 2:
        raise ValueError("canonical preset collection must use schema_version 2")
    if presets.get("default_preset") not in presets.get("presets", {}):
        raise ValueError("default_preset does not name a shipped preset")
    required_sections = set(v1) - {"schema_version"}
    required_colors = set(v1.get("colors", {}))
    for preset_id, document in presets.get("presets", {}).items():
        missing_sections = required_sections - set(document)
        missing_colors = required_colors - set(document.get("colors", {}))
        if missing_sections or missing_colors:
            raise ValueError(f"preset {preset_id!r} is incomplete")
    for path, required_reference in WEB_CONSUMERS.items():
        text = path.read_text(encoding="utf-8")
        if required_reference not in text:
            raise ValueError(f"{path.relative_to(REPO)} does not consume canonical tokens")
        definitions = sorted(set(PRIVATE_TOKEN_DEFINITION.findall(text)))
        if definitions:
            raise ValueError(f"{path.relative_to(REPO)} defines private canonical properties: {definitions}")


def main() -> int:
    try:
        validate()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"design-system-conformance: FAIL -- {exc}", file=sys.stderr)
        return 1
    print("design-system-conformance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

