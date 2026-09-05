"""The news verdict for the ORDER PATH — computed here, recorded there, enforcing nothing.

## WHY THIS MODULE EXISTS AT ALL (T-0036)

`GATE-012`, `GATE-013`, `GATE-015` and `GATE-016` have been built, tested and
mutation-verified since `T-0032`, and **the code that places orders could not see any of
them.** Measured on the order path — `crypto_loop -> strategy_step -> ExecutionService` —
the complete doctrine precondition set was `history`, `daily_bias` and `ltf_bos`, against
**79 distinct `HARD_GATE` rules in the registry.** So the engine could open a position inside
a high-impact news window and nothing in the platform would have said so.

`decision/engine.py` does read `candle.get("news_blackout")` — once, in its
`Blackout / risk warnings` step — and **nothing writes it anywhere in `app/`** (`B125`). That is not a weaker statement of this doctrine on the alerts path; it is a dead
one, and a dead statement beside a live one is worse than none, because it reads as coverage.

## STAGE A: RECORD, DO NOT BLOCK — and that is a rule about evidence, not caution

**A gate that has never been observed to block anything must not be given the power to
block.** The verdict is written onto `DecisionTrace` as an *unenforced* observation and
suppresses no signal. Stage B enforces only once the count of trades this would have stopped
is non-zero and a human has read it.

**`DecisionTrace.would_block_by` IS NOT THAT COUNT, AND AN EARLIER DRAFT OF THIS PARAGRAPH
SAID IT WAS.** It is a `list[str]` of gate names on ONE trace, and the verdict is recorded
BEFORE `history`/`daily_bias`/`ltf_bos` — deliberately, so it is present on every bar rather
than only on bars that survived three unrelated gates. **So it accrues on bars that could
never have produced a trade, which is most of them.** Two different derivations over the same
record, and they must be published together because they differ by a large factor:

    bars_where_news_would_block      GATE_NAME in trace.would_block_by
                                     "how often is the calendar hot" -- a real question,
                                     and NOT Stage B's precondition
    trades_news_would_have_stopped   ... and trace.took_trade
                                     Stage B's numerator. `took_trade` is set at exactly two
                                     sites, each immediately before a `return Signal(...)`,
                                     so it IS "a signal was produced" -- and it already
                                     implies `blocked_by is None`, since `gate()` returns
                                     early on failure. ONE condition, not two.

**Still derived from the record rather than tallied beside it**, so neither figure can
disagree with the trace it describes. **And the names carry the unit at the layer where the
unit exists** — `would_block_by` is neither bars nor trades, so putting either word in its
name would be false precision.

## WHY THE CALENDAR IS FETCHED BY THE CALLER AND NOT HERE

`evaluate_latest_bar_traced` is a plain `def` and `calendar_service.get_today_events()` is
`async`. Making the evaluator async would touch every caller — including
`evaluate_latest_bar`, six test files, and the `test_t0011_census` monkeypatch — to move I/O
*into* a function whose testability rests on having none. So the async caller fetches, this
module turns the result into a plain verdict, and the evaluator receives data.

## THE SHAPE `CalendarScope.scope()` NEEDS DID NOT EXIST BEFORE `T-0035`

`scope()` takes the provider's RAW payload *"so this rule's verdict does not inherit
`finnhub.py`'s fail-open normalisation"*, and it also requires a real `datetime`::

    provider raw     impact "tier-1"   time "2026-05-29T12:30:00Z" or an epoch int
    CalendarEvent    impact "low"      time datetime      <- normalisation destroyed the raw
    scope() needs    impact "tier-1"   time datetime      <- the CROSS PRODUCT

**Neither source produced it.** Wiring this before `T-0035` would not merely have gated on a
laundered impact — `isinstance(time_raw, datetime)` would have dropped **every** event
without a word, and a gate that sees no events returns *"no blackout"* and is
indistinguishable from a gate that works. **`T-0035`'s `impact_raw`, which round-trips
through the Redis cache, is what makes the input constructible at all.**

*Recorded because it generalises: that dependency was justified by the weaker of its two
reasons, and a prerequisite justified by the weaker reason is one someone can argue away.*
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Sequence

from app.core.logging import logger
from app.services.rules.gate_012_news_blackout import (
    NewsDecision,
    PostEventBlackout,
    PreEventBlackout,
    RedFolderDayFlag,
)
from app.services.rules.gate_015_calendar_scope import CalendarScope, ScopedEvent
from app.services.telemetry.ny_time import iso_ny, to_ny

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.calendar.finnhub import CalendarEvent

#: The name this verdict is recorded under on `DecisionTrace`.
GATE_NAME = "news_blackout"


def raw_from_calendar_events(events: Sequence["CalendarEvent"]) -> list[dict[str, Any]]:
    """Rebuild the RAW shape `CalendarScope.scope()` wants from parsed `CalendarEvent`s.

    **`impact` is `impact_raw`, NOT `impact`, and that is the whole point.** `event.impact`
    has already been through `_IMPACT_MAP`; handing it to `scope()` would give the rule the
    normalised value it exists to refuse, and `T-0035`'s third state would be laundered back
    into a two-valued one at the last step.

    `impact_raw` is `None` when the provider sent nothing to keep. That is passed through
    unchanged: `DeclaredMapping.classify(None)` is `UNKNOWN`, which blocks under the declared
    policy — **so an event we cannot read is not silently tradeable here either.**
    """
    return [
        {
            "id": f"{e.currency}-{e.time.isoformat()}-{i}",
            "time": e.time,  # already a datetime; scope() drops anything else in silence
            "currency": e.currency,
            "event": e.event,
            "impact": e.impact_raw,
        }
        for i, e in enumerate(events)
    ]


#: A no-block decision, used only to fill the fields of an UNAVAILABLE context. It is never
#: read as a verdict there: `available=False` makes `would_block` return None first.
_ALLOW = NewsDecision(
    decision="ALLOW", block_reason=None, blocks_new_entries=False, blocks_management=False,
)


@dataclass(frozen=True)
class NewsContext:
    """One bar's news verdict, with the funnel that produced it.

    **The counts are carried, not just the verdict.** *"No blackout"* from a scope that saw
    zero events and *"no blackout"* from a scope that saw eleven and none of them blocking
    are the same word and opposite facts, and the first is what an inert gate looks like.
    """

    now_ny: datetime
    #: How many events the provider gave us, before any filtering.
    raw_count: int
    #: How many survived `CalendarScope.scope()` — currency set and a usable time.
    scoped_count: int
    #: How many of those participate in a blackout at all (`RED_FOLDER`, or `UNKNOWN` under
    #: the declared policy).
    blocking_count: int
    pre: NewsDecision
    post: NewsDecision
    #: `UNKNOWN`-classified events among the scoped ones. Split out because their blocking is
    #: policy rather than data, and the policy is unratified.
    unknown_count: int = 0
    scoped: tuple[ScopedEvent, ...] = field(default=(), repr=False)
    #: False when the calendar could not be READ. See `unavailable`.
    #: GATE-016. RECORDED AND GATING NOTHING -- and that is the rule's own disposition, not
    #: Stage A's caution: `is_red_folder_day` is a DAY flag while GATE-012/013 are MINUTES
    #: gates, nothing reconciles them, and the rule must not pick. Salim round-3 question 6i.
    #: Carried so that if he later rules for reduced size on red-folder days, the stored
    #: telemetry can answer "what would this have been?" without a re-run.
    is_red_folder_day: bool = False
    available: bool = True
    unavailable_reason: str | None = None

    @classmethod
    def unavailable(cls, now_ny: datetime, reason: str) -> "NewsContext":
        """A context for *"we could not take this verdict"* — NOT for *"nothing was on"*.

        **MEASURED, AND IT IS WHY THIS CONSTRUCTOR EXISTS.** `_fetch_from_finnhub` returns
        `[]` — with a warning nobody downstream can see — when no API key is configured, and
        **there is no key in this repository**. Handed straight through, that `[]` scopes to
        zero events, decides ALLOW, and records *"no news blackout"* on every bar the
        platform ever evaluates. **A calendar that was never consulted would have been
        indistinguishable from a quiet news week, in the exact telemetry field built to make
        the difference visible.**

        That is the same fail-open `T-0035` closed at the source, one layer up at the
        consumer, and the API router already refuses it correctly at
        `api/routers/calendar.py:18` with a 503 rather than an empty list.
        """
        return cls(
            now_ny=now_ny, raw_count=0, scoped_count=0, blocking_count=0,
            pre=_ALLOW, post=_ALLOW, available=False, unavailable_reason=reason,
        )

    @property
    def would_block(self) -> bool | None:
        """Would this verdict stop a NEW ENTRY, if it were enforced? `None` == not readable.

        `blocks_new_entries`, never `decision == "BLOCK"`. `GATE-012` addresses new entries
        only and a blackout must never freeze the management of an open position — the rule
        carries that as a field precisely so a consumer cannot collapse it by reading the
        wrong one.

        **`None` rather than `False` when unavailable**, so a consumer that treats this as a
        boolean gets a truthiness answer it cannot mistake for a verdict, and
        `DecisionTrace.observe` records it as `NOT-EVALUATED` rather than as `OBSERVED`.
        """
        if not self.available:
            return None
        return self.pre.blocks_new_entries or self.post.blocks_new_entries

    @property
    def block_reason(self) -> str | None:
        if not self.available:
            return None
        if self.pre.blocks_new_entries:
            return self.pre.block_reason
        if self.post.blocks_new_entries:
            return self.post.block_reason
        return None

    @property
    def detail(self) -> str:
        """One line for `DecisionTrace.reasons`, naming the funnel either way."""
        if not self.available:
            return (
                f"calendar verdict NOT TAKEN — {self.unavailable_reason}. "
                f"This is NOT 'no blackout'."
            )
        # `is False`, NOT `not`. `would_block` is `bool | None` and `not None` is True, so the
        # truthiness form selects THIS branch for an unavailable calendar -- emitting
        # "no news blackout -- 0 blocking of 0 scoped of 0 provider events", which is what a
        # WORKING gate prints on a quiet day. B157: the funnel counts exist to tell an inert
        # gate from a working one, and rendering an absence through them makes the false
        # reading MORE convincing than a bare "no blackout" would have been.
        #
        # The `available` guard above returns first, so this is not reachable today. It is
        # written as `is False` anyway because that is this class's convention everywhere else
        # (`would_block is False`, `would_block is not None` in `observe`) and this line was
        # its single departure -- and because depending on a guard eight lines up is a
        # property of today's line order in a file that has already had one inserted paragraph
        # move a docstring 39 lines. `is False` also fails loudly if a fourth state is added,
        # where `not` would absorb it silently.
        if self.would_block is False:
            return (
                f"no news blackout — {self.blocking_count} blocking of {self.scoped_count} "
                f"scoped of {self.raw_count} provider events"
            )
        deciding = self.pre if self.pre.blocks_new_entries else self.post
        when = iso_ny(deciding.event_time_ny) if deciding.event_time_ny else "unknown time"
        return (
            f"WOULD BLOCK new entries — {self.block_reason} for event "
            f"{deciding.event_id} at {when}"
        )

    def values(self) -> dict[str, Any]:
        """The numbers behind the verdict, for `Gate.values`.

        `DecisionTrace`'s design rule: a gate records the values it compared, not just its
        verdict. Both rule decisions are carried whole — including `blocks_management: False`
        on every blocking path — so a stored trace can be re-read against a question nobody
        has asked yet without re-fetching a calendar we may no longer have access to.
        """
        if not self.available:
            return {
                "now_ny": iso_ny(self.now_ny),
                "evaluated": False,
                "unavailable_reason": self.unavailable_reason,
            }
        return {
            "now_ny": iso_ny(self.now_ny),
            "raw_events": self.raw_count,
            "scoped_events": self.scoped_count,
            "blocking_events": self.blocking_count,
            "unknown_impact_events": self.unknown_count,
            "is_red_folder_day": self.is_red_folder_day,
            "pre_window": self.pre.as_dict(),
            "post_window": self.post.as_dict(),
        }

    def record_on(self, trace: Any) -> None:
        """Write this verdict to a `DecisionTrace` as an UNENFORCED observation.

        `trace.observe`, never `trace.gate`. `gate` sets `blocked_by` on a failing verdict,
        which would make `summary` name this gate as the reason a bar was declined when it
        declined for another reason — and would drop `reasons`' `candidates:` census line,
        which is `B157`'s `B10` half rebuilt by a change that suppresses nothing. **This file
        is where BOTH halves are live**: the census line must EMIT an observed zero, and
        `detail()` must REFUSE to render a funnel of zeros the calendar never supplied.
        """
        trace.observe(GATE_NAME, self.would_block, self.detail, **self.values())


def build_news_context(
    now_utc: datetime,
    events: Sequence["CalendarEvent"],
    *,
    m15_closes: Sequence[datetime] | None = None,
    confluence: bool = False,
) -> NewsContext:
    """Compute the order path's news verdict from already-fetched calendar events.

    SYNC and pure. Every input is a value, so this is unit-testable without a network, a
    Redis, or a clock.
    """
    now_ny = to_ny(now_utc)
    raw = raw_from_calendar_events(events)
    scoped = CalendarScope.scope(raw, confluence=confluence)

    pre = PreEventBlackout.decide(now_ny, scoped)
    # Both windows are ALWAYS evaluated, even when the pre-window already blocks. A record
    # that stopped at the first BLOCK could not answer "would the other rule also have
    # blocked?", and Stage B's count is per-rule.
    post = PostEventBlackout.decide(now_ny, scoped, m15_closes=m15_closes)

    return NewsContext(
        now_ny=now_ny,
        raw_count=len(raw),
        scoped_count=len(scoped),
        blocking_count=sum(1 for e in scoped if e.blocks),
        unknown_count=sum(1 for e in scoped if e.impact_class == "UNKNOWN"),
        pre=pre,
        post=post,
        is_red_folder_day=RedFolderDayFlag.is_red_folder_day(scoped, now_ny.date()),
        scoped=tuple(scoped),
    )


async def fetch_calendar_events() -> tuple[list["CalendarEvent"] | None, str | None]:
    """Today's calendar as `(events, None)`, or `(None, reason)` when it could not be read.

    The reason is returned rather than logged only, because it ends up in the trace: a
    reader six weeks later needs to know whether the gate was silent for a week because the
    news was quiet, because the key was missing, or because the provider was down.

    **`None` IS NOT AN EMPTY CALENDAR.** An empty list means the provider answered and had
    nothing; `None` means we never got an answer. Returning `[]` on failure would make an
    unreachable calendar produce *"no blackout"* — the fail-open `T-0035` closed one layer
    up, rebuilt at the consumer.

    The caller records the `None` case as NOT-EVALUATED rather than silently skipping it, so
    a period of calendar outage is visible in the traces rather than being indistinguishable
    from a quiet news week.
    """
    from app.config import settings  # noqa: PLC0415

    # THE KEY CHECK IS FIRST AND IT IS NOT DEFENSIVE PADDING. `_fetch_from_finnhub` returns
    # `[]` when the key is unset -- it logs a warning and hands back an empty list that is
    # shape-identical to a real quiet day. Measured: this repository has no key, so without
    # this branch EVERY trace the platform writes would say "no news blackout" from a
    # calendar it never called. `api/routers/calendar.py:18` already refuses the same state
    # with a 503; this is the same refusal for the engine.
    if not settings.finnhub_api_key:
        return None, "FINNHUB_API_KEY not configured"
    try:
        from app.services.calendar.finnhub import calendar_service  # noqa: PLC0415

        return await calendar_service.get_today_events(), None
    except Exception as exc:  # noqa: BLE001 - any failure means "we do not know"
        logger.warning("News context: calendar unavailable, verdict NOT taken", error=str(exc))
        return None, f"calendar fetch failed: {exc}"
