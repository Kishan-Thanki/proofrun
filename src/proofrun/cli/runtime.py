"""Runtime execution and event loop orchestration for Proofrun CLI.

Contains asynchronous runtime runners, event loop selection, signal handlers,
and client factories used when executing scenarios.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import signal
from collections.abc import Coroutine
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar

import httpx
from rich.markup import escape

from proofrun.cli.render import (
    console,
    print_config_error,
    print_internal_error,
    render_scenario_result,
)
from proofrun.config.provider import ConfigProvider
from proofrun.health import StateManager
from proofrun.metrics.registry import MetricsRegistry
from proofrun.metrics.server import MetricsServer
from proofrun.monitor.daemon import Daemon
from proofrun.notify.base import Notifier
from proofrun.notify.webhook import WebhookNotifier
from proofrun.runner.execution import ClientFactory, run_scenario

T = TypeVar("T")

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def new_client() -> httpx.AsyncClient:
    """Create the HTTP client used for one attempt of one scenario."""
    return httpx.AsyncClient()


def _load_uvloop() -> ModuleType | None:
    """Return the uvloop module when it is available, otherwise ``None``.

    uvloop is a faster drop-in event loop, but it does not support Windows and
    is not installed there. Proofrun falls back to the standard asyncio loop.
    """
    try:
        return importlib.import_module("uvloop")
    except ImportError:
        return None


_uvloop = _load_uvloop()


def run_event_loop(main: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion on uvloop if available, else on asyncio."""
    if _uvloop is not None:
        return _uvloop.run(main)

    return asyncio.run(main)


def install_stop_on_sigterm(stop: asyncio.Event) -> None:
    """Set ``stop`` when the process receives SIGTERM.

    SIGTERM is what ``systemctl stop`` and ``docker stop`` send. Without a handler
    the daemon is killed abruptly, and as PID 1 in a container it does not receive
    the signal at all, so ``docker stop`` waits and then kills it.
    """
    with contextlib.suppress(NotImplementedError):  # not supported on Windows
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)


async def run_once(
    config_provider: ConfigProvider,
    client_factory: ClientFactory,
) -> bool:
    """Run every scenario once, concurrently, and render the results.

    Returns:
        ``True`` when every scenario passed.
    """
    proofrun_config, config_error = config_provider.load()

    if config_error is not None:
        console.print(
            f"[bold red]Configuration Error:[/bold red] {escape(str(config_error))}"
        )
        return False

    if proofrun_config is None:  # pragma: no cover - load() returns an error first
        console.print("[bold red]No valid configuration is available.[/bold red]")
        return False

    results = await asyncio.gather(
        *(
            run_scenario(scenario, client_factory)
            for scenario in proofrun_config.scenarios
        )
    )

    for result in results:
        render_scenario_result(result)

    return all(result.passed for result in results)


async def run_daemon_mode(
    config_path: Path,
    interval: int | None,
    webhook_url: str | None,
    metrics_host: str,
    metrics_port: int | None,
) -> int:
    """Run the daemon until it is stopped. Returns the exit code."""
    provider = ConfigProvider(config_path)
    _, config_error = provider.load()

    if config_error is not None:
        console.print(
            f"[bold red]Configuration Error:[/bold red] {escape(str(config_error))}"
        )
        console.print(
            "[yellow]Not starting: there is no valid configuration to monitor. "
            "Fix the file and start again.[/yellow]"
        )
        return 1

    registry: MetricsRegistry | None = None
    server: MetricsServer | None = None

    if metrics_port is not None:
        registry = MetricsRegistry()
        server = MetricsServer(registry, metrics_host, metrics_port)

        try:
            await server.start()
        except OSError as err:
            console.print(
                f"[bold red]Cannot start the metrics server on "
                f"{escape(metrics_host)}:{metrics_port}:[/bold red] {escape(str(err))}"
            )
            return 1

        console.print(
            f"[bold green]Metrics:[/bold green] "
            f"http://{metrics_host}:{server.port}/metrics"
        )

        if metrics_host not in _LOOPBACK_HOSTS:
            console.print(
                "[bold yellow]Warning:[/bold yellow] the metrics endpoint is "
                "reachable from the network and has no authentication."
            )

    try:
        async with httpx.AsyncClient() as notifier_client:
            notifier: Notifier | None = (
                WebhookNotifier(client=notifier_client, webhook_url=webhook_url)
                if webhook_url is not None
                else None
            )

            daemon = Daemon(
                provider,
                StateManager(),
                new_client,
                notifier=notifier,
                metrics=registry,
                interval_override=interval,
                on_result=render_scenario_result,
                on_config_error=print_config_error,
                on_internal_error=print_internal_error,
            )

            console.print(
                "[bold green]Starting daemon mode... "
                "Press Ctrl+C to stop.[/bold green]\n"
            )

            stop = asyncio.Event()
            install_stop_on_sigterm(stop)

            await daemon.run(stop)

            if stop.is_set():
                console.print("\n[yellow]Daemon stopped by SIGTERM.[/yellow]")
    finally:
        if server is not None:
            await server.stop()

    return 0
