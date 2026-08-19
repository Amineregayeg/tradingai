"""GATE-012 / GATE-013 / GATE-016 — the news windows, and the flag that gates nothing.

    GATE-012  "No new trade may be OPENED within 15 minutes before the scheduled time of any
              high-impact (red-folder) economic event… The rule addresses NEW ENTRIES ONLY;
              it says nothing about positions already open."
    GATE-013  "No new trades for at least 30 minutes after the scheduled release. After the
              30-minute cooldown, the engine must ADDITIONALLY wait for the first complete
              M15 candle to close… Both conditions must hold; the M15 close is an EXTRA
              CONDITION, NOT A SUBSTITUTE for the 30 minutes."
    GATE-016  "Undefined until ruled — record `is_red_folder_day` on every trade so the two
              readings can be tested against outcomes."

Three rules in one module because they are one decision surface over one event list, and
GATE-016's flag is computed from the same events GATE-012/013 window against. `GATE-029`'s
precedent: a module named for its primary rule may carry the cluster that decides with it.

## THE CONSTANTS HERE ARE HIS, AND THIS IS THE OPPOSITE OF THE HABIT THIS LOOP JUST BUILT

Four recent tasks trained the reflex *a constant is ours until Salim ratifies it*. **Here he
authorised 15 / 30 / first-M15 in writing** — GATE-012's notes record that they appear in no
workspace page and in none of the 1,258 images and are **trader-authorised engine constants**,
shipped with *"For implementation purposes, use the following deterministic rule"*.

> **So they are READ FROM THE REGISTRY and never retyped, never wrapped in a declared-parameter
> carrier, never stamped `ratified: False`.** Re-declaring them as ours would misattribute his
> own decision back to us — the mirror image of the `TARGET-005` mistake, and the tell is
> simple: **a number with a registry `values` entry is his.**

## THE M15 CONDITION IS A NO-OP ON EVERY REALISTIC FIXTURE, AND THAT IS THE TRAP

`first_permitted = max(release + 30min, first M15 close at/after release + 30min)`. **For any
release on the 15-minute grid the two terms are EQUAL and the M15 term decides nothing:**

    release 08:30   rel+30 09:00   firstM15 09:00   permitted 09:00   M15 IS A NO-OP
    release 08:31   rel+30 09:01   firstM15 09:15   permitted 09:15   M15 BINDS (+14 min)

**MEASURED: the clause binds on 56 of 60 release minutes (93.3%) and is inert on exactly the
four grid minutes — and real macro releases sit precisely on those four.** US data at 08:30
ET, FOMC at 14:00 ET. **The repository's only calendar data is `test_calendar_service.py`,
whose event times are `12:30 ×4 / 10:00 ×4 / 03:00 ×1` — three distinct times, ALL grid-aligned,
zero off-grid.** So a fixture built from the realistic case, or inherited from the one that
exists, exercises this clause zero times while every assertion passes.

**The off-grid case must therefore be CONSTRUCTED, and both arms of the `max()` must be shown
to win once.** A test where only one side ever binds has not tested `max()`.

## THE M15 SERIES IS AN INPUT, AND ITS BASIS IS DECLARED

`15m` is a real timeframe here — `market_data/sources/base.py` lists it, `aggregator.py:37`
serves it, `indicators.py:26` carries its seconds — **so a producer EXISTS and this rule does
not declare `CANNOT_FIRE_WITHOUT`.** But `aggregator` RESAMPLES it, and a resampled panel and
an exchange bar are different objects in this codebase.

**So the series is taken as an input.** Supplied, the observed candle closes decide and the
basis is `OBSERVED_M15_SERIES`. Not supplied, the scheduled 15-minute grid is used and the
basis is `SCHEDULED_M15_GRID`, **recorded on the decision** — because the two differ exactly
when it matters: a halt or a gap means the grid says a candle closed and no candle did.
**Reported as `NOT_READ`, naming the producer that exists and was not called — never
`NOT_EVALUABLE`, which would claim nobody had built one.**

## GATE-012 TOUCHES NEW ENTRIES AND NOTHING ELSE

Its final sentence is a carve-out and it sits in the tail where `| head` cuts it: *"The rule
addresses new entries only; it says nothing about positions already open."*

**A blackout that freezes management is a different rule nobody wrote**, and it would strand a
live position through exactly the volatility the rule exists to avoid. Every decision this
module emits carries `blocks_management=False`, and it is a field rather than a comment so a
test can assert it on every blocking path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, Sequence

from app.services.rules.base import (
    ConditionReading, RuleImplementation, quorum_blocked,
)
from app.services.rules.gate_015_calendar_scope import CalendarScope, ScopedEvent
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.ny_time import iso_ny, to_ny
from app.services.telemetry.records import RuleEvaluation, derived, from_registry

#: HIS, read from the registry. Never retyped: the registry is the single source and a
#: literal here would be a second home for a number the trader authorised.
PRE_EVENT_BLACKOUT_MINUTES: int = int(
    contract.rule("GATE-012")["values"]["pre_event_blackout_minutes"]
)
POST_EVENT_COOLDOWN_MINUTES: int = int(
    contract.rule("GATE-013")["values"]["post_event_cooldown_minutes"]
)
THEN_WAIT_FOR: str = str(contract.rule("GATE-013")["values"]["then_wait_for"])

#: The M15 grid, in minutes. Not a declared parameter and not his: it is what "M15" MEANS.
M15_MINUTES: int = 15

M15Basis = Literal["OBSERVED_M15_SERIES", "SCHEDULED_M15_GRID"]
BlockReason = Literal["NEWS_PRE_WINDOW", "NEWS_POST_WINDOW"]

#: GATE-013's blocked-state default, when the OBSERVED M15 series could not be read.
#:
#: BLOCK, and the direction is argued here beside the rule it belongs to because
#: `quorum_blocked` deliberately refuses to carry a fallback — GATE-041 defaults CONTINUE and
#: GATE-040 defaults FORWARD, opposite ways, each conservative for its own statement, and a
#: shared default would let a rule inherit the wrong direction silently.
#:
#: Here the statement is *"The objective is not to trade the news, but to avoid the
#: manipulation immediately surrounding the release."* **Standing aside is what this rule
#: does.** And the failure the unread series hides runs one way: a halt or a data gap means
#: the SCHEDULE says an M15 candle closed while no candle did, so the grid can only ever
#: permit entry EARLIER than the observed series would. Defaulting to ALLOW would take the
#: optimistic branch of exactly that asymmetry.
NEWS_BLOCKED_DEFAULT = "BLOCK"

#: Shared by every COVERAGE_NOTE in this module, so the four cannot drift apart. The
#: staleness class T-0036 was written against is "what did not change": a note is wrong by
#: having been LEFT ALONE, there is no hunk for it, and no amount of diff-reading reaches an
#: absent edit. Three notes here said NOT WIRED and were true until the moment this module
#: was imported from live/.
_WIRED_FOR_RECORDING = (
    'WIRED FOR RECORDING ONLY (T-0036 Stage A): app/services/live/news_context.py imports this module and the order path records the verdict on DecisionTrace as an UNENFORCED observation. It suppresses no signal. A gate never observed to block anything must not be given the power to block, so Stage B enforces only once trace.would_block_by has produced a non-zero, human-read count. '
)


def first_m15_close_at_or_after(
    moment: datetime, *, m15_closes: Sequence[datetime] | None = None
) -> tuple[datetime, M15Basis]:
    """The close of the first COMPLETE M15 candle at or after `moment`.

    `m15_closes` are OBSERVED candle close times. Supplied, they decide — a halt or a data
    gap means the grid says a candle closed and none did, and the observed series is the only
    thing that knows. Absent, the scheduled grid is used and the caller is told so through
    the returned basis rather than left to assume.

    NOT A RESAMPLER. Nothing here builds an M15 candle out of smaller ones; the fallback
    computes the SCHEDULE, which is what "M15" denotes, and labels itself as the schedule.
    """
    if m15_closes:
        later = sorted(c for c in m15_closes if c >= moment)
        if later:
            return later[0], "OBSERVED_M15_SERIES"
        # The series exists but ends before `moment`: falling through to the grid would
        # silently answer from a different source than the one the caller supplied.
        # Reported through the basis instead.
    floor = moment.replace(
        minute=(moment.minute // M15_MINUTES) * M15_MINUTES, second=0, microsecond=0
    )
    return (floor if floor >= moment else floor + timedelta(minutes=M15_MINUTES)), (
        "SCHEDULED_M15_GRID"
    )


def first_permitted_entry_time(
    release_ny: datetime, *, m15_closes: Sequence[datetime] | None = None
) -> tuple[datetime, datetime, datetime, M15Basis]:
    """GATE-013's `output` formula, in one place.

    Returns `(permitted, cooldown_end, m15_close, basis)` — all four, not just the answer,
    because *"the M15 close is an extra condition, not a substitute for the 30 minutes"* is
    only checkable if both terms are visible in the record.

    ## THE `max()` IS GONE, AND ITS ABSENCE IS LOAD-BEARING

    The registry writes this as `max(release + 30min, first M15 close at or after
    release + 30min)`, and the first version copied that literally. **The second argument is
    computed FROM the first, and `first_m15_close_at_or_after` returns `>= moment` on all
    three of its paths — so `m15_close >= cooldown_end` ALWAYS and the `max()` could never
    select its first argument.** Review deleted it and all 44 tests passed, including the one
    whose message read *"both arms must win somewhere or `max()` is untested"*. Measured over
    180 release times: the M15 term strictly wins 176, the two COINCIDE 4, **and the cooldown
    term strictly wins zero.**

    **The Manager ruled it out because a `max()` over a comparison that is true by
    construction is noise, and a criterion requiring both its arms to win is unsatisfiable.**
    There is a second reason, which is why removing it is better than keeping it as
    documentation:

    > *"The first M15 close after the EVENT"* is a plausible misreading of GATE-013, and
    > under it the close lands BEFORE `release + 30`. **With the `max()` present, that
    > misreading is SILENTLY ABSORBED — the wrong anchor produces the right answer and
    > nothing goes red. Without it, the same mistake changes behaviour visibly.** The `max()`
    > was not protecting against that change; it was hiding it.

    So the relationship is stated as what it is — **the M15 close is a RATCHET on the
    cooldown, never a substitute for it** — and `test_the_m15_close_is_measured_from_the_
    cooldown_end_not_from_the_release` pins the anchor that makes the ratchet hold.
    """
    cooldown_end = release_ny + timedelta(minutes=POST_EVENT_COOLDOWN_MINUTES)
    # The ratchet: measured FROM the cooldown end, so it can only ever push later. Anchoring
    # this to `release_ny` instead would permit entry up to 30 minutes early.
    m15_close, basis = first_m15_close_at_or_after(cooldown_end, m15_closes=m15_closes)
    return m15_close, cooldown_end, m15_close, basis


@dataclass(frozen=True)
class NewsDecision:
    """One news verdict, with the evidence a later reader would need to recompute it."""

    decision: Literal["BLOCK", "ALLOW"]
    block_reason: BlockReason | None
    #: THE CARVE-OUT, AS A FIELD RATHER THAN A COMMENT. GATE-012 addresses new entries only,
    #: so a blackout must never freeze the management of an open position. A test asserts
    #: this on every blocking path; a docstring could not be asserted at all.
    blocks_new_entries: bool
    blocks_management: bool
    event_id: str | None = None
    event_time_ny: datetime | None = None
    #: GATE-013's three terms, carried whenever a post-window decision was made.
    first_permitted_entry_time: datetime | None = None
    cooldown_end: datetime | None = None
    m15_close: datetime | None = None
    m15_basis: M15Basis | None = None

    @property
    def m15_bound(self) -> bool | None:
        """Did the M15 term decide, or did the 30 minutes? None when no post-window applied.

        This is the field that makes the no-op visible. A corpus in which this is never True
        has not exercised the M15 condition, however green it is.
        """
        if self.first_permitted_entry_time is None or self.cooldown_end is None:
            return None
        return self.first_permitted_entry_time > self.cooldown_end

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision": self.decision,
            "blocks_new_entries": self.blocks_new_entries,
            "blocks_management": self.blocks_management,
            "applies_to": "NEW_ENTRIES_ONLY",
        }
        if self.block_reason is not None:
            out["block_reason"] = self.block_reason
        if self.event_id is not None:
            out["event_id"] = self.event_id
        if self.event_time_ny is not None:
            out["event_time_ny"] = iso_ny(self.event_time_ny)
        for key, value in (
            ("first_permitted_entry_time", self.first_permitted_entry_time),
            ("cooldown_end", self.cooldown_end),
            ("m15_close", self.m15_close),
        ):
            if value is not None:
                out[key] = iso_ny(value)
        if self.m15_basis is not None:
            out["m15_basis"] = self.m15_basis
        if self.m15_bound is not None:
            out["m15_term_bound"] = self.m15_bound
        return out


def _m15_condition(basis: M15Basis | None) -> ConditionReading:
    """Whether the observed M15 series was actually read.

    NOT_READ rather than NOT_EVALUABLE when it was not: `15m` is a real timeframe with a
    producer (`market_data/sources/base.py`, `aggregator.py:37`), so "nobody built this" would
    be false. The two absences have different owners and different fixes (base.py:80-86).
    """
    if basis == "OBSERVED_M15_SERIES":
        return ConditionReading(name="m15_series_read", state="TRUE")
    return ConditionReading(
        name="m15_series_read",
        state="NOT_READ",
        unread_producer=(
            "market_data 15m series — it exists (sources/base.py TIMEFRAMES, "
            "aggregator.py:37) and was not supplied to this evaluation, so the SCHEDULED "
            "grid was used. The two differ exactly when a halt or gap means the grid says a "
            "candle closed and none did."
        ),
    )


class PreEventBlackout(RuleImplementation):
    """GATE-012: no NEW ENTRY within 15 minutes before a red-folder release."""

    RULE_ID = "GATE-012"

    CANNOT_FIRE_WITHOUT = ()

    COVERAGE_NOTE = (
        "Built and able to fire: the calendar producer is live (B125) and GATE-015 scopes "
        "the event list. The 15 minutes is HIS, read from the registry and never retyped. "
        "THE CARVE-OUT IS ENFORCED AS A FIELD, not a comment: every decision carries "
        "blocks_management=False, because the rule addresses new entries only and a blackout "
        "that froze management would strand an open position through the volatility the rule "
        "exists to avoid. " + _WIRED_FOR_RECORDING + "The pre-contract news branch in "
        "decision/engine.py is still NOT adopted (B125) and is marked dead in place: "
        "populating news_blackout and enforcing the block are one change or neither, and "
        "Stage A does neither."
    )

    @classmethod
    def window_start(cls, event_time_ny: datetime) -> datetime:
        return event_time_ny - timedelta(minutes=PRE_EVENT_BLACKOUT_MINUTES)

    @classmethod
    def decide(
        cls, now_ny: datetime, events: Sequence[ScopedEvent]
    ) -> NewsDecision:
        """BLOCK when `now` is inside [event - 15min, event) for any blocking event.

        The window is CLOSED at the start and OPEN at the release: at the release instant
        GATE-013's post-window takes over, and a moment owned by both rules would be reported
        under whichever happened to be checked first.
        """
        for event in sorted(events, key=lambda e: e.time_ny):
            if not event.blocks:
                continue
            start = cls.window_start(event.time_ny)
            if start <= now_ny < event.time_ny:
                return NewsDecision(
                    decision="BLOCK",
                    block_reason="NEWS_PRE_WINDOW",
                    blocks_new_entries=True,
                    blocks_management=False,
                    event_id=event.event_id,
                    event_time_ny=event.time_ny,
                )
        return NewsDecision(
            decision="ALLOW", block_reason=None,
            blocks_new_entries=False, blocks_management=False,
        )

    @classmethod
    def evaluate(
        cls, now_ny: datetime, events: Sequence[ScopedEvent]
    ) -> RuleEvaluation:
        decision = cls.decide(now_ny, events)
        blocking = [e for e in events if e.blocks]
        values: dict[str, Any] = {
            "pre_event_blackout_minutes": PRE_EVENT_BLACKOUT_MINUTES,
            "now_ny": iso_ny(now_ny),
            "events_considered": [e.as_dict() for e in events],
            "events_blocking": len(blocking),
            **decision.as_dict(),
        }
        provenance: dict[str, Any] = {
            "pre_event_blackout_minutes": from_registry(
                "GATE-012", "values.pre_event_blackout_minutes"
            ),
            "now_ny": derived("caller's evaluation moment, converted by GATE-023's tz"),
            "events_considered": derived("GATE-015's scoped list, recorded in full (C-14)"),
            "events_blocking": derived("scoped events whose impact_class blocks"),
            "decision": derived("now inside [event - pre_event_blackout_minutes, event)"),
            "blocks_new_entries": derived("GATE-012 decision"),
            "blocks_management": derived(
                "structural: GATE-012 'addresses new entries only; it says nothing about "
                "positions already open'"
            ),
            "applies_to": from_registry("GATE-012", "statement"),
        }
        for key in ("block_reason", "event_id", "event_time_ny"):
            if key in values:
                provenance[key] = derived("the blocking event GATE-015 scoped")
        verdict = "FAIL" if decision.decision == "BLOCK" else "PASS"
        return cls.evaluation(verdict, values=values, value_provenance=provenance)


class PostEventBlackout(RuleImplementation):
    """GATE-013: 30 minutes, AND THEN the first complete M15 close. Both, not either."""

    RULE_ID = "GATE-013"

    CANNOT_FIRE_WITHOUT = ()

    COVERAGE_NOTE = (
        "Built and able to fire. Both terms of the max() are computed and BOTH ARE EMITTED "
        "(cooldown_end and m15_close) plus which one bound, because 'the M15 close is an "
        "extra condition, not a substitute' is only checkable if both are visible. The 30 "
        "and the first-M15 rule are HIS, read from the registry. THE M15 SERIES IS AN INPUT: "
        "supplied, observed closes decide and the basis is OBSERVED_M15_SERIES; absent, the "
        "scheduled grid is used, the basis says so, and the condition reports NOT_READ "
        "naming the producer that exists — never NOT_EVALUABLE. Measured: the M15 term binds "
        "on 56 of 60 release minutes and COINCIDES with the cooldown on the four grid "
        "minutes, where every real macro release sits; it can never fall below the cooldown, "
        "so it is a RATCHET and there is no max(). "
        "REACHES A VERDICT ONLY IN THE FIXTURES, AND THAT IS THE HONEST FIGURE: no "
        "production path supplies an observed M15 series, so PASS/FAIL are reachable only "
        "when a test hands one over and NOT_APPLICABLE is the sole verdict deployment will "
        "ever see. That also OVERLOADS the verdict — 'no news at all' and 'inside the "
        "window, blocking' are both NOT_APPLICABLE with opposite `decision` — so whatever "
        "wires this must read `decision`/`news_window_outcome`, not the verdict. Pinned by "
        "test_the_not_applicable_verdict_OVERLOADS_no_news_with_blocking_news. "
        + _WIRED_FOR_RECORDING
    )

    @classmethod
    def decide(
        cls,
        now_ny: datetime,
        events: Sequence[ScopedEvent],
        *,
        m15_closes: Sequence[datetime] | None = None,
    ) -> NewsDecision:
        """BLOCK from the release until `max(release + 30, first complete M15 close)`."""
        for event in sorted(events, key=lambda e: e.time_ny):
            if not event.blocks:
                continue
            permitted, cooldown_end, m15_close, basis = first_permitted_entry_time(
                event.time_ny, m15_closes=m15_closes
            )
            if event.time_ny <= now_ny < permitted:
                return NewsDecision(
                    decision="BLOCK",
                    block_reason="NEWS_POST_WINDOW",
                    blocks_new_entries=True,
                    blocks_management=False,
                    event_id=event.event_id,
                    event_time_ny=event.time_ny,
                    first_permitted_entry_time=permitted,
                    cooldown_end=cooldown_end,
                    m15_close=m15_close,
                    m15_basis=basis,
                )
        return NewsDecision(
            decision="ALLOW", block_reason=None,
            blocks_new_entries=False, blocks_management=False,
        )

    @classmethod
    def evaluate(
        cls,
        now_ny: datetime,
        events: Sequence[ScopedEvent],
        *,
        m15_closes: Sequence[datetime] | None = None,
    ) -> RuleEvaluation:
        decision = cls.decide(now_ny, events, m15_closes=m15_closes)
        condition = _m15_condition(decision.m15_basis)
        values: dict[str, Any] = {
            "post_event_cooldown_minutes": POST_EVENT_COOLDOWN_MINUTES,
            "then_wait_for": THEN_WAIT_FOR,
            "now_ny": iso_ny(now_ny),
            "events_considered": [e.as_dict() for e in events],
            "conditions": {condition.name: condition.state},
            **decision.as_dict(),
        }
        if condition.state == "NOT_READ":
            values["unreadable_conditions"] = {condition.name: condition.unread_producer}
        provenance: dict[str, Any] = {
            "post_event_cooldown_minutes": from_registry(
                "GATE-013", "values.post_event_cooldown_minutes"
            ),
            "then_wait_for": from_registry("GATE-013", "values.then_wait_for"),
            "now_ny": derived("caller's evaluation moment"),
            "events_considered": derived("GATE-015's scoped list, recorded in full (C-14)"),
            "decision": derived("now inside [release, first_permitted_entry_time)"),
            "blocks_new_entries": derived("GATE-013 decision"),
            "blocks_management": derived(
                "structural: the news gates address new entries only"
            ),
            "applies_to": from_registry("GATE-012", "statement"),
            "conditions": derived("whether the OBSERVED M15 series was read"),
        }
        for key in ("block_reason", "event_id", "event_time_ny"):
            if key in values:
                provenance[key] = derived("the blocking event GATE-015 scoped")
        for key in ("first_permitted_entry_time", "cooldown_end", "m15_close",
                    "m15_basis", "m15_term_bound", "unreadable_conditions"):
            if key in values:
                provenance[key] = derived(
                    "max(release + post_event_cooldown_minutes, first complete M15 close at "
                    "or after it) — both terms emitted, with which one bound"
                )

        # THE SHARED INVARIANT: no verdict while a condition is unreadable. Routed through
        # `base.quorum_blocked` rather than derived inline, because two inline copies are
        # SUPPOSED to differ in exactly the place a mistake would appear.
        #
        # THE UNREAD SERIES IS NOT A COSMETIC GAP. The scheduled grid says an M15 candle
        # closed at 09:15 whether or not one did; a halt means none did and entry is
        # permitted early. So a verdict computed from the grid is a verdict on incomplete
        # evidence, and reporting PASS would assert a window this rule did not verify.
        blocked = quorum_blocked([condition], default_outcome=NEWS_BLOCKED_DEFAULT)
        if blocked is not None:
            unreadable, default_outcome = blocked
            values["news_window_outcome"] = default_outcome
            values["not_applicable_reason"] = (
                "the OBSERVED M15 series was not supplied, so the first permitted entry time "
                "above was computed from the SCHEDULED grid. A halt or gap means the grid "
                "says a candle closed when none did, which can only permit entry EARLIER "
                f"than the truth — so the conservative default {default_outcome} is recorded "
                "rather than a verdict this rule could not verify."
            )
            provenance["news_window_outcome"] = derived(
                f"GATE-013's own blocked-state default, {NEWS_BLOCKED_DEFAULT}: the rule "
                "exists to avoid the manipulation around the release, and the unread series "
                "fails one way — the grid can only permit entry too early"
            )
            provenance["not_applicable_reason"] = derived(
                "base.quorum_blocked over GATE-013's condition readings"
            )
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance
            )

        verdict = "FAIL" if decision.decision == "BLOCK" else "PASS"
        return cls.evaluation(verdict, values=values, value_provenance=provenance)


class RedFolderDayFlag(RuleImplementation):
    """GATE-016: record `is_red_folder_day`. **BLOCK nothing on it; SIZE from it.**

    **Both halves are Salim's round-3 item 1, and they pull in different directions.**

        ruling (a)  the flag does NOT block. Blocking stays per EVENT — GATE-012/013, and
                    GATE-014 for the exceptional class. T-0032's deferral was RATIFIED.
        ruling (b)  a red-folder day sizes ONE RUNG DOWN the disturbance axis.

    So *"GATE NOTHING ON IT"* — this docstring through `T-0047` — is now half true and half
    false, which is worse than either. **The flag gates no ENTRY and re-selects the risk CELL**,
    and those are different verbs on different paths: `GATE-012` decides whether to trade in a
    window, `GATE-032` decides how much when a trade is allowed.
    """

    RULE_ID = "GATE-016"

    CANNOT_FIRE_WITHOUT = ()

    COVERAGE_NOTE = (
        "NO LONGER TELEMETRY ONLY. Round-3 ruling (b) makes this flag SIZE: GATE-032 re-selects "
        "one rung down the disturbance axis when it is true (T-0048). Ruling (a) ratified the "
        "other half -- it still BLOCKS nothing, and blocking stays per event. AND IT CANNOT "
        "REACH A TRADE TODAY, for two independent reasons: B179, no Finnhub key, so the flag is "
        "FALSE on every production bar; and B188, RiskMatrix.size() has ZERO production callers "
        "-- live trades are sized from fixed.RISK_PCT, one constant. A '0 rung-downs' figure is "
        "therefore consistent with no red-folder days, no calendar, AND no sizer. "
        "THE ORIGINAL NOTE FOLLOWS, kept because it records why the flag was built inert: "
        "'Undefined until ruled — record "
        "is_red_folder_day on every trade so the two readings can be tested against "
        "outcomes.' The workspace reads eco-data avoidance as a DAY gate; the engine "
        "constants are a MINUTES gate; nothing reconciles them and this rule must not pick. "
        "So the flag is recorded and NOTHING branches on it — asserted, not just stated. "
        "risk_pct is recorded beside it per the rule's inputs, so if he later rules for "
        "reduced size on red-folder days the stored telemetry can answer 'what would this "
        "have been?' without a re-run. Salim round-3 question 6i. This was CONSTRUCTION, not "
        "preservation: before T-0032, is_red_folder_day had ZERO occurrences outside "
        "telemetry/contract/, as did the whole news_context block. " + _WIRED_FOR_RECORDING
    )

    @classmethod
    def is_red_folder_day(
        cls, events: Sequence[ScopedEvent], session_date: date
    ) -> bool:
        """Does the session date carry any blocking event?

        Reads GATE-015's classification rather than re-deriving one, so an UNKNOWN event
        counts as a red-folder day under the same declared policy that makes it block —
        two answers from one classification, which is the point of GATE-015 being the
        producer.
        """
        return any(
            e.blocks and e.time_ny.date() == session_date for e in events
        )

    @classmethod
    def evaluate(
        cls,
        events: Sequence[ScopedEvent],
        session_date: date,
        *,
        risk_pct: float | None = None,
    ) -> RuleEvaluation:
        """Telemetry only. The verdict is never a block and never depends on the flag."""
        flag = cls.is_red_folder_day(events, session_date)
        values: dict[str, Any] = {
            "is_red_folder_day": flag,
            "session_date": session_date.isoformat(),
            "events_on_session_date": sum(
                1 for e in events if e.time_ny.date() == session_date
            ),
            "blocking_events_on_session_date": sum(
                1 for e in events if e.blocks and e.time_ny.date() == session_date
            ),
            "gates_anything": False,
            "unreconciled_readings": ["DAY_LEVEL", "MINUTES_LEVEL"],
            "pending_ruling": "Salim round-3 question 6i — day-vs-minutes",
        }
        if risk_pct is not None:
            values["risk_pct"] = risk_pct
        provenance: dict[str, Any] = {
            "is_red_folder_day": derived(
                "any GATE-015 blocking event whose NY date is the session date"
            ),
            "session_date": derived("caller's session date, NY local"),
            "events_on_session_date": derived("scoped events on that NY date"),
            "blocking_events_on_session_date": derived(
                "scoped blocking events on that NY date"
            ),
            "gates_anything": derived(
                "structural claim: no branch anywhere reads is_red_folder_day to decide"
            ),
            "unreconciled_readings": from_registry("GATE-016", "statement"),
            "pending_ruling": from_registry("GATE-016", "output"),
        }
        if risk_pct is not None:
            provenance["risk_pct"] = derived(
                "recorded beside the flag per GATE-016 inputs, so a later day-level ruling "
                "can be applied to stored history rather than re-derived"
            )
        # NOT_APPLICABLE ALWAYS, and that is the rule's own disposition rather than a
        # limitation of this implementation: GATE-016 is "undefined until ruled". A PASS
        # would assert conformance to a reading nobody has chosen.
        values["not_applicable_reason"] = (
            "GATE-016 is unreconciled — the workspace reads a DAY gate, the engine "
            "constants read a MINUTES gate, and the rule's own output field says to record "
            "the flag until it is ruled. Recording it is the whole requirement; deciding "
            "anything from it would be picking between the two readings."
        )
        provenance["not_applicable_reason"] = from_registry("GATE-016", "output")
        return cls.evaluation(
            "NOT_APPLICABLE", values=values, value_provenance=provenance
        )
