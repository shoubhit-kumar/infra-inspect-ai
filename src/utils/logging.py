"""Structured logging with rich console output.

The `_add_request_id` processor pulls the active correlation ID and injects
it into every structlog line, so every log emitted during a request is
automatically tagged with the request_id - no per-call-site change.
"""
import logging

import structlog
from rich.console import Console
from rich.logging import RichHandler

from src.config.settings import get_settings

_console = Console(stderr=True)


def _add_request_id(logger, method_name, event_dict):
    """Structlog processor: inject the active request_id into every log line.

    Pulls from src.api.request_context.get_request_id(). Empty string means
    no request is in flight (e.g., during boot or background script runs),
    in which case we skip the field to keep logs clean.

    Imported lazily to avoid a circular import - configure_logging() runs
    very early in app startup, before all modules are necessarily safe to import.
    """
    try:
        from src.api.request_context import get_request_id
        rid = get_request_id()
        if rid:
            event_dict["request_id"] = rid
    except ImportError:
        pass
    return event_dict


def configure_logging() -> None:
    """Configure structlog + rich. Call once at app startup."""
    settings = get_settings()
    level = getattr(logging, settings.log_level)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, rich_tracebacks=True, show_path=False)],
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger. Use module's `__name__`."""
    return structlog.get_logger(name)