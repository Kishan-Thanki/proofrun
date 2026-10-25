# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Adversarial and resource-exhaustion tests for Proofrun."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import HttpUrl

from proofrun.config.compiler import ConfigCompilerError, load_and_compile_config
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
)


@pytest.mark.asyncio
async def test_deeply_nested_json_response_does_not_crash_parser() -> None:
    """Extreme JSON nesting levels must be handled safely without recursion crash."""
    # Build 150-level nested JSON object
    data: dict[str, Any] = {"leaf": "target_value"}
    for _ in range(150):
        data = {"nest": data}

    payload_bytes = json.dumps(data).encode("utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload_bytes)

    step = StepConfig(
        name="Deep JSON Step",
        request=RequestConfig(method="GET", path="/nested", timeout=5.0),
        expect=ExpectConfig(status=200),
        extract={"val": "$..leaf"},
    )
    scenario = ScenarioConfig(
        name="Adversarial Nesting",
        base_url=HttpUrl("https://target.example"),
        steps=[step],
    )

    context = ExecutionContext()
    runner = ScenarioRunner(scenario, context=context)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is True
    assert context.get("val") == "target_value"


@pytest.mark.asyncio
async def test_response_streaming_exact_boundary() -> None:
    """A body exactly at _MAX_RESPONSE_BODY_BYTES must pass without error."""

    class ExactBoundaryStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> Any:
            chunk = b"A" * (64 * 1024)
            remaining = _MAX_RESPONSE_BODY_BYTES
            while remaining > 0:
                size = min(remaining, len(chunk))
                yield chunk[:size]
                remaining -= size

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ExactBoundaryStream())

    step = StepConfig(
        name="Boundary Step",
        request=RequestConfig(method="GET", path="/boundary", timeout=5.0),
        expect=ExpectConfig(status=200),
    )
    scenario = ScenarioConfig(
        name="Boundary Test",
        base_url=HttpUrl("https://target.example"),
        steps=[step],
    )

    runner = ScenarioRunner(scenario)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await runner.execute_step(step, client)

    assert result.passed is True


def test_malformed_billion_laughs_yaml_rejected(tmp_path: Path) -> None:
    """YAML expansion bomb must not cause unbounded memory expansion."""
    malicious_yaml = tmp_path / "bomb.yaml"
    malicious_yaml.write_text(
        """version: "1.0"
a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
scenarios:
  - name: "Bomb"
    steps:
      - name: "Step"
        request:
          method: GET
          path: "/test"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    # Extra fields at root are forbidden by StrictModel, rejected early
    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(malicious_yaml)

    assert "extra inputs are not permitted" in str(exc_info.value).lower()
