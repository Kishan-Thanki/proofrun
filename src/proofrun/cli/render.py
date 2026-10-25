"""Terminal output for Proofrun, built with Rich."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from proofrun.runner.engine import ScenarioResult

console = Console()


def render_scenario_result(result: ScenarioResult) -> None:
    """Render a scenario result using Rich."""
    status_style = "bold green" if result.passed else "bold red"
    status_text = "PASSED" if result.passed else "FAILED"

    table = Table(
        title=f"Scenario: [bold white]{escape(result.scenario_name)}[/bold white]",
        title_style="bold cyan",
        show_header=True,
        header_style="bold magenta",
        expand=True,
    )

    table.add_column("Step Name", style="dim", min_width=25)
    table.add_column("Status", justify="center", width=10)
    table.add_column("HTTP Code", justify="right", width=10)
    table.add_column("Latency", justify="right", width=12)
    table.add_column("Error Details", style="red", min_width=20)

    for step in result.step_results:
        step_status = (
            "[bold green]PASS[/bold green]"
            if step.passed
            else "[bold red]FAIL[/bold red]"
        )

        code_style = "green" if step.passed else "red"
        code_str = f"[{code_style}]{step.status_code}[/{code_style}]"
        latency_str = f"{step.latency_ms:.2f} ms"
        error_str = escape(step.error) if step.error else "-"

        table.add_row(
            escape(step.step_name),
            step_status,
            code_str,
            latency_str,
            error_str,
        )

    console.print(table)

    summary_text = Text()
    summary_text.append("Status: ", style="bold")
    summary_text.append(status_text, style=status_style)
    summary_text.append("    Total Latency: ", style="bold")
    summary_text.append(
        f"{result.total_latency_ms:.2f} ms",
        style="cyan",
    )

    if result.attempts > 1:
        summary_text.append("    Attempts: ", style="bold")
        summary_text.append(str(result.attempts), style="yellow")

    panel = Panel(
        summary_text,
        title="[bold]Summary[/bold]",
        border_style="green" if result.passed else "red",
        expand=False,
    )

    console.print(panel)
    console.print()


def print_config_error(error: str, using_last_known_good: bool) -> None:
    console.print(f"[bold red]Configuration Error:[/bold red] {escape(error)}")

    if using_last_known_good:
        console.print("[yellow]Using last known-good configuration.[/yellow]")
    else:
        console.print(
            "[yellow]No valid configuration yet. Waiting for the file to be "
            "fixed.[/yellow]"
        )


def print_internal_error(scenario_name: str, error: BaseException) -> None:
    console.print(
        f"[bold red]Internal error while running "
        f"'{escape(scenario_name)}':[/bold red] "
        f"{type(error).__name__} (details suppressed)"
    )
