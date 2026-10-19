# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Exhaustive unit and integration tests for Proofrun configuration compiler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fastjsonschema
import pytest
from pydantic import ValidationError

from proofrun.config.compiler import (
    ConfigCompilerError,
    _format_validation_error,
    load_and_compile_config,
)
from proofrun.config.models import ProofrunConfig

# ============================================================================
# Integration & File Loading Tests
# ============================================================================


def test_load_and_compile_config_integration() -> None:
    """Verifies end-to-end config compilation using the profile scenario."""
    project_root = Path(__file__).parent.parent
    scenario_path = project_root / "scenarios" / "profile.yaml"

    config = load_and_compile_config(scenario_path)

    assert config.global_config is not None
    assert config.global_config.base_url is not None
    base_url_str = str(config.global_config.base_url).rstrip("/")
    assert base_url_str == "http://127.0.0.1:8099"
    assert config.global_config.timeout_seconds == 5.0

    scenario = config.scenarios[0]
    step = scenario.steps[0]

    assert scenario.name == "User Profile Check"
    assert scenario.interval_seconds == 60
    assert step.name == "Fetch User #1"
    assert step.expect.max_latency_ms == 1000.0

    schema_func = step.expect._compiled_schema

    assert schema_func is not None
    assert callable(schema_func)

    valid_payload = {
        "id": 1,
        "name": "Leanne Graham",
        "username": "Bret",
        "email": "Sincere@april.biz",
    }

    assert schema_func(valid_payload) == valid_payload

    invalid_payload = {"id": "not-an-int"}

    with pytest.raises(fastjsonschema.JsonSchemaValueException):
        schema_func(invalid_payload)


def test_load_and_compile_file_not_found() -> None:
    """Verifies missing config paths raise ConfigCompilerError."""
    missing_path = Path("scenarios/non_existent_file.yaml")

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(missing_path)

    assert "Configuration file not found" in str(exc_info.value)


def test_load_and_compile_invalid_yaml(tmp_path: Path) -> None:
    """Verifies malformed YAML syntax raises ConfigCompilerError."""
    config_path = tmp_path / "invalid.yaml"

    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
  timeout_seconds: [
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    assert "Invalid YAML syntax" in str(exc_info.value)


def test_load_and_compile_os_error_reading_file(tmp_path: Path) -> None:
    """Verifies OSError during file reading (e.g. passing a directory) raises error."""
    dir_path = tmp_path / "directory_as_file.yaml"
    dir_path.mkdir()

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(dir_path)

    assert "Failed to read configuration file" in str(exc_info.value)


def test_load_and_compile_non_mapping_yaml(tmp_path: Path) -> None:
    """Verifies a top-level YAML list/scalar instead of a mapping is rejected."""
    config_path = tmp_path / "invalid.yaml"

    config_path.write_text(
        """
- item_one
- item_two
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    assert "Expected a top-level YAML mapping" in str(exc_info.value)


def test_load_and_compile_pydantic_validation_error(tmp_path: Path) -> None:
    """Verifies Pydantic schema validation failures raise ConfigCompilerError."""
    config_path = tmp_path / "invalid_schema.yaml"

    config_path.write_text(
        """
version: "2.0"
scenarios: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    assert "Config validation failed" in str(exc_info.value)


# ============================================================================
# Inheritance & Default Resolution Tests
# ============================================================================


def test_load_and_compile_missing_base_url(tmp_path: Path) -> None:
    """Verifies compilation fails when both scenario and global base_url are omitted."""
    config_path = tmp_path / "bad_config.yaml"

    config_path.write_text(
        """
version: "1.0"

scenarios:
  - name: "No URL Scenario"
    steps:
      - name: "Step 1"
        request:
          method: "GET"
          path: "/ping"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    assert "missing 'base_url'" in str(exc_info.value)


def test_scenario_inherits_global_base_url(tmp_path: Path) -> None:
    """Verifies scenario inherits base_url from global configuration."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "Inherited URL Scenario"
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    assert config.scenarios[0].base_url is not None
    base_url_str = str(config.scenarios[0].base_url).rstrip("/")
    assert base_url_str == "https://api.example.com"


def test_scenario_with_own_base_url_and_no_global(tmp_path: Path) -> None:
    """Verifies scenario works when specifying its own base_url without global block."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

scenarios:
  - name: "Self-Contained Scenario"
    base_url: "https://self.example.com"
    steps:
      - name: "Ping"
        request:
          method: "GET"
          path: "/ping"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    assert config.scenarios[0].base_url is not None
    base_url_str = str(config.scenarios[0].base_url).rstrip("/")
    assert base_url_str == "https://self.example.com"
    assert config.scenarios[0].steps[0].request.timeout == 10.0


def test_step_inherits_global_timeout(tmp_path: Path) -> None:
    """Verifies step inherits timeout from global configuration."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"
  timeout_seconds: 7.5

scenarios:
  - name: "Inherited Timeout Scenario"
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    assert config.scenarios[0].steps[0].request.timeout == 7.5


def test_step_timeout_overrides_global_timeout(tmp_path: Path) -> None:
    """Verifies step timeout overrides global timeout."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"
  timeout_seconds: 7.5

scenarios:
  - name: "Step Timeout Scenario"
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
          timeout: 3.0
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    assert config.scenarios[0].steps[0].request.timeout == 3.0


def test_global_headers_are_merged_with_step_headers(tmp_path: Path) -> None:
    """Verifies global headers are inherited and step headers override them."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"
  headers:
    Authorization: "Bearer global-token"
    X-Environment: "production"
    X-Shared: "global"

scenarios:
  - name: "Header Merge Scenario"
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
          headers:
            X-Shared: "step"
            X-Step: "true"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    headers = config.scenarios[0].steps[0].request.headers

    assert headers == {
        "Authorization": "Bearer global-token",
        "X-Environment": "production",
        "X-Shared": "step",
        "X-Step": "true",
    }


def test_step_without_schema_continues(tmp_path: Path) -> None:
    """Verifies steps without schema skip schema compilation cleanly."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "No Schema Scenario"
    steps:
      - name: "Simple Step"
        request:
          method: "GET"
          path: "/status"
        expect:
          status: 200
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    assert config.scenarios[0].steps[0].expect._compiled_schema is None


# ============================================================================
# Schema Compilation & Resolution Edge Cases
# ============================================================================


def test_inline_schema_is_compiled(tmp_path: Path) -> None:
    """Verifies inline JSON schema compilation."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "Inline Schema Scenario"
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
        expect:
          status: 200
          schema:
            type: object
            required:
              - id
            properties:
              id:
                type: integer
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    schema_func = config.scenarios[0].steps[0].expect._compiled_schema

    assert schema_func is not None
    assert schema_func({"id": 123}) == {"id": 123}

    with pytest.raises(fastjsonschema.JsonSchemaValueException):
        schema_func({"id": "invalid"})


def test_external_schema_compiled_relative_to_yaml_dir(tmp_path: Path) -> None:
    """Verifies JSON schema files are resolved relative to the YAML directory."""
    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()

    schema_path = sub_dir / "user_schema.json"
    config_path = sub_dir / "config.yaml"

    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}},
            }
        ),
        encoding="utf-8",
    )

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "External Schema Scenario"
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
        expect:
          status: 200
          schema: "user_schema.json"
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    schema_func = config.scenarios[0].steps[0].expect._compiled_schema

    assert schema_func is not None
    assert schema_func({"id": 1}) == {"id": 1}


def test_external_schema_compiled_relative_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies fallback resolution of external schema relative to CWD."""
    yaml_dir = tmp_path / "yaml_dir"
    yaml_dir.mkdir()

    cwd_dir = tmp_path / "cwd_dir"
    cwd_dir.mkdir()

    monkeypatch.chdir(cwd_dir)

    schema_in_cwd = cwd_dir / "cwd_schema.json"
    schema_in_cwd.write_text(
        json.dumps({"type": "object", "required": ["ok"]}),
        encoding="utf-8",
    )

    config_path = yaml_dir / "config.yaml"
    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "CWD Schema Scenario"
    steps:
      - name: "Step 1"
        request:
          method: "GET"
          path: "/"
        expect:
          status: 200
          schema: "cwd_schema.json"
""",
        encoding="utf-8",
    )

    config = load_and_compile_config(config_path)

    schema_func = config.scenarios[0].steps[0].expect._compiled_schema

    assert schema_func is not None
    assert schema_func({"ok": True}) == {"ok": True}


def test_missing_external_schema_raises_error(tmp_path: Path) -> None:
    """Verifies missing external schema raises ConfigCompilerError."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "Missing Schema Scenario"
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
        expect:
          status: 200
          schema: "missing.json"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    assert "JSON Schema file not found" in str(exc_info.value)


def test_external_schema_invalid_json_raises_error(tmp_path: Path) -> None:
    """Verifies JSON decode errors on schema files raise ConfigCompilerError."""
    schema_path = tmp_path / "bad_schema.json"
    schema_path.write_text("{ invalid json structure", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "Bad JSON Schema Scenario"
    steps:
      - name: "Step 1"
        request:
          method: "GET"
          path: "/"
        expect:
          status: 200
          schema: "bad_schema.json"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    assert "Failed to read JSON schema file" in str(exc_info.value)


def test_invalid_json_schema_definition_raises_error(tmp_path: Path) -> None:
    """Verifies invalid schema definitions cause fastjsonschema compilation failure."""
    config_path = tmp_path / "config.yaml"

    config_path.write_text(
        """
version: "1.0"

global:
  base_url: "https://api.example.com"

scenarios:
  - name: "Invalid Schema Structure Scenario"
    steps:
      - name: "Step 1"
        request:
          method: "GET"
          path: "/"
        expect:
          status: 200
          schema:
            type: "non_existent_json_type"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(config_path)

    assert "Failed to compile JSON schema" in str(exc_info.value)


def _write(tmp_path: Path, text: str) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


_STEP = """
      - name: "Ping"
        request:
          method: "GET"
          path: "/"
        expect:
          status: 200
"""


def test_env_references_are_resolved_before_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARGET_URL", "https://env.example.com")
    monkeypatch.setenv("API_TOKEN", "s3cret")

    config = load_and_compile_config(
        _write(
            tmp_path,
            f"""
version: "1.0"
global:
  base_url: "${{env.TARGET_URL}}"
  headers:
    Authorization: "Bearer ${{env.API_TOKEN}}"
scenarios:
  - name: "Env Scenario"
    steps:{_STEP}
""",
        )
    )

    scenario = config.scenarios[0]

    assert str(scenario.base_url) == "https://env.example.com/"
    assert scenario.steps[0].request.headers["Authorization"] == "Bearer s3cret"


def test_runtime_variables_survive_env_resolution(tmp_path: Path) -> None:
    config = load_and_compile_config(
        _write(
            tmp_path,
            """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Chained"
    steps:
      - name: "Use token"
        request:
          method: "GET"
          path: "/users/${user_id}"
          headers:
            Authorization: "Bearer ${token}"
        expect:
          status: 200
""",
        )
    )

    request = config.scenarios[0].steps[0].request

    assert request.path == "/users/${user_id}"
    assert request.headers["Authorization"] == "Bearer ${token}"


def test_missing_env_variable_is_a_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(
            _write(
                tmp_path,
                f"""
version: "1.0"
global:
  base_url: "https://example.com"
  headers:
    X-Key: "${{env.DEFINITELY_NOT_SET}}"
scenarios:
  - name: "S"
    steps:{_STEP}
""",
            )
        )

    message = str(exc_info.value)

    assert "'DEFINITELY_NOT_SET' is not set" in message
    assert "global.headers.X-Key" in message


def test_validation_errors_do_not_echo_resolved_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEAKY", "super-secret-value")

    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(
            _write(
                tmp_path,
                f"""
version: "1.0"
global:
  base_url: "https://example.com"
  timeout_seconds: "${{env.LEAKY}}"
scenarios:
  - name: "S"
    steps:{_STEP}
""",
            )
        )

    message = str(exc_info.value)

    assert "super-secret-value" not in message
    assert "global.timeout_seconds" in message


def test_validation_error_lists_each_problem_with_its_location(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(_write(tmp_path, 'version: "2.0"\nscenarios: []\n'))

    message = str(exc_info.value)

    assert message.startswith("Config validation failed:")
    assert "  version: " in message


def test_root_level_validation_error_is_labelled(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProofrunConfig.model_validate("not a mapping")

    assert "<root>" in _format_validation_error(exc_info.value)


def test_duplicate_scenario_names_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigCompilerError, match="Duplicate scenario name 'Same'"):
        load_and_compile_config(
            _write(
                tmp_path,
                f"""
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Same"
    steps:{_STEP}
  - name: "Same"
    steps:{_STEP}
""",
            )
        )


def test_reserved_extract_names_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigCompilerError, match="reserved for environment"):
        load_and_compile_config(
            _write(
                tmp_path,
                """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "S"
    steps:
      - name: "Extract"
        request:
          method: "GET"
          path: "/"
        expect:
          status: 200
        extract:
          env.token: "$.token"
""",
            )
        )


def test_scenarios_inherit_global_reliability_settings(tmp_path: Path) -> None:
    config = load_and_compile_config(
        _write(
            tmp_path,
            f"""
version: "1.0"
global:
  base_url: "https://example.com"
  interval_seconds: 15
  retries: 2
  retry_delay_seconds: 0.5
  failure_threshold: 3
  recovery_threshold: 4
scenarios:
  - name: "Inherits"
    steps:{_STEP}
  - name: "Overrides"
    interval_seconds: 90
    retries: 0
    retry_delay_seconds: 7
    failure_threshold: 1
    recovery_threshold: 1
    steps:{_STEP}
""",
        )
    )

    inherits, overrides = config.scenarios

    assert (
        inherits.interval_seconds,
        inherits.retries,
        inherits.retry_delay_seconds,
        inherits.failure_threshold,
        inherits.recovery_threshold,
    ) == (15, 2, 0.5, 3, 4)
    assert (
        overrides.interval_seconds,
        overrides.retries,
        overrides.retry_delay_seconds,
        overrides.failure_threshold,
        overrides.recovery_threshold,
    ) == (90, 0, 7.0, 1, 1)


def test_reliability_defaults_preserve_previous_behavior(tmp_path: Path) -> None:
    config = load_and_compile_config(
        _write(
            tmp_path,
            f"""
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Defaults"
    steps:{_STEP}
""",
        )
    )

    scenario = config.scenarios[0]

    assert scenario.interval_seconds == 60
    assert scenario.retries == 0
    assert scenario.failure_threshold == 1
    assert scenario.recovery_threshold == 1


def test_empty_scenario_list_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(
        ConfigCompilerError, match="scenarios: List should have at least 1"
    ):
        load_and_compile_config(
            _write(tmp_path, 'version: "1.0"\nscenarios: []\n'),
        )


def test_scenario_without_steps_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(ConfigCompilerError, match="steps: List should have at least 1"):
        load_and_compile_config(
            _write(
                tmp_path,
                """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Nothing to do"
    steps: []
""",
            )
        )


def test_misspelled_field_reports_its_location(tmp_path: Path) -> None:
    with pytest.raises(ConfigCompilerError) as exc_info:
        load_and_compile_config(
            _write(
                tmp_path,
                f"""
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: "Typo"
    retriess: 3
    steps:{_STEP}
""",
            )
        )

    message = str(exc_info.value)

    assert "scenarios.0.retriess" in message
    assert "Extra inputs are not permitted" in message


def test_external_schema_must_be_object(tmp_path: Path) -> None:
    config_path = tmp_path / "proofrun.yaml"
    schema_path = tmp_path / "schema.json"

    schema_path.write_text("[]", encoding="utf-8")
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: test
    steps:
      - name: check
        request:
          method: GET
          path: /
        expect:
          status: 200
          schema: schema.json
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigCompilerError,
        match="JSON Schema must be an object",
    ):
        load_and_compile_config(config_path)


def test_rejects_unexpected_schema_data_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "proofrun.yaml"
    config_path.write_text(
        """
version: "1.0"
global:
  base_url: "https://example.com"
scenarios:
  - name: test
    steps:
      - name: check
        request:
          method: GET
          path: /
        expect:
          status: 200
          schema:
            type: object
""",
        encoding="utf-8",
    )

    original_validate = ProofrunConfig.model_validate

    def validate_then_corrupt_schema(
        cls: type[ProofrunConfig],
        data: Any,
    ) -> ProofrunConfig:
        config = original_validate(data)

        # Deliberately simulate an invalid internal state for defensive coverage.
        expect: Any = config.scenarios[0].steps[0].expect
        expect.schema_data = []

        return config

    monkeypatch.setattr(
        ProofrunConfig,
        "model_validate",
        classmethod(validate_then_corrupt_schema),
    )

    with pytest.raises(
        ConfigCompilerError,
        match="JSON Schema must be an object",
    ):
        load_and_compile_config(config_path)
