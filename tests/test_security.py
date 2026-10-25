"""Security regression tests for Proofrun."""

from io import StringIO

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

from proofrun.cli.commands import app
from proofrun.cli.render import render_scenario_result
from proofrun.config.compiler import (
    ConfigCompilerError,
    load_and_compile_config,
)
from proofrun.metrics.registry import MetricsRegistry
from proofrun.redaction import redact_secrets
from proofrun.runner.engine import InternalExecutionError, ScenarioRunner


@pytest.mark.asyncio
async def test_environment_secret_is_redacted_from_request_errors(
    tmp_path,
    monkeypatch,
) -> None:
    """An environment secret in a request URL must not leak into errors."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-9f2ab63"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Security test"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health/${env.PROOFRUN_TEST_SECRET}"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    scenario = load_and_compile_config(config_path).scenarios[0]
    assert secret in scenario.steps[0].request.path

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"Connection failed for {request.url}",
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await ScenarioRunner(scenario).execute_step(
            scenario.steps[0],
            client,
        )

    assert not result.passed
    assert result.error is not None
    assert secret not in result.error


@pytest.mark.asyncio
async def test_environment_secret_is_redacted_from_unexpected_errors(
    tmp_path,
    monkeypatch,
) -> None:
    """Unexpected exceptions must not expose environment secrets."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-UNEXPECTED-4d7c"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Security test"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health/${env.PROOFRUN_TEST_SECRET}"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    scenario = load_and_compile_config(config_path).scenarios[0]
    assert secret in scenario.steps[0].request.path

    async def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"Unexpected failure for {request.url}")

    with pytest.raises(InternalExecutionError) as exc_info:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await ScenarioRunner(scenario).execute_step(
                scenario.steps[0],
                client,
            )

    assert "RuntimeError" in str(exc_info.value)
    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


@pytest.mark.asyncio
async def test_environment_secret_is_redacted_from_header_assertion_errors(
    tmp_path,
    monkeypatch,
) -> None:
    """Environment secrets must not leak through header assertion errors."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-HEADER-5a8d"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Security test"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
          headers:
            X-Internal-Label: "${env.PROOFRUN_TEST_SECRET}"
""",
        encoding="utf-8",
    )

    scenario = load_and_compile_config(config_path).scenarios[0]
    assert scenario.steps[0].expect.headers["X-Internal-Label"] == secret

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-Internal-Label": "ordinary-value"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await ScenarioRunner(scenario).execute_step(
            scenario.steps[0],
            client,
        )

    assert not result.passed
    assert result.error is not None
    assert "X-Internal-Label" in result.error
    assert secret not in result.error


def test_redact_secrets_handles_overlapping_values() -> None:
    assert (
        redact_secrets(
            "token-long token",
            {"token", "token-long", ""},
        )
        == "[REDACTED] [REDACTED]"
    )


def test_redact_secrets_with_no_values_preserves_message() -> None:
    assert redact_secrets("Safe diagnostic message", set()) == (
        "Safe diagnostic message"
    )


def test_environment_secret_in_scenario_name_is_not_exported_as_metric_label(
    tmp_path,
    monkeypatch,
) -> None:
    """Environment secrets must not appear in Prometheus scenario labels."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-METRICS-72bd"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    scenario = load_and_compile_config(config_path).scenarios[0]
    assert scenario.name == secret

    registry = MetricsRegistry()
    registry.record_run(
        scenario.name,
        True,
        0.1,
        1.0,
        secret_values=scenario._secret_values,
    )

    output = registry.render()

    assert secret not in output


@pytest.mark.asyncio
async def test_environment_secret_is_redacted_from_terminal_output(
    tmp_path,
    monkeypatch,
) -> None:
    """Environment secrets must not leak through displayed scenario or step names."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-TERMINAL-9c2e"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "${env.PROOFRUN_TEST_SECRET}"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    scenario = load_and_compile_config(config_path).scenarios[0]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await ScenarioRunner(scenario).run(client)

    output = StringIO()
    terminal = Console(file=output, force_terminal=False, color_system=None)
    monkeypatch.setattr("proofrun.cli.render.console", terminal)

    render_scenario_result(result)

    assert secret not in output.getvalue()


def test_environment_secret_is_redacted_from_duplicate_name_config_error(
    tmp_path,
    monkeypatch,
) -> None:
    """Duplicate-name errors must not expose environment-resolved names."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-CONFIG-5c82"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request A"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request B"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "Duplicate scenario name" in message
    assert secret not in message


def test_environment_secret_is_redacted_from_missing_base_url_error(
    tmp_path,
    monkeypatch,
) -> None:
    """Missing-base-URL errors must not expose environment-resolved names."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-BASEURL-3a71"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "base_url" in message
    assert secret not in message


def test_environment_secret_is_redacted_from_missing_schema_error(
    tmp_path,
    monkeypatch,
) -> None:
    """A missing schema-file error must not expose an environment value."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-SCHEMA-2e64"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Schema security test"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
          schema: "${env.PROOFRUN_TEST_SECRET}"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "JSON Schema file not found" in message
    assert secret not in message


def test_environment_secret_is_redacted_from_schema_read_error(
    tmp_path,
    monkeypatch,
) -> None:
    """Schema read errors must not expose environment-provided paths."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-SCHEMA-READ-87d2.json"
    monkeypatch.setenv("PROOFRUN_TEST_SCHEMA_PATH", secret)

    # Create an existing but invalid JSON file so loading reaches the
    # JSON parsing error instead of the missing-file error.
    (tmp_path / secret).write_text("{ invalid JSON", encoding="utf-8")

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Schema read security test"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
          schema: "${env.PROOFRUN_TEST_SCHEMA_PATH}"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "Failed to read JSON schema file" in message
    assert secret not in message


def test_environment_secret_is_redacted_from_schema_compile_error(
    tmp_path,
    monkeypatch,
) -> None:
    """Schema compilation errors must not expose environment secrets."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-COMPILE-4a73"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
          schema:
            type: string
            pattern: "["
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "Failed to compile JSON schema" in message
    assert secret not in message


def test_environment_secret_is_redacted_from_schema_type_error(
    tmp_path,
    monkeypatch,
) -> None:
    """Schema-type errors must not expose environment-resolved names."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-SCHEMA-TYPE-a3c9"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    (tmp_path / "schema.json").write_text("[]", encoding="utf-8")

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
          schema: schema.json
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "JSON Schema must be an object" in message
    assert secret not in message


def test_environment_secret_is_redacted_from_invalid_extract_error(
    tmp_path,
    monkeypatch,
) -> None:
    """Invalid extraction errors must not expose resolved scenario names."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-EXTRACT-6d28"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
        extract:
          env.blocked: "$.token"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "Invalid extract variable" in message
    assert secret not in message


def test_environment_secret_is_redacted_from_validation_error_location(
    tmp_path,
    monkeypatch,
) -> None:
    """Validation errors must not expose environment-resolved mapping keys."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-VALIDATION-91ef"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Validation security test"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
        "${env.PROOFRUN_TEST_SECRET}": "unexpected"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    message = str(exc_info.value)

    assert "Extra inputs are not permitted" in message
    assert secret not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_environment_secret_is_redacted_from_validate_output(
    tmp_path,
    monkeypatch,
) -> None:
    """The --validate command must not print environment secrets in names."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-VALIDATE-71bd"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, [str(config_path), "--validate"])

    assert result.exit_code == 0
    assert "Configuration is valid" in result.stdout
    assert secret not in result.stdout


def test_redaction_does_not_create_duplicate_metric_labels(
    tmp_path,
    monkeypatch,
) -> None:
    """Redacting a secret must not collapse distinct scenarios into one series."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-COLLISION-b82e"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)

    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "${env.PROOFRUN_TEST_SECRET}"
    steps:
      - name: "Request A"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
  - name: "[REDACTED]"
    steps:
      - name: "Request B"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
  - name: "[REDACTED] [series 1]"
    steps:
      - name: "Request C"
        request:
          method: GET
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)
    registry = MetricsRegistry()

    for scenario in config.scenarios:
        registry.record_run(
            scenario.name,
            True,
            0.1,
            1.0,
            secret_values=scenario._secret_values,
        )

    output = registry.render()
    run_series = [
        line
        for line in output.splitlines()
        if line.startswith("proofrun_scenario_runs_total{")
    ]
    label_sets = [line.split("}", maxsplit=1)[0] for line in run_series]

    assert len(label_sets) == 3
    assert len(label_sets) == len(set(label_sets))
    assert secret not in output


@pytest.mark.parametrize("location", ["header", "query", "json"])
@pytest.mark.asyncio
async def test_environment_secret_is_redacted_from_request_components(
    tmp_path, monkeypatch, location: str
) -> None:
    """Request secrets reach the mock server but stay out of failures."""
    secret = "PROOFRUN-TEST-REQUEST-COMPONENT-CANARY-67ab"
    monkeypatch.setenv("PROOFRUN_TEST_SECRET", secret)
    fields = {
        "header": (
            "          headers:"
            + chr(10)
            + "            X-API-Key: ${env.PROOFRUN_TEST_SECRET}"
            + chr(10)
        ),
        "query": (
            "          params:"
            + chr(10)
            + "            api_key: ${env.PROOFRUN_TEST_SECRET}"
            + chr(10)
        ),
        "json": (
            "          json:"
            + chr(10)
            + "            api_key: ${env.PROOFRUN_TEST_SECRET}"
            + chr(10)
        ),
    }
    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Request component security test"
    steps:
      - name: "Request"
        request:
          method: POST
          path: "/health"
"""
        + fields[location]
        + """        expect:
          status: 200
""",
        encoding="utf-8",
    )
    scenario = load_and_compile_config(config_path).scenarios[0]
    observed_values: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if location == "header":
            value = request.headers["X-API-Key"]
        elif location == "query":
            value = request.url.params["api_key"]
        else:
            value = request.content.decode("utf-8")
        observed_values.append(value)
        raise httpx.ConnectError(f"Mock failure: {value}", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await ScenarioRunner(scenario).execute_step(scenario.steps[0], client)

    assert len(observed_values) == 1
    assert secret in observed_values[0]
    assert not result.passed
    assert result.error == "HTTP request failed (ConnectError)"
    assert secret not in result.error


@pytest.mark.asyncio
async def test_extracted_token_is_not_leaked_from_later_request_error(
    tmp_path,
) -> None:
    """An extracted token must not leak through a later request failure."""
    access_token = "PROOFRUN-RUNTIME-TOKEN-CANARY-6bb2"
    config_path = tmp_path / "scenario.yaml"
    config_path.write_text(
        """version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Runtime token security test"
    steps:
      - name: "Login"
        request:
          method: GET
          path: "/login"
        expect:
          status: 200
        extract:
          token: "$.access_token"
      - name: "Authenticated request"
        request:
          method: GET
          path: "/profile"
          headers:
            Authorization: "Bearer ${token}"
        expect:
          status: 200
""",
        encoding="utf-8",
    )
    scenario = load_and_compile_config(config_path).scenarios[0]
    observed_authorization: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"access_token": access_token})
        authorization = request.headers["Authorization"]
        observed_authorization.append(authorization)
        raise httpx.ConnectError(f"Mock failure: {authorization}", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await ScenarioRunner(scenario).run(client)

    assert observed_authorization == [f"Bearer {access_token}"]
    assert not result.passed
    assert result.step_results[1].error == "HTTP request failed (ConnectError)"
    assert access_token not in repr(result)
