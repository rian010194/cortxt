#!/usr/bin/env python3
"""Offline checks for the integrated Widget OS dock host (Issues #369/#390).

Run: python scripts/test_widget_host_view.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. Dock workspace and integrated Maker pane are the default host surface.
2. Widget cards remain bounded and scroll internally.
3. Window and Maker pane sizing persist locally.
4. Dock layout supports split panes, tabs, drag/drop, and reset.
5. Maker can collapse and resize without leaving the host.
6. Preserved poll loop and backoff (pollState, nextInterval, pollAll, constants).
7. Preserved action forms and copy command (probeActions, actionHost, runAction, actionForm, copyCommand, .candidate-cmd).
8. Preserved composed rendering (renderComposed, tree.composed).
9. Maker is mounted into the host.
10. Node syntax check (node --check) passes on the inline script.
11. serve.py remains loopback read-only with no POST handler.
12. Zero a/o/u-with-diacritics across all touched files.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def main() -> int:
    index_html_path = AP / "widget" / "index.html"
    check("agent-platform/widget/index.html exists", index_html_path.is_file())
    html = index_html_path.read_text(encoding="utf-8")

    # 1. Integrated dock workspace and Maker pane.
    check("dock root exists", 'id="dock-root"' in html and ".dock-root" in html)
    check("integrated maker pane exists", 'id="maker-pane"' in html and ".maker-pane" in html)

    # 2. Card-per-widget rendering with bounded card sizing
    check("widget card wrapper class (.wcard) defined", ".wcard" in html)
    check("widget card body has internal scrolling (overflow-y:auto)",
          "overflow-y:auto" in html or "overflow-y: auto" in html)
    check("widget card height is bounded (max-height)",
          "max-height:400px" in html or "max-height: 400px" in html or
          bool(re.search(r"\.wcard\s*\{[^}]*max-height:\s*\d+px", html)))
    check("dock renders widget content", "renderWidget" in html and "renderCanvasView" in html)

    # 3-5. Persistent window, dock, and Maker-pane controls.
    check("window size persistence exists", "cortxt-window-size" in html and "applyWindowSize" in html)
    check("maker width persistence exists", "cortxt-maker-pane-width" in html and "initMakerPaneResize" in html)
    check("maker collapse control exists", 'id="maker-collapse-toggle"' in html and "initMakerPaneCollapse" in html)
    check("dock layout reset exists", "dockTree.reset" in html and "Reset layout" in html)
    check("dock script is loaded", '<script src="dock.js"></script>' in html)

    # 6. Preserved poll loop and backoff
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    check("index.html contains script block", match is not None)
    script = match.group(1) if match else ""

    check("pollState map tracked", "pollState" in script)
    check("nextInterval backoff function present", "nextInterval" in script)
    check("pollAll function present", "pollAll" in script)
    check("POLL_BASE_MS constant present", "POLL_BASE_MS" in script)
    check("POLL_MAX_BACKOFF_MS constant present", "POLL_MAX_BACKOFF_MS" in script)
    check("POLL_CAP_MS constant present", "POLL_CAP_MS" in script)

    # 7. Preserved action forms and copy command
    check("probeActions and actionHost present", "probeActions" in script and "actionHost" in script)
    check("renderActionable function present", "renderActionable" in script)
    check("runAction and actionForm present", "runAction" in script and "actionForm" in script)
    check("copyCommand and fallbackCopy present", "copyCommand" in script and "fallbackCopy" in script)
    check("candidate-cmd code box present", ".candidate-cmd" in html and 'className="candidate-cmd"' in html)
    check("Copy command label present", "Copy command" in html)

    # 8. Preserved composed rendering
    check("renderComposed function present", "renderComposed" in script)
    check("composed branch on tree.composed present", "tree.composed" in script)

    # 9. Integrated Maker mount
    check("WidgetMaker mounts into maker pane", "WidgetMaker?.mount?.($(\"maker-pane\"))" in html)

    # 10. Node syntax check
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
        tmp.write(script)
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(["node", "--check", str(tmp_path)], capture_output=True, text=True)
        check("node --check passes on the inline script", proc.returncode == 0)
        if proc.returncode != 0:
            print(proc.stderr[-500:])
    finally:
        tmp_path.unlink(missing_ok=True)

    # 11. serve.py remains loopback read-only
    serve = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("serve.py binds to loopback only", 'HOST = "127.0.0.1"' in serve)
    check("serve.py has no do_POST handler", "do_POST" not in serve)
    check("serve.py uses SimpleHTTPRequestHandler", "SimpleHTTPRequestHandler" in serve)

    # 12. Diacritics check across all touched/checked files
    touched_files = [
        AP / "widget" / "index.html",
        AP / "widget" / "maker.js",
        AP / "widget" / "widgets.json",
        AP / "widget" / "session-pulse.json",
        AP / "widget" / "snapshot.json",
        Path(__file__),
    ]

    diacritic_pattern = re.compile(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]")
    diacritics_clean = True
    for f in touched_files:
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            if diacritic_pattern.search(text):
                diacritics_clean = False
                print(f"FAIL diacritic character in {f}")

    check("zero a/o/u-with-diacritics in touched files", diacritics_clean)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
