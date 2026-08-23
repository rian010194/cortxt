#!/usr/bin/env python3
"""Offline checks for the Copy command UX fix (#309).

Run: python scripts/test_widget_copy_command.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the "Open in CLI" label is gone, the visible label is
"Copy command", the command is visible in a read-only box
(.candidate-cmd), the copied state still gives feedback, and the
read-only default surface is unchanged (no POST handler).
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def main() -> int:
    html = (AP / "widget" / "index.html").read_text(encoding="utf-8")
    check("no 'Open in CLI' label remains", "Open in CLI" not in html)
    check("'Copy command' label present", "Copy command" in html)
    check("copied state feedback retained", 'button.textContent="Copied"' in html)
    check("command is visible in a read-only box",
          'className="candidate-cmd"' in html and ".candidate-cmd" in html)
    check("clipboard copy still wired", "navigator.clipboard?.writeText" in html
          and "copyCommand" in html and "fallbackCopy" in html)
    serve = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("read-only default surface unchanged (no POST handler)", "do_POST" not in serve)

    # The inline script must stay syntactically valid.
    match = re.search(r"<script>(.*?)</script>", html, re.S)
    check("index.html contains one inline script block", match is not None)
    if match:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(match.group(1))
            tmp = Path(handle.name)
        try:
            proc = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
            check("node --check passes on the inline script", proc.returncode == 0)
            if proc.returncode != 0:
                print(proc.stderr[-500:])
        finally:
            tmp.unlink(missing_ok=True)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
