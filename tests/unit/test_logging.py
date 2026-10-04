from asgi_correlation_id import correlation_id
from fastapi.testclient import TestClient

from src.infrastructure.configs.logging_processors import (
    inject_correlation_id,
    redact_sensitive_data,
)
from src.infrastructure.configs.logging_setup import configure_logging
from src.main import app


def test_inject_correlation_id_fallback():
    """Verify inject_correlation_id falls back to 'system' when no context exists."""
    token = correlation_id.set(None)
    try:
        event_dict = {"event": "test"}
        result = inject_correlation_id(None, "info", event_dict)
        assert result["request_id"] == "system"
    finally:
        correlation_id.reset(token)


def test_inject_correlation_id_present():
    """Verify inject_correlation_id extracts active correlation ID."""
    token = correlation_id.set("req-custom-uuid-1234")
    try:
        event_dict = {"event": "test"}
        result = inject_correlation_id(None, "info", event_dict)
        assert result["request_id"] == "req-custom-uuid-1234"
    finally:
        correlation_id.reset(token)


def test_redact_sensitive_data_shallow():
    """Verify top-level sensitive keys are masked."""
    event = {
        "event": "Login attempt",
        "username": "admin",
        "password": "secret_password",
        "api_key": "live_key_999",
    }
    sanitized = redact_sensitive_data(None, "info", event)
    assert sanitized["username"] == "admin"
    assert sanitized["password"] == "***REDACTED***"
    assert sanitized["api_key"] == "***REDACTED***"


def test_redact_sensitive_data_nested_and_bearer():
    """Verify nested objects and Authorization Bearer patterns are sanitized."""
    event = {
        "event": "API call",
        "payload": {
            "user": {
                "token": "sensitive_jwt_token",
                "email": "user@test.local",
            },
            "credentials": ["secret1", "secret2"],
        },
        "headers": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    }
    sanitized = redact_sensitive_data(None, "info", event)
    assert sanitized["payload"]["user"]["token"] == "***REDACTED***"
    assert sanitized["payload"]["user"]["email"] == "user@test.local"
    assert "***REDACTED***" in sanitized["headers"]
    assert "eyJhbGci" not in sanitized["headers"]


def test_configure_logging_idempotent():
    """Verify configure_logging runs cleanly without errors."""
    configure_logging()


def test_fastapi_health_endpoint():
    """Verify health endpoint responds 200 OK and generates correlation ID."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "tavanir-ai-assistant-v2"


def test_logging_handles_persian_alphabet_characters_without_encode_error():
    """Verify logging Persian alphabet characters (like 'ب') does not raise UnicodeEncodeError."""
    configure_logging()
    import structlog

    log = structlog.get_logger("test_persian_logger")
    log.warning(
        "skipping_invalid_suggestion",
        reason="Suggestion title must contain substantive content, got 'ب'.",
        suggestion_id="2181//95",
    )


def test_logging_handles_zwnj_characters_without_encode_error():
    """Verify logging Zero-Width Non-Joiner (ZWNJ / نیم‌فاصله) does not raise UnicodeEncodeError."""
    configure_logging()
    import structlog

    log = structlog.get_logger("test_persian_logger")
    log.info(
        "persian_zwnj_log",
        title="پیشنهاد‌های سازمانی و بهره‌وری شبکه",
    )


def test_logging_handles_persian_numerals_without_encode_error():
    """Verify logging Persian numerals does not raise UnicodeEncodeError."""
    configure_logging()
    import structlog

    log = structlog.get_logger("test_persian_logger")
    log.info(
        "persian_numerals_log",
        count="۱۲۳۴۵",
    )


def test_logging_exception_traceback_with_persian_message_no_encode_error():
    """Verify logging exception tracebacks with Persian descriptions does not raise UnicodeEncodeError."""
    configure_logging()
    import structlog

    log = structlog.get_logger("test_persian_logger")
    try:
        raise ValueError("خطای آزمایشی در پردازش پیشنهاد")
    except Exception as exc:
        log.exception("caught_persian_exception", error=str(exc))
