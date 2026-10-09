"""Generic webhook notification delivery."""

from __future__ import annotations

import httpx
from rich.console import Console

from proofrun.health import Status
from proofrun.notify.base import NotificationEvent

console = Console()


class WebhookNotifier:
    """Deliver notification events to a generic HTTP webhook."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        webhook_url: str,
    ) -> None:
        self.client = client
        self.webhook_url = webhook_url

    async def notify(self, event: NotificationEvent) -> None:
        """Send a notification event as provider-neutral JSON."""
        if event.new_status == Status.HEALTHY:
            event_type = "scenario_recovered"
        elif event.new_status == Status.FAILING:
            event_type = "scenario_failed"
        else:
            return

        payload = {
            "event": event_type,
            "scenario": event.scenario_name,
            "previous_status": event.old_status.value,
            "status": event.new_status.value,
            "details": event.details,
        }

        try:
            response = await self.client.post(
                self.webhook_url,
                json=payload,
                timeout=5.0,
            )
            response.raise_for_status()

            console.print(
                f"[dim]Dispatched webhook alert for: {event.scenario_name}[/dim]"
            )

        except httpx.HTTPError as err:
            console.print(f"[bold red]Failed to send webhook:[/bold red] {err}")
