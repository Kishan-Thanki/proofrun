# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Verification suite for ExecutionContext."""

from __future__ import annotations

import re
import time
import uuid

import pytest

from proofrun.runner.context import ContextError, ExecutionContext


def test_initial_vars_get_and_set() -> None:
    """Verifies getter, setter, defaults, and initial variables."""
    ctx = ExecutionContext(
        initial_vars={"env": "production"},
    )

    assert ctx.get("env") == "production"
    assert ctx.get("non_existent", "default_val") == "default_val"

    ctx.set("auth_type", "Bearer")

    assert ctx.get("auth_type") == "Bearer"


def test_initial_vars_are_copied() -> None:
    """Verifies context mutations don't modify caller dictionary."""
    initial_vars = {"env": "production"}

    ctx = ExecutionContext(initial_vars=initial_vars)
    ctx.set("token", "abc123")

    assert initial_vars == {"env": "production"}
    assert ctx.get("token") == "abc123"


def test_extraction_and_interpolation() -> None:
    """Verifies JSONPath extraction and variable interpolation."""
    ctx = ExecutionContext()

    mock_api_response = {
        "status": "success",
        "data": {
            "user_id": 101,
            "profile": {
                "email": "janedoe@example.com",
            },
        },
        "token": "bearer_token_xyz123",
    }

    extraction_rules = {
        "user_id": "$.data.user_id",
        "user_email": "$.data.profile.email",
        "auth_token": "$.token",
    }

    ctx.extract_variables(
        mock_api_response,
        extraction_rules,
    )

    assert ctx.get("user_id") == 101
    assert ctx.get("user_email") == "janedoe@example.com"
    assert ctx.get("auth_token") == "bearer_token_xyz123"

    raw_user_id = ctx.interpolate_data("${user_id}")

    assert raw_user_id == 101
    assert isinstance(raw_user_id, int)

    interpolated_path = ctx.interpolate_string("/v1/users/${user_id}/profile")

    assert interpolated_path == "/v1/users/101/profile"

    request_payload = {
        "headers": {
            "Authorization": "Bearer ${auth_token}",
        },
        "json": {
            "account_id": "${user_id}",
            "contact_email": "${user_email}",
        },
    }

    processed_payload = ctx.interpolate_data(request_payload)

    assert processed_payload["headers"]["Authorization"] == (
        "Bearer bearer_token_xyz123"
    )
    assert processed_payload["json"]["account_id"] == 101
    assert processed_payload["json"]["contact_email"] == "janedoe@example.com"


def test_dynamic_variables() -> None:
    """Verifies all supported built-in dynamic variables."""
    ctx = ExecutionContext()

    generated_uuid = ctx.interpolate_string("${$uuid}")
    val_uuid = uuid.UUID(generated_uuid)

    assert str(val_uuid) == generated_uuid

    generated_ts = ctx.interpolate_string("${$timestamp}")

    assert isinstance(generated_ts, int)
    assert abs(generated_ts - int(time.time())) <= 2

    generated_ts_ms = ctx.interpolate_string("${$timestamp_ms}")

    assert isinstance(generated_ts_ms, int)
    assert abs(generated_ts_ms - int(time.time() * 1000)) <= 2000

    generated_iso = ctx.interpolate_string("${$iso_timestamp}")

    assert isinstance(generated_iso, str)
    assert (
        re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            generated_iso,
        )
        is not None
    )

    generated_rand = ctx.interpolate_string("${$random_int}")

    assert isinstance(generated_rand, int)
    assert 1000 <= generated_rand <= 9999

    email_string = ctx.interpolate_string("user_${$random_int}@test.com")

    assert email_string.startswith("user_")
    assert email_string.endswith("@test.com")


def test_recursive_list_interpolation() -> None:
    """Verifies recursive list traversal and type preservation."""
    ctx = ExecutionContext(
        {
            "tag": "v1.0",
            "limit": 50,
        }
    )

    raw_list = [
        "/api/${tag}/items",
        "${limit}",
        True,
        100,
    ]

    processed_list = ctx.interpolate_data(raw_list)

    assert processed_list == [
        "/api/v1.0/items",
        50,
        True,
        100,
    ]
    assert isinstance(processed_list[1], int)


def test_non_string_values_are_unchanged() -> None:
    """Verifies primitive non-string values remain unchanged."""
    ctx = ExecutionContext({"value": "replacement"})

    data = {
        "boolean": True,
        "integer": 42,
        "float": 3.14,
        "none": None,
    }

    assert ctx.interpolate_data(data) == data


def test_list_and_nested_dictionary_interpolation() -> None:
    """Verifies deeply nested structures are interpolated."""
    ctx = ExecutionContext(
        {
            "user_id": 123,
            "token": "abc",
        }
    )

    data = {
        "outer": {
            "items": [
                "${user_id}",
                {
                    "Authorization": "Bearer ${token}",
                },
            ],
        },
    }

    result = ctx.interpolate_data(data)

    assert result["outer"]["items"][0] == 123
    assert result["outer"]["items"][1]["Authorization"] == "Bearer abc"


def test_error_handling() -> None:
    """Verifies missing variables and failed JSONPath queries."""
    ctx = ExecutionContext()

    with pytest.raises(
        ContextError,
        match="Missing required context variable",
    ):
        ctx.interpolate_string("/api/v1/resource/${missing_var}")

    with pytest.raises(
        ContextError,
        match="Missing required context variable",
    ):
        ctx.interpolate_string("${missing_var}")

    with pytest.raises(
        ContextError,
        match=re.escape(
            "JSONPath extraction failed: Path '$.data.missing_key' "
            "did not match any value in response."
        ),
    ):
        ctx.extract_variables(
            {"status": "ok"},
            {"nonexistent": "$.data.missing_key"},
        )

    with pytest.raises(
        ContextError,
        match="Invalid JSONPath expression",
    ):
        ctx.extract_variables(
            {"status": "ok"},
            {"bad_syntax": "$[invalid_jsonpath"},
        )


def test_unknown_dynamic_variable_raises_error() -> None:
    """Verifies unknown built-in dynamic variables raise missing error."""
    ctx = ExecutionContext()

    with pytest.raises(
        ContextError,
        match="Missing required context variable",
    ):
        ctx.interpolate_string("${$unknown_generator}")


def test_unknown_dynamic_variable_in_string_raises_error() -> None:
    """Verifies unknown dynamic variables inside composite strings raise errors."""
    ctx = ExecutionContext()

    with pytest.raises(
        ContextError,
        match="Missing required context variable",
    ):
        ctx.interpolate_string("prefix_${$invalid}_suffix")


def test_interpolated_keys_that_collide_are_an_error() -> None:
    context = ExecutionContext()
    context.variables.update({"a": "resolved-xyz", "b": "resolved-xyz"})

    with pytest.raises(ContextError) as exc_info:
        context.interpolate_data({"${a}": 1, "${b}": 2})

    message = str(exc_info.value)

    assert "'${a}'" in message
    assert "'${b}'" in message
    assert "resolved-xyz" not in message


def test_interpolated_keys_that_stay_unique_are_kept() -> None:
    context = ExecutionContext()
    context.variables.update({"a": "first", "b": "second"})

    assert context.interpolate_data({"${a}": 1, "${b}": 2, "plain": 3}) == {
        "first": 1,
        "second": 2,
        "plain": 3,
    }


def test_a_literal_key_that_collides_with_an_interpolated_one_is_an_error() -> None:
    context = ExecutionContext()
    context.variables["a"] = "plain"

    with pytest.raises(ContextError, match="interpolate to the same name"):
        context.interpolate_data({"plain": 1, "${a}": 2})
