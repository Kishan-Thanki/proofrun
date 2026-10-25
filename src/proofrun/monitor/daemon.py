"""Daemon loop: runs every scenario on its own schedule.

Each scenario runs as its own task, so a slow scenario never delays another,
and a scenario is never started while its previous run is still in progress.
Configuration is checked for changes on every tick, so edits are picked up
within ``max_tick`` seconds.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from proofrun.config.models import ScenarioConfig
from proofrun.config.provider import ConfigProvider
from proofrun.health import StateManager, StateTransition, Status
from proofrun.metrics.registry import MetricsRegistry
from proofrun.monitor.scheduler import Scheduler
from proofrun.notify.base import NotificationEvent, Notifier
from proofrun.redaction import redact_secrets
from proofrun.runner.engine import ScenarioResult
from proofrun.runner.execution import ClientFactory, Sleep, run_scenario


class Daemon:
    """Run scenarios continuously and report health transitions."""

    def __init__(
        self,
        provider: ConfigProvider,
        state: StateManager,
        client_factory: ClientFactory,
        *,
        notifier: Notifier | None = None,
        metrics: MetricsRegistry | None = None,
        interval_override: int | None = None,
        on_result: Callable[[ScenarioResult], None] | None = None,
        on_config_error: Callable[[str, bool], None] | None = None,
        on_internal_error: Callable[[str, BaseException], None] | None = None,
        scheduler: Scheduler | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Sleep = asyncio.sleep,
        max_tick: float = 1.0,
    ) -> None:
        """Create a daemon.

        Args:
            provider: Source of the compiled, hot-reloaded configuration.
            state: Health state tracking and transition detection.
            client_factory: Creates a new HTTP client for every scenario attempt.
            notifier: Receives alerts for health transitions.
            metrics: Receives run results and health states.
            interval_override: Replaces every scenario's ``interval_seconds``.
            on_result: Called with every finished scenario run.
            on_config_error: Called with the error text, and whether the last
                known-good configuration keeps running, when a configuration
                problem is first seen.
            on_internal_error: Called when a scenario task fails unexpectedly.
            scheduler: Decides which scenarios are due.
            clock: Monotonic clock in seconds.
            wall_clock: Unix time in seconds, used for metric timestamps.
            sleep: Waits between attempts of a retried scenario.
            max_tick: Longest time in seconds between configuration checks.
        """
        self.provider = provider
        self.state = state
        self.client_factory = client_factory
        self.notifier = notifier
        self.metrics = metrics
        self.interval_override = interval_override
        self.on_result = on_result
        self.on_config_error = on_config_error
        self.on_internal_error = on_internal_error
        self.scheduler = scheduler if scheduler is not None else Scheduler()
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleep = sleep
        self.max_tick = max_tick

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """Run until ``stop`` is set, or until the task is cancelled."""
        running: dict[str, asyncio.Task[None]] = {}
        running_secrets: dict[str, frozenset[str]] = {}
        last_error: str | None = None

        try:
            while stop is None or not stop.is_set():
                config, error = self.provider.load()

                if error is None:
                    last_error = None
                elif str(error) != last_error:
                    last_error = str(error)

                    if self.on_config_error is not None:
                        self.on_config_error(last_error, config is not None)

                scenarios = (
                    {scenario.name: scenario for scenario in config.scenarios}
                    if config is not None
                    else {}
                )

                self.state.sync(set(scenarios))

                if self.metrics is not None:
                    self.metrics.sync(set(scenarios))

                now = self.clock()
                intervals = {
                    name: float(self.interval_override or scenario.interval_seconds)
                    for name, scenario in scenarios.items()
                }

                for name in self.scheduler.due(intervals, running.keys(), now):
                    scenario = scenarios[name]
                    running[name] = asyncio.create_task(self._execute(scenario))
                    running_secrets[name] = scenario._secret_values

                delay = self.scheduler.seconds_until_next(now, running.keys())
                timeout = self.max_tick if delay is None else min(delay, self.max_tick)

                if running:
                    await asyncio.wait(
                        running.values(),
                        timeout=timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                else:
                    await asyncio.sleep(timeout)

                self._reap(running, running_secrets)
        finally:
            for task in running.values():
                task.cancel()

            if running:
                await asyncio.gather(*running.values(), return_exceptions=True)

    def _reap(
        self,
        running: dict[str, asyncio.Task[None]],
        running_secrets: dict[str, frozenset[str]],
    ) -> None:
        """Forget finished tasks and report unexpected failures safely."""
        for name in [name for name, task in running.items() if task.done()]:
            error = running.pop(name).exception()
            secret_values = running_secrets.pop(name, frozenset())

            if error is not None and self.on_internal_error is not None:
                safe_name = redact_secrets(name, secret_values)
                safe_error = RuntimeError(
                    f"Scenario task failed ({type(error).__name__}); details suppressed"
                )
                self.on_internal_error(safe_name, safe_error)

    async def _execute(self, scenario: ScenarioConfig) -> None:
        """Run one scenario and record the outcome."""
        result = await run_scenario(scenario, self.client_factory, self.sleep)

        transition = self.state.update(
            scenario.name,
            result.passed,
            scenario.failure_threshold,
            scenario.recovery_threshold,
        )

        if self.metrics is not None:
            self.metrics.record_run(
                scenario.name,
                result.passed,
                result.total_latency_ms / 1000,
                self.wall_clock(),
                secret_values=scenario._secret_values,
            )
            self.metrics.set_health(scenario.name, transition.new_status)

        if self.on_result is not None:
            self.on_result(result)

        await self._notify(transition, result, scenario._secret_values)

    async def _notify(
        self,
        transition: StateTransition,
        result: ScenarioResult,
        secret_values: frozenset[str],
    ) -> None:
        """Send an alert when the scenario started failing or recovered."""
        if self.notifier is None or not transition.changed:
            return

        if transition.new_status == Status.FAILING:
            errors = [
                f"- {step.step_name}: {step.error}"
                for step in result.step_results
                if not step.passed
            ]
            details = "\n".join(errors)
        elif (
            transition.old_status == Status.FAILING
            and transition.new_status == Status.HEALTHY
        ):
            details = "All steps passing."
        else:
            return

        await self.notifier.notify(
            NotificationEvent(
                scenario_name=redact_secrets(
                    transition.scenario_name,
                    secret_values,
                ),
                old_status=transition.old_status,
                new_status=transition.new_status,
                details=redact_secrets(details, secret_values),
            )
        )
