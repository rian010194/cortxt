"""Loopback-only static file server for the sessions widget.

Browsers block fetch() of file:// URLs (CORS), so index.html's poll loop
can't read snapshot.json without something serving it over HTTP. This
serves this directory's static files only -- no custom endpoint or
request-handling logic, bound to 127.0.0.1 so it's never reachable off the
machine. `cli/unified_cli.py sessions` writes snapshot.json here; this just
hands it back out.
"""
from __future__ import annotations

import functools
import http.server
import json
import socketserver
from pathlib import Path

try:
    from widget.poll_policy import MAX_ARTIFACT_BYTES
except ImportError:
    from poll_policy import MAX_ARTIFACT_BYTES

WIDGET_DIR = Path(__file__).parent
HOST = "127.0.0.1"
PORT = 8765


class WidgetHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Static file handler enforcing artifact size limits."""

    def do_GET(self) -> None:
        path = self.translate_path(self.path)
        p = Path(path)
        if p.is_file() and p.name != "index.html":
            try:
                size = p.stat().st_size
                if size > MAX_ARTIFACT_BYTES:
                    body = json.dumps({
                        "error": {
                            "kind": "artifact_too_large",
                            "message": f"Artifact exceeds maximum size of {MAX_ARTIFACT_BYTES} bytes ({size} bytes)",
                        }
                    }).encode("utf-8")
                    self.send_response(http.HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
            except OSError:
                pass
        super().do_GET()


class _ReusableTCPServer(socketserver.TCPServer):
    # Without this, restarting the widget within the OS's TIME_WAIT window
    # fails with "address already in use" on a routine Ctrl+C + rerun.
    allow_reuse_address = True


def main() -> int:
    handler = functools.partial(
        WidgetHTTPRequestHandler, directory=str(WIDGET_DIR)
    )
    with _ReusableTCPServer((HOST, PORT), handler) as httpd:
        print(f"Cortxt sessions widget: http://{HOST}:{PORT}/index.html")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
