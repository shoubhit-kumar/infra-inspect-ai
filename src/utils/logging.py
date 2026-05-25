"""Structured logging with rich console output."""
import logging
import sys

import structlog
from rich.console import Console
from rich.logging import RichHandler

from src.config.settings import get_settings

_console = Console(stderr=True)


def configure_logging() -> None:
    """Configure structlog + rich. Call once at app startup."""
    settings = get_settings()
    level = getattr(logging, settings.log_level)

    # stdlib logging → routes through Rich for pretty output
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, rich_tracebacks=True, show_path=False)],
    )

    # structlog → structured JSON-able logs
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
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