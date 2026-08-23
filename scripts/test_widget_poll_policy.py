#!/usr/bin/env python3
"""Offline checks for widget host bounded polling and result-size defaults (#326).

Run: python scripts/test_widget_poll_policy.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
- next_interval exponential backoff calculation and cap bounds
- truncate_rows result volume truncation and truncated boolean marker
- artifact_size_exceeded byte-limit check
- index.html backoff constants, state tracking, and truncation note rendering
- serve.py artifact size limit handling and typed error response
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
from http import HTTPStatus
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

from widget.poll_policy import (  # noqa: E402
    DEFAULT_BASE_MS,
    DEFAULT_CAP_MS,
    DEFAULT_MAX_BACKOFF_MS,
    DEFAULT_ROW_CAP,
    MAX_ARTIFACT_BYTES,
    artifact_size_exceeded,
    next_interval,
    truncate_rows,
)
from widget.serve import WidgetHTTPRequestHandler  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def main() -> int:
    # 1. next_interval: backoff shape and bounds
    check("next_interval 0 failures returns base_ms",
          next_interval(0) == DEFAULT_BASE_MS)
    check("next_interval negative failures returns base_ms",
          next_interval(-1) == DEFAULT_BASE_MS)
    check("next_interval 1 failure returns 2x base",
          next_interval(1) == 6000)
    check("next_interval 2 failures returns 4x base",
          next_interval(2) == 12000)
    check("next_interval 3 failures returns 8x base",
          next_interval(3) == 24000)
    check("next_interval 4 failures capped at max_backoff_ms",
          next_interval(4) == DEFAULT_MAX_BACKOFF_MS)
    check("next_interval high failures capped at max_backoff_ms",
          next_interval(10) == DEFAULT_MAX_BACKOFF_MS
          and next_interval(100) == DEFAULT_MAX_BACKOFF_MS)
    check("next_interval never exceeds cap_ms even if max_backoff is larger",
          next_interval(10, base_ms=5000, max_backoff_ms=100000, cap_ms=45000) == 45000)
    check("next_interval base_ms capped by cap_ms on 0 failures",
          next_interval(0, base_ms=80000, cap_ms=50000) == 50000)

    # 2. truncate_rows: cap enforcement and boolean flag
    empty_res, empty_trunc = truncate_rows([])
    check("truncate_rows empty list is not truncated",
          empty_res == [] and not empty_trunc)

    below_rows = list(range(10))
    res_below, trunc_below = truncate_rows(below_rows, cap=500)
    check("truncate_rows below cap returns full list and False",
          res_below == below_rows and not trunc_below)

    exact_rows = list(range(500))
    res_exact, trunc_exact = truncate_rows(exact_rows, cap=500)
    check("truncate_rows at exact cap returns full list and False",
          len(res_exact) == 500 and not trunc_exact)

    above_rows = list(range(600))
    res_above, trunc_above = truncate_rows(above_rows, cap=500)
    check("truncate_rows above cap returns capped list and True",
          len(res_above) == 500 and res_above == list(range(500)) and trunc_above)

    res_default, trunc_default = truncate_rows(list(range(DEFAULT_ROW_CAP + 10)))
    check("truncate_rows uses DEFAULT_ROW_CAP (500) by default",
          len(res_default) == DEFAULT_ROW_CAP and trunc_default)

    # 3. artifact_size_exceeded: byte boundary check
    check("artifact_size_exceeded returns False below max_bytes",
          not artifact_size_exceeded(100))
    check("artifact_size_exceeded returns False at exact max_bytes",
          not artifact_size_exceeded(MAX_ARTIFACT_BYTES))
    check("artifact_size_exceeded returns True above max_bytes",
          artifact_size_exceeded(MAX_ARTIFACT_BYTES + 1))
    check("artifact_size_exceeded custom max_bytes respected",
          artifact_size_exceeded(501, max_bytes=500)
          and not artifact_size_exceeded(500, max_bytes=500))

    # 4. index.html: backoff constants, state tracking, and truncation rendering
    html_path = AP / "widget" / "index.html"
    check("index.html exists", html_path.is_file())
    html_content = html_path.read_text(encoding="utf-8")

    match = re.search(r"<script>(.*?)</script>", html_content, re.DOTALL)
    check("index.html contains script block", match is not None)
    script = match.group(1) if match else ""

    check("index.html defines POLL_BASE_MS constant", "POLL_BASE_MS" in script)
    check("index.html defines POLL_MAX_BACKOFF_MS constant", "POLL_MAX_BACKOFF_MS" in script)
    check("index.html defines POLL_CAP_MS constant", "POLL_CAP_MS" in script)
    check("index.html tracks pollState map", "pollState" in script)
    check("index.html defines nextInterval function", "nextInterval" in script)
    check("index.html renders truncated note for table/list",
          "truncated (" in script and "shown)" in script)

    # node --check syntax check on script
    with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w", encoding="utf-8") as tmp:
        tmp.write(script)
        tmp.flush()
        node_res = subprocess.run(["node", "--check", tmp.name], capture_output=True, text=True)
        check("node --check passes on index.html script", node_res.returncode == 0)

    # 5. serve.py: size-bound handling and typed error response
    check("serve.py defines MAX_ARTIFACT_BYTES", MAX_ARTIFACT_BYTES == 1024 * 1024)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_dir_path = Path(tmpdir)
        oversized_file = tmp_dir_path / "big_artifact.json"
        oversized_file.write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 10))

        class DummySocket:
            def __init__(self):
                self.data = io.BytesIO()

            def makefile(self, mode, *args, **kwargs):
                return io.BytesIO()

            def sendall(self, data):
                self.data.write(data)

        # Instantiate WidgetHTTPRequestHandler with translated path pointing to oversized file
        class TestHandler(WidgetHTTPRequestHandler):
            def __init__(self, req_path):
                self.path = req_path
                self.wfile = io.BytesIO()
                self.rfile = io.BytesIO()
                self.headers = {}
                self._headers_buffer = []

            def translate_path(self, path):
                return str(oversized_file)

            def send_response(self, code, message=None):
                self.status_code = code

            def send_header(self, keyword, value):
                self._headers_buffer.append((keyword, value))

            def end_headers(self):
                pass

        handler = TestHandler("/big_artifact.json")
        handler.do_GET()
        check("oversized artifact returns HTTP 200 with typed error",
              getattr(handler, "status_code", None) == HTTPStatus.OK)
        output_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        check("oversized artifact response contains error.kind artifact_too_large",
              output_data.get("error", {}).get("kind") == "artifact_too_large")

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
