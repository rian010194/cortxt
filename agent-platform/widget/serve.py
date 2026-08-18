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
import socketserver
from pathlib import Path

WIDGET_DIR = Path(__file__).parent
HOST = "127.0.0.1"
PORT = 8765


class _ReusableTCPServer(socketserver.TCPServer):
    # Without this, restarting the widget within the OS's TIME_WAIT window
    # fails with "address already in use" on a routine Ctrl+C + rerun.
    allow_reuse_address = True


def main() -> int:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(WIDGET_DIR)
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
