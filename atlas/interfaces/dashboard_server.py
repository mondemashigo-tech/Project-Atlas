"""Local HTTP server for the existing dashboard — hardened.

The original inline server (in cli.py) was single-threaded and wrote the response
with no guard, so a browser aborting an in-flight auto-refresh GET (or closing the
tab) raised ConnectionAbortedError / BrokenPipeError, which socketserver printed
as an alarming — but non-fatal — traceback. This module fixes both issues:

- ``ThreadingHTTPServer`` so one slow/aborted client can't block others, and
- the response write is guarded, and ``handle_error`` swallows the benign
  connection-reset family (still logging anything genuinely unexpected).

Behaviour is otherwise identical: it serves the same ``dashboard.render`` HTML.
This keeps the current dashboard a stable fallback while Atlas Live is built.
"""
from __future__ import annotations

import http.server
import sys
import traceback

from . import dashboard

# The connection-reset family raised when a client goes away mid-response.
_BENIGN = (ConnectionError, ConnectionResetError, ConnectionAbortedError,
           BrokenPipeError)


class QuietThreadingServer(http.server.ThreadingHTTPServer):
    """Threaded server that treats client disconnects as routine, not errors."""
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, _BENIGN):
            return                      # browser hung up — expected, ignore
        traceback.print_exc()           # anything else is a real bug: surface it


def make_handler(root: str, refresh_secs: int):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                body = dashboard.render(root, refresh_secs=refresh_secs).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except _BENIGN:
                return                  # client went away mid-response — harmless

        def log_message(self, *a):      # keep the console quiet
            pass

    return Handler


def make_server(root: str = ".", port: int = 8787, refresh_secs: int = 15
                ) -> QuietThreadingServer:
    """Build (but do not start) the dashboard server. Pass port=0 for an
    ephemeral port (used by tests)."""
    return QuietThreadingServer(("127.0.0.1", port), make_handler(root, refresh_secs))


def serve(root: str = ".", port: int = 8787, refresh_secs: int = 15) -> None:
    srv = make_server(root, port, refresh_secs)
    actual = srv.server_address[1]
    print(f"Atlas dashboard live at  http://127.0.0.1:{actual}  "
          f"(auto-refresh {refresh_secs}s)\nPress Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        srv.server_close()
