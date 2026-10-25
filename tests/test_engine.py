# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Unit tests for the Proofrun asynchronous execution engine."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import HttpUrl

from proofrun.config.models import (
    ExpectConfig,
    RequestConfig,
    ScenarioConfig,
    StepConfig,
)
from proofrun.runner.context import ExecutionContext
from proofrun.runner.engine import (
    _MAX_RESPONSE_BODY_BYTES,
    ScenarioRunner,
    describe_header_mismatch,
    is_sensitive_header,
)


def build_runner(steps: list[StepConfig]) -> ScenarioRunner:
    """Build a scenario runner targeting the mock HTTP server."""
    scenario = ScenarioConfig(
        name="Engine Test Scenario",
        base_url=HttpUrl("https://test.example.com"),
        steps=steps,
    )

    return ScenarioRunner(scenario)


def make_transport(
    handler: Any,
) -> httpx.MockTransport:
    """Create an HTTPX mock transport."""
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_successful_get_request() -> None:
    """Verifies a basic successful HTTP GET step."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://test.example.com/health"

        return httpx.Response(
            200,
            json={"status": "ok"},
        )

    step = StepConfig(
        name="Health Check",
        request=RequestConfig(
            method="GET",
            path="/health",
            timeout=5.0,
        ),
        expect=ExpectConfig(status=200),
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is True
    assert result.status_code == 200
    assert result.error is None
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_oversized_response_fails_and_closes_stream() -> None:
    """Reject oversized response bodies and close the HTTP stream."""

    class OversizedStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> Any:
            remaining = _MAX_RESPONSE_BODY_BYTES + 1
            chunk = b"x" * (64 * 1024)

            while remaining:
                size = min(remaining, len(chunk))
                yield chunk[:size]
                remaining -= size

        async def aclose(self) -> None:
            self.closed = True

    stream = OversizedStream()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    step = StepConfig(
        name="Oversized Response",
        request=RequestConfig(
            method="GET",
            path="/large",
            timeout=5.0,
        ),
        expect=ExpectConfig(status=200),
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.status_code == 200
    assert result.error == "Response body exceeds the 10 MiB limit."
    assert stream.closed is True


@pytest.mark.asyncio
async def test_status_code_mismatch_reports_response_status() -> None:
    """Verifies status failures preserve the actual HTTP status."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": "not found"},
        )

    step = StepConfig(
        name="Missing Resource",
        request=RequestConfig(
            method="GET",
            path="/missing",
            timeout=5.0,
        ),
        expect=ExpectConfig(status=200),
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.status_code == 404
    assert result.error is not None
    assert "Status code mismatch" in result.error
    assert "expected one of [200], got 404" in result.error


@pytest.mark.asyncio
async def test_network_failure_reports_status_zero() -> None:
    """Verifies failures without an HTTP response report status 0."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "Connection failed",
            request=request,
        )

    step = StepConfig(
        name="Connection Failure",
        request=RequestConfig(
            method="GET",
            path="/health",
            timeout=5.0,
        ),
        expect=ExpectConfig(status=200),
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.status_code == 0
    assert result.error is not None
    assert "HTTP request failed (ConnectError)" in result.error
    assert "Connection failed" not in result.error


@pytest.mark.asyncio
async def test_expected_headers_are_validated() -> None:
    """Verifies expected response headers are checked."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-Test": "expected"},
            json={"status": "ok"},
        )

    step = StepConfig(
        name="Header Check",
        request=RequestConfig(
            method="GET",
            path="/headers",
            timeout=5.0,
        ),
        expect=ExpectConfig(
            status=200,
            headers={"X-Test": "expected"},
        ),
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is True
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_header_mismatch_fails_step() -> None:
    """Verifies incorrect expected response headers fail the step."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-Test": "actual"},
            json={"status": "ok"},
        )

    step = StepConfig(
        name="Header Mismatch",
        request=RequestConfig(
            method="GET",
            path="/headers",
            timeout=5.0,
        ),
        expect=ExpectConfig(
            status=200,
            headers={"X-Test": "expected"},
        ),
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.status_code == 200
    assert result.error is not None
    assert "Header 'X-Test' mismatch" in result.error


@pytest.mark.asyncio
async def test_compiled_json_schema_validation() -> None:
    """Verifies that compiled_schema callable is executed and reported on failure."""

    def mock_compiled_schema(data: Any) -> None:
        if not isinstance(data.get("id"), int):
            raise ValueError("Field 'id' must be an integer")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "not-an-int"})

    expect_cfg = ExpectConfig(status=200)
    expect_cfg._compiled_schema = mock_compiled_schema

    step = StepConfig(
        name="Schema Check",
        request=RequestConfig(method="GET", path="/user", timeout=5.0),
        expect=expect_cfg,
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.status_code == 200
    assert result.error is not None
    assert "Schema assertion failed" in result.error
    assert "Field 'id' must be an integer" not in result.error


@pytest.mark.asyncio
async def test_compiled_json_schema_validation_succeeds() -> None:
    """Verifies a valid response passes compiled schema validation."""

    def mock_compiled_schema(data: Any) -> None:
        if not isinstance(data.get("id"), int):
            raise ValueError("Field 'id' must be an integer")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 123})

    expect_cfg = ExpectConfig(status=200)
    expect_cfg._compiled_schema = mock_compiled_schema

    step = StepConfig(
        name="Schema Check",
        request=RequestConfig(method="GET", path="/user", timeout=5.0),
        expect=expect_cfg,
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is True
    assert result.error is None


@pytest.mark.asyncio
async def test_invalid_json_fails_when_extraction_is_required() -> None:
    """Verifies invalid JSON fails when extraction is configured."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"this is not json",
            headers={"Content-Type": "text/plain"},
        )

    step = StepConfig(
        name="Invalid JSON",
        request=RequestConfig(
            method="GET",
            path="/invalid-json",
            timeout=5.0,
        ),
        expect=ExpectConfig(status=200),
        extract={"value": "$.value"},
    )

    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.status_code == 200
    assert result.error is not None
    assert "JSON" in result.error
    assert "Expecting value" not in result.error


@pytest.mark.asyncio
async def test_multi_step_context_extraction_and_interpolation() -> None:
    """Verifies extracted values flow into subsequent requests."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts/1":
            return httpx.Response(
                200,
                json={
                    "userId": 1,
                    "title": "Test Post",
                },
            )

        if request.url.path == "/users/1":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "email": "user@example.com",
                },
            )

        if request.url.path == "/posts":
            body = request.content.decode()

            assert '"userId":1' in body
            assert "user@example.com" in body

            return httpx.Response(
                201,
                json={
                    "created": True,
                },
            )

        return httpx.Response(404)

    step1 = StepConfig(
        name="Fetch Post",
        request=RequestConfig(
            method="GET",
            path="/posts/1",
            timeout=5.0,
        ),
        expect=ExpectConfig(status=200),
        extract={
            "target_user_id": "$.userId",
            "post_title": "$.title",
        },
    )

    step2 = StepConfig(
        name="Fetch User",
        request=RequestConfig(
            method="GET",
            path="/users/${target_user_id}",
            timeout=5.0,
        ),
        expect=ExpectConfig(status=200),
        extract={
            "user_email": "$.email",
        },
    )

    req3 = RequestConfig(
        method="POST",
        path="/posts",
        timeout=5.0,
    )
    req3.json_payload = {
        "title": "Synthetic ${post_title}",
        "body": "Author email: ${user_email}",
        "userId": "${target_user_id}",
    }

    step3 = StepConfig(
        name="Create Post",
        request=req3,
        expect=ExpectConfig(status=201),
    )

    runner = build_runner([step1, step2, step3])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        for step in runner.scenario.steps:
            result = await runner.execute_step(step, client)
            assert result.passed is True

    assert runner.context.get("target_user_id") == 1
    assert runner.context.get("post_title") == "Test Post"
    assert runner.context.get("user_email") == "user@example.com"


@pytest.mark.asyncio
async def test_scenario_runner_clears_cookies_and_executes_all_steps() -> None:
    """Verifies runner.run() clears cookies from client and halts on failure."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/step1":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/step2":
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(200)

    step1 = StepConfig(
        name="Step 1",
        request=RequestConfig(method="GET", path="/step1", timeout=5.0),
        expect=ExpectConfig(status=200),
    )
    step2 = StepConfig(
        name="Step 2",
        request=RequestConfig(method="GET", path="/step2", timeout=5.0),
        expect=ExpectConfig(status=200),
    )
    step3 = StepConfig(
        name="Step 3",
        request=RequestConfig(method="GET", path="/step3", timeout=5.0),
        expect=ExpectConfig(status=200),
    )

    runner = build_runner([step1, step2, step3])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        client.cookies.set("session_token", "stale_cookie_data")

        scenario_result = await runner.run(client)

        assert len(client.cookies) == 0

    assert scenario_result.passed is False
    assert len(scenario_result.step_results) == 2
    assert scenario_result.step_results[0].passed is True
    assert scenario_result.step_results[1].passed is False


@pytest.mark.asyncio
async def test_missing_base_url_fails_step() -> None:
    """Verifies missing base URL raises an error during execution."""
    step = StepConfig(
        name="No Base URL",
        request=RequestConfig(method="GET", path="/", timeout=5.0),
        expect=ExpectConfig(status=200),
    )
    scenario = ScenarioConfig(
        name="Missing Base",
        base_url=None,
        steps=[step],
    )
    runner = ScenarioRunner(scenario)

    async with httpx.AsyncClient() as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.error is not None
    assert "missing a valid base_url" in result.error


@pytest.mark.asyncio
async def test_missing_timeout_fails_step() -> None:
    """Verifies a step without a resolved timeout fails."""
    step = StepConfig(
        name="No Timeout",
        request=RequestConfig(method="GET", path="/", timeout=None),
        expect=ExpectConfig(status=200),
    )
    runner = build_runner([step])

    async with httpx.AsyncClient() as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.error is not None
    assert "missing a resolved request timeout" in result.error


@pytest.mark.asyncio
async def test_latency_limit_exceeded_fails_step() -> None:
    """Verifies step fails if max_latency_ms is exceeded."""
    import asyncio

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"status": "ok"})

    step = StepConfig(
        name="Latency Check",
        request=RequestConfig(method="GET", path="/fast", timeout=5.0),
        expect=ExpectConfig(
            status=200,
            max_latency_ms=1.0,
        ),
    )
    runner = build_runner([step])

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is False
    assert result.error is not None
    assert "Latency limit exceeded" in result.error


@pytest.mark.asyncio
async def test_scenario_runner_custom_context_and_successful_run() -> None:
    """Verifies passing a custom context and all steps passing in run()."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    step1 = StepConfig(
        name="Step 1",
        request=RequestConfig(method="GET", path="/1", timeout=5.0),
        expect=ExpectConfig(status=200),
    )
    step2 = StepConfig(
        name="Step 2",
        request=RequestConfig(method="GET", path="/2", timeout=5.0),
        expect=ExpectConfig(status=200),
    )

    scenario = ScenarioConfig(
        name="Successful Run",
        base_url=HttpUrl("https://test.example.com"),
        steps=[step1, step2],
    )

    context = ExecutionContext()
    runner = ScenarioRunner(scenario, context=context)

    async with httpx.AsyncClient(
        transport=make_transport(handler),
    ) as client:
        scenario_result = await runner.run(client)

    assert scenario_result.passed is True
    assert len(scenario_result.step_results) == 2
    assert scenario_result.step_results[0].passed is True
    assert scenario_result.step_results[1].passed is True


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "Proxy-Authorization",
        "Cookie",
        "Set-Cookie",
        "X-Api-Key",
        "X-Auth-Token",
        "X-Session-Id",
        "X-Client-Secret",
        "X-Password",
    ],
)
def test_sensitive_header_names_are_detected(name: str) -> None:
    assert is_sensitive_header(name)


@pytest.mark.parametrize(
    "name",
    ["Content-Type", "Cache-Control", "ETag", "Keep-Alive", "X-Request-Id", "Server"],
)
def test_ordinary_header_names_are_not_sensitive(name: str) -> None:
    assert not is_sensitive_header(name)


def test_ordinary_header_mismatch_shows_both_values() -> None:
    message = describe_header_mismatch("Content-Type", "text/html", "application/json")

    assert message == (
        "Header 'Content-Type' mismatch: expected 'text/html', got 'application/json'"
    )


def test_missing_ordinary_header_is_reported() -> None:
    message = describe_header_mismatch("X-Request-Id", "abc", None)

    assert "got 'None'" in message


def test_sensitive_header_mismatch_hides_both_values() -> None:
    message = describe_header_mismatch("Set-Cookie", "session=expected", "session=real")

    assert "expected" not in message
    assert "real" not in message
    assert "Set-Cookie" in message
    assert "hidden" in message


def test_missing_sensitive_header_has_no_values_to_leak() -> None:
    message = describe_header_mismatch("Authorization", "Bearer expected", None)

    assert message == "Header 'Authorization' is missing"


@pytest.mark.asyncio
async def test_sensitive_header_secret_never_reaches_the_step_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Set-Cookie": "session=super-secret-cookie"},
            json={},
        )

    step = StepConfig(
        name="Cookie Check",
        request=RequestConfig(method="GET", path="/", timeout=5.0),
        expect=ExpectConfig(
            status=200,
            headers={"Set-Cookie": "session=other-secret"},
        ),
    )

    async with httpx.AsyncClient(transport=make_transport(handler)) as client:
        result = await build_runner([step]).execute_step(step, client)

    assert result.passed is False
    assert result.error is not None
    assert "super-secret-cookie" not in result.error
    assert "other-secret" not in result.error
