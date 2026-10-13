"""Exhaustive unit tests for declarative Pydantic configuration models."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from proofrun.config.models import (
    ExpectConfig,
    GlobalConfig,
    ProofrunConfig,
    RequestConfig,
    ScenarioConfig,
    StepConfig,
)

# ============================================================================
# GlobalConfig Tests
# ============================================================================


def test_global_config_defaults() -> None:
    """Verifies default values for GlobalConfig."""
    config = GlobalConfig()

    assert config.base_url is None
    assert config.timeout_seconds == 10.0
    assert config.headers == {}


def test_global_config_custom_valid() -> None:
    """Verifies instantiation with valid custom arguments."""
    # Using model_validate safely simulates data loading and avoids strict
    # type-checker errors assigning string literals to HttpUrl fields.
    config = GlobalConfig.model_validate(
        {
            "base_url": "https://api.example.com",
            "timeout_seconds": 5.5,
            "headers": {"Authorization": "Bearer token123"},
        }
    )

    assert config.base_url is not None
    assert str(config.base_url).rstrip("/") == "https://api.example.com"
    assert config.timeout_seconds == 5.5
    assert config.headers == {"Authorization": "Bearer token123"}


def test_global_config_headers_default_factory_isolation() -> None:
    """Verifies default header dicts are isolated across model instances."""
    config1 = GlobalConfig()
    config2 = GlobalConfig()

    config1.headers["X-Test"] = "true"

    assert "X-Test" not in config2.headers


@pytest.mark.parametrize("invalid_timeout", [0, -1, -0.001])
def test_global_config_timeout_gt_zero(invalid_timeout: float) -> None:
    """Verifies global timeout must be strictly greater than zero."""
    with pytest.raises(ValidationError) as exc_info:
        GlobalConfig(timeout_seconds=invalid_timeout)

    assert "timeout_seconds" in str(exc_info.value)


# ============================================================================
# RequestConfig Tests
# ============================================================================


def test_request_config_required_fields() -> None:
    """Verifies missing required fields trigger validation errors."""
    with pytest.raises(ValidationError) as exc_info:
        RequestConfig.model_validate({})

    errors = str(exc_info.value)
    assert "method" in errors
    assert "path" in errors


def test_request_config_defaults() -> None:
    """Verifies default optional fields for RequestConfig."""
    config = RequestConfig(method="GET", path="/health")

    assert config.headers == {}
    assert config.params == {}
    assert config.json_payload is None
    assert config.timeout is None


def test_request_config_json_alias() -> None:
    """Verifies YAML key 'json' correctly maps to 'json_payload'."""
    raw_data = {
        "method": "POST",
        "path": "/users",
        "json": {"name": "Alice", "role": "admin"},
    }

    config = RequestConfig.model_validate(raw_data)

    assert config.json_payload == {"name": "Alice", "role": "admin"}


def test_request_config_dict_isolation() -> None:
    """Verifies default factories for headers and params are isolated."""
    req1 = RequestConfig(method="GET", path="/a")
    req2 = RequestConfig(method="GET", path="/b")

    req1.headers["X-Step"] = "1"
    req1.params["debug"] = True

    assert "X-Step" not in req2.headers
    assert "debug" not in req2.params


@pytest.mark.parametrize("invalid_timeout", [0, -1.0, -0.0001])
def test_request_config_timeout_gt_zero(invalid_timeout: float) -> None:
    """Verifies step request timeout must be greater than zero when provided."""
    with pytest.raises(ValidationError) as exc_info:
        RequestConfig(
            method="GET",
            path="/",
            timeout=invalid_timeout,
        )

    assert "timeout" in str(exc_info.value)


# ============================================================================
# ExpectConfig Tests
# ============================================================================


def test_expect_config_required_fields() -> None:
    """Verifies 'status' is required."""
    with pytest.raises(ValidationError) as exc_info:
        ExpectConfig.model_validate({})

    assert "status" in str(exc_info.value)


def test_expect_config_defaults() -> None:
    """Verifies default optional fields for ExpectConfig."""
    config = ExpectConfig(status=200)

    assert config.status == 200
    assert config.headers == {}
    assert config.max_latency_ms is None
    assert config.schema_data is None
    assert config._compiled_schema is None


def test_expect_config_schema_alias_and_types() -> None:
    """Verifies 'schema' alias supports inline dicts and file paths."""
    dict_schema = ExpectConfig.model_validate(
        {
            "status": 200,
            "schema": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        }
    )
    assert isinstance(dict_schema.schema_data, dict)

    path_schema = ExpectConfig.model_validate(
        {
            "status": 200,
            "schema": "schemas/user.json",
        }
    )
    assert path_schema.schema_data == "schemas/user.json"


def test_expect_config_arbitrary_types_compiled_schema() -> None:
    """Verifies callable functions can be assigned to _compiled_schema."""
    dummy_validator = lambda x: True  # noqa: E731

    config = ExpectConfig(status=200)
    config._compiled_schema = dummy_validator

    assert callable(config._compiled_schema)
    assert config._compiled_schema({"any": "data"}) is True


@pytest.mark.parametrize("invalid_latency", [0, -1, -500.0])
def test_expect_config_max_latency_gt_zero(invalid_latency: float) -> None:
    """Verifies max_latency_ms must be strictly positive."""
    with pytest.raises(ValidationError) as exc_info:
        ExpectConfig(status=200, max_latency_ms=invalid_latency)

    assert "max_latency_ms" in str(exc_info.value)


# ============================================================================
# StepConfig Tests
# ============================================================================


def test_step_config_required_fields() -> None:
    """Verifies 'name', 'request', and 'expect' are mandatory."""
    with pytest.raises(ValidationError) as exc_info:
        StepConfig.model_validate({})

    errors = str(exc_info.value)
    assert "name" in errors
    assert "request" in errors
    assert "expect" in errors


def test_step_config_valid_and_extract_isolation() -> None:
    """Verifies StepConfig init and extract dict isolation."""
    step1 = StepConfig.model_validate(
        {
            "name": "Step 1",
            "request": {"method": "GET", "path": "/items"},
            "expect": {"status": 200},
        }
    )
    step2 = StepConfig.model_validate(
        {
            "name": "Step 2",
            "request": {"method": "POST", "path": "/items"},
            "expect": {"status": 201},
        }
    )

    step1.extract["item_id"] = "$.id"

    assert step1.extract == {"item_id": "$.id"}
    assert step2.extract == {}


def test_step_config_nested_validation_error() -> None:
    """Verifies nested validation failures bubble up correctly."""
    invalid_raw_step = {
        "name": "Invalid Request Method Step",
        "request": {},
        "expect": {"status": 200},
    }

    with pytest.raises(ValidationError) as exc_info:
        StepConfig.model_validate(invalid_raw_step)

    assert "request" in str(exc_info.value)


# ============================================================================
# ScenarioConfig Tests
# ============================================================================


def test_scenario_config_required_fields() -> None:
    """Verifies 'name' and 'steps' are mandatory."""
    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate({})

    errors = str(exc_info.value)
    assert "name" in errors
    assert "steps" in errors


def test_scenario_config_defaults() -> None:
    """Verifies default values for scenario settings."""
    scenario = ScenarioConfig.model_validate(
        {
            "name": "Ping Scenario",
            "steps": [
                {
                    "name": "Ping",
                    "request": {"method": "GET", "path": "/ping"},
                    "expect": {"status": 200},
                }
            ],
        }
    )

    assert scenario.base_url is None
    assert scenario.interval_seconds == 60
    assert len(scenario.steps) == 1


@pytest.mark.parametrize("invalid_interval", [0, -1, -60])
def test_scenario_config_interval_gt_zero(invalid_interval: int) -> None:
    """Verifies scenario daemon interval must be strictly positive."""
    with pytest.raises(ValidationError) as exc_info:
        ScenarioConfig.model_validate(
            {
                "name": "Bad Interval",
                "interval_seconds": invalid_interval,
                "steps": [
                    {
                        "name": "Ping",
                        "request": {"method": "GET", "path": "/ping"},
                        "expect": {"status": 200},
                    }
                ],
            }
        )

    assert "interval_seconds" in str(exc_info.value)


# ============================================================================
# ProofrunConfig Tests
# ============================================================================


def test_proofrun_config_required_fields() -> None:
    """Verifies 'version' and 'scenarios' are mandatory at root level."""
    with pytest.raises(ValidationError) as exc_info:
        ProofrunConfig.model_validate({})

    errors = str(exc_info.value)
    assert "version" in errors
    assert "scenarios" in errors


@pytest.mark.parametrize("invalid_version", ["2.0", "1.1", "1", "v1.0", 1.0])
def test_proofrun_config_version_literal_strictly_enforced(
    invalid_version: Any,
) -> None:
    """Verifies schema version strictly rejects anything other than '1.0'."""
    raw_config = {
        "version": invalid_version,
        "scenarios": [
            {
                "name": "Dummy",
                "steps": [
                    {
                        "name": "S",
                        "request": {"method": "GET", "path": "/"},
                        "expect": {"status": 200},
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValidationError) as exc_info:
        ProofrunConfig.model_validate(raw_config)

    assert "version" in str(exc_info.value)


def test_proofrun_config_global_alias_unpacking() -> None:
    """Verifies root YAML alias 'global' correctly populates config."""
    raw_config = {
        "version": "1.0",
        "global": {
            "base_url": "https://api.example.com",
            "timeout_seconds": 15.0,
            "headers": {"X-App": "Proofrun"},
        },
        "scenarios": [
            {
                "name": "Suite",
                "steps": [
                    {
                        "name": "Step 1",
                        "request": {"method": "GET", "path": "/"},
                        "expect": {"status": 200},
                    }
                ],
            }
        ],
    }

    config = ProofrunConfig.model_validate(raw_config)

    assert config.global_config is not None
    assert config.global_config.base_url is not None

    base_url_str = str(config.global_config.base_url).rstrip("/")
    assert base_url_str == "https://api.example.com"

    assert config.global_config.timeout_seconds == 15.0
    assert config.global_config.headers == {"X-App": "Proofrun"}


def test_proofrun_config_full_exhaustive_yaml_parsing() -> None:
    """Verifies end-to-end parsing of a complex multi-scenario YAML structure."""
    raw_yaml_dict = {
        "version": "1.0",
        "global": {
            "base_url": "https://api.service.io",
            "timeout_seconds": 8.0,
            "headers": {"User-Agent": "Proofrun-Daemon/1.0"},
        },
        "scenarios": [
            {
                "name": "E2E User Flow",
                "base_url": "https://override.service.io",
                "interval_seconds": 30,
                "steps": [
                    {
                        "name": "Create User",
                        "request": {
                            "method": "POST",
                            "path": "/users",
                            "headers": {"Content-Type": "application/json"},
                            "params": {"notify": True},
                            "json": {"username": "john_doe"},
                            "timeout": 3.0,
                        },
                        "expect": {
                            "status": 201,
                            "max_latency_ms": 1500,
                            "headers": {"Content-Type": "application/json"},
                            "schema": {
                                "type": "object",
                                "required": ["id"],
                            },
                        },
                        "extract": {"user_id": "$.id"},
                    }
                ],
            }
        ],
    }

    config = ProofrunConfig.model_validate(raw_yaml_dict)

    # Root asserts
    assert config.version == "1.0"
    assert config.global_config is not None
    assert config.global_config.timeout_seconds == 8.0

    # Scenario asserts
    scenario = config.scenarios[0]
    assert scenario.name == "E2E User Flow"
    assert scenario.base_url is not None

    base_url_str = str(scenario.base_url).rstrip("/")
    assert base_url_str == "https://override.service.io"
    assert scenario.interval_seconds == 30

    # Step & Request & Expect asserts
    step = scenario.steps[0]
    assert step.name == "Create User"
    assert step.request.method == "POST"
    assert step.request.params == {"notify": True}
    assert step.request.json_payload == {"username": "john_doe"}
    assert step.request.timeout == 3.0
    assert step.expect.status == 201
    assert step.expect.max_latency_ms == 1500
    assert step.extract == {"user_id": "$.id"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retries", -1),
        ("retries", 11),
        ("retry_delay_seconds", -0.1),
        ("retry_delay_seconds", 301),
        ("failure_threshold", 0),
        ("recovery_threshold", 0),
        ("interval_seconds", 0),
    ],
)
def test_reliability_settings_are_bounded(field: str, value: float) -> None:
    step = {
        "name": "s",
        "request": {"method": "GET", "path": "/"},
        "expect": {"status": 200},
    }

    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate({"name": "x", "steps": [step], field: value})

    with pytest.raises(ValidationError):
        GlobalConfig.model_validate({field: value})


_STEP: dict[str, Any] = {
    "name": "s",
    "request": {"method": "GET", "path": "/"},
    "expect": {"status": 200},
}


def _scenario(**overrides: Any) -> dict[str, Any]:
    return {"name": "x", "steps": [dict(_STEP)], **overrides}


def test_a_configuration_needs_at_least_one_scenario() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        ProofrunConfig.model_validate({"version": "1.0", "scenarios": []})


def test_a_scenario_needs_at_least_one_step() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        ScenarioConfig.model_validate({"name": "x", "steps": []})


@pytest.mark.parametrize(
    "document",
    [
        {"version": "1.0", "scenarioz": [], "scenarios": [_scenario()]},
        {
            "version": "1.0",
            "global": {"timeout_second": 5},
            "scenarios": [_scenario()],
        },
        {"version": "1.0", "scenarios": [_scenario(retriess=3)]},
        {"version": "1.0", "scenarios": [_scenario(failure_treshold=3)]},
        {
            "version": "1.0",
            "scenarios": [
                _scenario(
                    steps=[
                        {
                            **_STEP,
                            "request": {"method": "GET", "path": "/", "timeoutt": 1},
                        }
                    ]
                )
            ],
        },
        {
            "version": "1.0",
            "scenarios": [
                _scenario(
                    steps=[
                        {
                            **_STEP,
                            "expect": {"status": 200, "max_latenc_ms": 1},
                        }
                    ]
                )
            ],
        },
        {
            "version": "1.0",
            "scenarios": [_scenario(steps=[{**_STEP, "extractt": {"a": "$.a"}}])],
        },
    ],
    ids=[
        "root",
        "global",
        "scenario-retries",
        "scenario-threshold",
        "request",
        "expect",
        "step",
    ],
)
def test_unknown_fields_are_rejected_at_every_level(
    document: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProofrunConfig.model_validate(document)


def test_aliased_fields_still_work_with_strict_models() -> None:
    config = ProofrunConfig.model_validate(
        {
            "version": "1.0",
            "global": {"base_url": "https://example.com"},
            "scenarios": [
                _scenario(
                    steps=[
                        {
                            "name": "s",
                            "request": {
                                "method": "POST",
                                "path": "/",
                                "json": {"a": 1},
                            },
                            "expect": {"status": 201, "schema": {"type": "object"}},
                        }
                    ]
                )
            ],
        }
    )

    step = config.scenarios[0].steps[0]

    assert step.request.json_payload == {"a": 1}
    assert step.expect.schema_data == {"type": "object"}


@pytest.mark.parametrize("status", [200, 100, 599, [200, 201], [404]])
def test_valid_status_codes_are_accepted(status: int | list[int]) -> None:
    assert ExpectConfig(status=status).status == status


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ([], "must not be an empty list"),
        (0, "outside the range 100-599"),
        (99, "outside the range 100-599"),
        (600, "outside the range 100-599"),
        (-5, "outside the range 100-599"),
        ([200, 999], "status code 999 is outside"),
    ],
)
def test_invalid_status_codes_are_rejected(
    status: int | list[int],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExpectConfig(status=status)
