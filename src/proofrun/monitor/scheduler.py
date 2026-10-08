"""Per-scenario scheduling for daemon mode.

The scheduler only decides *when* each scenario is due. It does no I/O and
takes the current time as an argument, so it is deterministic to test.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field


@dataclass
class Scheduler:
    """Tracks the next due time of every scenario independently.

    Attributes:
        jitter: Each interval is multiplied by a random factor between
            ``1 - jitter`` and ``1 + jitter`` so checks do not align.
        uniform: Source of the random factor.
    """

    jitter: float = 0.15
    uniform: Callable[[float, float], float] = random.uniform
    _next_due: dict[str, float] = field(default_factory=dict)

    def due(
        self,
        intervals: Mapping[str, float],
        running: Collection[str],
        now: float,
    ) -> list[str]:
        """Return the scenarios to start now and schedule their next run.

        A scenario that is still running is never started again, so runs of the
        same scenario cannot overlap. Scenarios missing from ``intervals`` (for
        example after a configuration reload) are forgotten.

        Args:
            intervals: Interval in seconds of every active scenario.
            running: Names of scenarios whose previous run has not finished.
            now: Current time on a monotonic clock, in seconds.
        """
        for stale in set(self._next_due) - set(intervals):
            del self._next_due[stale]

        started: list[str] = []

        for name, interval in intervals.items():
            if name in running or self._next_due.get(name, now) > now:
                continue

            factor = self.uniform(1 - self.jitter, 1 + self.jitter)
            self._next_due[name] = now + interval * factor
            started.append(name)

        return started

    def seconds_until_next(
        self,
        now: float,
        running: Collection[str],
    ) -> float | None:
        """Return seconds until the next scenario that is not running is due.

        Running scenarios are ignored because their completion wakes the
        daemon up. Returns ``None`` when nothing is scheduled.
        """
        pending = [due for name, due in self._next_due.items() if name not in running]

        if not pending:
            return None

        return max(0.0, min(pending) - now)
