"""Generic webhook notification delivery."""

from __future__ import annotations

import httpx
from rich.console import Console
from rich.markup import escape

from proofrun.health import Status
from proofrun.notify.base import NotificationEvent

console = Console()

TIMEOUT_SECONDS = 5.0


def describe_delivery_error(err: httpx.HTTPError) -> str:
    """Describe a failed webhook delivery without exposing the webhook URL.

    The text of an ``httpx`` error can include the full request URL, and webhook
    URLs often carry a secret token in their path, so only the failure category
    is reported.
    """
    if isinstance(err, httpx.HTTPStatusError):
        return f"the endpoint responded with HTTP {err.response.status_code}"

    if isinstance(err, httpx.TimeoutException):
        return f"the request timed out after {TIMEOUT_SECONDS:g}s"

    if isinstance(err, httpx.ConnectError):
        return "could not connect to the endpoint"

    return f"the request failed ({type(err).__name__})"


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
                follow_redirects=False,
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()

            console.print(
                f"[dim]Dispatched webhook alert for: {event.scenario_name}[/dim]"
            )

        except httpx.HTTPError as err:
            console.print(
                f"[bold red]Failed to send webhook alert for "
                f"'{escape(event.scenario_name)}':[/bold red] "
                f"{describe_delivery_error(err)}"
            )
