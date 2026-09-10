import re
from typing import Any

import structlog
from asgi_correlation_id import correlation_id

BEARER_PATTERN = re.compile(r"Bearer\s+([A-Za-z0-9\-._~+/]+=*)", re.IGNORECASE)
SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "token",
    "secret",
    "api_key",
    "auth",
    "credential",
    "private_key",
)
REDACTED_VALUE = "***REDACTED***"


def _sanitize_value(value: Any) -> Any:
    """Recursively redacts sensitive values in dicts, lists, and strings."""
    if isinstance(value, dict):
        sanitized = {}
        for k, v in value.items():
            if any(sub in str(k).lower() for sub in SENSITIVE_KEY_SUBSTRINGS):
                sanitized[k] = REDACTED_VALUE
            else:
                sanitized[k] = _sanitize_value(v)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]

    if isinstance(value, str):
        # Mask Bearer tokens in headers or strings
        return BEARER_PATTERN.sub(r"Bearer " + REDACTED_VALUE, value)

    return value


def inject_correlation_id(
    logger: Any, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """
    Injects the ASGI correlation ID into the log record.
    Falls back to 'system' if no request ID is set in context.
    """
    event_dict["request_id"] = correlation_id.get() or "system"
    return event_dict


def redact_sensitive_data(
    logger: Any, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """
    Recursively scans and redacts sensitive data (passwords, tokens, auth headers)
    from event dictionary.
    """
    for key in list(event_dict.keys()):
        val = event_dict[key]
        if any(sub in str(key).lower() for sub in SENSITIVE_KEY_SUBSTRINGS):
            event_dict[key] = REDACTED_VALUE
        else:
            event_dict[key] = _sanitize_value(val)

    return event_dict
