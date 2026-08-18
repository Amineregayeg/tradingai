"""Finnhub economic calendar integration with Redis caching."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.logging import logger

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Forex currencies we care about
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]

# Finnhub uses ISO country codes, not currency codes — map them
_COUNTRY_TO_CURRENCY: dict[str, str] = {
    "US": "USD",
    "EU": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "PT": "EUR",
    "NL": "EUR",
    "BE": "EUR",
    "AT": "EUR",
    "FI": "EUR",
    "GR": "EUR",
    "IE": "EUR",
    "GB": "GBP",
    "JP": "JPY",
    "AU": "AUD",
    "NZ": "NZD",
    "CA": "CAD",
    "CH": "CHF",
}

# Pair → set of two currencies
_PAIR_CURRENCIES: dict[str, list[str]] = {}

# Finnhub impact values → normalised strings.
#
# DO NOT WIDEN THIS MAP TO SILENCE AN UNKNOWN. A wider map makes the NEXT unrecognised
# value silently "low" again — the same shape as loosening a grep pattern to clear a
# false positive, which `check_partial_rules.py` refuses in its own failure message.
# An unrecognised value is a fact about the provider and belongs in UNKNOWN_IMPACT.
_IMPACT_MAP: dict[str, str] = {
    "1": "low",
    "2": "medium",
    "3": "high",
    "low": "low",
    "medium": "medium",
    "high": "high",
}

#: The third state. An impact we could not resolve is NOT "low" (T-0035, B126 1a).
#:
#: **THIS IS DELIBERATELY NON-BLOCKING.** `is_in_blackout` skips anything that is not
#: "high", so an UNKNOWN event is treated exactly as a "low" one was — the recording
#: changes and the decision does not. Whether an unclassifiable event should BLOCK is a
#: safety-versus-availability trade on live trading; it is Malek's call, it needs the
#: count `resolution_stats()` starts accruing here, and `B126` criterion 1b is explicit
#: that the operational cost is unknowable without it.
UNKNOWN_IMPACT = "unknown"

#: Why an impact resolved the way it did. The three are NOT interchangeable:
#: `_parse_events` has TWO independent fail-open defaults and a fixture that exercises
#: one does not exercise the other.
RESOLVED = "resolved"        # the provider sent a value this map knows
ABSENT = "absent"            # neither `impact` nor `importance` was present or truthy
UNRECOGNISED = "unrecognised"  # a value was sent and this map does not know it

_CACHE_KEY_PREFIX = "calendar"
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _resolve_impact(item: dict) -> tuple[str, str | None, str]:
    """Return `(impact, raw_value, reason)` for one raw provider event.

    **THE OLD LINE COLLAPSED THREE DIFFERENT SITUATIONS INTO ONE ANSWER:**

        impact_raw = str(item.get("impact") or item.get("importance") or "low")
        impact = _IMPACT_MAP.get(impact_raw.lower(), "low")

    **Two independent defaults, and a fix that handled only the second would pass three
    of the four fixtures `T-0035` names.** `{}`, `{"impact": ""}` and `{"impact": None}`
    are decided by the `or` chain and never reach the dict lookup at all; only
    `{"impact": "tier-1"}` reaches the dict's default. Both said `"low"`, and `"low"`
    is a CLAIM about the event rather than an admission that we have none.

    **`raw_value` is returned, and kept on the event, because criterion 2 needs to count
    WHICH values the provider actually sends.** A count of unknowns tells you how often;
    the values tell you whether the map is missing a tier or the provider changed its
    schema, and those have opposite fixes.
    """
    raw = item.get("impact")
    if raw is None or str(raw).strip() == "":
        raw = item.get("importance")
    if raw is None or str(raw).strip() == "":
        return UNKNOWN_IMPACT, None, ABSENT

    raw_str = str(raw).strip()
    mapped = _IMPACT_MAP.get(raw_str.lower())
    if mapped is None:
        return UNKNOWN_IMPACT, raw_str, UNRECOGNISED
    return mapped, raw_str, RESOLVED


def _pair_to_currencies(pair: str) -> list[str]:
    """Extract the two currency codes from a pair string.

    Handles formats: EURUSD, EUR/USD, EUR_USD.
    """
    pair = pair.replace("/", "").replace("_", "").upper()
    if len(pair) == 6:
        return [pair[:3], pair[3:]]
    return []


@dataclass
class CalendarEvent:
    """Normalised economic calendar event."""

    time: datetime
    event: str
    currency: str
    impact: str  # "high", "medium", "low", or UNKNOWN_IMPACT
    forecast: str | None = None
    previous: str | None = None
    #: The provider's own string, kept verbatim when it did not resolve. `None` means the
    #: provider sent nothing to keep — which is a DIFFERENT fact from sending something
    #: we could not read, and the two have opposite fixes.
    impact_raw: str | None = None

    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "event": self.event,
            "currency": self.currency,
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
            "impact_raw": self.impact_raw,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalendarEvent":
        # `.get`, not `[...]`: a Redis entry cached BEFORE this field existed has a live
        # TTL of up to an hour, so the first hour after any deploy reads dicts without it.
        return cls(
            time=datetime.fromisoformat(d["time"]),
            event=d["event"],
            currency=d["currency"],
            impact=d["impact"],
            forecast=d.get("forecast"),
            previous=d.get("previous"),
            impact_raw=d.get("impact_raw"),
        )


class CalendarService:
    """Fetch and cache economic calendar events from Finnhub.

    Typical lifecycle::

        calendar_service.init(api_key=settings.finnhub_api_key, redis_client=redis)
        events = await calendar_service.get_today_events()
        in_blackout, next_event = await calendar_service.is_in_blackout("EURUSD", 30)

    An event's `impact` is one of "high", "medium", "low" or `UNKNOWN_IMPACT`. **The
    fourth is not a severity — it is the absence of one**, and it is non-blocking by
    construction; see `is_in_blackout` and `resolution_stats`.
    """

    def __init__(self) -> None:
        self._redis: Any = None
        self._api_key: str = ""
        # T-0035 criterion 2. Per-instance, not module-level: production has one
        # singleton so this IS the process count, and a test constructing its own
        # service gets a clean slate rather than whatever ran before it.
        self._impact_resolution: dict[str, int] = {RESOLVED: 0, ABSENT: 0, UNRECOGNISED: 0}
        self._unrecognised_values: dict[str, int] = {}

    def resolution_stats(self) -> dict[str, Any]:
        """Return the impact-resolution counts seen by THIS service since construction.

        **This exists because `B126` criterion 1b is blocked on a count that could not be
        taken.** The old code coerced an unresolvable impact to `"low"` before anything
        could observe it, so *"how often does this fire?"* had no answer and the question
        of whether an unknown event should block could not be decided. **You cannot count
        what you do not record, so the recording comes first.**

        **`unrecognised_values` is the half that says what to DO about the count.** A high
        `unrecognised` count with one repeated value means `_IMPACT_MAP` is missing a tier
        the provider has always sent; the same count spread across many values means the
        provider's schema moved. **Opposite fixes, and the bare total distinguishes
        neither** — a figure whose population is unnamed is this register's most repeated
        finding.

        NOTE the counters advance only on a live PARSE. A cache hit rebuilds events from
        Redis via `from_dict` and does not re-resolve, so these are counts of parses and
        not of events served. Stated because the difference is invisible in the number.
        """
        return {
            "counts": dict(self._impact_resolution),
            "unrecognised_values": dict(self._unrecognised_values),
        }

    def init(self, api_key: str, redis_client: Any) -> None:
        """Initialise the service with API credentials and a Redis client.

        Args:
            api_key: Finnhub API token.
            redis_client: Async redis-py client (redis.asyncio.Redis).
        """
        self._api_key = api_key
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_today_events(self) -> list[CalendarEvent]:
        """Return today's economic events, sorted ascending by time.

        Tries Redis cache first (TTL 1 h); falls back to Finnhub API.
        """
        today_str = date.today().isoformat()
        cache_key = f"{_CACHE_KEY_PREFIX}:{today_str}"

        cached = await self._get_cache(cache_key)
        if cached is not None:
            return sorted(
                [CalendarEvent.from_dict(e) for e in cached],
                key=lambda e: e.time,
            )

        raw = await self._fetch_from_finnhub(today_str)
        events = self._parse_events(raw)
        await self._set_cache(cache_key, [e.to_dict() for e in events])
        return sorted(events, key=lambda e: e.time)

    async def refresh(self) -> None:
        """Force a fresh fetch from Finnhub and update the Redis cache."""
        today_str = date.today().isoformat()
        cache_key = f"{_CACHE_KEY_PREFIX}:{today_str}"

        raw = await self._fetch_from_finnhub(today_str)
        events = self._parse_events(raw)
        await self._set_cache(cache_key, [e.to_dict() for e in events], force=True)
        logger.info(f"Calendar refreshed: {len(events)} events for {today_str}")

    async def is_in_blackout(
        self,
        pair: str,
        blackout_minutes: int,
    ) -> tuple[bool, datetime | None]:
        """Check whether *pair* is in a news blackout window.

        A blackout occurs when any HIGH-impact event for either currency in
        *pair* is within *blackout_minutes* minutes in the past **or** future.

        Args:
            pair: Instrument symbol, e.g. ``"EURUSD"`` or ``"EUR/USD"``.
            blackout_minutes: Number of minutes before/after event to block.

        Returns:
            ``(True, next_event_time)`` if in blackout, else ``(False, None)``.
        """
        currencies = _pair_to_currencies(pair)
        if not currencies:
            logger.warning(f"Could not parse currencies from pair '{pair}'")
            return False, None

        events = await self.get_today_events()
        now = datetime.now(tz=timezone.utc)
        window = timedelta(minutes=blackout_minutes)

        for event in events:
            # T-0035 CRITERION 1, AND IT IS THE LINE THAT MAKES THE CHANGE SAFE.
            #
            # `!= "high"` is UNCHANGED, so UNKNOWN_IMPACT skips here exactly as "low" did
            # and this function's verdict is identical for every input, before and after.
            # `test_t0035_impact_unknown.py` asserts that pairwise rather than describing
            # it -- the assertion is what a later seat can re-run.
            #
            # STATED SO IT CANNOT EXPIRE QUIETLY: today NOTHING IN PRODUCTION CALLS THIS.
            # `grep -rn is_in_blackout backend --include=*.py` returns this def, the class
            # docstring above, and seven test lines. The control arm is `get_today_events`,
            # which the same command finds at `api/routers/calendar.py:26`. So the live
            # blast radius of the old fail-open was `GET /calendar/today` and the UI it
            # feeds -- NOT the engine, whose `decision/engine.py` reads a `news_blackout`
            # boolean that nothing writes (B125).
            #
            # T-0035 SAID "T-0036 IS WHAT MAKES THIS LINE MATTER". IT DID NOT, AND THE
            # REASON IS WORTH MORE THAN THE PREDICTION WAS.
            #
            # T-0036 wired the news subsystem onto the order path and DELIBERATELY BYPASSED
            # this function: `live/news_context.py` calls `get_today_events()` and then the
            # RULE modules directly. Measured after that task landed, `is_in_blackout` still
            # has ZERO production callers -- its only hits in `app/` are this def, the class
            # docstring, and these comments.
            #
            # IT WAS BYPASSED BECAUSE IT IMPLEMENTS A DIFFERENT, PRE-CONTRACT DOCTRINE.
            # Three measurable disagreements with the ratified rules:
            #
            #   window     here `abs(now - event) <= blackout_minutes`, SYMMETRIC
            #              GATE-012 blocks [event-15, event); GATE-013 blocks [event,
            #              first M15 close at or after event+30) -- ASYMMETRIC, and the
            #              M15 term is a ratchet the symmetric form has no expression for
            #   pre-window at the caller's `blackout_minutes` (30 in the docstring example)
            #              versus the rule's declared 15
            #   impact     `!= "high"` reads the NORMALISED value, so UNKNOWN_IMPACT never
            #              blocks here. That is the fail-open T-0035 closed at the source,
            #              still live INSIDE this function -- harmless only because nothing
            #              calls it
            #
            # SO THIS IS A SECOND STATEMENT OF THE NEWS DOCTRINE THAT DISAGREES WITH THE
            # RATIFIED ONE, in live code, now shadowed by a correct implementation. It is
            # not dead-and-marked like `decision/engine.py`'s branch -- it reads as the
            # platform's news gate, and a seat reaching for "the blackout function" gets the
            # wrong doctrine with no warning. Recorded rather than deleted or rewritten:
            # deleting live code is not this task's scope, and rewriting it to match the
            # rules would create a THIRD implementation of them.
            #
            # `!= "high"` is therefore still UNCHANGED, and the identical-verdict assertion
            # in `test_t0035_impact_unknown.py` still holds. Whether UNKNOWN should BLOCK
            # anywhere is a live safety-versus-availability decision that needs the count
            # `resolution_stats()` accrues, and it belongs to Malek.
            if event.impact != "high":
                continue
            if event.currency not in currencies:
                continue

            event_time = event.time
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)

            if abs(now - event_time) <= window:
                return True, event_time

        return False, None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_from_finnhub(self, date_str: str) -> list[dict]:
        """Fetch economic calendar data from Finnhub for a single date.

        Args:
            date_str: ISO date string, e.g. ``"2026-05-16"``.

        Returns:
            List of raw event dicts from the Finnhub response.
        """
        if not self._api_key:
            logger.warning("Finnhub API key not set; returning empty calendar.")
            return []

        url = f"{FINNHUB_BASE}/calendar/economic"
        params = {
            "from": date_str,
            "to": date_str,
            "token": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                f"Finnhub calendar HTTP error {exc.response.status_code}: {exc}"
            )
            return []
        except Exception as exc:
            logger.error(f"Finnhub calendar fetch failed: {exc}")
            return []

        # Finnhub wraps events under "economicCalendar"
        if isinstance(data, dict):
            return data.get("economicCalendar", [])
        return []

    def _parse_events(self, raw: list[dict]) -> list[CalendarEvent]:
        """Parse raw Finnhub events and filter to CURRENCIES only."""
        events: list[CalendarEvent] = []

        for item in raw:
            country = (item.get("country") or "").upper()
            # Finnhub sends ISO country codes; map to currency codes
            currency = _COUNTRY_TO_CURRENCY.get(country) or (item.get("currency") or "").upper()
            if currency not in CURRENCIES:
                continue

            # Finnhub uses "time" (Unix epoch or ISO string)
            raw_time = item.get("time") or item.get("date") or ""
            event_time = self._parse_time(raw_time)
            if event_time is None:
                continue

            impact, impact_raw, reason = _resolve_impact(item)
            self._impact_resolution[reason] = self._impact_resolution.get(reason, 0) + 1
            if reason == UNRECOGNISED:
                assert impact_raw is not None  # UNRECOGNISED means a value was present
                self._unrecognised_values[impact_raw] = (
                    self._unrecognised_values.get(impact_raw, 0) + 1
                )
                logger.warning(
                    "Calendar impact UNRECOGNISED — recorded as unknown, NOT as low",
                    impact_raw=impact_raw,
                    event=str(item.get("event") or item.get("name") or ""),
                    currency=currency,
                )
            elif reason == ABSENT:
                logger.warning(
                    "Calendar impact ABSENT — recorded as unknown, NOT as low",
                    event=str(item.get("event") or item.get("name") or ""),
                    currency=currency,
                )

            forecast = item.get("estimate") or item.get("forecast")
            previous = item.get("prev") or item.get("previous") or item.get("actual")
            unit = item.get("unit", "")

            def fmt_val(v: object) -> str | None:
                if v is None:
                    return None
                return f"{v}{unit}" if unit else str(v)

            events.append(
                CalendarEvent(
                    time=event_time,
                    event=str(item.get("event") or item.get("name") or ""),
                    currency=currency,
                    impact=impact,
                    forecast=fmt_val(forecast),
                    previous=fmt_val(previous),
                    impact_raw=impact_raw,
                )
            )

        return events

    @staticmethod
    def _parse_time(raw: str | int | float) -> datetime | None:
        """Parse various Finnhub time formats to a UTC-aware datetime."""
        if not raw:
            return None

        # Unix timestamp (seconds)
        if isinstance(raw, (int, float)):
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None

        raw_str = str(raw).strip()

        # ISO 8601 with timezone (e.g. "2026-05-16T08:30:00+00:00")
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(raw_str[:len(fmt) + 6], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        # Try numeric string
        try:
            return datetime.fromtimestamp(float(raw_str), tz=timezone.utc)
        except (ValueError, OSError):
            pass

        logger.warning(f"Could not parse Finnhub time value: {raw!r}")
        return None

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    async def _get_cache(self, key: str) -> list[dict] | None:
        """Return cached value or None on miss / error."""
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning(f"Redis cache read error for '{key}': {exc}")
            return None

    async def _set_cache(
        self, key: str, value: list[dict], force: bool = False
    ) -> None:
        """Write value to Redis with the standard TTL."""
        if self._redis is None:
            return
        try:
            if force:
                await self._redis.delete(key)
            await self._redis.set(key, json.dumps(value), ex=_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning(f"Redis cache write error for '{key}': {exc}")


# Module-level singleton
calendar_service = CalendarService()
