"""Unit tests for the AI circuit-breaker state machine.

Verifies all state transitions:
  CLOSED -> OPEN  (after FAILURE_THRESHOLD consecutive failures)
  OPEN   -> HALF_OPEN (after OPEN_DURATION_SECONDS)
  HALF_OPEN -> CLOSED  (probe succeeded)
  HALF_OPEN -> OPEN    (probe failed)
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.ai.circuit_breaker import (
    FAILURE_THRESHOLD,
    OPEN_DURATION_SECONDS,
    CircuitBreaker,
)


class TestCircuitBreakerInitialState:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"
        assert not cb.is_open

    def test_starts_allowing_requests(self) -> None:
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_custom_name(self) -> None:
        cb = CircuitBreaker(name="test-service")
        assert cb.name == "test-service"


class TestCircuitBreakerFailureAccumulation:
    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.is_open
        assert cb.state == "OPEN"

    def test_does_not_open_before_threshold(self) -> None:
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD - 1):
            cb.record_failure()
        assert not cb.is_open
        assert cb.allow_request() is True

    def test_open_blocks_requests(self) -> None:
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.allow_request() is False

    def test_success_resets_failures(self) -> None:
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD - 1):
            cb.record_failure()
        cb.record_success()
        # Failure count should be reset; circuit stays closed
        assert not cb.is_open
        assert cb.allow_request() is True

    def test_success_after_open_closes_circuit(self) -> None:
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True


class TestCircuitBreakerHalfOpen:
    def _open_and_age(self, cb: CircuitBreaker) -> CircuitBreaker:
        """Open the breaker then fast-forward past OPEN_DURATION_SECONDS."""
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._opened_at = datetime.now(timezone.utc) - timedelta(
            seconds=OPEN_DURATION_SECONDS + 1
        )
        return cb

    def test_half_open_allows_one_probe(self) -> None:
        cb = self._open_and_age(CircuitBreaker())
        # First request after cooldown should be the probe
        assert cb.allow_request() is True

    def test_half_open_blocks_second_concurrent_request(self) -> None:
        cb = self._open_and_age(CircuitBreaker())
        cb.allow_request()  # probe in-flight
        # Second request while probe is in-flight must be blocked
        assert cb.allow_request() is False

    def test_half_open_success_closes_circuit(self) -> None:
        cb = self._open_and_age(CircuitBreaker())
        cb.allow_request()  # probe in-flight
        cb.record_success()
        assert cb.state == "CLOSED"
        assert not cb.is_open
        assert cb.allow_request() is True

    def test_half_open_failure_reopens_circuit(self) -> None:
        cb = self._open_and_age(CircuitBreaker())
        cb.allow_request()  # probe in-flight
        cb.record_failure()  # probe failed
        assert cb.state == "OPEN"
        assert cb.is_open
        assert cb.allow_request() is False

    def test_still_open_within_cooldown(self) -> None:
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        # Do NOT advance time — still within cooldown
        assert cb.allow_request() is False

    def test_is_open_property_returns_false_when_cooldown_elapsed(self) -> None:
        """is_open should return False (probe might be allowed) once cooldown passes."""
        cb = self._open_and_age(CircuitBreaker())
        # After cooldown, is_open returns False because a probe can be dispatched
        assert not cb.is_open


class TestCircuitBreakerRepr:
    def test_repr_contains_state(self) -> None:
        cb = CircuitBreaker(name="repr-test")
        r = repr(cb)
        assert "CLOSED" in r
        assert "repr-test" in r
