# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Unit tests for the scenario state manager."""

from __future__ import annotations

from proofrun.health import ScenarioState, StateManager, Status


def test_scenario_state_defaults() -> None:
    """Verifies the dataclass default instantiation values."""
    state = ScenarioState()
    assert state.status == Status.UNKNOWN
    assert state.fail_count == 0
    assert state.pass_count == 0


def test_initial_to_healthy() -> None:
    """Verifies transition from unknown to healthy."""
    manager = StateManager()
    transition = manager.update("API Test", True)

    assert transition.old_status == Status.UNKNOWN
    assert transition.new_status == Status.HEALTHY
    assert transition.changed is True
    assert manager.states["API Test"].pass_count == 1
    assert manager.states["API Test"].fail_count == 0


def test_initial_to_failing() -> None:
    """Verifies transition from unknown to failing."""
    manager = StateManager()
    transition = manager.update("API Test", False)

    assert transition.old_status == Status.UNKNOWN
    assert transition.new_status == Status.FAILING
    assert transition.changed is True
    assert manager.states["API Test"].pass_count == 0
    assert manager.states["API Test"].fail_count == 1


def test_recovery_transition() -> None:
    """Verifies failing to healthy transition (Recovery)."""
    manager = StateManager()
    manager.update("API Test", False)
    manager.update("API Test", False)

    assert manager.states["API Test"].fail_count == 2

    transition = manager.update("API Test", True)

    assert transition.old_status == Status.FAILING
    assert transition.new_status == Status.HEALTHY
    assert transition.changed is True
    assert manager.states["API Test"].pass_count == 1
    assert manager.states["API Test"].fail_count == 0


def test_failure_transition() -> None:
    """Verifies healthy to failing transition."""
    manager = StateManager()
    manager.update("API Test", True)

    transition = manager.update("API Test", False)

    assert transition.old_status == Status.HEALTHY
    assert transition.new_status == Status.FAILING
    assert transition.changed is True
    assert manager.states["API Test"].pass_count == 0
    assert manager.states["API Test"].fail_count == 1


def test_continuous_healthy() -> None:
    """Verifies consecutive passes increment pass_count and maintain HEALTHY state."""
    manager = StateManager()
    manager.update("API Test", True)

    manager.update("API Test", True)
    transition = manager.update("API Test", True)

    assert transition.old_status == Status.HEALTHY
    assert transition.new_status == Status.HEALTHY
    assert transition.changed is False
    assert manager.states["API Test"].pass_count == 3
    assert manager.states["API Test"].fail_count == 0


def test_continuous_failing() -> None:
    """Verifies consecutive failures increment fail_count and maintain FAILING state."""
    manager = StateManager()
    manager.update("API Test", False)

    manager.update("API Test", False)
    transition = manager.update("API Test", False)

    assert transition.old_status == Status.FAILING
    assert transition.new_status == Status.FAILING
    assert transition.changed is False
    assert manager.states["API Test"].pass_count == 0
    assert manager.states["API Test"].fail_count == 3


def test_multiple_independent_scenarios() -> None:
    """Verifies state is isolated correctly between different scenarios."""
    manager = StateManager()

    manager.update("Scenario A", True)
    manager.update("Scenario B", False)

    # Scenario A checks
    assert manager.states["Scenario A"].status == Status.HEALTHY
    assert manager.states["Scenario A"].pass_count == 1
    assert manager.states["Scenario A"].fail_count == 0

    # Scenario B checks
    assert manager.states["Scenario B"].status == Status.FAILING
    assert manager.states["Scenario B"].pass_count == 0
    assert manager.states["Scenario B"].fail_count == 1

    # Update B to pass; A should remain unchanged
    manager.update("Scenario B", True)

    assert manager.states["Scenario A"].pass_count == 1
    assert manager.states["Scenario B"].status == Status.HEALTHY
    assert manager.states["Scenario B"].pass_count == 1


def test_sync_removes_stale_states() -> None:
    """Verifies sync removes states for scenarios no longer active."""
    manager = StateManager()
    manager.update("Scenario A", True)
    manager.update("Scenario B", True)

    assert "Scenario A" in manager.states
    assert "Scenario B" in manager.states

    manager.sync({"Scenario A"})

    assert "Scenario A" in manager.states
    assert "Scenario B" not in manager.states


def test_failure_threshold_delays_failing() -> None:
    manager = StateManager()
    manager.update("a", True)

    first = manager.update("a", False, failure_threshold=3)
    second = manager.update("a", False, failure_threshold=3)
    third = manager.update("a", False, failure_threshold=3)

    assert first.new_status == Status.HEALTHY
    assert not first.changed
    assert second.new_status == Status.HEALTHY
    assert third.new_status == Status.FAILING
    assert third.changed
    assert manager.states["a"].fail_count == 3


def test_a_pass_resets_the_consecutive_failure_count() -> None:
    manager = StateManager()
    manager.update("a", True)

    manager.update("a", False, failure_threshold=2)
    manager.update("a", True, failure_threshold=2)
    transition = manager.update("a", False, failure_threshold=2)

    assert transition.new_status == Status.HEALTHY
    assert manager.states["a"].fail_count == 1


def test_unknown_stays_unknown_until_the_failure_threshold() -> None:
    manager = StateManager()

    first = manager.update("a", False, failure_threshold=2)
    second = manager.update("a", False, failure_threshold=2)

    assert first.new_status == Status.UNKNOWN
    assert not first.changed
    assert second.old_status == Status.UNKNOWN
    assert second.new_status == Status.FAILING


def test_unknown_becomes_healthy_on_the_first_pass() -> None:
    manager = StateManager()

    manager.update("a", False, failure_threshold=3)
    transition = manager.update("a", True, recovery_threshold=5)

    assert transition.new_status == Status.HEALTHY


def test_recovery_threshold_delays_recovery() -> None:
    manager = StateManager()
    manager.update("a", False)

    first = manager.update("a", True, recovery_threshold=2)
    second = manager.update("a", True, recovery_threshold=2)

    assert first.new_status == Status.FAILING
    assert not first.changed
    assert second.new_status == Status.HEALTHY
    assert second.changed


def test_a_failure_resets_the_consecutive_pass_count() -> None:
    manager = StateManager()
    manager.update("a", False)

    manager.update("a", True, recovery_threshold=2)
    manager.update("a", False)
    transition = manager.update("a", True, recovery_threshold=2)

    assert transition.new_status == Status.FAILING
    assert manager.states["a"].pass_count == 1
