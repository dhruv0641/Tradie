"""Structured JSON logging subsystem based on structlog."""

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import cast

import structlog
from structlog.types import EventDict, WrappedLogger
from structlog.typing import FilteringBoundLogger

# Context variable for tracking correlation IDs across async and sync call hierarchies
_CORRELATION_ID_CTX: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def bind_correlation_id(correlation_id: str | None = None) -> str:
    """Bind a correlation ID to the current context.

    If not provided, a random UUIDv4 string is generated.
    """
    cid = correlation_id or str(uuid.uuid4())
    _CORRELATION_ID_CTX.set(cid)
    return cid


def get_correlation_id() -> str | None:
    """Retrieve current correlation ID from context."""
    return _CORRELATION_ID_CTX.get()


def clear_correlation_id() -> None:
    """Clear correlation ID from current context."""
    _CORRELATION_ID_CTX.set(None)


def add_correlation_id(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Structlog processor to inject correlation_id into the event dictionary."""
    cid = get_correlation_id()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(
    environment: str = "test",
    log_level: str = "INFO",
) -> None:
    """Configure structlog and standard library logging for the application.

    In 'local' or 'dev' environments, logs are formatted with console colors.
    In 'test', 'research', 'paper', and 'live' environments, logs are emitted
    as single-line machine-parseable JSON records.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if environment.lower() in ("local", "dev"):
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a configured structlog bound logger."""
    return cast("FilteringBoundLogger", structlog.get_logger(name))
