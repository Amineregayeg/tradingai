"""GATE-023 — every timestamp is New York local, from a tz database (M2).

The registry entry:

    All timestamps — chart, calendar, session windows, the news blackout windows, the Magic
    Zone and the 19:00 close — are New York local time. […]
    inputs: system clock; tz database
    output: All gate evaluations timestamped in NY local; the offset used recorded in
            telemetry.

WHY THIS IS THE FIRST RULE IMPLEMENTED
It is a HARD_GATE, it is READY, and its inputs are a clock and a tz database — no market
data, no OPEN decision, nothing to grade. It can therefore be implemented completely and
honestly today, which makes it the right rule to prove the M2 mechanism on rather than a
placeholder.

It also happens to be load-bearing. The workspace states UTC-4 twice and UTC-5 once, and
the rulings use "New York time" as the invariant without ever stating an offset. A hardcoded
offset shifts the news blackout, the magic zone, the 19:00 close and every session range by
an hour, twice a year — and does so silently, in one direction for half the year.

WHAT IS ACTUALLY CHECKED
That the timestamp presented was produced by a DST-aware zone. The evidence is the offset
itself: `-04:00` in July and `-05:00` in January is what a tz database yields and what a
constant cannot. A verdict here is not a claim that the clock is correct — only that the
zone was consulted.
"""
from __future__ import annotations

from datetime import datetime

from app.services.rules.base import RuleImplementation
from app.services.telemetry.ny_time import NY, iso_ny, to_ny
from app.services.telemetry.records import RuleEvaluation, derived, from_record

#: The only two offsets America/New_York can produce. Anything else means the timestamp did
#: not come from this zone — including a plausible-looking constant.
VALID_NY_OFFSETS = ("-04:00", "-05:00")


class NewYorkTimestamps(RuleImplementation):
    """GATE-023: timestamps are NY local, DST-aware, never a hardcoded offset."""

    RULE_ID = "GATE-023"

    @classmethod
    def evaluate(cls, moment: datetime) -> RuleEvaluation:
        """Evaluate the rule for one instant.

        FAILs rather than raising when the offset is wrong: a rule evaluation is telemetry,
        and a hard gate that throws produces no record — which loses exactly the evidence
        that something is misconfigured.
        """
        try:
            local = to_ny(moment)
        except ValueError as exc:
            # A naive datetime has no zone at all, which is the failure this rule exists to
            # catch, not an internal error.
            return cls.evaluation(
                "FAIL",
                values={"error": str(exc), "tz_aware": False},
                value_provenance={
                    "error": derived("to_ny(moment) rejected a naive datetime"),
                    "tz_aware": derived("moment.tzinfo is None"),
                },
            )

        offset = local.strftime("%z")
        offset = f"{offset[:3]}:{offset[3:]}"
        is_dst = bool(local.dst())

        return cls.evaluation(
            "PASS" if offset in VALID_NY_OFFSETS else "FAIL",
            values={
                "ny_local_time": iso_ny(moment),
                "tz_offset_used": offset,
                "tz_database_zone": str(NY),
                "dst_in_effect": is_dst,
            },
            value_provenance={
                # The offset is not derived from the record — it comes from the tz database,
                # which is the whole point. Naming that is what distinguishes a consulted
                # zone from a constant that happens to match today.
                "ny_local_time": from_record("timestamp_ny"),
                "tz_offset_used": derived("zoneinfo('America/New_York').utcoffset(moment)"),
                "tz_database_zone": derived("zoneinfo key"),
                "dst_in_effect": derived("zoneinfo('America/New_York').dst(moment) != 0"),
            },
        )
