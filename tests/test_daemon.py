# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Unit tests for the daemon loop."""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from proofrun.cli.render import print_internal_error
from proofrun.config.models import ScenarioConfig
from proofrun.config.provider import ConfigProvider
from proofrun.health import StateManager, Status
from proofrun.metrics.registry import MetricsRegistry
from proofrun.monitor.daemon import Daemon
from proofrun.monitor.scheduler import Scheduler
from proofrun.notify.base import NotificationEvent
from proofrun.runner.engine import ScenarioResult, StepResult
from proofrun.runner.execution import ClientFactory, Sleep


class FakeClock:
    """A monotonic clock that advances on every read, so intervals elapse fast."""

    def __init__(self, step: float = 0.5) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    async def notify(self, event: NotificationEvent) -> None:
        self.events.append(event)


def make_result(name: str, passed: bool) -> ScenarioResult:
    return ScenarioResult(
        scenario_name=name,
        passed=passed,
        total_latency_ms=250.0,
        step_results=[
            StepResult(
                step_name="Step",
                passed=passed,
                status_code=200 if passed else 500,
                latency_ms=250.0,
                error=None if passed else "boom",
            )
        ],
    )


def scenario_dict(name: str, **overrides: Any) -> dict[str, Any]:
    return {
        "name": name,
        "interval_seconds": 1,
        "steps": [
            {
                "name": "Step",
                "request": {"method": "GET", "path": "/"},
                "expect": {"status": 200},
            }
        ],
        **overrides,
    }


def write_config(path: Path, *scenarios: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "global": {"base_url": "http://test.invalid"},
                "scenarios": list(scenarios),
            }
        ),
        encoding="utf-8",
    )


def touch_newer(path: Path, seconds: int = 5) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 1_000_000_000))


async def until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition was not met in time")

        await asyncio.sleep(0.005)


def no_http() -> ClientFactory:
    def factory() -> Any:  # pragma: no cover - run_scenario is faked in these tests
        raise AssertionError("no HTTP expected")

    return factory


def scripted(
    results: list[bool],
    starts: Counter[str] | None = None,
) -> Callable[..., Any]:
    """Fake run_scenario: replay pass/fail results, then block forever."""
    queue: Iterator[bool] = iter(results)

    async def fake(
        scenario: ScenarioConfig,
        client_factory: ClientFactory,
        sleep: Sleep,
    ) -> ScenarioResult:
        if starts is not None:
            starts[scenario.name] += 1

        try:
            passed = next(queue)
        except StopIteration:
            await asyncio.Event().wait()
            raise  # pragma: no cover

        return make_result(scenario.name, passed)

    return fake


def make_daemon(
    config_path: Path,
    **kwargs: Any,
) -> Daemon:
    kwargs.setdefault("clock", FakeClock())
    kwargs.setdefault("scheduler", Scheduler(uniform=lambda low, high: 1.0))
    kwargs.setdefault("max_tick", 0.01)

    return Daemon(
        ConfigProvider(config_path),
        kwargs.pop("state", StateManager()),
        no_http(),
        **kwargs,
    )


async def run_until(
    daemon: Daemon,
    condition: Callable[[], bool],
) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))

    try:
        await until(condition)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)


async def test_scenario_runs_repeatedly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    starts: Counter[str] = Counter()
    results: list[ScenarioResult] = []
    monkeypatch.setattr(
        "proofrun.monitor.daemon.run_scenario",
        scripted([True, True, True], starts),
    )
    state = StateManager()

    await run_until(
        make_daemon(config, state=state, on_result=results.append),
        lambda: len(results) >= 3,
    )

    assert [r.scenario_name for r in results] == ["A", "A", "A"]
    assert state.states["A"].status == Status.HEALTHY
    assert state.states["A"].pass_count == 3


async def test_scenarios_follow_independent_schedules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(
        config,
        scenario_dict("fast", interval_seconds=1),
        scenario_dict("slow", interval_seconds=1000),
    )
    starts: Counter[str] = Counter()

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        starts[scenario.name] += 1
        return make_result(scenario.name, True)

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)

    await run_until(make_daemon(config), lambda: starts["fast"] >= 4)

    assert starts["slow"] == 1


async def test_interval_override_replaces_scenario_intervals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A", interval_seconds=1000))
    starts: Counter[str] = Counter()
    monkeypatch.setattr(
        "proofrun.monitor.daemon.run_scenario",
        scripted([True] * 5, starts),
    )

    await run_until(
        make_daemon(config, interval_override=1),
        lambda: starts["A"] >= 3,
    )


async def test_slow_scenario_does_not_delay_or_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("slow"), scenario_dict("fast"))
    starts: Counter[str] = Counter()
    release = asyncio.Event()

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        starts[scenario.name] += 1

        if scenario.name == "slow":
            await release.wait()

        return make_result(scenario.name, True)

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)
    daemon = make_daemon(config)
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))

    try:
        await until(lambda: starts["fast"] >= 4)

        assert starts["slow"] == 1

        release.set()
        await until(lambda: starts["slow"] >= 2)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)


async def test_thresholds_control_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(
        config,
        scenario_dict("A", failure_threshold=2, recovery_threshold=2),
    )
    results: list[ScenarioResult] = []
    notifier = RecordingNotifier()
    monkeypatch.setattr(
        "proofrun.monitor.daemon.run_scenario",
        scripted([True, False, True, False, False, True, True]),
    )

    await run_until(
        make_daemon(config, notifier=notifier, on_result=results.append),
        lambda: len(results) >= 7,
    )

    assert [(e.old_status, e.new_status) for e in notifier.events] == [
        (Status.HEALTHY, Status.FAILING),
        (Status.FAILING, Status.HEALTHY),
    ]
    assert notifier.events[0].details == "- Step: boom"
    assert notifier.events[1].details == "All steps passing."


async def test_unknown_to_healthy_does_not_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    results: list[ScenarioResult] = []
    notifier = RecordingNotifier()
    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", scripted([True, True]))

    await run_until(
        make_daemon(config, notifier=notifier, on_result=results.append),
        lambda: len(results) >= 2,
    )

    assert notifier.events == []


async def test_metrics_are_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    results: list[ScenarioResult] = []
    registry = MetricsRegistry()
    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", scripted([True, False]))

    await run_until(
        make_daemon(
            config,
            metrics=registry,
            on_result=results.append,
            wall_clock=lambda: 1234.5,
        ),
        lambda: len(results) >= 2,
    )

    output = registry.render()

    assert 'proofrun_scenario_runs_total{scenario="A"} 2' in output
    assert 'proofrun_scenario_failures_total{scenario="A"} 1' in output
    assert 'proofrun_scenario_up{scenario="A"} 0' in output
    assert 'proofrun_scenario_duration_seconds{scenario="A"} 0.25' in output
    assert (
        'proofrun_scenario_last_failure_timestamp_seconds{scenario="A"} 1234.5'
        in output
    )


async def test_environment_secret_in_scenario_name_is_redacted_from_daemon_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daemon metrics must not export environment secrets in scenario labels."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-DAEMON-METRICS-81cf"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("${env.PROOFRUN_TEST_SECRET}"))

    results: list[ScenarioResult] = []
    registry = MetricsRegistry()
    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", scripted([True]))

    await run_until(
        make_daemon(
            config,
            metrics=registry,
            on_result=results.append,
        ),
        lambda: len(results) >= 1,
    )

    output = registry.render()

    assert secret not in output
    assert 'scenario="[REDACTED]"' in output


async def test_works_without_optional_collaborators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    starts: Counter[str] = Counter()
    monkeypatch.setattr(
        "proofrun.monitor.daemon.run_scenario",
        scripted([False, True], starts),
    )

    await run_until(make_daemon(config), lambda: starts["A"] >= 2)


async def test_configuration_errors_are_reported_once(tmp_path: Path) -> None:
    config = tmp_path / "c.yaml"
    config.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")
    errors: list[tuple[str, bool]] = []

    daemon = make_daemon(
        config,
        on_config_error=lambda text, last_good: errors.append((text, last_good)),
    )

    await run_until(daemon, lambda: daemon.clock() > 20)

    assert len(errors) == 1
    assert "Config validation failed" in errors[0][0]
    assert errors[0][1] is False


async def test_invalid_reload_keeps_last_known_good_and_fix_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    starts: Counter[str] = Counter()
    errors: list[tuple[str, bool]] = []

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        starts[scenario.name] += 1
        return make_result(scenario.name, True)

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)
    daemon = make_daemon(
        config,
        on_config_error=lambda text, last_good: errors.append((text, last_good)),
    )
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))

    try:
        await until(lambda: starts["A"] >= 2)

        config.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")
        touch_newer(config, 1)
        await until(lambda: len(errors) == 1)

        runs_after_break = starts["A"]
        await until(lambda: starts["A"] >= runs_after_break + 2)

        assert errors[0][1] is True

        write_config(config, scenario_dict("A"), scenario_dict("B"))
        touch_newer(config, 2)
        await until(lambda: starts["B"] >= 1)

        config.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")
        touch_newer(config, 3)
        await until(lambda: len(errors) == 2)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    assert errors[0][0] == errors[1][0]


async def test_removed_scenarios_lose_state_and_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"), scenario_dict("B"))
    starts: Counter[str] = Counter()

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        starts[scenario.name] += 1
        return make_result(scenario.name, True)

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)
    state = StateManager()
    registry = MetricsRegistry()
    daemon = make_daemon(config, state=state, metrics=registry)
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))

    try:
        await until(lambda: starts["A"] >= 1 and starts["B"] >= 1)

        write_config(config, scenario_dict("A"))
        touch_newer(config)
        await until(lambda: "B" not in state.states)
        await until(lambda: 'scenario="B"' not in registry.render())
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    assert "A" in state.states


async def test_unexpected_scenario_errors_are_reported_and_survived(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    calls: Counter[str] = Counter()
    internal: list[tuple[str, BaseException]] = []

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        calls[scenario.name] += 1

        if calls[scenario.name] == 1:
            raise RuntimeError("bug")

        return make_result(scenario.name, True)

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)

    await run_until(
        make_daemon(config, on_internal_error=lambda n, e: internal.append((n, e))),
        lambda: calls["A"] >= 2,
    )

    assert internal[0][0] == "A"
    assert "RuntimeError" in str(internal[0][1])
    assert "details suppressed" in str(internal[0][1])


async def test_unexpected_errors_without_a_handler_are_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    calls: Counter[str] = Counter()

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        calls[scenario.name] += 1
        raise RuntimeError("bug")

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)

    await run_until(make_daemon(config), lambda: calls["A"] >= 2)


async def test_stopping_cancels_running_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    started = asyncio.Event()
    cancelled: list[bool] = []

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        started.set()

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)

    await run_until(make_daemon(config), started.is_set)

    assert cancelled == [True]


async def test_cancelling_the_daemon_cancels_running_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("A"))
    started = asyncio.Event()
    cancelled: list[bool] = []

    async def fake(scenario: ScenarioConfig, *_: Any) -> ScenarioResult:
        started.set()

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr("proofrun.monitor.daemon.run_scenario", fake)
    task = asyncio.create_task(make_daemon(config).run())

    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled == [True]


async def test_configuration_errors_without_a_handler_are_ignored(
    tmp_path: Path,
) -> None:
    config = tmp_path / "c.yaml"
    config.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")
    daemon = make_daemon(config)

    await run_until(daemon, lambda: daemon.clock() > 5)


async def test_environment_secret_in_scenario_name_is_redacted_from_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment secrets must not leak through notification events."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-WEBHOOK-63af"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("${env.PROOFRUN_TEST_SECRET}"))

    notifier = RecordingNotifier()
    monkeypatch.setattr(
        "proofrun.monitor.daemon.run_scenario",
        scripted([False]),
    )

    await run_until(
        make_daemon(config, notifier=notifier),
        lambda: len(notifier.events) >= 1,
    )

    event = notifier.events[0]

    assert secret not in event.scenario_name
    assert secret not in event.details


async def test_environment_secret_is_redacted_from_internal_error_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected daemon errors must not expose environment secrets."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-INTERNAL-4b91"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config = tmp_path / "c.yaml"
    write_config(config, scenario_dict("${env.PROOFRUN_TEST_SECRET}"))

    output: list[str] = []
    internal_errors: list[tuple[str, BaseException]] = []

    monkeypatch.setattr(
        "proofrun.cli.render.console.print",
        lambda *args, **kwargs: output.append(str(args[0])),
    )

    async def fail_with_secret(
        scenario: ScenarioConfig,
        *_: Any,
    ) -> ScenarioResult:
        raise RuntimeError(f"Unexpected internal failure: {secret}")

    def capture_internal_error(name: str, error: BaseException) -> None:
        internal_errors.append((name, error))
        print_internal_error(name, error)

    monkeypatch.setattr(
        "proofrun.monitor.daemon.run_scenario",
        fail_with_secret,
    )

    await run_until(
        make_daemon(config, on_internal_error=capture_internal_error),
        lambda: bool(output),
    )

    assert secret not in "\n".join(output)
    assert internal_errors
    assert secret not in str(internal_errors[0][1])
    assert internal_errors[0][1].__cause__ is None
    assert internal_errors[0][1].__context__ is None
