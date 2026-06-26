"""Loguru configuration for Trading AI Co-Pilot.

Features:
- JSON-formatted structured logs
- Automatic redaction of secrets from log output
- Request-ID context binding via contextvars
"""
import re
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger

from app.config import settings

# ContextVar holding the current request ID (set by middleware)
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Patterns of secret values to redact from log records
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(sk-ant-[A-Za-z0-9\-_]+)", re.IGNORECASE),          # Anthropic API key
    re.compile(r"(Bearer\s+sk-ant-[A-Za-z0-9\-_]+)", re.IGNORECASE),
    re.compile(r"(ANTHROPIC_API_KEY\s*=\s*\S+)", re.IGNORECASE),
    re.compile(r"(oanda_api_key\s*=\s*\S+)", re.IGNORECASE),
    re.compile(r"(OANDA_API_KEY\s*=\s*\S+)", re.IGNORECASE),
    re.compile(r"(smtp_password\s*=\s*\S+)", re.IGNORECASE),
    re.compile(r"(SMTP_PASSWORD\s*=\s*\S+)", re.IGNORECASE),
    # Generic "secret_key = value" pattern
    re.compile(r"(secret[_-]?key\s*=\s*\S+)", re.IGNORECASE),
]

_REDACTED = "[REDACTED]"


def _redact(value: str) -> str:
    """Replace any known-secret patterns in *value* with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(_REDACTED, value)
    return value


def _secrets_filter(record: dict[str, Any]) -> bool:
    """Loguru filter that redacts secrets before the record reaches the sink."""
    record["message"] = _redact(record["message"])
    # Also clean up any extra fields that might contain secrets
    for key, val in record.get("extra", {}).items():
        if isinstance(val, str):
            record["extra"][key] = _redact(val)
    return True


def get_request_id() -> str | None:
    """Return the current request ID from context, or None."""
    return _request_id_var.get()


def bind_request_id(request_id: str) -> None:
    """Bind a request ID to the current async context."""
    _request_id_var.set(request_id)


def setup_logging() -> None:
    """Configure loguru for the application.

    Must be called once at application startup before any logging occurs.
    """
    logger.remove()  # Remove default handler

    log_format = (
        "{time:YYYY-MM-DDTHH:mm:ss.SSSZ} | {level} | {name}:{function}:{line} | {message}"
    )

    logger.add(
        sys.stdout,
        level=settings.log_level.upper(),
        format=log_format,
        serialize=True,         # JSON output
        filter=_secrets_filter,
        backtrace=True,
        diagnose=False,         # Don't show local variable values in tracebacks (security)
        colorize=False,
    )

    logger.info(
        "Logging configured",
        log_level=settings.log_level,
        json_output=True,
    )


__all__ = [
    "logger",
    "setup_logging",
    "get_request_id",
    "bind_request_id",
]
