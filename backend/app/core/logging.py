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
    # ------------------------------------------------------------------
    # ALPACA, added when `B403`'s transport fix began persisting exception text (`T-0138`) —
    # and REWRITTEN after the manager controlled the first version against realistic
    # credentials and it leaked FOUR of five cases, including both it was written for.
    #
    # **THE FIRST VERSION WAS RIGHT ABOUT THE NAME AND WRONG ABOUT THE PUNCTUATION.** It was
    # `APCA-API-KEY-ID\s*[:=]\s*\S+`, which matches `APCA-API-KEY-ID: value` — a shape I
    # invented. **What a stringified headers object actually produces is a Python dict repr:**
    # `{'APCA-API-KEY-ID': 'PK...'}`, with a quote between the name and the colon. `\s*` does
    # not match `'`, so the pattern never fired on the one serialisation it existed for.
    #
    # *And my arm passed, because I wrote the fixture from the pattern instead of from the real
    # output.* That is the mock encoding its author's reading, in a security control.
    # ------------------------------------------------------------------
    # Header name followed by ANY punctuation — `: v`, `': 'v'`, `="v"`, `, v`.
    re.compile(r"(APCA-API-(?:KEY-ID|SECRET-KEY)['\"]?\s*[:=,]\s*['\"]?)[A-Za-z0-9/+_\-]{8,}",
               re.IGNORECASE),
    re.compile(r"(ALPACA_API_(?:KEY|SECRET)\s*=\s*\S+)", re.IGNORECASE),
    # Credentials in a query string. `key_id`/`secret_key` are ALPACA's names and were missing.
    # `auth-token` is METAAPI's (`B406`): its SDK builds `?auth-token=<token>&clientId=...` into
    # the websocket URL, and the plain `token` alternative never fired because the character
    # before `token` is a HYPHEN, not the `?`/`&` the pattern anchors on. Right about the name,
    # wrong about what precedes it — the same shape as the first APCA-API-* pattern, which was
    # right about the name and wrong about the punctuation after it.
    #
    # **THIS RULE EXISTS FOR SINGLE-SEGMENT ACCOUNT TOKENS**, not JWTs. A JWT's signature
    # segment is already caught by the bare-token backstop below. An ACCOUNT token
    # (`metaapi_client.py:27-31`) evades that backstop if it lacks a lowercase letter, lacks an
    # uppercase letter, lacks a digit, or is under 32 characters — and then only this named
    # rule protects it. (This comment first wrote the value as `<jwt>`: it named the shape
    # that was already safe, so a literal reader would conclude the rule was never needed.)
    re.compile(
        r"([?&](?:api[_-]?key|api[_-]?secret|key[_-]?id|secret[_-]?key|auth[_-]?token|"
        r"secret|token|password)=)"
        r"[^&\s\"']+",
        re.IGNORECASE,
    ),
    # BARE TOKENS, with no name beside them — in a message, a traceback frame, a response body.
    # Alpaca key ids are `PK` (paper) or `AK` (live) + uppercase alphanumerics; secrets are long
    # mixed-case strings. **This is the pattern that catches a credential nobody labelled**, and
    # it is deliberately the broadest: over-redacting a diagnostic string costs a reader some
    # context, while under-redacting one writes a live key into a table.
    re.compile(r"\b((?:PK|AK)[A-Z0-9]{12,})\b"),
    re.compile(r"\b((?=[A-Za-z0-9/+_\-]*[a-z])(?=[A-Za-z0-9/+_\-]*[A-Z])"
               r"(?=[A-Za-z0-9/+_\-]*\d)[A-Za-z0-9/+_\-]{32,})\b"),
]

_REDACTED = "[REDACTED]"


def _redact(value: str) -> str:
    """Replace any known-secret patterns in *value* with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(_REDACTED, value)
    return value


def redact_for_storage(value: str, *, limit: int = 300) -> str:
    """Redact and BOUND a string that is about to be PERSISTED rather than logged.

    **THE LOGURU FILTER DOES NOT PROTECT THE DATABASE.** `_secrets_filter` runs on the way to a
    log sink; a value written to a column never passes through it. `B403`'s transport fix put
    `str(exc)` into `DecisionRecord.rejection_reason`, and an SDK error can carry request headers,
    a URL with query parameters, or a response body — so the venue's own text reaches a table that
    nothing redacts, and rows outlive every log rotation.

    **A PATTERN LIST IS A FLOOR, NOT A CEILING**, and this one is an allow-list of shapes we have
    thought of: it cannot recognise a credential format nobody added. That is why the caller in
    `execution/service.py` records the exception TYPE as the primary fact and treats the message
    as secondary — *the structured field is for counting, the prose for diagnosing, and neither is
    worth a leaked key.*

    The length bound is separate from the redaction and does its own job: an SDK that renders a
    whole response body would otherwise persist it in full.
    """
    return _redact(value)[:limit]


def redact_for_response(value: str, *, limit: int = 1000) -> str:
    """Redact a string that is about to be SENT TO A CLIENT in an HTTP response body (`B404`).

    **THE THIRD BOUNDARY, AND THE ONE NOTHING COVERED.** `_secrets_filter` guards the log sink and
    `redact_for_storage` guards database columns — and an HTTP response body passed through
    neither. `calendar.py` put the upstream `httpx` error into a 502 detail, and an `httpx` error
    renders the request URL; Finnhub authenticates with `?token=<key>` in that URL. So a failing
    upstream call handed the Finnhub key to whoever made the request, **precisely when the key
    was wrong or expired — which is when someone is most likely to be hitting that endpoint.**

    Same patterns, same floor-not-ceiling caveat: an allow-list of shapes cannot recognise a
    credential format nobody added. The looser bound is for legitimate long details (validation
    messages); the tight one on storage is for rows that outlive every rotation.
    """
    return _redact(value)[:limit]


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
