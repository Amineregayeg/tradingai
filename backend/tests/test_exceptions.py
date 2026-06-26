"""Unit tests for the custom exception hierarchy."""
import pytest

from app.core.exceptions import (
    AIBudgetExceeded,
    AICircuitOpen,
    AIUnavailable,
    AlertNotFound,
    BrokerConnectionError,
    BrokerRateLimitError,
    ComplianceError,
    InvalidAlertAction,
    KillSwitchArmed,
    ScreenshotError,
    TradingAIError,
    problem_response,
)


def test_trading_ai_error_base() -> None:
    exc = TradingAIError("base error", detail="more detail")
    assert exc.message == "base error"
    assert exc.detail == "more detail"
    assert str(exc) == "base error"


def test_broker_connection_error_inherits() -> None:
    exc = BrokerConnectionError("connection failed", broker="oanda")
    assert isinstance(exc, TradingAIError)
    assert exc.broker == "oanda"


def test_broker_rate_limit_error() -> None:
    exc = BrokerRateLimitError("rate limited", broker="oanda", retry_after_seconds=30)
    assert exc.retry_after_seconds == 30


def test_ai_budget_exceeded() -> None:
    exc = AIBudgetExceeded(used_usd=31.5, budget_usd=30.0)
    assert exc.reason == AIUnavailable.REASON_BUDGET_EXCEEDED
    assert exc.used_usd == 31.5
    assert isinstance(exc, AIUnavailable)


def test_ai_circuit_open() -> None:
    exc = AICircuitOpen()
    assert exc.reason == AIUnavailable.REASON_CIRCUIT_OPEN
    assert isinstance(exc, AIUnavailable)


def test_kill_switch_armed() -> None:
    exc = KillSwitchArmed(profile_id="prof-123")
    assert isinstance(exc, ComplianceError)
    assert exc.profile_id == "prof-123"


def test_alert_not_found_with_id() -> None:
    exc = AlertNotFound("alert-abc")
    assert "alert-abc" in exc.message


def test_alert_not_found_without_id() -> None:
    exc = AlertNotFound()
    assert exc.message == "Alert not found"


def test_invalid_alert_action() -> None:
    exc = InvalidAlertAction("bad action", action="explode", current_status="PENDING")
    assert exc.action == "explode"
    assert exc.current_status == "PENDING"


def test_screenshot_error_inherits() -> None:
    exc = ScreenshotError("capture failed")
    assert isinstance(exc, TradingAIError)


def test_problem_response_minimal() -> None:
    result = problem_response(title="Not Found", status=404)
    assert result["title"] == "Not Found"
    assert result["status"] == 404
    assert result["type"] == "about:blank"
    assert "detail" not in result


def test_problem_response_full() -> None:
    result = problem_response(
        title="Budget Exceeded",
        status=402,
        detail="Monthly AI budget of $30 has been reached",
        instance="/api/analysis",
        type_uri="https://tradingai.local/errors/budget-exceeded",
        extensions={"used_usd": 31.5},
    )
    assert result["type"] == "https://tradingai.local/errors/budget-exceeded"
    assert result["detail"] == "Monthly AI budget of $30 has been reached"
    assert result["instance"] == "/api/analysis"
    assert result["used_usd"] == 31.5
