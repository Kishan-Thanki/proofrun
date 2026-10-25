# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Unit tests for the Proofrun CLI interface."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from proofrun.cli.commands import app
from proofrun.cli.render import (
    print_config_error,
    print_internal_error,
    render_scenario_result,
)
from proofrun.cli.runtime import (
    _load_uvloop,
    install_stop_on_sigterm,
    new_client,
    run_daemon_mode,
    run_event_loop,
    run_once,
)
from proofrun.config.provider import ConfigProvider
from proofrun.metrics.registry import MetricsRegistry
from proofrun.monitor.daemon import Daemon
from proofrun.notify.webhook import WebhookNotifier
from proofrun.runner.engine import ScenarioResult, StepResult

runner = CliRunner()


def cli_result_text(result: Any) -> str:
    """Return CLI output across Click versions with separate output streams."""
    parts = [result.output]

    for stream_name in ("stdout", "stderr"):
        try:
            stream = getattr(result, stream_name, "")
        except (AttributeError, ValueError):
            continue

        if stream and stream not in parts:
            parts.append(stream)

    return "\n".join(parts)


def write_config(
    tmp_path: Path,
    base_url: str,
    status: int = 200,
    path: str = "/posts/1",
    extra: str = "",
) -> Path:
    config_file = tmp_path / "scenario.yaml"
    config_file.write_text(
        f"""
version: "1.0"

global:
  base_url: "{base_url}"

scenarios:
  - name: "CLI Scenario"{extra}
    steps:
      - name: "Step"
        request:
          method: "GET"
          path: "{path}"
        expect:
          status: {status}
""",
        encoding="utf-8",
    )

    return config_file


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeDaemon:
    """Stands in for Daemon: records its arguments and is interrupted at once."""

    instances: list[FakeDaemon] = []

    def __init__(self, provider: Any, state: Any, client_factory: Any, **kwargs: Any):
        self.provider = provider
        self.client_factory = client_factory
        self.kwargs = kwargs
        self.instances.append(self)

    async def run(self, stop: asyncio.Event | None = None) -> None:
        raise KeyboardInterrupt


@pytest.fixture(autouse=True)
def _reset_fake_daemon() -> None:
    FakeDaemon.instances = []


class StoppingDaemon(Daemon):
    """A real Daemon that stops after its first finished scenario run."""

    async def run(self, stop: asyncio.Event | None = None) -> None:
        stop_event = asyncio.Event()
        original = self.on_result

        def on_result(result: ScenarioResult) -> None:
            if original is not None:
                original(result)

            stop_event.set()

        self.on_result = on_result
        self.max_tick = 0.01

        await super().run(stop_event)


def test_cli_version_flag() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "Proofrun version" in result.stdout


def test_cli_run_successful_scenario(tmp_path: Path, local_api: str) -> None:
    result = runner.invoke(app, [str(write_config(tmp_path, local_api))])

    assert result.exit_code == 0
    assert "CLI Scenario" in result.stdout
    assert "PASSED" in result.stdout
    assert "Attempts" not in result.stdout


def test_cli_run_failing_scenario(tmp_path: Path, local_api: str) -> None:
    result = runner.invoke(app, [str(write_config(tmp_path, local_api, status=404))])

    assert result.exit_code == 1
    assert "FAILED" in result.stdout


def test_cli_run_nonexistent_file() -> None:
    result = runner.invoke(app, ["non_existent_file.yaml"])

    assert result.exit_code != 0


def test_cli_reports_retry_attempts(tmp_path: Path, local_api: str) -> None:
    config = write_config(
        tmp_path,
        local_api,
        path="/fail",
        extra="\n    retries: 2\n    retry_delay_seconds: 0",
    )

    result = runner.invoke(app, [str(config)])

    assert result.exit_code == 1
    assert "Attempts" in result.stdout
    assert "3" in result.stdout


def test_cli_once_mode_reports_invalid_configuration(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")

    result = runner.invoke(app, [str(config_file)])

    assert result.exit_code == 1
    assert "Configuration Error" in result.stdout


def test_cli_resolves_env_references(tmp_path: Path, local_api: str) -> None:
    config = write_config(tmp_path, "${env.TARGET}")

    result = runner.invoke(app, [str(config)], env={"TARGET": local_api})

    assert result.exit_code == 0
    assert "PASSED" in result.stdout


def test_cli_missing_env_variable_is_a_configuration_error(tmp_path: Path) -> None:
    config = write_config(tmp_path, "${env.PROOFRUN_TEST_MISSING}")

    result = runner.invoke(app, [str(config)], env={"PROOFRUN_TEST_MISSING": None})

    assert result.exit_code == 1
    assert "PROOFRUN_TEST_MISSING" in result.stdout.replace("\n", "")


def test_cli_validate_accepts_a_valid_configuration(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        "http://127.0.0.1:9",
        extra="\n    retries: 2\n    failure_threshold: 3",
    )

    result = runner.invoke(app, [str(config), "--validate"])

    assert result.exit_code == 0
    assert "Configuration is valid" in result.stdout
    assert "1 scenario(s), 1 step(s)" in result.stdout
    assert "No requests were sent" in result.stdout
    assert "PASSED" not in result.stdout


def test_cli_validate_rejects_an_invalid_configuration(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")

    result = runner.invoke(app, [str(config_file), "--validate"])

    assert result.exit_code == 1
    assert "Configuration Error" in result.stdout


def test_cli_validate_cannot_be_combined_with_daemon(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    result = runner.invoke(app, [str(config), "--validate", "--daemon"])

    assert result.exit_code == 2


def test_cli_daemon_mode_wiring_and_interrupt(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        result = runner.invoke(app, [str(config), "--daemon", "-i", "5"])

    kwargs = FakeDaemon.instances[0].kwargs

    assert result.exit_code == 0
    assert "Starting daemon mode..." in result.stdout
    assert "Daemon execution stopped by user." in result.stdout
    assert kwargs["interval_override"] == 5
    assert kwargs["notifier"] is None
    assert kwargs["metrics"] is None
    assert FakeDaemon.instances[0].client_factory is new_client


def test_cli_daemon_without_interval_does_not_override(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        runner.invoke(app, [str(config), "--daemon"])

    assert FakeDaemon.instances[0].kwargs["interval_override"] is None


def test_webhook_url_is_read_from_proofrun_env_var(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        runner.invoke(
            app,
            [str(config), "--daemon"],
            env={"PROOFRUN_WEBHOOK_URL": "https://hooks.example.com/env"},
        )

    notifier = FakeDaemon.instances[0].kwargs["notifier"]

    assert isinstance(notifier, WebhookNotifier)
    assert notifier.webhook_url == "https://hooks.example.com/env"


def test_webhook_flag_overrides_env_var(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        runner.invoke(
            app,
            [
                str(config),
                "--daemon",
                "--webhook-url",
                "https://hooks.example.com/flag",
            ],
            env={"PROOFRUN_WEBHOOK_URL": "https://hooks.example.com/env"},
        )

    notifier = FakeDaemon.instances[0].kwargs["notifier"]

    assert notifier.webhook_url == "https://hooks.example.com/flag"


def test_old_proof_env_var_is_not_read(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        runner.invoke(
            app,
            [str(config), "--daemon"],
            env={
                "PROOF_WEBHOOK_URL": "https://hooks.example.com/old",
                "PROOFRUN_WEBHOOK_URL": None,
            },
        )

    assert FakeDaemon.instances[0].kwargs["notifier"] is None


def test_cli_daemon_runs_real_scenarios(tmp_path: Path, local_api: str) -> None:
    config = write_config(tmp_path, local_api)

    with patch("proofrun.cli.runtime.Daemon", StoppingDaemon):
        result = runner.invoke(app, [str(config), "--daemon"])

    assert result.exit_code == 0
    assert "Starting daemon mode..." in result.stdout
    assert "PASSED" in result.stdout


def test_cli_daemon_serves_metrics(tmp_path: Path, local_api: str) -> None:
    config = write_config(tmp_path, local_api)
    port = free_port()

    with patch("proofrun.cli.runtime.Daemon", StoppingDaemon):
        result = runner.invoke(
            app,
            [str(config), "--daemon", "--metrics-port", str(port)],
        )

    assert result.exit_code == 0
    assert f"http://127.0.0.1:{port}/metrics" in result.stdout
    assert "reachable from the network" not in result.stdout


def test_cli_passes_a_registry_to_the_daemon_when_metrics_are_enabled(
    tmp_path: Path,
) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        runner.invoke(
            app,
            [str(config), "--daemon"],
            env={"PROOFRUN_METRICS_PORT": str(free_port())},
        )

    assert isinstance(FakeDaemon.instances[0].kwargs["metrics"], MetricsRegistry)


def test_cli_warns_when_metrics_are_exposed(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        result = runner.invoke(
            app,
            [
                str(config),
                "--daemon",
                "--metrics-port",
                str(free_port()),
                "--metrics-host",
                "0.0.0.0",
            ],
        )

    assert "reachable from the network" in result.stdout


def test_cli_reports_a_metrics_port_that_is_in_use(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]

        with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
            result = runner.invoke(
                app,
                [str(config), "--daemon", "--metrics-port", str(port)],
            )

    assert result.exit_code == 1
    assert "Cannot start the metrics server" in result.stdout
    assert FakeDaemon.instances == []


def test_cli_rejects_invalid_metrics_ports(tmp_path: Path) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    assert runner.invoke(app, [str(config), "--metrics-port", "0"]).exit_code == 2
    assert runner.invoke(app, [str(config), "--metrics-port", "70000"]).exit_code == 2


def test_new_client_returns_a_fresh_client_each_time() -> None:
    first = new_client()
    second = new_client()

    assert isinstance(first, httpx.AsyncClient)
    assert first is not second


def test_config_error_messages() -> None:
    with patch("proofrun.cli.render.console.print") as mock_print:
        print_config_error("bad [bold]file", True)
        print_config_error("bad file", False)

    printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list)

    assert "Using last known-good configuration." in printed
    assert "No valid configuration yet" in printed
    assert "\\[bold]" in printed


def test_internal_error_message() -> None:
    with patch("proofrun.cli.render.console.print") as mock_print:
        print_internal_error("Scenario A", RuntimeError("bug"))

    printed = str(mock_print.call_args.args[0])

    assert "Scenario A" in printed
    assert "RuntimeError" in printed


def test_render_scenario_result_passed() -> None:
    result = ScenarioResult(
        scenario_name="Passing Scenario",
        passed=True,
        step_results=[
            StepResult(
                step_name="GET /health",
                passed=True,
                status_code=200,
                latency_ms=12.34,
                error=None,
            )
        ],
        total_latency_ms=12.34,
    )

    with patch("proofrun.cli.render.console.print") as mock_print:
        render_scenario_result(result)

    assert mock_print.call_count == 3

    table = mock_print.call_args_list[0].args[0]
    panel = mock_print.call_args_list[1].args[0]

    assert table.title == "Scenario: [bold white]Passing Scenario[/bold white]"
    assert panel.border_style == "green"
    assert "Attempts" not in panel.renderable.plain


def test_render_scenario_result_failed_with_attempts() -> None:
    result = ScenarioResult(
        scenario_name="Failed Scenario",
        passed=False,
        step_results=[
            StepResult(
                step_name="GET /health",
                passed=False,
                status_code=500,
                latency_ms=45.67,
                error="Internal Server Error",
            )
        ],
        total_latency_ms=45.67,
        attempts=3,
    )

    with patch("proofrun.cli.render.console.print") as mock_print:
        render_scenario_result(result)

    table = mock_print.call_args_list[0].args[0]
    panel = mock_print.call_args_list[1].args[0]

    assert table.title == "Scenario: [bold white]Failed Scenario[/bold white]"
    assert panel.border_style == "red"
    assert "Attempts: 3" in panel.renderable.plain


def test_render_escapes_markup_in_names_and_errors() -> None:
    result = ScenarioResult(
        scenario_name="[red]Odd[/red]",
        passed=False,
        step_results=[
            StepResult(
                step_name="[bold]step",
                passed=False,
                status_code=0,
                latency_ms=1.0,
                error="expected one of [200]",
            )
        ],
        total_latency_ms=1.0,
    )

    with patch("proofrun.cli.render.console.print") as mock_print:
        render_scenario_result(result)

    table = mock_print.call_args_list[0].args[0]

    assert table.title == "Scenario: [bold white]\\[red]Odd\\[/red][/bold white]"


def test_load_uvloop_returns_module_when_installed() -> None:
    pytest.importorskip("uvloop")

    assert _load_uvloop() is not None


def test_load_uvloop_returns_none_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "uvloop", None)

    assert _load_uvloop() is None


def test_run_event_loop_falls_back_to_asyncio() -> None:
    async def main() -> int:
        return 7

    with patch("proofrun.cli.runtime._uvloop", None):
        assert run_event_loop(main()) == 7


def test_run_event_loop_uses_uvloop_when_available() -> None:
    calls: list[str] = []

    def fake_run(coro: Any) -> int:
        calls.append("uvloop.run")
        assert asyncio.iscoroutine(coro)
        coro.close()
        return 9

    async def main() -> int:
        return 0  # pragma: no cover - closed by fake_run before it executes

    with patch("proofrun.cli.runtime._uvloop", SimpleNamespace(run=fake_run)):
        assert run_event_loop(main()) == 9

    assert calls == ["uvloop.run"]


@pytest.mark.asyncio
async def test_run_once_reports_internal_errors_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected errors fail the run without exposing exception details."""
    config_path = write_config(tmp_path, "https://example.com")
    output: list[str] = []

    monkeypatch.setattr(
        "proofrun.cli.render.console.print",
        lambda *args, **kwargs: output.append(str(args[0])),
    )

    async def fail_with_bug(scenario: Any, *_: Any) -> Any:
        raise RuntimeError("internal secret detail")

    monkeypatch.setattr("proofrun.cli.runtime.run_scenario", fail_with_bug)

    passed = await run_once(ConfigProvider(config_path), new_client)
    displayed = " ".join(output)

    assert passed is False
    assert "RuntimeError" in displayed
    assert "internal secret detail" not in displayed


@pytest.mark.asyncio
async def test_run_once_propagates_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation must propagate instead of becoming a normal failure."""
    config_path = write_config(tmp_path, "https://example.com")

    async def cancel_run(scenario: Any, *_: Any) -> Any:
        raise asyncio.CancelledError()

    monkeypatch.setattr("proofrun.cli.runtime.run_scenario", cancel_run)

    with pytest.raises(asyncio.CancelledError):
        await run_once(ConfigProvider(config_path), new_client)


@pytest.mark.asyncio
async def test_run_once_propagates_non_exception_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BaseException signals must propagate instead of being swallowed."""

    class FatalSignal(BaseException):
        pass

    config_path = write_config(tmp_path, "https://example.com")

    async def fail_with_fatal_signal(scenario: Any, *_: Any) -> Any:
        raise FatalSignal()

    monkeypatch.setattr(
        "proofrun.cli.runtime.run_scenario",
        fail_with_fatal_signal,
    )

    with pytest.raises(FatalSignal):
        await run_once(ConfigProvider(config_path), new_client)


def test_cli_once_mode_without_daemon_options_prints_no_warning(
    tmp_path: Path,
    local_api: str,
) -> None:
    result = runner.invoke(app, [str(write_config(tmp_path, local_api))])

    assert "is ignored" not in result.stdout


def test_daemon_refuses_to_start_with_an_invalid_configuration(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        result = runner.invoke(app, [str(config_file), "--daemon"])

    assert result.exit_code == 1
    assert "Configuration Error" in result.stdout
    assert "Not starting" in result.stdout
    assert FakeDaemon.instances == []


def test_an_invalid_configuration_does_not_open_the_metrics_port(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("version: '1.0'\nscenarios: []\n", encoding="utf-8")

    with patch("proofrun.cli.runtime.Daemon", FakeDaemon):
        result = runner.invoke(
            app,
            [str(config_file), "--daemon", "--metrics-port", str(free_port())],
        )

    assert result.exit_code == 1
    assert "Metrics:" not in result.stdout


@pytest.fixture
def harmless_sigterm() -> Iterator[None]:
    """Make a stray SIGTERM harmless to the test process itself."""
    previous = signal.signal(signal.SIGTERM, lambda *_: None)

    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@pytest.mark.skipif(sys.platform == "win32", reason="no SIGTERM handlers on Windows")
@pytest.mark.asyncio
async def test_sigterm_sets_the_stop_event(harmless_sigterm: None) -> None:
    stop = asyncio.Event()
    install_stop_on_sigterm(stop)

    try:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(stop.wait(), timeout=2)
    finally:
        asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)

    assert stop.is_set()


@pytest.mark.asyncio
async def test_installing_the_sigterm_handler_is_safe_where_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported(*args: object, **kwargs: object) -> None:
        raise NotImplementedError

    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", unsupported)

    install_stop_on_sigterm(asyncio.Event())


class WaitingDaemon:
    """Stands in for Daemon: runs until it is told to stop."""

    def __init__(self, provider: Any, state: Any, client_factory: Any, **kwargs: Any):
        self.stopped = False

    async def run(self, stop: asyncio.Event | None = None) -> None:
        assert stop is not None
        await stop.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="no SIGTERM handlers on Windows")
@pytest.mark.asyncio
async def test_daemon_mode_stops_cleanly_on_sigterm(
    tmp_path: Path,
    harmless_sigterm: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = write_config(tmp_path, "http://127.0.0.1:9")

    with patch("proofrun.cli.runtime.Daemon", WaitingDaemon):
        task = asyncio.create_task(
            run_daemon_mode(config, None, None, "127.0.0.1", None)
        )

        try:
            await asyncio.sleep(0.3)
            os.kill(os.getpid(), signal.SIGTERM)
            exit_code = await asyncio.wait_for(task, timeout=5)
        finally:
            asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)

    assert exit_code == 0
    assert "stopped by SIGTERM" in capsys.readouterr().out


def test_cli_once_mode_rejects_daemon_only_options(
    tmp_path: Path,
    local_api: str,
) -> None:
    config = write_config(tmp_path, local_api)

    result = runner.invoke(
        app,
        [
            str(config),
            "--webhook-url",
            "https://hooks.example.com/x",
        ],
        standalone_mode=False,
    )

    assert result.exception is not None
    assert result.exception.__class__.__name__ == "BadParameter"
    assert "--webhook-url can only be used with --daemon." in str(result.exception)


def test_cli_once_mode_rejects_interval_option(
    tmp_path: Path,
    local_api: str,
) -> None:
    config = write_config(tmp_path, local_api)

    result = runner.invoke(
        app,
        [str(config), "--interval", "30"],
        standalone_mode=False,
    )

    assert result.exception is not None
    assert result.exception.__class__.__name__ == "BadParameter"
    assert "--interval can only be used with --daemon." in str(result.exception)


def test_metrics_host_requires_port_in_daemon_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROOFRUN_METRICS_PORT", raising=False)
    config = write_config(tmp_path, "http://127.0.0.1:9")

    result = runner.invoke(
        app,
        [
            str(config),
            "--daemon",
            "--metrics-host",
            "0.0.0.0",
        ],
        standalone_mode=False,
    )

    assert result.exception is not None
    assert result.exception.__class__.__name__ == "BadParameter"
    assert "--metrics-host requires --metrics-port" in str(result.exception)
