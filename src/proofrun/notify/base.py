"""Notification abstractions: the event payload and the notifier interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from proofrun.health import Status


@dataclass(frozen=True)
class NotificationEvent:
    """Data payload for a scenario health-state transition notification."""

    scenario_name: str
    old_status: Status
    new_status: Status
    details: str = ""


class Notifier(Protocol):
    """Interface for delivering notification events."""

    async def notify(self, event: NotificationEvent) -> None:
        """Deliver a notification event."""
        ...  # pragma: no cover
