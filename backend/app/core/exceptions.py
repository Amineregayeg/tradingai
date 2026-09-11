"""Custom exception hierarchy for Trading AI Co-Pilot."""
from typing import Any


class TradingAIError(Exception):
    """Base exception for all Trading AI errors."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or message


class BrokerError(TradingAIError):
    """Base exception for broker-related errors."""

    def __init__(self, message: str, *, broker: str | None = None, detail: str | None = None) -> None:
        super().__init__(message, detail=detail)
        self.broker = broker


class BrokerConnectionError(BrokerError):
    """Raised when a broker connection cannot be established or is lost."""


class DirectionNotSupported(BrokerError):
    """The venue cannot take an order in this DIRECTION. A CAPABILITY, not a failure.

    **The distinction is the whole point of a dedicated type.** A generic rejection —
    *"order rejected"* — is indistinguishable from a transport failure (`B375`), and the two
    demand opposite responses: a transport failure is worth retrying and a venue that does not
    support shorting will refuse the same order forever. Sharing a type with
    `BrokerConnectionError` would make *"the network was down for an hour"* and *"this venue is
    long only"* read identically in the record.

    `reason` is supplied BY THE VENUE and must name the constraint rather than restate the
    refusal. It travels unaltered into `DecisionRecord.rejection_reason`, so whatever is written
    here is what a reader sees months later with no other context.
    """

    def __init__(self, *, venue: str, direction: str, reason: str) -> None:
        super().__init__(reason, broker=venue, detail=reason)
        self.venue = venue
        self.direction = direction
        self.reason = reason


class BrokerRateLimitError(BrokerError):
    """Raised when broker API rate limit is hit."""

    def __init__(
        self,
        message: str,
        *,
        broker: str | None = None,
        retry_after_seconds: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, broker=broker, detail=detail)
        self.retry_after_seconds = retry_after_seconds


class AIUnavailable(TradingAIError):
    """Raised when the AI subsystem cannot process a request."""

    REASON_AI_DISABLED = "ai_disabled"
    REASON_BUDGET_EXCEEDED = "budget_exceeded"
    REASON_CIRCUIT_OPEN = "circuit_open"
    REASON_UPSTREAM_ERROR = "upstream_error"

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.reason = reason


class AIBudgetExceeded(AIUnavailable):
    """Raised when the monthly AI budget is exhausted."""

    def __init__(
        self,
        message: str = "Monthly AI budget exceeded",
        *,
        used_usd: float | None = None,
        budget_usd: float | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            message,
            reason=AIUnavailable.REASON_BUDGET_EXCEEDED,
            detail=detail,
        )
        self.used_usd = used_usd
        self.budget_usd = budget_usd


class AICircuitOpen(AIUnavailable):
    """Raised when the AI circuit-breaker is open after repeated failures."""

    def __init__(
        self,
        message: str = "AI circuit breaker is open",
        *,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            message,
            reason=AIUnavailable.REASON_CIRCUIT_OPEN,
            detail=detail,
        )


class ComplianceError(TradingAIError):
    """Raised when an action violates prop firm or risk compliance rules."""


class KillSwitchArmed(ComplianceError):
    """Raised when the kill-switch is active and trading is halted."""

    def __init__(
        self,
        message: str = "Kill switch is armed — trading is halted",
        *,
        profile_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.profile_id = profile_id


class AlertNotFound(TradingAIError):
    """Raised when a requested alert does not exist."""

    def __init__(self, alert_id: str | None = None) -> None:
        msg = f"Alert '{alert_id}' not found" if alert_id else "Alert not found"
        super().__init__(msg)
        self.alert_id = alert_id


class InvalidAlertAction(TradingAIError):
    """Raised when an unsupported or invalid action is applied to an alert."""

    def __init__(
        self,
        message: str,
        *,
        action: str | None = None,
        current_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.current_status = current_status


class ScreenshotError(TradingAIError):
    """Raised when screenshot capture or storage fails."""


# ---------------------------------------------------------------------------
# RFC 7807 helper
# ---------------------------------------------------------------------------

def problem_response(
    *,
    title: str,
    status: int,
    detail: str | None = None,
    instance: str | None = None,
    type_uri: str = "about:blank",
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an RFC 7807 Problem Details dictionary.

    **`detail` IS REDACTED HERE, AND THIS IS THE CHOKEPOINT ON PURPOSE** (`B404`).

    Every problem+json body in the app is built by this function — the `HTTPException` handler,
    the `TradingAIError` handler, and any handler added later. Eight router sites interpolate an
    exception into a detail (`alerts.py` ×3, `brokers.py` ×4, `calendar.py` ×1), and the two
    `brokers.py` connect paths carry CONNECTION-ERROR text, which is exactly where a credential
    rides. **Fixing the sites leaves the next one uncovered; fixing the builder covers the
    contract** — `B398`'s argument, applied to a security boundary.

    `title` is a type name and `instance` is `request.url.path`, which excludes the query string,
    so neither carries a credential and neither is touched.
    """
    # Imported here rather than at module scope: `app.core.logging` pulls in settings, and this
    # module is imported by the broker contract and the models — a cycle there would surface as
    # an ImportError in a place nobody looks.
    from app.core.logging import redact_for_response

    response: dict[str, Any] = {
        "type": type_uri,
        "title": title,
        "status": status,
    }
    if detail:
        response["detail"] = redact_for_response(str(detail))
    if instance:
        response["instance"] = instance
    if extensions:
        response.update(extensions)
    return response
