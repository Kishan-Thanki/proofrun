"""Unit tests for per-scenario scheduling."""

from __future__ import annotations

from proofrun.monitor.scheduler import Scheduler


def _scheduler(factor: float = 1.0) -> Scheduler:
    return Scheduler(uniform=lambda low, high: factor)


def test_every_scenario_is_due_on_first_call() -> None:
    scheduler = _scheduler()

    assert scheduler.due({"a": 10, "b": 20}, set(), now=0.0) == ["a", "b"]


def test_scenarios_follow_their_own_intervals() -> None:
    scheduler = _scheduler()
    intervals = {"fast": 10, "slow": 30}

    assert scheduler.due(intervals, set(), now=0.0) == ["fast", "slow"]
    assert scheduler.due(intervals, set(), now=5.0) == []
    assert scheduler.due(intervals, set(), now=10.0) == ["fast"]
    assert scheduler.due(intervals, set(), now=20.0) == ["fast"]
    assert scheduler.due(intervals, set(), now=30.0) == ["fast", "slow"]


def test_running_scenario_is_not_started_again() -> None:
    scheduler = _scheduler()
    intervals = {"a": 10}

    scheduler.due(intervals, set(), now=0.0)

    assert scheduler.due(intervals, {"a"}, now=50.0) == []
    assert scheduler.due(intervals, set(), now=50.0) == ["a"]


def test_jitter_scales_the_interval() -> None:
    scheduler = Scheduler(jitter=0.15, uniform=lambda low, high: high)

    scheduler.due({"a": 100}, set(), now=0.0)

    assert scheduler.due({"a": 100}, set(), now=114.0) == []
    assert scheduler.due({"a": 100}, set(), now=115.0) == ["a"]


def test_jitter_bounds_are_passed_to_the_random_source() -> None:
    bounds: list[tuple[float, float]] = []

    def uniform(low: float, high: float) -> float:
        bounds.append((low, high))
        return 1.0

    Scheduler(jitter=0.2, uniform=uniform).due({"a": 10}, set(), now=0.0)

    assert bounds == [(0.8, 1.2)]


def test_removed_scenarios_are_forgotten() -> None:
    scheduler = _scheduler()

    scheduler.due({"a": 10, "b": 10}, set(), now=0.0)
    scheduler.due({"a": 10}, set(), now=1.0)

    assert scheduler.due({"a": 10, "b": 10}, set(), now=2.0) == ["b"]


def test_seconds_until_next_without_schedule_is_none() -> None:
    assert _scheduler().seconds_until_next(0.0, set()) is None


def test_seconds_until_next_uses_the_earliest_due_time() -> None:
    scheduler = _scheduler()

    scheduler.due({"a": 10, "b": 4}, set(), now=0.0)

    assert scheduler.seconds_until_next(1.0, set()) == 3.0


def test_seconds_until_next_is_never_negative() -> None:
    scheduler = _scheduler()

    scheduler.due({"a": 10}, set(), now=0.0)

    assert scheduler.seconds_until_next(99.0, set()) == 0.0


def test_seconds_until_next_ignores_running_scenarios() -> None:
    scheduler = _scheduler()

    scheduler.due({"a": 1, "b": 50}, set(), now=0.0)

    assert scheduler.seconds_until_next(10.0, {"a"}) == 40.0
    assert scheduler.seconds_until_next(10.0, {"a", "b"}) is None
