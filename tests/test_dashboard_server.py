"""The hardened dashboard server: serves real HTML, and survives a client that
disconnects mid-request without crashing or spewing a traceback."""
import socket
import threading
import urllib.request

from atlas.interfaces import dashboard_server


def _start(tmp_path):
    srv = dashboard_server.make_server(str(tmp_path), port=0, refresh_secs=5)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def test_serves_dashboard_html(tmp_path):
    srv, port = _start(tmp_path)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
            body = r.read().decode("utf-8")
        assert "<html" in body.lower() and "atlas" in body.lower()
    finally:
        srv.shutdown()
        srv.server_close()


def test_survives_client_disconnect(tmp_path):
    srv, port = _start(tmp_path)
    try:
        # Rudely open a connection, send a partial request, and hang up — the
        # exact shape of a browser aborting an auto-refresh GET.
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n")   # incomplete: no blank line
        s.close()                                      # abort mid-request

        # The server must still answer the next request normally.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_handle_error_swallows_benign_disconnects(tmp_path):
    """handle_error must ignore the connection-reset family and re-raise nothing
    for them (so no traceback is printed on a normal browser hang-up)."""
    srv = dashboard_server.make_server(str(tmp_path), port=0)
    try:
        for exc in (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            try:
                raise exc()
            except exc:
                srv.handle_error(None, ("127.0.0.1", 0))   # must not raise/print
    finally:
        srv.server_close()
