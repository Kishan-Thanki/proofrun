"""Metrics for daemon mode.

Metrics use a single label, ``scenario``. Request URLs, error messages, and
response data are never used as labels because their cardinality is unbounded.
Series of scenarios that are removed from the configuration are dropped.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from proofrun.health import Status


@dataclass
class _Series:
    """Metric values of one scenario."""

    runs: int = 0
    failures: int = 0
    duration_seconds: float | None = None
    last_success_timestamp: float | None = None
    last_failure_timestamp: float | None = None
    up: int | None = None


def _escape(value: str) -> str:
    """Escape a label value for the text format."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    """Format a number for the text format."""
    if isinstance(value, int):
        return str(value)

    return repr(round(value, 6))


_DEFINITIONS: tuple[tuple[str, str, str, Callable[[_Series], float | None]], ...] = (
    (
        "proofrun_scenario_up",
        "gauge",
        "Scenario health: 1 when HEALTHY, 0 when FAILING. Absent while UNKNOWN.",
        lambda series: series.up,
    ),
    (
        "proofrun_scenario_runs_total",
        "counter",
        "Total scenario runs, counted after retries.",
        lambda series: series.runs,
    ),
    (
        "proofrun_scenario_failures_total",
        "counter",
        "Total scenario runs that failed after all retries.",
        lambda series: series.failures,
    ),
    (
        "proofrun_scenario_duration_seconds",
        "gauge",
        "Duration of the last scenario run in seconds.",
        lambda series: series.duration_seconds,
    ),
    (
        "proofrun_scenario_last_success_timestamp_seconds",
        "gauge",
        "Unix time of the last passing run.",
        lambda series: series.last_success_timestamp,
    ),
    (
        "proofrun_scenario_last_failure_timestamp_seconds",
        "gauge",
        "Unix time of the last failed run.",
        lambda series: series.last_failure_timestamp,
    ),
)


class MetricsRegistry:
    """In-memory metric values for all scenarios."""

    def __init__(self) -> None:
        self._series: dict[str, _Series] = {}

    def _get(self, scenario_name: str) -> _Series:
        return self._series.setdefault(scenario_name, _Series())

    def record_run(
        self,
        scenario_name: str,
        passed: bool,
        duration_seconds: float,
        timestamp: float,
    ) -> None:
        """Record the outcome of one finished scenario run."""
        series = self._get(scenario_name)
        series.runs += 1
        series.duration_seconds = duration_seconds

        if passed:
            series.last_success_timestamp = timestamp
        else:
            series.failures += 1
            series.last_failure_timestamp = timestamp

    def set_health(self, scenario_name: str, status: Status) -> None:
        """Record the scenario's current health state."""
        self._get(scenario_name).up = {
            Status.HEALTHY: 1,
            Status.FAILING: 0,
        }.get(status)

    def sync(self, active_scenario_names: set[str]) -> None:
        """Drop the series of scenarios that no longer exist."""
        for name in set(self._series) - active_scenario_names:
            del self._series[name]

    def render(self) -> str:
        """Render all metrics in the text exposition format."""
        lines: list[str] = []

        for metric, kind, help_text, getter in _DEFINITIONS:
            lines.append(f"# HELP {metric} {help_text}")
            lines.append(f"# TYPE {metric} {kind}")

            for name in sorted(self._series):
                value = getter(self._series[name])

                if value is not None:
                    lines.append(
                        f'{metric}{{scenario="{_escape(name)}"}} {_number(value)}'
                    )

        return "\n".join(lines) + "\n"
