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

# Finnhub impact values → normalised strings
_IMPACT_MAP: dict[str, str] = {
    "1": "low",
    "2": "medium",
    "3": "high",
    "low": "low",
    "medium": "medium",
    "high": "high",
}

_CACHE_KEY_PREFIX = "calendar"
_CACHE_TTL_SECONDS = 3600  # 1 hour


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
    impact: str  # "high", "medium", "low"
    forecast: str | None = None
    previous: str | None = None

    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "event": self.event,
            "currency": self.currency,
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalendarEvent":
        return cls(
            time=datetime.fromisoformat(d["time"]),
            event=d["event"],
            currency=d["currency"],
            impact=d["impact"],
            forecast=d.get("forecast"),
            previous=d.get("previous"),
        )


class CalendarService:
    """Fetch and cache economic calendar events from Finnhub.

    Typical lifecycle::

        calendar_service.init(api_key=settings.finnhub_api_key, redis_client=redis)
        events = await calendar_service.get_today_events()
        in_blackout, next_event = await calendar_service.is_in_blackout("EURUSD", 30)
    """

    def __init__(self) -> None:
        self._redis: Any = None
        self._api_key: str = ""

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

            impact_raw = str(item.get("impact") or item.get("importance") or "low")
            impact = _IMPACT_MAP.get(impact_raw.lower(), "low")

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
