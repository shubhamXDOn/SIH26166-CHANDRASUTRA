"""Structured logging foundation.

M0 provides a compact, reliable logging setup. Later milestones will attach
diagnostic fields (Pair ID, Configuration ID, matcher, runtime, status,
failure reason) through the ``extra=`` mechanism already supported here.

Design principles:
    * Single ``setup_logging()`` call at application startup.
    * Console + rotating file handler (logs/backend.log).
    * Contextual fields are appended via ``extra``; never leak secrets.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .security import redact_text

LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    "%(context)s"
)

_REDACTED_FIELDS = ("gemini_api_key", "auth_secret_key", "password", "token", "api_key")


class ContextFilter(logging.Filter):
    """Append structured ``extra`` context fields to every log line.

    Redacts values whose field name looks like a secret even if a caller
    mistakenly passes them through ``extra``, and scrubs common secret
    patterns from the message itself (Authorization headers, Bearer tokens,
    JWTs, API keys, refresh tokens).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        parts = []
        for key in ("pair_id", "config_id", "operation", "status", "matcher", "failure_reason"):
            value = getattr(record, key, None)
            if value is not None:
                parts.append(f" [{key}={value}]")
        record.context = "".join(parts)
        if hasattr(record, "render"):
            # explicitly redact any suspicious key
            for field in _REDACTED_FIELDS:
                if hasattr(record, field):
                    setattr(record, field, "***")
        safe_msg = redact_text(str(record.getMessage()))
        if safe_msg != str(record.getMessage()):
            record.msg = safe_msg
            record.args = ()
        return True


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure root logger for console and rotating file output."""
    root = logging.getLogger()
    root.setLevel(level.upper() if level else "INFO")

    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S%z")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "backend.log",
                maxBytes=2_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            # Never crash startup because logging cannot write.
            root.warning("Could not create file log handler at %s; console only.", log_dir)

    ctx = ContextFilter()
    for handler in root.handlers:
        handler.addFilter(ctx)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Usage::

        logger = get_logger(__name__)
        logger.info("matcher finished", extra={"pair_id": "P0001", "status": "ok"})
    """
    return logging.getLogger(name)