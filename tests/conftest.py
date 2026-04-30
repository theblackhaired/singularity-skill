"""Shared test fixtures."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import pytest
except ImportError:  # unittest-only environments do not require pytest.
    pytest = None

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = ROOT / "tests" / "snapshots" / "cli"


class MockHTTPServer:
    """Small stdlib HTTP fixture for contract tests.

    routes: {(method, path): callable(query_params) -> (status, json_body)}
    """

    def __init__(self, routes: dict):
        self.routes = {
            (method.upper(), path): handler
            for (method, path), handler in routes.items()
        }
        self._request_log = []
        self._server = None
        self._thread = None
        self._base_url = None

    def start(self) -> str:
        if self._server is not None:
            return self._base_url

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return

            def do_GET(self):
                self._handle()

            def do_POST(self):
                self._handle()

            def do_PATCH(self):
                self._handle()

            def do_DELETE(self):
                self._handle()

            def _handle(self):
                parsed = urlparse(self.path)
                query_params = parse_qs(parsed.query, keep_blank_values=True)
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(length) if length else b""
                body_text = raw_body.decode("utf-8", errors="replace")
                json_body = None
                if raw_body:
                    try:
                        json_body = json.loads(body_text)
                    except json.JSONDecodeError:
                        json_body = None

                outer._request_log.append({
                    "method": self.command,
                    "path": parsed.path,
                    "query": query_params,
                    "headers": dict(self.headers),
                    "body": body_text,
                    "json": json_body,
                })

                route = outer.routes.get((self.command, parsed.path))
                if route is None:
                    self._send_json(404, {
                        "error": f"no route for {self.command} {parsed.path}",
                    })
                    return

                try:
                    status, payload = route(query_params)
                except Exception as exc:  # noqa: BLE001 - fixture should surface route failures.
                    status, payload = 500, {"error": f"{type(exc).__name__}: {exc}"}
                self._send_json(status, payload)

            def _send_json(self, status: int, payload):
                if payload is None:
                    body = b""
                elif isinstance(payload, bytes):
                    body = payload
                elif isinstance(payload, str):
                    body = payload.encode("utf-8")
                else:
                    body = json.dumps(payload).encode("utf-8")

                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        port = self._server.server_address[1]
        self._base_url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return self._base_url

    def stop(self):
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        self._base_url = None

    @property
    def request_log(self) -> list:
        return self._request_log


if pytest is not None:
    @pytest.fixture
    def mock_server():
        servers = []

        def factory(routes) -> MockHTTPServer:
            server = MockHTTPServer(routes)
            server.start()
            servers.append(server)
            return server

        try:
            yield factory
        finally:
            for server in servers:
                server.stop()
