"""Redact known environment-provided values from diagnostic messages."""

import re
from collections.abc import Iterable

_REDACTION_MARKER = "[REDACTED]"


def collect_scalar_strings(data: object) -> set[str]:
    """Recursively extract all non-empty string representations of scalars from data."""
    scalars: set[str] = set()

    def _walk(obj: object) -> None:
        if isinstance(obj, str):
            scalars.add(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                _walk(value)
        elif isinstance(obj, list | tuple | set | frozenset):
            for item in obj:
                _walk(item)

    _walk(data)
    return {s for s in scalars if s}


def redact_secrets(message: str, secret_values: Iterable[str]) -> str:
    """Replace known non-empty secret values in a message.

    Longer values are matched first to handle overlapping secrets safely.
    """
    values = sorted(
        {value for value in secret_values if value},
        key=len,
        reverse=True,
    )

    if not values:
        return message

    pattern = re.compile("|".join(re.escape(value) for value in values))
    return pattern.sub(_REDACTION_MARKER, message)
