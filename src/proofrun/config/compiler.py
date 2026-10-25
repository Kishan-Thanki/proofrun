"""AOT Schema Compiler for Proofrun scenario configurations.

This module loads YAML configuration, resolves ``${env.NAME}`` references,
validates it using Pydantic, applies global defaults, and pre-compiles JSON
schemas into executable validators.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import fastjsonschema
import yaml
from pydantic import ValidationError

from proofrun.config.envvars import EnvVarError, resolve_env_references
from proofrun.config.models import GlobalConfig, ProofrunConfig
from proofrun.redaction import redact_secrets

_INHERITED_SCENARIO_FIELDS = (
    "interval_seconds",
    "retries",
    "retry_delay_seconds",
    "failure_threshold",
    "recovery_threshold",
)


class ConfigCompilerError(Exception):
    """Raised when a Proofrun configuration cannot be loaded, validated, or compiled."""


def _format_validation_error(
    err: ValidationError,
    secret_values: set[str] | frozenset[str] = frozenset(),
) -> str:
    """Describe validation problems without echoing the offending input.

    Environment references are resolved before validation, so the input of a
    failing field could be a secret. Only the location and the message are shown.
    """
    lines = [
        f"  {'.'.join(str(part) for part in problem['loc']) or '<root>'}: "
        f"{problem['msg']}"
        for problem in err.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    ]

    message = "Config validation failed:\n" + "\n".join(lines)
    return redact_secrets(message, secret_values)


def load_and_compile_config(config_path: str | Path) -> ProofrunConfig:
    """Load, validate, resolve, and compile a Proofrun configuration.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        A validated and executable ProofrunConfig.

    Raises:
        ConfigCompilerError: If loading, validation, inheritance, or schema
            compilation fails.
    """
    path = Path(config_path).resolve()

    if not path.exists():
        raise ConfigCompilerError(f"Configuration file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            raw_data = yaml.safe_load(file)
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        location = (
            f" at line {mark.line + 1}, column {mark.column + 1}"
            if mark is not None
            else ""
        )
        raise ConfigCompilerError(f"Invalid YAML syntax in {path}{location}.") from None
    except OSError as err:
        reason = err.strerror or "I/O error"
        raise ConfigCompilerError(
            f"Failed to read configuration file {path}: {reason}."
        ) from None

    if not isinstance(raw_data, dict):
        raise ConfigCompilerError(
            f"Invalid format in {path}. Expected a top-level YAML mapping."
        )

    secret_values: set[str] = set()

    try:
        raw_data = resolve_env_references(
            raw_data,
            os.environ,
            secret_values=secret_values,
        )
    except EnvVarError as err:
        raise ConfigCompilerError(f"Invalid configuration in {path}: {err}") from err

    validation_message: str | None = None

    try:
        config = ProofrunConfig.model_validate(raw_data)
    except ValidationError as err:
        validation_message = _format_validation_error(err, secret_values)

    if validation_message is not None:
        raise ConfigCompilerError(validation_message)

    seen_names: set[str] = set()

    for scenario in config.scenarios:
        scenario._secret_values = frozenset(secret_values)

        if scenario.name in seen_names:
            safe_name = redact_secrets(scenario.name, secret_values)
            raise ConfigCompilerError(
                f"Duplicate scenario name '{safe_name}'. Scenario names must be unique."
            )

        seen_names.add(scenario.name)

    global_config = config.global_config or GlobalConfig()

    global_base_url = global_config.base_url
    global_timeout = global_config.timeout_seconds
    global_headers = global_config.headers

    for scenario in config.scenarios:
        for field_name in _INHERITED_SCENARIO_FIELDS:
            if field_name not in scenario.model_fields_set:
                setattr(scenario, field_name, getattr(global_config, field_name))

        if scenario.base_url is None:
            if global_base_url is None:
                safe_name = redact_secrets(scenario.name, secret_values)
                raise ConfigCompilerError(
                    f"Scenario '{safe_name}' is missing 'base_url' "
                    "and no global 'base_url' is defined."
                )

            scenario.base_url = global_base_url

        for step in scenario.steps:
            for variable_name in step.extract:
                if variable_name.startswith("env."):
                    safe_variable_name = redact_secrets(
                        variable_name,
                        secret_values,
                    )
                    safe_scenario_name = redact_secrets(
                        scenario.name,
                        secret_values,
                    )
                    safe_step_name = redact_secrets(
                        step.name,
                        secret_values,
                    )

                    raise ConfigCompilerError(
                        f"Invalid extract variable '{safe_variable_name}' "
                        f"in scenario '{safe_scenario_name}', "
                        f"step '{safe_step_name}': names starting "
                        "with 'env.' are reserved for environment references."
                    )

            if step.request.timeout is None:
                step.request.timeout = global_timeout

            step.request.headers = {
                **global_headers,
                **step.request.headers,
            }

            if step.expect.schema_data is None:
                continue

            raw_schema: dict[str, Any] | None = None

            if isinstance(step.expect.schema_data, dict):
                raw_schema = step.expect.schema_data

            elif isinstance(step.expect.schema_data, str):
                schema_file = path.parent / step.expect.schema_data

                if not schema_file.exists():
                    schema_file = Path(step.expect.schema_data)

                if not schema_file.exists():
                    safe_schema_path = redact_secrets(
                        step.expect.schema_data,
                        secret_values,
                    )
                    safe_scenario_name = redact_secrets(scenario.name, secret_values)
                    safe_step_name = redact_secrets(step.name, secret_values)

                    raise ConfigCompilerError(
                        f"JSON Schema file not found: "
                        f"'{safe_schema_path}' "
                        f"(referenced in scenario '{safe_scenario_name}', "
                        f"step '{safe_step_name}')"
                    )

                try:
                    with schema_file.open("r", encoding="utf-8") as file:
                        raw_schema = json.load(file)
                except (OSError, json.JSONDecodeError) as err:
                    safe_schema_path = redact_secrets(
                        step.expect.schema_data,
                        secret_values,
                    )
                    safe_scenario_name = redact_secrets(
                        scenario.name,
                        secret_values,
                    )
                    safe_step_name = redact_secrets(
                        step.name,
                        secret_values,
                    )

                    raise ConfigCompilerError(
                        f"Failed to read JSON schema file "
                        f"'{safe_schema_path}' "
                        f"(scenario '{safe_scenario_name}', "
                        f"step '{safe_step_name}'): "
                        f"{type(err).__name__}."
                    ) from None

            if not isinstance(raw_schema, dict):
                safe_scenario_name = redact_secrets(
                    scenario.name,
                    secret_values,
                )
                safe_step_name = redact_secrets(
                    step.name,
                    secret_values,
                )

                raise ConfigCompilerError(
                    f"JSON Schema must be an object in scenario "
                    f"'{safe_scenario_name}', step '{safe_step_name}'."
                )

            try:
                compiled = fastjsonschema.compile(raw_schema)
                step.expect._compiled_schema = cast(
                    Callable[[Any], Any],
                    compiled,
                )
            except Exception as err:
                safe_scenario_name = redact_secrets(
                    scenario.name,
                    secret_values,
                )
                safe_step_name = redact_secrets(
                    step.name,
                    secret_values,
                )

                raise ConfigCompilerError(
                    f"Failed to compile JSON schema in "
                    f"scenario '{safe_scenario_name}', "
                    f"step '{safe_step_name}': "
                    f"{type(err).__name__}."
                ) from None

    return config
