"""New York local time, DST-aware (GATE-023, M0 §3).

WHY THIS EXISTS AS ITS OWN MODULE
The platform is UTC end to end and should stay that way — UTC storage, UTC arithmetic. But
the strategy is written in New York local time, and every window it defines (news blackout,
magic zone, the 19:00 close, session ranges) moves with US daylight saving. `GATE-023`
forbids a hardcoded offset for exactly that reason: the workspace states UTC-4 twice and
UTC-5 once, and a fixed offset silently shifts every window by an hour, twice a year.

So there is one boundary layer, here, and nothing else in the codebase converts.

WHY NAIVE DATETIMES ARE REFUSED
A naive datetime has no answer to "which zone" — it acquires one from whatever code touches
it next, usually the machine's. That is how an engine ends up correct in CI and an hour wrong
in production for six months of the year. Refusing them means the mistake is a crash at the
boundary rather than a plausible-looking timestamp in stored evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def to_ny(dt: datetime) -> datetime:
    """Convert an aware datetime to New York local time."""
    if dt.tzinfo is None:
        raise ValueError(
            "naive datetime passed to to_ny(). Attach a timezone at the source — "
            "an implicit zone is how a DST bug survives review (GATE-023)."
        )
    return dt.astimezone(NY)


def iso_ny(dt: datetime) -> str:
    """NY local time as the telemetry schema's ``iso_ny``: ISO-8601 WITH offset.

    The offset in the string is not decoration — it is the evidence of which zone was used,
    and conformance HG-23 reads it. `-04:00` in July and `-05:00` in January is the proof
    that a tz database was consulted rather than a constant.
    """
    return to_ny(dt).isoformat(timespec="seconds")


def tz_offset_used(dt: datetime) -> str:
    """The offset alone, e.g. ``-04:00``, for ``session.tz_offset_used``."""
    return to_ny(dt).strftime("%z")[:3] + ":" + to_ny(dt).strftime("%z")[3:]


def now_ny() -> datetime:
    return datetime.now(tz=timezone.utc).astimezone(NY)
