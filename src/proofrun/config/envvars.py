"""Environment-variable references in configuration files.

``${env.NAME}`` is resolved once, when a configuration file is loaded and
before it is validated, so it works in every field, including ``base_url``.
It is a different namespace from run-time variables such as ``${token}``,
which are resolved per request by the execution context.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

ENV_PATTERN = re.compile(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}")


class EnvVarError(Exception):
    """Raised when a referenced environment variable is not set."""


def resolve_env_references(
    data: Any,
    environ: Mapping[str, str],
    _location: str = "",
    *,
    secret_values: set[str] | None = None,
) -> Any:
    """Resolve environment references and optionally collect their values.

    Dictionary keys and string values are resolved; other types pass through.
    The result is always a string for a string input, even when the whole
    value is a single reference, because environment values are text.

    When ``secret_values`` is provided, every resolved environment value is
    added to that set so downstream diagnostics can redact known values.

    Args:
        data: A parsed YAML structure (dicts, lists, and scalars).
        environ: The environment to read, normally ``os.environ``.
        secret_values: Optional set in which to collect resolved values.

    Raises:
        EnvVarError: If a referenced variable is not set. The message names
            the variable and where it was referenced, never its value.
    """
    if isinstance(data, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)

            if name not in environ:
                where = f" (referenced at {_location})" if _location else ""
                raise EnvVarError(f"Environment variable '{name}' is not set{where}")

            value = environ[name]

            if secret_values is not None:
                secret_values.add(value)

            return value

        return ENV_PATTERN.sub(replace, data)

    if isinstance(data, dict):
        resolved: dict[Any, Any] = {}

        for key, value in data.items():
            key_location = f"{_location}.{key}" if _location else str(key)

            new_key = (
                resolve_env_references(
                    key,
                    environ,
                    key_location,
                    secret_values=secret_values,
                )
                if isinstance(key, str)
                else key
            )

            resolved[new_key] = resolve_env_references(
                value,
                environ,
                key_location,
                secret_values=secret_values,
            )

        return resolved

    if isinstance(data, list):
        return [
            resolve_env_references(
                item,
                environ,
                f"{_location}[{index}]",
                secret_values=secret_values,
            )
            for index, item in enumerate(data)
        ]

    return data
