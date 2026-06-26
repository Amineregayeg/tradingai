"""Tests for the Finnhub calendar service — country mapping, parsing, blackout calc."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.calendar.finnhub import (
    CURRENCIES,
    CalendarEvent,
    CalendarService,
    _COUNTRY_TO_CURRENCY,
    _pair_to_currencies,
)


# ---------------------------------------------------------------------------
# Pair parsing
# ---------------------------------------------------------------------------


def test_pair_to_currencies_compact():
    assert _pair_to_currencies("EURUSD") == ["EUR", "USD"]


def test_pair_to_currencies_slash():
    assert _pair_to_currencies("EUR/USD") == ["EUR", "USD"]


def test_pair_to_currencies_underscore():
    assert _pair_to_currencies("EUR_USD") == ["EUR", "USD"]


def test_pair_to_currencies_lowercase_normalises():
    assert _pair_to_currencies("eur/usd") == ["EUR", "USD"]


def test_pair_to_currencies_invalid_returns_empty():
    assert _pair_to_currencies("XYZ") == []
    assert _pair_to_currencies("") == []


# ---------------------------------------------------------------------------
# Country → currency mapping (fixed in a prior session for Finnhub's ISO codes)
# ---------------------------------------------------------------------------


def test_us_maps_to_usd():
    assert _COUNTRY_TO_CURRENCY["US"] == "USD"


def test_gb_maps_to_gbp_not_great_britain():
    """Finnhub sends 'GB', not 'GBP' — the mapping is essential."""
    assert _COUNTRY_TO_CURRENCY["GB"] == "GBP"


def test_jp_maps_to_jpy():
    assert _COUNTRY_TO_CURRENCY["JP"] == "JPY"


def test_au_nz_ca_ch():
    assert _COUNTRY_TO_CURRENCY["AU"] == "AUD"
    assert _COUNTRY_TO_CURRENCY["NZ"] == "NZD"
    assert _COUNTRY_TO_CURRENCY["CA"] == "CAD"
    assert _COUNTRY_TO_CURRENCY["CH"] == "CHF"


def test_all_eu_members_map_to_eur():
    """All Eurozone members must collapse to EUR for the blackout calc."""
    for code in ["DE", "FR", "IT", "ES", "PT", "NL", "BE", "AT", "FI", "GR", "IE"]:
        assert _COUNTRY_TO_CURRENCY[code] == "EUR", f"{code} should map to EUR"


def test_eu_aggregate_maps_to_eur():
    assert _COUNTRY_TO_CURRENCY["EU"] == "EUR"


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


def test_parse_events_filters_to_supported_currencies():
    svc = CalendarService()
    raw = [
        {"country": "US", "event": "NFP", "time": "2026-05-29T12:30:00Z", "impact": "high"},
        {"country": "BR", "event": "Brazil CPI", "time": "2026-05-29T12:30:00Z", "impact": "high"},
        {"country": "JP", "event": "BOJ", "time": "2026-05-29T03:00:00Z", "impact": "high"},
    ]
    events = svc._parse_events(raw)
    currencies = {e.currency for e in events}
    assert currencies == {"USD", "JPY"}  # BRL dropped


def test_parse_events_normalises_impact_strings_and_numbers():
    svc = CalendarService()
    raw = [
        {"country": "US", "event": "A", "time": "2026-05-29T10:00:00Z", "impact": "3"},
        {"country": "US", "event": "B", "time": "2026-05-29T10:00:00Z", "impact": "2"},
        {"country": "US", "event": "C", "time": "2026-05-29T10:00:00Z", "impact": "1"},
        {"country": "US", "event": "D", "time": "2026-05-29T10:00:00Z", "impact": "HIGH"},
    ]
    events = svc._parse_events(raw)
    impacts = [e.impact for e in events]
    assert impacts == ["high", "medium", "low", "high"]


def test_parse_events_uses_estimate_field_finnhub_calls_it_estimate_not_forecast():
    svc = CalendarService()
    raw = [{
        "country": "US",
        "event": "GDP",
        "time": "2026-05-29T12:30:00Z",
        "impact": "high",
        "estimate": "2.5",
        "prev": "2.1",
    }]
    events = svc._parse_events(raw)
    assert events[0].forecast == "2.5"
    assert events[0].previous == "2.1"


def test_parse_time_iso_with_z():
    dt = CalendarService._parse_time("2026-05-29T12:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 5 and dt.day == 29


def test_parse_time_unix_epoch():
    dt = CalendarService._parse_time(1748520000)  # ~2025-05-29
    assert dt is not None
    assert dt.tzinfo is timezone.utc


def test_parse_time_invalid_returns_none():
    assert CalendarService._parse_time("not-a-time") is None
    assert CalendarService._parse_time(None) is None
    assert CalendarService._parse_time("") is None


# ---------------------------------------------------------------------------
# Blackout window
# ---------------------------------------------------------------------------


def _ev(currency, impact, dt):
    return CalendarEvent(time=dt, event="X", currency=currency, impact=impact)


@pytest.mark.asyncio
async def test_blackout_true_when_high_event_imminent_for_quote_currency():
    svc = CalendarService()
    now = datetime.now(tz=timezone.utc)
    svc.get_today_events = lambda: _async_return([_ev("USD", "high", now + timedelta(minutes=15))])
    in_blackout, next_event = await svc.is_in_blackout("EUR/USD", blackout_minutes=30)
    assert in_blackout is True
    assert next_event is not None


@pytest.mark.asyncio
async def test_blackout_false_when_event_outside_window():
    svc = CalendarService()
    now = datetime.now(tz=timezone.utc)
    svc.get_today_events = lambda: _async_return([_ev("USD", "high", now + timedelta(minutes=60))])
    in_blackout, next_event = await svc.is_in_blackout("EUR/USD", blackout_minutes=30)
    assert in_blackout is False
    assert next_event is None


@pytest.mark.asyncio
async def test_blackout_false_for_low_impact_event():
    svc = CalendarService()
    now = datetime.now(tz=timezone.utc)
    svc.get_today_events = lambda: _async_return([_ev("USD", "low", now + timedelta(minutes=5))])
    in_blackout, _ = await svc.is_in_blackout("EUR/USD", blackout_minutes=30)
    assert in_blackout is False


@pytest.mark.asyncio
async def test_blackout_false_for_unrelated_currency():
    """USD/JPY high event must not blacken EUR/GBP."""
    svc = CalendarService()
    now = datetime.now(tz=timezone.utc)
    svc.get_today_events = lambda: _async_return([_ev("USD", "high", now + timedelta(minutes=5))])
    in_blackout, _ = await svc.is_in_blackout("EUR/GBP", blackout_minutes=30)
    assert in_blackout is False


@pytest.mark.asyncio
async def test_blackout_true_for_base_currency_match():
    """EUR high event blackens EUR/USD via the base side."""
    svc = CalendarService()
    now = datetime.now(tz=timezone.utc)
    svc.get_today_events = lambda: _async_return([_ev("EUR", "high", now + timedelta(minutes=5))])
    in_blackout, _ = await svc.is_in_blackout("EUR/USD", blackout_minutes=30)
    assert in_blackout is True


@pytest.mark.asyncio
async def test_blackout_true_for_past_event_within_window():
    """Window is past **or** future — high event 10 min ago still blacks out."""
    svc = CalendarService()
    now = datetime.now(tz=timezone.utc)
    svc.get_today_events = lambda: _async_return([_ev("USD", "high", now - timedelta(minutes=10))])
    in_blackout, _ = await svc.is_in_blackout("EUR/USD", blackout_minutes=30)
    assert in_blackout is True


@pytest.mark.asyncio
async def test_blackout_false_for_unparseable_pair():
    svc = CalendarService()
    svc.get_today_events = lambda: _async_return([])
    in_blackout, next_event = await svc.is_in_blackout("XYZ", blackout_minutes=30)
    assert in_blackout is False
    assert next_event is None


# ---------------------------------------------------------------------------
# Currencies whitelist sanity
# ---------------------------------------------------------------------------


def test_supported_currencies_cover_majors():
    for c in ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]:
        assert c in CURRENCIES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_return(value):
    return value
