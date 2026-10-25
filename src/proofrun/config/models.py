"""Declarative configuration models for Proofrun synthetic monitoring scenarios.

This module defines the Pydantic schemas used to parse, validate, and structure
YAML monitoring scenarios, including global settings, request parameters,
expectations, schema validations, and extraction rules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PrivateAttr,
    field_validator,
)


class StrictModel(BaseModel):
    """Base for every configuration model.

    Unknown fields are rejected. Without this a misspelled key (for example
    ``max_latenc_ms``) would be ignored and the check it was meant to configure
    would silently never run.
    """

    model_config = ConfigDict(extra="forbid")


class GlobalConfig(StrictModel):
    """Global default settings applied across all scenarios and steps."""

    base_url: HttpUrl | None = Field(
        default=None,
        description="Default root URL target for scenarios.",
    )
    timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Default HTTP request timeout ceiling in seconds.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Default HTTP headers sent with all requests.",
    )
    interval_seconds: int = Field(
        default=60,
        gt=0,
        description="Default execution interval in seconds for daemon mode.",
    )
    retries: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Default number of extra attempts after a failed scenario run.",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        ge=0,
        le=300,
        description="Default delay in seconds between attempts of a scenario.",
    )
    failure_threshold: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Default consecutive failed runs before a scenario is FAILING.",
    )
    recovery_threshold: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Default consecutive passing runs before a scenario recovers.",
    )


class RequestConfig(StrictModel):
    """Defines the parameters for an outgoing HTTP request."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = Field(
        ...,
        description="HTTP method.",
    )
    path: str = Field(
        ...,
        description="Endpoint path relative to base_url.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Key-value pairs for HTTP request headers.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="URL query parameters.",
    )
    json_payload: Any = Field(
        default=None,
        alias="json",
        description="JSON serializable body payload.",
    )
    timeout: float | None = Field(
        default=None,
        gt=0,
        description="Step-specific HTTP request timeout ceiling in seconds.",
    )


class ExpectConfig(StrictModel):
    """Defines assertion criteria evaluated against the HTTP response."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: int | list[int] = Field(
        ...,
        description="Expected HTTP status code(s), each between 100 and 599.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Expected HTTP headers and their exact values.",
    )
    max_latency_ms: float | None = Field(
        default=None,
        gt=0,
        description="Maximum allowed response latency in milliseconds.",
    )
    schema_data: str | dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="Path to a JSON schema file or inline schema dictionary.",
    )

    _compiled_schema: Callable[[Any], Any] | None = PrivateAttr(default=None)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: int | list[int]) -> int | list[int]:
        """Reject empty lists and codes outside the valid HTTP range."""
        codes = value if isinstance(value, list) else [value]

        if not codes:
            raise ValueError("status must not be an empty list")

        for code in codes:
            if not 100 <= code <= 599:
                raise ValueError(f"status code {code} is outside the range 100-599")

        return value


class StepConfig(StrictModel):
    """Represents an atomic execution step in a multi-step API scenario."""

    name: str = Field(
        ...,
        description="Human-readable identifier for the scenario step.",
    )
    request: RequestConfig = Field(
        ...,
        description="HTTP request specifications.",
    )
    expect: ExpectConfig = Field(
        ...,
        description="Response assertion rules.",
    )
    extract: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of variable names to JSONPath expressions.",
    )


class ScenarioConfig(StrictModel):
    """Defines a sequence of dependent execution steps against a target host."""

    _secret_values: frozenset[str] = PrivateAttr(default_factory=frozenset)

    name: str = Field(
        ...,
        description="Human-readable scenario suite name.",
    )
    base_url: HttpUrl | None = Field(
        default=None,
        description="Root URL target for all steps in this scenario.",
    )
    interval_seconds: int = Field(
        default=60,
        gt=0,
        description="Execution interval in seconds for daemon mode.",
    )
    retries: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Extra attempts after a failed run; the whole scenario is re-run.",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        ge=0,
        le=300,
        description="Delay in seconds between attempts of this scenario.",
    )
    failure_threshold: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Consecutive failed runs before the scenario becomes FAILING.",
    )
    recovery_threshold: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Consecutive passing runs before a FAILING scenario recovers.",
    )
    steps: list[StepConfig] = Field(
        ...,
        min_length=1,
        description="Ordered sequence of steps executed within shared context memory.",
    )


class ProofrunConfig(StrictModel):
    """Root configuration model representing a parsed Proofrun YAML file."""

    version: Literal["1.0"] = Field(
        ...,
        description="Configuration schema version. Currently only '1.0' is supported.",
    )
    global_config: GlobalConfig | None = Field(
        default=None,
        alias="global",
        description="Global configuration settings applied across scenarios.",
    )
    scenarios: list[ScenarioConfig] = Field(
        ...,
        min_length=1,
        description="List of scenario workflows defined in the configuration file.",
    )
