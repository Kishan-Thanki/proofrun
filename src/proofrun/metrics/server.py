"""A minimal HTTP server exposing metrics and a health endpoint."""

from __future__ import annotations

import asyncio
import contextlib

from proofrun.metrics.registry import MetricsRegistry

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
MAX_HEADER_LINES = 100


def _response(
    status: str,
    body: str,
    content_type: str = "text/plain; charset=utf-8",
    extra_headers: str = "",
) -> bytes:
    data = body.encode()
    head = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(data)}\r\n"
        f"{extra_headers}"
        "Connection: close\r\n\r\n"
    )

    return head.encode("latin-1") + data


class MetricsServer:
    """A minimal HTTP server exposing ``/metrics`` and ``/health``.

    It has no authentication. It binds to loopback by default; binding to other
    interfaces is an explicit choice made by the caller.
    """

    def __init__(
        self,
        registry: MetricsRegistry,
        host: str = "127.0.0.1",
        port: int = 0,
        request_timeout: float = 5.0,
    ) -> None:
        self.registry = registry
        self.host = host
        self.port = port
        self.request_timeout = request_timeout
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start listening. ``port`` is updated with the bound port."""
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Stop listening."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _read_request_line(self, reader: asyncio.StreamReader) -> str:
        """Read the request line and discard the headers."""
        request_line = (await reader.readline()).decode("latin-1")

        for _ in range(MAX_HEADER_LINES):
            if (await reader.readline()).strip() == b"":
                break

        return request_line

    def _route(self, request_line: str) -> bytes:
        parts = request_line.split()

        if len(parts) < 2:
            return _response("400 Bad Request", "bad request\n")

        method, target = parts[0], parts[1]

        if method != "GET":
            return _response(
                "405 Method Not Allowed",
                "method not allowed\n",
                extra_headers="Allow: GET\r\n",
            )

        path = target.split("?", 1)[0]

        if path == "/metrics":
            return _response("200 OK", self.registry.render(), CONTENT_TYPE)

        if path == "/health":
            return _response("200 OK", "ok\n")

        return _response("404 Not Found", "not found\n")

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(
                self._read_request_line(reader),
                timeout=self.request_timeout,
            )
            writer.write(self._route(request_line))
            await writer.drain()
        except (TimeoutError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
