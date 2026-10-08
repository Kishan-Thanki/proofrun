"""Scenario execution with retries.

Each attempt of a scenario gets its own HTTP client. That isolates cookies and
connections between runs, so scenarios that execute at the same time cannot
interfere with each other.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from proofrun.config.models import ScenarioConfig
from proofrun.runner.engine import ScenarioResult, ScenarioRunner

ClientFactory = Callable[[], httpx.AsyncClient]
Sleep = Callable[[float], Awaitable[None]]


async def run_scenario(
    scenario: ScenarioConfig,
    client_factory: ClientFactory,
    sleep: Sleep = asyncio.sleep,
) -> ScenarioResult:
    """Run a scenario, re-running the whole scenario when it fails.

    A scenario is attempted up to ``scenario.retries + 1`` times, waiting
    ``scenario.retry_delay_seconds`` between attempts. The whole scenario is
    repeated, not just the failed step, because earlier steps may have created
    state that later steps depend on. Every attempt starts with an empty
    execution context and a new HTTP client.

    Args:
        scenario: Compiled scenario configuration.
        client_factory: Creates a new HTTP client for each attempt.
        sleep: Awaitable used to wait between attempts.

    Returns:
        The result of the last attempt, with ``attempts`` set to the number of
        attempts made.
    """
    attempt = 1

    while True:
        async with client_factory() as client:
            result = await ScenarioRunner(scenario).run(client)

        result.attempts = attempt

        if result.passed or attempt > scenario.retries:
            return result

        await sleep(scenario.retry_delay_seconds)
        attempt += 1
