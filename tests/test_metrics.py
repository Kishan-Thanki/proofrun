"""Unit tests for metrics and the metrics server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from proofrun.health import Status
from proofrun.metrics.registry import MetricsRegistry
from proofrun.metrics.server import MetricsServer


def _line(output: str, metric: str, scenario: str) -> str | None:
    prefix = f'{metric}{{scenario="{scenario}"}} '

    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]

    return None


def test_empty_registry_renders_only_headers() -> None:
    output = MetricsRegistry().render()

    assert output.endswith("\n")
    assert "# TYPE proofrun_scenario_up gauge" in output
    assert "# TYPE proofrun_scenario_runs_total counter" in output
    assert "{" not in output.replace("{scenario", "")
    assert 'scenario="' not in output


def test_records_runs_durations_and_timestamps() -> None:
    registry = MetricsRegistry()

    registry.record_run("api", True, 0.25, 1000.5)
    registry.record_run("api", False, 1.5, 2000.5)
    registry.record_run("api", True, 0.5, 3000.5)

    output = registry.render()

    assert _line(output, "proofrun_scenario_runs_total", "api") == "3"
    assert _line(output, "proofrun_scenario_failures_total", "api") == "1"
    assert _line(output, "proofrun_scenario_duration_seconds", "api") == "0.5"
    assert (
        _line(output, "proofrun_scenario_last_success_timestamp_seconds", "api")
        == "3000.5"
    )
    assert (
        _line(output, "proofrun_scenario_last_failure_timestamp_seconds", "api")
        == "2000.5"
    )


def test_timestamps_are_absent_until_they_happen() -> None:
    registry = MetricsRegistry()

    registry.record_run("api", True, 0.1, 10.0)

    output = registry.render()

    assert (
        _line(output, "proofrun_scenario_last_failure_timestamp_seconds", "api") is None
    )
    assert (
        _line(output, "proofrun_scenario_last_success_timestamp_seconds", "api")
        == "10.0"
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [(Status.HEALTHY, "1"), (Status.FAILING, "0"), (Status.UNKNOWN, None)],
)
def test_health_is_exported_as_up(status: Status, expected: str | None) -> None:
    registry = MetricsRegistry()

    registry.record_run("api", True, 0.1, 1.0)
    registry.set_health("api", status)

    assert _line(registry.render(), "proofrun_scenario_up", "api") == expected


def test_sync_drops_removed_scenarios() -> None:
    registry = MetricsRegistry()

    registry.record_run("keep", True, 0.1, 1.0)
    registry.record_run("gone", True, 0.1, 1.0)
    registry.sync({"keep"})

    output = registry.render()

    assert 'scenario="keep"' in output
    assert 'scenario="gone"' not in output


def test_label_values_are_escaped() -> None:
    registry = MetricsRegistry()

    registry.record_run('a "quoted" \\ name\nline', True, 0.1, 1.0)

    assert 'scenario="a \\"quoted\\" \\\\ name\\nline"' in registry.render()


def test_scenarios_are_sorted() -> None:
    registry = MetricsRegistry()

    registry.record_run("b", True, 0.1, 1.0)
    registry.record_run("a", True, 0.1, 1.0)

    runs = [
        line
        for line in registry.render().splitlines()
        if line.startswith("proofrun_scenario_runs_total{")
    ]

    assert runs == [
        'proofrun_scenario_runs_total{scenario="a"} 1',
        'proofrun_scenario_runs_total{scenario="b"} 1',
    ]


async def _request(port: int, raw: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()

    data = await asyncio.wait_for(reader.read(), timeout=5)

    writer.close()

    return data


@pytest.fixture
async def server() -> AsyncIterator[MetricsServer]:
    registry = MetricsRegistry()
    registry.record_run("api", True, 0.1, 1.0)

    metrics_server = MetricsServer(registry, request_timeout=0.2)
    await metrics_server.start()

    yield metrics_server

    await metrics_server.stop()


async def test_server_serves_metrics(server: MetricsServer) -> None:
    response = await _request(
        server.port,
        b"GET /metrics HTTP/1.1\r\nHost: x\r\n\r\n",
    )

    head, _, body = response.partition(b"\r\n\r\n")

    assert head.startswith(b"HTTP/1.1 200 OK")
    assert b"Content-Type: text/plain; version=0.0.4; charset=utf-8" in head
    assert b'proofrun_scenario_runs_total{scenario="api"} 1' in body


async def test_server_ignores_the_query_string(server: MetricsServer) -> None:
    response = await _request(server.port, b"GET /metrics?x=1 HTTP/1.1\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 200 OK")


async def test_server_health_endpoint(server: MetricsServer) -> None:
    response = await _request(server.port, b"GET /health HTTP/1.1\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 200 OK")
    assert response.endswith(b"ok\n")


async def test_server_unknown_path_is_404(server: MetricsServer) -> None:
    response = await _request(server.port, b"GET /nope HTTP/1.1\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 404 Not Found")


async def test_server_rejects_other_methods(server: MetricsServer) -> None:
    response = await _request(server.port, b"POST /metrics HTTP/1.1\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 405 Method Not Allowed")
    assert b"Allow: GET" in response


async def test_server_rejects_malformed_requests(server: MetricsServer) -> None:
    response = await _request(server.port, b"nonsense\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 400 Bad Request")


async def test_server_stops_reading_after_too_many_headers(
    server: MetricsServer,
) -> None:
    headers = b"X-Header: value\r\n" * 150
    response = await _request(server.port, b"GET /health HTTP/1.1\r\n" + headers)

    assert response.startswith(b"HTTP/1.1 200 OK")


async def test_server_drops_oversized_request_lines(server: MetricsServer) -> None:
    try:
        response = await _request(
            server.port,
            b"GET /" + b"a" * 200_000 + b" HTTP/1.1\r\n\r\n",
        )
    except ConnectionError:
        response = b""

    assert response == b""


async def test_server_times_out_idle_connections(server: MetricsServer) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)

    data = await asyncio.wait_for(reader.read(), timeout=5)

    writer.close()

    assert data == b""


async def test_server_survives_clients_that_disconnect(server: MetricsServer) -> None:
    _, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.close()
    await asyncio.sleep(0.05)

    response = await _request(server.port, b"GET /health HTTP/1.1\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 200 OK")


async def test_server_binds_to_loopback_by_default() -> None:
    assert MetricsServer(MetricsRegistry()).host == "127.0.0.1"


async def test_stop_is_safe_before_start_and_twice() -> None:
    metrics_server = MetricsServer(MetricsRegistry())

    await metrics_server.stop()
    await metrics_server.start()
    await metrics_server.stop()
    await metrics_server.stop()
