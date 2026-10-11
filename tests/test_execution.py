"""Unit tests for scenario execution with retries."""

from __future__ import annotations

from typing import Any

import httpx

from proofrun.config.models import ScenarioConfig
from proofrun.runner.execution import run_scenario


def _scenario(retries: int = 0, delay: float = 0.25) -> ScenarioConfig:
    def step(name: str, path: str) -> dict[str, Any]:
        return {
            "name": name,
            "request": {"method": "GET", "path": path, "timeout": 5},
            "expect": {"status": 200},
        }

    return ScenarioConfig.model_validate(
        {
            "name": "Retry Scenario",
            "base_url": "http://test.invalid",
            "retries": retries,
            "retry_delay_seconds": delay,
            "steps": [step("First", "/first"), step("Second", "/second")],
        }
    )


class _Backend:
    """Records requests and fails ``/second`` for the first N attempts."""

    def __init__(self, failing_attempts: int = 0) -> None:
        self.failing_attempts = failing_attempts
        self.requests: list[str] = []
        self.clients_created = 0
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)

        if request.url.path == "/second" and self.failing_attempts > 0:
            self.failing_attempts -= 1
            return httpx.Response(503)

        return httpx.Response(200, json={})

    def client_factory(self) -> httpx.AsyncClient:
        self.clients_created += 1
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


async def test_passing_scenario_runs_once() -> None:
    backend = _Backend()

    result = await run_scenario(
        _scenario(retries=3), backend.client_factory, backend.sleep
    )

    assert result.passed
    assert result.attempts == 1
    assert backend.requests == ["/first", "/second"]
    assert backend.sleeps == []


async def test_no_retries_by_default() -> None:
    backend = _Backend(failing_attempts=5)

    result = await run_scenario(_scenario(), backend.client_factory, backend.sleep)

    assert not result.passed
    assert result.attempts == 1
    assert backend.sleeps == []


async def test_scenario_is_retried_until_it_passes() -> None:
    backend = _Backend(failing_attempts=2)

    result = await run_scenario(
        _scenario(retries=3), backend.client_factory, backend.sleep
    )

    assert result.passed
    assert result.attempts == 3
    assert backend.sleeps == [0.25, 0.25]


async def test_retries_are_exhausted() -> None:
    backend = _Backend(failing_attempts=99)

    result = await run_scenario(
        _scenario(retries=2), backend.client_factory, backend.sleep
    )

    assert not result.passed
    assert result.attempts == 3
    assert result.step_results[-1].status_code == 503
    assert len(backend.sleeps) == 2


async def test_retry_repeats_the_whole_scenario() -> None:
    backend = _Backend(failing_attempts=1)

    await run_scenario(_scenario(retries=1), backend.client_factory, backend.sleep)

    assert backend.requests == ["/first", "/second", "/first", "/second"]


async def test_every_attempt_gets_its_own_client() -> None:
    backend = _Backend(failing_attempts=2)

    await run_scenario(_scenario(retries=2), backend.client_factory, backend.sleep)

    assert backend.clients_created == 3


async def test_default_sleep_waits_between_attempts() -> None:
    backend = _Backend(failing_attempts=1)

    result = await run_scenario(_scenario(retries=1, delay=0), backend.client_factory)

    assert result.passed
    assert result.attempts == 2
