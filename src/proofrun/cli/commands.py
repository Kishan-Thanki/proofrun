"""Command Line Interface for Proofrun synthetic API monitoring daemon.

Provides terminal rendering and workflow orchestration for running synthetic
monitoring scenarios using Typer and Rich.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from proofrun import __version__
from proofrun.cli.render import console
from proofrun.cli.runtime import (
    new_client,
    run_daemon_mode,
    run_event_loop,
    run_once,
)
from proofrun.config.compiler import ConfigCompilerError, load_and_compile_config
from proofrun.config.provider import ConfigProvider

__all__ = [
    "app",
    "main",
    "run_command",
    "validate_config",
    "version_callback",
]

app = typer.Typer(
    name="proofrun",
    help="Synthetic API monitoring as code daemon.",
    add_completion=True,
)

DEFAULT_METRICS_HOST = "127.0.0.1"


# CLI callbacks and option validation


def version_callback(value: bool) -> None:
    """Print the Proofrun version and exit."""
    if value:
        console.print(
            f"[bold cyan]Proofrun[/bold cyan] "
            f"version [bold green]{__version__}[/bold green]"
        )
        raise typer.Exit(code=0)


def _check_daemon_options(
    ctx: typer.Context,
    once: bool,
) -> None:
    """Reject daemon-only options when running once."""
    if not once:
        return

    daemon_options = (
        ("interval", "--interval"),
        ("webhook_url", "--webhook-url"),
        ("metrics_port", "--metrics-port"),
        ("metrics_host", "--metrics-host"),
    )

    for parameter_name, option_name in daemon_options:
        source = ctx.get_parameter_source(parameter_name)

        if source is not None and source.name == "COMMANDLINE":
            raise typer.BadParameter(
                f"{option_name} can only be used with --daemon.",
                ctx=ctx,
                param_hint=option_name,
            )


# Configuration validation


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


# CLI command


@app.command()
def run_command(
    ctx: typer.Context,
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
        str | None,
        typer.Option(
            "--metrics-host",
            envvar="PROOFRUN_METRICS_HOST",
            help=(
                "Address the metrics server binds to. The default is 127.0.0.1 "
                "(loopback); other addresses expose it, unauthenticated, to the "
                "network."
            ),
        ),
    ] = None,
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
    _check_daemon_options(ctx, once)

    if validate:
        if not once:
            raise typer.BadParameter("--validate cannot be combined with --daemon.")

        raise typer.Exit(code=validate_config(config_path))

    if not once and metrics_host is not None and metrics_port is None:
        raise typer.BadParameter(
            "--metrics-host requires --metrics-port or PROOFRUN_METRICS_PORT.",
            ctx=ctx,
            param_hint="--metrics-host",
        )

    console.print(
        f"[bold cyan]Proofrun[/bold cyan] executing config: "
        f"[bold yellow]{escape(str(config_path))}[/bold yellow]\n"
    )

    if once:
        passed = run_event_loop(run_once(ConfigProvider(config_path), new_client))
        raise typer.Exit(code=0 if passed else 1)

    try:
        exit_code = run_event_loop(
            run_daemon_mode(
                config_path,
                interval,
                webhook_url,
                metrics_host or DEFAULT_METRICS_HOST,
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
