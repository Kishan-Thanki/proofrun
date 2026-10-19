# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Unit tests for the webhook notification system."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from proofrun.health import Status
from proofrun.notify.base import NotificationEvent
from proofrun.notify.webhook import WebhookNotifier, describe_delivery_error


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

        assert "Failed to send webhook alert for 'Payment API'" in call_args
        assert "HTTP 500" in call_args
        assert "fake.webhook.com" not in call_args


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

        assert "Failed to send webhook alert for 'Payment API'" in call_args
        assert "could not connect to the endpoint" in call_args
        assert "fake.webhook.com" not in call_args


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


SECRET_URL = "https://hooks.example.com/services/T000/B000/SECRET-TOKEN-123"


def _raise(error_type: type[httpx.RequestError]) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("failure text", request=request)

    return handler


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (lambda request: httpx.Response(404), "HTTP 404"),
        (lambda request: httpx.Response(500), "HTTP 500"),
        (_raise(httpx.ConnectError), "could not connect to the endpoint"),
        (_raise(httpx.ConnectTimeout), "timed out after 5s"),
        (_raise(httpx.ReadTimeout), "timed out after 5s"),
        (_raise(httpx.WriteError), "the request failed (WriteError)"),
    ],
    ids=["404", "500", "connect", "connect-timeout", "read-timeout", "other"],
)
@pytest.mark.asyncio
async def test_delivery_failures_never_print_the_webhook_url(
    handler: object,
    expected: str,
) -> None:
    event = NotificationEvent(
        scenario_name="Payment API",
        old_status=Status.HEALTHY,
        new_status=Status.FAILING,
    )

    with patch("proofrun.notify.webhook.console.print") as mock_print:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        ) as client:
            await WebhookNotifier(client, SECRET_URL).notify(event)

    printed = mock_print.call_args[0][0]

    assert expected in printed
    assert "SECRET-TOKEN" not in printed
    assert "hooks.example.com" not in printed


@pytest.mark.asyncio
async def test_delivery_failure_message_escapes_markup_in_scenario_names() -> None:
    event = NotificationEvent(
        scenario_name="[red]odd[/red]",
        old_status=Status.HEALTHY,
        new_status=Status.FAILING,
    )

    with patch("proofrun.notify.webhook.console.print") as mock_print:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        ) as client:
            await WebhookNotifier(client, SECRET_URL).notify(event)

    assert "\\[red]odd\\[/red]" in mock_print.call_args[0][0]


def test_describe_delivery_error_has_a_fallback_for_unknown_errors() -> None:
    assert describe_delivery_error(httpx.HTTPError("anything")) == (
        "the request failed (HTTPError)"
    )
