import io
import logging
import sys

import structlog

from src.infrastructure.configs.logging_processors import (
    inject_correlation_id,
    redact_sensitive_data,
)
from src.infrastructure.configs.settings import logging_settings


def configure_logging() -> None:
    """
    Initializes structured enterprise logging for Tavanir AI Assistant V2.
    Routes all application and 3rd-party logs cleanly to sys.stdout without
    in-process database or file blocking, allowing Vector to stream them to OpenObserve.
    """
    # 1. Shared Structlog Processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
        structlog.processors.UnicodeDecoder(),
        inject_correlation_id,
        redact_sensitive_data,
    ]

    # 2. Configure Structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
        ]
        + shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 3. Determine Console vs JSON Renderer
    is_json = (
        logging_settings.LOG_FORMAT.strip().lower() == "json"
        or logging_settings.ENVIRONMENT.strip().lower() == "production"
    )

    if is_json:
        # Machine-readable single-line JSON with full tracebacks for Docker/Vector/OpenObserve
        renderer_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    else:
        # Colorized human-readable output for local terminal development
        renderer_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    stdout_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=renderer_processors,
    )

    # 3.5 Reconfigure standard streams for UTF-8 resilience (Windows fix)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:
                pass

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(stdout_formatter)

    # 4. Configure Root Logger
    resolved_level = getattr(
        logging, logging_settings.LOG_LEVEL.strip().upper(), logging.INFO
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    root_logger.handlers = [stdout_handler]

    # 5. Tune 3rd-party library log levels
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("qdrant_client").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    structlog.get_logger(__name__).info(
        "Tavanir logging initialized",
        log_format="json" if is_json else "console",
        level=logging_settings.LOG_LEVEL,
        environment=logging_settings.ENVIRONMENT,
    )
