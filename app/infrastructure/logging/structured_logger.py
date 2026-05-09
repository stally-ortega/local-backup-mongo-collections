"""Structured logging factory using structlog with daily file rotation.

Features
--------
- JSON output in production, pretty console in development.
- Daily file rotation for ops, errors, and audit streams.
- correlation_id propagation via :class:`~contextvars.ContextVar`.
- Every entry contains ``timestamp``, ``level``, ``logger``, ``correlation_id``.
"""

import logging
import logging.handlers
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import structlog

#: Holds the active correlation_id for the current async context.
_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def _add_correlation_id(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """Processor that injects ``correlation_id`` from the ContextVar."""
    cid = _correlation_id_var.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def _make_file_handler(
    path: Path,
    *,
    json_format: bool,
    level: int = logging.DEBUG,
) -> logging.handlers.TimedRotatingFileHandler:
    """Create a daily-rotating file handler formatted by structlog."""
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(path),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    handler.setLevel(level)

    if json_format:
        renderer: Any = structlog.processors.JSONRenderer()
        timestamp_fmt = "iso"
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)
        timestamp_fmt = "%Y-%m-%d %H:%M:%S"

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt=timestamp_fmt),
            _add_correlation_id,
        ],
    )
    handler.setFormatter(formatter)
    return handler


def _make_console_handler(json_format: bool) -> logging.Handler:
    """Create a stdout console handler formatted by structlog."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    if json_format:
        renderer: Any = structlog.processors.JSONRenderer()
        timestamp_fmt = "iso"
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
        timestamp_fmt = "%Y-%m-%d %H:%M:%S"

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt=timestamp_fmt),
            _add_correlation_id,
        ],
    )
    handler.setFormatter(formatter)
    return handler


def configure_logging(
    log_dir: Path | None = None,
    *,
    json_format: bool | None = None,
    level: str | int = logging.INFO,
) -> None:
    """Configure structlog and stdlib logging with daily file rotation.

    Three file streams are created:

    - ``ops.log`` – INFO+ operational logs.
    - ``errors.log`` – ERROR+ logs.
    - ``audit.log`` – all logs emitted through :func:`get_audit_logger`.

    A console handler is always attached for container/development visibility.

    Parameters
    ----------
    log_dir:
        Directory for log files. Defaults to ``./logs``.
    json_format:
        ``True`` for JSON output, ``False`` for pretty console.
        Defaults to ``True`` when ``ENV`` is ``production``/``prod``/``staging``.
    level:
        Root logging level (default ``INFO``). Accepts ``str`` names or
        ``int`` constants.
    """
    if json_format is None:
        env = os.environ.get("ENV", "development").lower()
        json_format = env in ("production", "prod", "staging")

    log_dir = log_dir or Path("logs")

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    shared_pre_chain: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso" if json_format else "%Y-%m-%d %H:%M:%S"),
        _add_correlation_id,
    ]

    structlog.configure(
        processors=[
            *shared_pre_chain,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    ops_handler = _make_file_handler(
        log_dir / "ops.log",
        json_format=json_format,
        level=logging.INFO,
    )
    errors_handler = _make_file_handler(
        log_dir / "errors.log",
        json_format=json_format,
        level=logging.ERROR,
    )
    console_handler = _make_console_handler(json_format)

    root.addHandler(ops_handler)
    root.addHandler(errors_handler)
    root.addHandler(console_handler)

    audit_logger = logging.getLogger("audit")
    audit_logger.setLevel(level)
    audit_logger.propagate = False

    for handler in audit_logger.handlers[:]:
        audit_logger.removeHandler(handler)

    audit_handler = _make_file_handler(
        log_dir / "audit.log",
        json_format=json_format,
        level=logging.DEBUG,
    )
    audit_logger.addHandler(audit_handler)
    audit_logger.addHandler(console_handler)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a general-purpose structlog :class:`~structlog.stdlib.BoundLogger`."""
    return structlog.stdlib.get_logger(name)


def get_audit_logger() -> structlog.stdlib.BoundLogger:
    """Return an audit-specific structlog :class:`~structlog.stdlib.BoundLogger`.

    Logs emitted through this logger are routed exclusively to
    ``audit.log`` and the console.
    """
    return structlog.stdlib.get_logger("audit")


def set_correlation_id(correlation_id: str) -> None:
    """Set the active ``correlation_id`` for the current context."""
    _correlation_id_var.set(correlation_id)


def clear_correlation_id() -> None:
    """Clear the active ``correlation_id``."""
    _correlation_id_var.set(None)
