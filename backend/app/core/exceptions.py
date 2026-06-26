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
    """Build an RFC 7807 Problem Details dictionary."""
    response: dict[str, Any] = {
        "type": type_uri,
        "title": title,
        "status": status,
    }
    if detail:
        response["detail"] = detail
    if instance:
        response["instance"] = instance
    if extensions:
        response.update(extensions)
    return response
