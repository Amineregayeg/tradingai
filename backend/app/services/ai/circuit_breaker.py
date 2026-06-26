"""Circuit breaker for the AI subsystem.

States:
    CLOSED   — normal operation, all requests pass through.
    OPEN     — too many consecutive failures; all requests blocked.
    HALF_OPEN — probe state after the cooldown; exactly one request allowed.

Transitions:
    CLOSED → OPEN     : after FAILURE_THRESHOLD consecutive failures
    OPEN   → HALF_OPEN: after OPEN_DURATION_SECONDS have elapsed
    HALF_OPEN → CLOSED: probe succeeded
    HALF_OPEN → OPEN  : probe failed
"""
from datetime import datetime, timedelta, timezone


FAILURE_THRESHOLD = 5       # consecutive failures before opening
OPEN_DURATION_SECONDS = 60  # stay open for 60 s before allowing a probe


class CircuitBreaker:
    """Thread-safe (asyncio-safe) circuit breaker for a named upstream service."""

    def __init__(self, name: str = "ai") -> None:
        self.name = name
        self._state: str = "CLOSED"
        self._failure_count: int = 0
        self._last_failure_time: datetime | None = None
        self._opened_at: datetime | None = None
        # Whether a half-open probe has already been dispatched
        self._probe_in_flight: bool = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Return the current state string (CLOSED | OPEN | HALF_OPEN)."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Return True when the circuit is OPEN and no probe is currently allowed.

        Note: call :meth:`allow_request` to get the authoritative answer, as
        that method handles the OPEN→HALF_OPEN transition.
        """
        if self._state == "OPEN":
            if self._opened_at is not None:
                elapsed = (datetime.now(tz=timezone.utc) - self._opened_at).total_seconds()
                if elapsed >= OPEN_DURATION_SECONDS:
                    return False  # probe might be allowed
            return True
        return False

    # ------------------------------------------------------------------
    # State mutators
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        """Reset failure count and move to CLOSED state."""
        self._failure_count = 0
        self._last_failure_time = None
        self._opened_at = None
        self._probe_in_flight = False
        self._state = "CLOSED"

    def record_failure(self) -> None:
        """Record a failure; open the circuit when FAILURE_THRESHOLD is reached."""
        self._failure_count += 1
        self._last_failure_time = datetime.now(tz=timezone.utc)

        if self._state == "HALF_OPEN":
            # Probe failed — back to open
            self._state = "OPEN"
            self._opened_at = datetime.now(tz=timezone.utc)
            self._probe_in_flight = False
            return

        if self._state == "CLOSED" and self._failure_count >= FAILURE_THRESHOLD:
            self._state = "OPEN"
            self._opened_at = datetime.now(tz=timezone.utc)

    def allow_request(self) -> bool:
        """Decide whether an incoming request should be allowed.

        * CLOSED  → always True
        * OPEN    → False unless OPEN_DURATION_SECONDS have passed, in which
                    case transition to HALF_OPEN and return True once.
        * HALF_OPEN → True for exactly the one probe request (while it is
                      in-flight no further requests are allowed).
        """
        if self._state == "CLOSED":
            return True

        if self._state == "OPEN":
            if self._opened_at is None:
                return False
            elapsed = (datetime.now(tz=timezone.utc) - self._opened_at).total_seconds()
            if elapsed >= OPEN_DURATION_SECONDS:
                # Transition to HALF_OPEN and allow the probe
                self._state = "HALF_OPEN"
                self._probe_in_flight = True
                return True
            return False

        # HALF_OPEN
        if not self._probe_in_flight:
            # Shouldn't normally happen, but be safe
            self._probe_in_flight = True
            return True
        # A probe is already in flight — block further requests
        return False

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<CircuitBreaker name={self.name!r} state={self._state} "
            f"failures={self._failure_count}>"
        )


# Module-level singleton
ai_circuit_breaker = CircuitBreaker(name="ai")
