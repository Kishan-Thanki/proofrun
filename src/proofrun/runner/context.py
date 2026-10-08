"""Execution context and dynamic variable interpolation module for Proofrun.

This module manages runtime state persistence across scenario steps, JSONPath
variable extraction from API responses, nested payload interpolation, and
built-in dynamic generators.
"""

import random
import re
import time
import uuid
from typing import Any

from jsonpath_ng import parse


class ContextError(Exception):
    """Raised when variable extraction or interpolation fails."""


class ExecutionContext:
    """Manages runtime state and dynamic variable interpolation."""

    VAR_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_.$]+)\}")

    def __init__(
        self,
        initial_vars: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the execution context.

        Args:
            initial_vars: Optional initial variables. The dictionary is copied.
        """
        self.variables: dict[str, Any] = (
            dict(initial_vars) if initial_vars is not None else {}
        )

    def set(self, key: str, value: Any) -> None:
        """Set a runtime variable."""
        self.variables[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a runtime variable."""
        return self.variables.get(key, default)

    def _get_dynamic_variable(self, var_name: str) -> Any | None:
        """Resolve a built-in dynamic variable.

        Note: These generate a new value every time they are called. Multiple
        references to ${$uuid} in a single payload will yield different UUIDs.
        """
        if var_name == "$uuid":
            return str(uuid.uuid4())

        if var_name == "$timestamp":
            return int(time.time())

        if var_name == "$timestamp_ms":
            return int(time.time() * 1000)

        if var_name == "$iso_timestamp":
            return time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(),
            )

        if var_name == "$random_int":
            return random.randint(1000, 9999)

        return None

    def extract_variables(
        self,
        payload: dict[str, Any] | list[Any],
        rules: dict[str, str],
    ) -> None:
        """Extract variables from a JSON payload using JSONPath.

        Args:
            payload: JSON response body.
            rules: Mapping of variable names to JSONPath expressions.

        Raises:
            ContextError: If a JSONPath expression is invalid or produces
                no matches.
        """
        for var_name, jsonpath_expr in rules.items():
            try:
                expression = parse(jsonpath_expr)
                matches = [match.value for match in expression.find(payload)]
            except Exception as err:
                raise ContextError(
                    f"Invalid JSONPath expression "
                    f"'{jsonpath_expr}' for variable "
                    f"'{var_name}': {err}"
                ) from err

            if not matches:
                raise ContextError(
                    f"JSONPath extraction failed: Path "
                    f"'{jsonpath_expr}' did not match any value "
                    "in response."
                )

            self.variables[var_name] = matches[0]

    def interpolate_string(self, text: str) -> Any:
        """Interpolate variables inside a string.

        An exact variable reference preserves its original type.

        For example:

            "${user_id}"

        can return:

            123

        while:

            "User ${user_id}"

        returns:

            "User 123"
        """
        exact_match = self.VAR_PATTERN.fullmatch(text.strip())

        if exact_match:
            var_name = exact_match.group(1)

            if var_name.startswith("$"):
                dynamic_value = self._get_dynamic_variable(var_name)

                if dynamic_value is not None:
                    return dynamic_value

            if var_name not in self.variables:
                raise ContextError(
                    f"Missing required context variable: '${{{var_name}}}'"
                )

            return self.variables[var_name]

        def replace_var(match: re.Match[str]) -> str:
            var_name = match.group(1)

            if var_name.startswith("$"):
                dynamic_value = self._get_dynamic_variable(var_name)

                if dynamic_value is not None:
                    return str(dynamic_value)

            if var_name not in self.variables:
                raise ContextError(
                    f"Missing required context variable: '${{{var_name}}}'"
                )

            return str(self.variables[var_name])

        return self.VAR_PATTERN.sub(replace_var, text)

    def interpolate_data(self, data: Any) -> Any:
        """Recursively interpolate strings inside nested request data.

        This will interpolate strings found in dictionary values,
        dictionary keys, and list items.
        """
        if isinstance(data, str):
            return self.interpolate_string(data)

        if isinstance(data, dict):
            return {
                (
                    self.interpolate_string(key) if isinstance(key, str) else key
                ): self.interpolate_data(value)
                for key, value in data.items()
            }

        if isinstance(data, list):
            return [self.interpolate_data(item) for item in data]

        return data
