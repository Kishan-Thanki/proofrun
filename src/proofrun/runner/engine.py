"""Asynchronous HTTP execution engine for Proofrun synthetic monitoring.

This module executes multi-step HTTP monitoring scenarios using httpx,
evaluates response assertions, extracts runtime variables into
ExecutionContext, and records high-resolution latency metrics.
"""

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import fastjsonschema
import httpx

from proofrun.config.models import ScenarioConfig, StepConfig
from proofrun.redaction import redact_secrets
from proofrun.runner.context import ContextError, ExecutionContext

_MAX_RESPONSE_BODY_BYTES = 10 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 64 * 1024

_SENSITIVE_HEADER_PARTS = (
    "auth",
    "cookie",
    "token",
    "secret",
    "password",
    "passwd",
    "key",
    "session",
    "credential",
)


def is_sensitive_header(header_name: str) -> bool:
    """Return whether a header's value must not appear in failure messages."""
    lowered = header_name.lower()

    return any(part in lowered for part in _SENSITIVE_HEADER_PARTS)


def describe_header_mismatch(
    header_name: str,
    expected_value: str,
    actual_value: str | None,
) -> str:
    """Describe a failed header assertion without leaking sensitive values."""
    if not is_sensitive_header(header_name):
        return (
            f"Header '{header_name}' mismatch: expected "
            f"'{expected_value}', got '{actual_value}'"
        )

    if actual_value is None:
        return f"Header '{header_name}' is missing"

    return (
        f"Header '{header_name}' mismatch "
        "(values are hidden because this header may contain secrets)"
    )


class EngineError(Exception):
    """Raised when HTTP step execution or assertion evaluation fails."""


class InternalExecutionError(Exception):
    """Unexpected execution failure with sensitive details suppressed."""


@dataclass
class StepResult:
    """Execution outcome and performance metrics for one scenario step."""

    step_name: str
    passed: bool
    status_code: int
    latency_ms: float
    error: str | None = None


@dataclass
class ScenarioResult:
    """Aggregated execution outcome for a complete scenario."""

    scenario_name: str
    passed: bool
    total_latency_ms: float
    step_results: list[StepResult] = field(default_factory=list)
    attempts: int = 1


class ScenarioRunner:
    """Execute multi-step HTTP monitoring scenarios asynchronously."""

    def __init__(
        self,
        scenario: ScenarioConfig,
        context: ExecutionContext | None = None,
    ) -> None:
        """Initialize a scenario runner.

        Args:
            scenario: Compiled scenario configuration.
            context: Optional execution context shared across steps.
        """
        self.scenario = scenario
        self.context = context if context is not None else ExecutionContext()

    async def execute_step(
        self,
        step: StepConfig,
        client: httpx.AsyncClient,
    ) -> StepResult:
        """Execute and validate a single scenario step.

        The execution pipeline is:

        1. Validate the scenario base URL.
        2. Validate the resolved request timeout.
        3. Interpolate path, headers, query parameters, and JSON payload.
        4. Execute the HTTP request.
        5. Validate the HTTP status code(s).
        6. Validate the latency ceiling.
        7. Validate expected response headers.
        8. Parse JSON when schema validation or extraction is required.
        9. Validate the pre-compiled JSON schema.
        10. Extract runtime variables for subsequent steps.

        Args:
            step: Individual scenario step configuration.
            client: Shared asynchronous HTTP client.

        Returns:
            A StepResult describing success/failure and timing.
        """
        start_time = perf_counter()
        response: httpx.Response | None = None

        try:
            if not self.scenario.base_url:
                raise EngineError(
                    f"Scenario '{self.scenario.name}' is missing a valid base_url."
                )

            if step.request.timeout is None:
                raise EngineError(
                    f"Step '{step.name}' is missing a resolved request timeout."
                )

            interpolated_path = self.context.interpolate_string(step.request.path)

            base_url = str(self.scenario.base_url).rstrip("/")
            full_url = f"{base_url}/{str(interpolated_path).lstrip('/')}"

            headers = self.context.interpolate_data(step.request.headers)
            params = self.context.interpolate_data(step.request.params)
            json_payload = self.context.interpolate_data(step.request.json_payload)

            async with client.stream(
                method=step.request.method,
                url=full_url,
                headers=headers,
                params=params,
                json=json_payload,
                timeout=step.request.timeout,
            ) as streamed_response:
                response = streamed_response
                response_body = bytearray()

                async for chunk in streamed_response.aiter_bytes(
                    chunk_size=_RESPONSE_CHUNK_BYTES,
                ):
                    if len(response_body) + len(chunk) > _MAX_RESPONSE_BODY_BYTES:
                        raise EngineError("Response body exceeds the 10 MiB limit.")

                    response_body.extend(chunk)

            latency_ms = (perf_counter() - start_time) * 1000

            expected_statuses = (
                [step.expect.status]
                if isinstance(step.expect.status, int)
                else step.expect.status
            )
            if response.status_code not in expected_statuses:
                raise EngineError(
                    f"Status code mismatch: expected one of "
                    f"{expected_statuses}, got {response.status_code}"
                )

            if (
                step.expect.max_latency_ms is not None
                and latency_ms > step.expect.max_latency_ms
            ):
                raise EngineError(
                    f"Latency limit exceeded: response took "
                    f"{latency_ms:.2f} ms "
                    f"(max allowed: "
                    f"{step.expect.max_latency_ms} ms)"
                )

            for expected_header, expected_value in step.expect.headers.items():
                actual_value = response.headers.get(expected_header)

                if actual_value != expected_value:
                    raise EngineError(
                        describe_header_mismatch(
                            expected_header,
                            expected_value,
                            actual_value,
                        )
                    )

            response_data: Any = None

            if step.expect._compiled_schema is not None or step.extract:
                json_error: str | None = None

                try:
                    response_data = json.loads(response_body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    json_error = "Response body is not valid JSON."

                if json_error is not None:
                    raise EngineError(json_error)

            if step.expect._compiled_schema is not None:
                schema_error: str | None = None

                try:
                    step.expect._compiled_schema(response_data)
                except fastjsonschema.JsonSchemaException:
                    schema_error = "Schema assertion failed."

                if schema_error is not None:
                    raise EngineError(schema_error)

            if step.extract:
                self.context.extract_variables(
                    response_data,
                    step.extract,
                )

            return StepResult(
                step_name=redact_secrets(
                    step.name,
                    self.scenario._secret_values,
                ),
                passed=True,
                status_code=response.status_code,
                latency_ms=round(latency_ms, 2),
            )

        except (httpx.RequestError, EngineError, ContextError) as err:
            latency_ms = (perf_counter() - start_time) * 1000
            status_code = response.status_code if response is not None else 0

            if isinstance(err, httpx.RequestError):
                error_message = f"HTTP request failed ({type(err).__name__})"
            else:
                error_message = str(err)

            all_secrets = set(self.scenario._secret_values)
            all_secrets.update(
                str(v) for v in self.context.variables.values() if str(v)
            )

            error_message = redact_secrets(
                error_message,
                all_secrets,
            )

            return StepResult(
                step_name=redact_secrets(
                    step.name,
                    all_secrets,
                ),
                passed=False,
                status_code=status_code,
                latency_ms=round(latency_ms, 2),
                error=error_message,
            )

        except Exception as err:
            raise InternalExecutionError(
                f"Unexpected error during step execution "
                f"({type(err).__name__}); details suppressed"
            ) from None

    async def run(self, client: httpx.AsyncClient) -> ScenarioResult:
        """Execute all scenario steps sequentially.

        All steps share the same ExecutionContext, allowing values extracted
        from earlier responses to be used by later requests.

        Execution stops at the first failed step.

        Args:
            client: Shared asynchronous HTTP client for connection pooling.

        Returns:
            ScenarioResult containing the aggregate scenario outcome,
            total execution latency, and individual step results.
        """
        step_results: list[StepResult] = []
        scenario_passed = True

        total_start = perf_counter()

        client.cookies.clear()

        for step in self.scenario.steps:
            result = await self.execute_step(step, client)
            step_results.append(result)

            if not result.passed:
                scenario_passed = False
                break

        total_latency_ms = (perf_counter() - total_start) * 1000

        return ScenarioResult(
            scenario_name=redact_secrets(
                self.scenario.name,
                self.scenario._secret_values,
            ),
            passed=scenario_passed,
            total_latency_ms=round(total_latency_ms, 2),
            step_results=step_results,
        )
