# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Unit tests for environment-variable references in configuration."""

from __future__ import annotations

import pytest

from proofrun.config.envvars import EnvVarError, resolve_env_references


def test_resolves_references_in_strings() -> None:
    environ = {"HOST": "api.example.com", "TOKEN": "s3cret"}

    assert resolve_env_references("https://${env.HOST}/v1", environ) == (
        "https://api.example.com/v1"
    )
    assert resolve_env_references("Bearer ${env.TOKEN}", environ) == "Bearer s3cret"


def test_resolves_nested_structures_and_keys() -> None:
    environ = {"A": "1", "B": "two"}
    data = {
        "x": ["${env.A}", {"k-${env.B}": "v-${env.A}"}],
        "y": {"z": "${env.B}"},
    }

    assert resolve_env_references(data, environ) == {
        "x": ["1", {"k-two": "v-1"}],
        "y": {"z": "two"},
    }


def test_whole_value_reference_stays_a_string() -> None:
    assert resolve_env_references("${env.PORT}", {"PORT": "8080"}) == "8080"


def test_non_string_values_pass_through() -> None:
    data = {"a": 1, "b": 2.5, "c": True, "d": None, 5: "x"}

    assert resolve_env_references(data, {}) == data


def test_empty_value_is_a_value() -> None:
    assert resolve_env_references("a${env.EMPTY}b", {"EMPTY": ""}) == "ab"


def test_runtime_variables_are_left_alone() -> None:
    text = "Bearer ${token} ${$uuid} ${environment} ${env} ${env.}"

    assert resolve_env_references(text, {"token": "x"}) == text


def test_missing_variable_names_it_and_its_location() -> None:
    data = {"scenarios": [{"steps": [{"headers": {"Authorization": "${env.NOPE}"}}]}]}

    with pytest.raises(EnvVarError) as exc_info:
        resolve_env_references(data, {"OTHER": "hidden-value"})

    message = str(exc_info.value)

    assert "'NOPE' is not set" in message
    assert "scenarios[0].steps[0].headers.Authorization" in message
    assert "hidden-value" not in message


def test_missing_variable_at_top_level_has_no_location() -> None:
    with pytest.raises(EnvVarError) as exc_info:
        resolve_env_references("${env.NOPE}", {})

    assert str(exc_info.value) == "Environment variable 'NOPE' is not set"
