"""Unit tests for the webhook notification system."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from proofrun.health import Status
from proofrun.notify.base import NotificationEvent
from proofrun.notify.webhook import WebhookNotifier


@pytest.mark.asyncio
async def test_webhook_alert_failure() -> None:
    """Verifies failure transition payload and dispatch log."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(await request.aread())

        assert body["event"] == "scenario_failed"
        assert body["scenario"] == "Payment API"
        assert body["previous_status"] == "UNKNOWN"
        assert body["status"] == "FAILING"
        assert body["details"] == "Timeout reached"

        return httpx.Response(200)

    event = NotificationEvent(
        scenario_name="Payment API",
        old_status=Status.UNKNOWN,
        new_status=Status.FAILING,
        details="Timeout reached",
    )

    with patch(
        "proofrun.notify.webhook.console.print",
    ) as mock_print:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            notifier = WebhookNotifier(
                client=client,
                webhook_url="https://fake.webhook.com",
            )

            await notifier.notify(event)

        mock_print.assert_called_once_with(
            "[dim]Dispatched webhook alert for: Payment API[/dim]"
        )


@pytest.mark.asyncio
async def test_webhook_alert_recovery() -> None:
    """Verifies recovery transition payload and dispatch log."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(await request.aread())

        assert body["event"] == "scenario_recovered"
        assert body["scenario"] == "Payment API"
        assert body["previous_status"] == "FAILING"
        assert body["status"] == "HEALTHY"
        assert body["details"] == "All steps passing."

        return httpx.Response(200)

    event = NotificationEvent(
        scenario_name="Payment API",
        old_status=Status.FAILING,
        new_status=Status.HEALTHY,
        details="All steps passing.",
    )

    with patch(
        "proofrun.notify.webhook.console.print",
    ) as mock_print:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            notifier = WebhookNotifier(
                client=client,
                webhook_url="https://fake.webhook.com",
            )

            await notifier.notify(event)

        mock_print.assert_called_once_with(
            "[dim]Dispatched webhook alert for: Payment API[/dim]"
        )


@pytest.mark.asyncio
async def test_webhook_alert_http_error() -> None:
    """Verifies webhook HTTP errors are caught and logged."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text="Internal Server Error",
        )

    event = NotificationEvent(
        scenario_name="Payment API",
        old_status=Status.UNKNOWN,
        new_status=Status.FAILING,
        details="Timeout reached",
    )

    with patch(
        "proofrun.notify.webhook.console.print",
    ) as mock_print:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            notifier = WebhookNotifier(
                client=client,
                webhook_url="https://fake.webhook.com",
            )

            await notifier.notify(event)

        assert mock_print.call_count == 1

        call_args = mock_print.call_args[0][0]

        assert "[bold red]Failed to send webhook:[/bold red]" in call_args
        assert "500" in call_args


@pytest.mark.asyncio
async def test_webhook_alert_network_exception() -> None:
    """Verifies network failures are caught and logged."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "Network unreachable",
            request=request,
        )

    event = NotificationEvent(
        scenario_name="Payment API",
        old_status=Status.UNKNOWN,
        new_status=Status.FAILING,
    )

    with patch(
        "proofrun.notify.webhook.console.print",
    ) as mock_print:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            notifier = WebhookNotifier(
                client=client,
                webhook_url="https://fake.webhook.com",
            )

            await notifier.notify(event)

        assert mock_print.call_count == 1

        call_args = mock_print.call_args[0][0]

        assert "[bold red]Failed to send webhook:[/bold red]" in call_args
        assert "Network unreachable" in call_args


@pytest.mark.asyncio
async def test_webhook_alert_unknown_status_is_ignored() -> None:
    """Verifies UNKNOWN target states do not generate webhook requests."""

    client = httpx.AsyncClient()

    event = NotificationEvent(
        scenario_name="Payment API",
        old_status=Status.UNKNOWN,
        new_status=Status.UNKNOWN,
        details="No state transition.",
    )

    notifier = WebhookNotifier(
        client=client,
        webhook_url="https://fake.webhook.com",
    )

    with patch.object(client, "post", new_callable=AsyncMock) as mock_post:
        await notifier.notify(event)

        mock_post.assert_not_awaited()

    await client.aclose()
