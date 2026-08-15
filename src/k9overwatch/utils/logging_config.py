"""Structured logging configuration for K9-Overwatch using structlog."""
from __future__ import annotations

import logging
import sys

import structlog

_CONFIGURED = False


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_format: bool = False,
) -> None:
    """
    Configure root logger via structlog. Safe to call multiple times — only applies once.

    Args:
        level:       Log level string (DEBUG, INFO, WARNING, ERROR).
        log_file:    Optional path to write logs to (in addition to stderr).
        json_format: Emit JSON-structured lines instead of human-readable text.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processor chain for both structlog-native and stdlib log records
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_format:
        # Production: machine-readable JSON on each line
        stdlib_formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=shared_processors,
        )
        structlog.configure(
            processors=shared_processors + [
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        # Development: colourful, human-readable console output
        stdlib_formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer(),
            ],
            foreign_pre_chain=shared_processors,
        )
        structlog.configure(
            processors=shared_processors + [
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    root = logging.getLogger()
    root.setLevel(log_level)

    # stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(stdlib_formatter)
    root.addHandler(stderr_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(stdlib_formatter)
        root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call configure_logging() first."""
    return logging.getLogger(name)
