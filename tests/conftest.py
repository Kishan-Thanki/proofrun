# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Shared pytest fixtures."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _LocalAPIHandler(BaseHTTPRequestHandler):
    """Tiny deterministic API so tests never touch the internet.

    ``GET /fail`` returns 500; every other GET returns 200 with a JSON body.
    """

    def do_GET(self) -> None:  # noqa: N802
        status = 500 if self.path == "/fail" else 200
        body = json.dumps({"id": 1, "title": "hello"}).encode()

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence request logging."""


@pytest.fixture
def local_api() -> Iterator[str]:
    """Serve a local HTTP API on a free port and yield its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
