"""Redact known environment-provided values from diagnostic messages."""

import re
from collections.abc import Iterable

_REDACTION_MARKER = "[REDACTED]"


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
