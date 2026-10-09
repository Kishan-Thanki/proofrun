"""Command Line Interface for Proofrun synthetic API monitoring daemon.

Provides terminal rendering and workflow orchestration for running synthetic
monitoring scenarios using Typer and Rich.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Coroutine
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, TypeVar

import httpx
import typer
from rich.markup import escape
from rich.table import Table

from proofrun import __version__
from proofrun.cli.render import (
    console,
    print_config_error,
    print_internal_error,
    render_scenario_result,
)
from proofrun.config.compiler import ConfigCompilerError, load_and_compile_config
from proofrun.config.provider import ConfigProvider
from proofrun.health import StateManager
from proofrun.metrics.registry import MetricsRegistry
from proofrun.metrics.server import MetricsServer
from proofrun.monitor.daemon import Daemon
from proofrun.notify.base import Notifier
from proofrun.notify.webhook import WebhookNotifier
from proofrun.runner.execution import ClientFactory, run_scenario

app = typer.Typer(
    name="proofrun",
    help="Synthetic API monitoring as code daemon.",
    add_completion=True,
)

T = TypeVar("T")


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


def version_callback(value: bool) -> None:
    """Print the Proofrun version and exit."""
    if value:
        console.print(
            f"[bold cyan]Proofrun[/bold cyan] "
            f"version [bold green]{__version__}[/bold green]"
        )
        raise typer.Exit(code=0)


def new_client() -> httpx.AsyncClient:
    """Create the HTTP client used for one attempt of one scenario."""
    return httpx.AsyncClient()


def validate_config(config_path: Path) -> int:
    """Check a configuration file without sending any requests.

    Returns:
        ``0`` when the configuration is valid, otherwise ``1``.
    """
    try:
        config = load_and_compile_config(config_path)
    except ConfigCompilerError as err:
        console.print(f"[bold red]Configuration Error:[/bold red] {escape(str(err))}")
        return 1

    step_count = sum(len(scenario.steps) for scenario in config.scenarios)

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Scenario")
    table.add_column("Steps", justify="right")
    table.add_column("Interval", justify="right")
    table.add_column("Retries", justify="right")
    table.add_column("Fail after", justify="right")
    table.add_column("Recover after", justify="right")

    for scenario in config.scenarios:
        table.add_row(
            escape(scenario.name),
            str(len(scenario.steps)),
            f"{scenario.interval_seconds}s",
            str(scenario.retries),
            str(scenario.failure_threshold),
            str(scenario.recovery_threshold),
        )

    console.print(table)
    console.print(
        f"[bold green]Configuration is valid:[/bold green] "
        f"{len(config.scenarios)} scenario(s), {step_count} step(s). "
        "No requests were sent."
    )

    return 0


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


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


async def run_daemon_mode(
    config_path: Path,
    interval: int | None,
    webhook_url: str | None,
    metrics_host: str,
    metrics_port: int | None,
) -> int:
    """Run the daemon until it is interrupted. Returns the exit code."""
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
                ConfigProvider(config_path),
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

            await daemon.run()
    finally:
        if server is not None:
            await server.stop()

    return 0


@app.command()
def run_command(
    config_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to YAML scenario configuration file.",
        ),
    ],
    once: Annotated[
        bool,
        typer.Option(
            "--once/--daemon",
            help="Run scenarios once and exit, or loop continuously in daemon mode.",
        ),
    ] = True,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Check the configuration and exit without sending any requests.",
        ),
    ] = False,
    interval: Annotated[
        int | None,
        typer.Option(
            "--interval",
            "-i",
            min=1,
            help=(
                "Daemon mode: run every scenario every N seconds, "
                "replacing each scenario's interval_seconds."
            ),
        ),
    ] = None,
    webhook_url: Annotated[
        str | None,
        typer.Option(
            "--webhook-url",
            envvar="PROOFRUN_WEBHOOK_URL",
            help="Daemon mode: HTTP webhook URL for state transition alerts.",
        ),
    ] = None,
    metrics_port: Annotated[
        int | None,
        typer.Option(
            "--metrics-port",
            envvar="PROOFRUN_METRICS_PORT",
            min=1,
            max=65535,
            help="Daemon mode: serve metrics on this port.",
        ),
    ] = None,
    metrics_host: Annotated[
        str,
        typer.Option(
            "--metrics-host",
            envvar="PROOFRUN_METRICS_HOST",
            help=(
                "Address the metrics server binds to. The default is loopback; "
                "other addresses expose it, unauthenticated, to the network."
            ),
        ),
    ] = "127.0.0.1",
    _show_version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show Proofrun version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Execute synthetic monitoring scenarios defined in YAML."""
    if validate:
        if not once:
            raise typer.BadParameter("--validate cannot be combined with --daemon.")

        raise typer.Exit(code=validate_config(config_path))

    console.print(
        f"[bold cyan]Proofrun[/bold cyan] executing config: "
        f"[bold yellow]{escape(str(config_path))}[/bold yellow]\n"
    )

    if once:
        for ignored, given in (
            ("--webhook-url", webhook_url is not None),
            ("--metrics-port", metrics_port is not None),
        ):
            if given:
                console.print(
                    f"[yellow]{ignored} is ignored when running once; "
                    "use --daemon.[/yellow]"
                )

        passed = run_event_loop(run_once(ConfigProvider(config_path), new_client))

        raise typer.Exit(code=0 if passed else 1)

    try:
        exit_code = run_event_loop(
            run_daemon_mode(
                config_path,
                interval,
                webhook_url,
                metrics_host,
                metrics_port,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Daemon execution stopped by user.[/yellow]")
        raise typer.Exit(code=0) from None

    raise typer.Exit(code=exit_code)


def main() -> None:
    """Run the Proofrun CLI."""
    app()
