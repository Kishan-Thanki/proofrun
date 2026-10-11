"""A tiny local API for trying Proofrun without any external service.

Every scenario in this directory runs against it, so the examples and the
integration checks in CI work offline and never depend on a third-party host.

Endpoints
  GET    /health              -> 200
  POST   /login               -> 200 + access_token (password: demo-password)
  GET    /me                  -> 200 + user id (requires Bearer token)
  GET    /users/<id>/orders   -> 200 + orders (requires Bearer token, id 42)
  GET    /users/<id>          -> 200 + user (id 1), else 404
  GET    /posts/<id>          -> 200 + post (id 1), else 404
  GET    /posts/<id>/comments -> 200 + comments (id 1), else 404
  POST   /posts               -> 201 + the posted body with a new id
  PUT    /posts/<id>          -> 200 + the posted body (id 1), else 404
  DELETE /posts/<id>          -> 200 (id 1), else 404

Run it:
  python3 scenarios/server.py           # healthy
  python3 scenarios/server.py --break   # /me returns 500
"""

from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

TOKEN = "demo-token-123"
PASSWORD = "demo-password"
BROKEN = False

JSON_CONTENT_TYPE = "application/json; charset=utf-8"

USER_1: dict[str, Any] = {
    "id": 1,
    "name": "Ada Lovelace",
    "username": "ada",
    "email": "ada@example.com",
    "address": {"street": "1 Analytical Way", "city": "London", "zipcode": "10001"},
    "company": {"name": "Difference Engines Ltd"},
}

POST_1: dict[str, Any] = {
    "userId": 1,
    "id": 1,
    "title": "First post",
    "body": "Hello from the Proofrun demo API.",
}

COMMENTS_POST_1: list[dict[str, Any]] = [
    {
        "postId": 1,
        "id": 1,
        "name": "First comment",
        "email": "grace@example.com",
        "body": "Nice post.",
    }
]

ORDERS: list[dict[str, Any]] = [{"id": 1, "total": 19.99}]

POST_PATH = re.compile(r"^/posts/(\d+)$")
POST_COMMENTS_PATH = re.compile(r"^/posts/(\d+)/comments$")
USER_PATH = re.compile(r"^/users/(\d+)$")
USER_ORDERS_PATH = re.compile(r"^/users/(\d+)/orders$")


class Handler(BaseHTTPRequestHandler):
    """HTTP request handler for the mock API server."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence request logging."""

    def _send(self, code: int, body: dict[str, Any] | list[Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _not_found(self) -> None:
        self._send(404, {"error": "not found"})

    def _authed(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) or b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return body if isinstance(body, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if path == "/health":
            return self._send(200, {"status": "ok"})

        if path == "/me":
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            if BROKEN:
                time.sleep(0.05)
                return self._send(500, {"error": "profile service unavailable"})
            return self._send(200, {"id": 42, "email": "demo@example.com"})

        if USER_ORDERS_PATH.match(path):
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            if path == "/users/42/orders":
                return self._send(200, ORDERS)
            return self._not_found()

        if USER_PATH.match(path):
            if path == "/users/1":
                return self._send(200, USER_1)
            return self._not_found()

        if POST_COMMENTS_PATH.match(path):
            if path == "/posts/1/comments":
                return self._send(200, COMMENTS_POST_1)
            return self._not_found()

        if POST_PATH.match(path):
            if path == "/posts/1":
                return self._send(200, POST_1)
            return self._not_found()

        self._not_found()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self._read_json()

        if path == "/login":
            if body.get("password") == PASSWORD:
                return self._send(200, {"access_token": TOKEN, "expires_in": 3600})
            return self._send(401, {"error": "bad credentials"})

        if path == "/posts":
            return self._send(201, {**body, "id": 101})

        self._not_found()

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self._read_json()

        if path == "/posts/1":
            return self._send(200, {**body, "id": 1})

        self._not_found()

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if path == "/posts/1":
            return self._send(200, {})

        self._not_found()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--break",
        dest="broken",
        action="store_true",
        help="make GET /me return 500",
    )
    args = parser.parse_args()
    BROKEN = args.broken
    print(
        f"Mock API on http://127.0.0.1:{args.port}  (broken={BROKEN})  Ctrl+C to stop"
    )
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
