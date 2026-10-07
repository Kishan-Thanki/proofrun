"""State management for tracking scenario health transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    """The health status of a scenario."""

    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    FAILING = "FAILING"


@dataclass
class ScenarioState:
    """Tracks the current state of a single scenario."""

    status: Status = Status.UNKNOWN
    fail_count: int = 0
    pass_count: int = 0


@dataclass(frozen=True)
class StateTransition:
    """Describes a scenario health-state transition."""

    scenario_name: str
    old_status: Status
    new_status: Status

    @property
    def changed(self) -> bool:
        """Return whether the scenario changed health state."""
        return self.old_status != self.new_status


class StateManager:
    """Manages state across all scenarios for alerting purposes."""

    def __init__(self) -> None:
        self.states: dict[str, ScenarioState] = {}

    def update(
        self,
        scenario_name: str,
        passed: bool,
        failure_threshold: int = 1,
        recovery_threshold: int = 1,
    ) -> StateTransition:
        """Update scenario state and return the resulting transition.

        ``pass_count`` and ``fail_count`` are consecutive counters: a result of
        the opposite kind resets the other counter.

        Args:
            scenario_name: Scenario whose result is being recorded.
            passed: Whether the run passed (after any retries).
            failure_threshold: Consecutive failed runs needed to move to
                ``FAILING``. Until then a ``HEALTHY`` or ``UNKNOWN`` scenario
                keeps its status.
            recovery_threshold: Consecutive passing runs needed to move from
                ``FAILING`` back to ``HEALTHY``. A scenario that is not
                ``FAILING`` becomes ``HEALTHY`` on its first pass.
        """
        if scenario_name not in self.states:
            self.states[scenario_name] = ScenarioState()

        state = self.states[scenario_name]
        old_status = state.status

        if passed:
            state.pass_count += 1
            state.fail_count = 0

            if state.status != Status.FAILING or state.pass_count >= recovery_threshold:
                state.status = Status.HEALTHY
        else:
            state.fail_count += 1
            state.pass_count = 0

            if state.fail_count >= failure_threshold:
                state.status = Status.FAILING

        return StateTransition(
            scenario_name=scenario_name,
            old_status=old_status,
            new_status=state.status,
        )

    def sync(self, active_scenario_names: set[str]) -> None:
        """Remove state for scenarios that no longer exist in the configuration.

        Call this periodically or after a configuration hot-reload to prevent
        memory leaks from deleted scenarios.
        """
        stale_keys = set(self.states.keys()) - active_scenario_names
        for key in stale_keys:
            del self.states[key]
