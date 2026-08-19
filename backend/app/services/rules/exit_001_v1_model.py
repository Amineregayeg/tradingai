"""EXIT-001 — the v1 exit model: 70% at 2R, a 30% runner, three ways it ends (T-0022).

The registry entry, quoted whole because every clause of it is load-bearing:

    "Use Option (a) as the default exit model for the live system. The engine should: Take
    70% of the position at 2R. Move the remaining 30% according to the active trade
    management rules and allow it to run until either: the final target is reached, the
    stop-loss is hit, or the end of the trading session (19:00 New York time), at which
    point any remaining position is closed."
    Exactly three terminal conditions for the runner, plus the 2R partial. Each exit event
    must be timestamped and labelled with which condition fired.
    output: exit_events[] each {timestamp_ny, fraction, price, reason}

THIS IS THE FIRST RULE IN THE PROGRAMME THAT GOVERNS WHAT HAPPENS AFTER A TRADE IS TAKEN.
Every rule before it decides admission. Nothing decided management, and the platform's only
exit is `broker/paper.py:on_tick`, which closes a position WHOLE at `sl` or `tp`.

IT IS NOT WIRED, AND THAT IS THE TASK'S OWN CRITERION 7.
Nothing under `app/services/live/` or `app/services/broker/` imports this module. This is the
RULE and its telemetry, evaluated in shadow like every rules task before it. Wiring it into
`paper.py` changes what the platform does with money and is a separate task with its own
deploy. **A green suite here is not a live 70/30 exit.**

WHY THE THREE FRACTIONS ARE READ FROM THE REGISTRY AND ARE NOT PARAMETERS
`partial_fraction: 0.7`, `partial_at_r: 2.0`, `runner_fraction: 0.3` are quoted doctrine with
no range and no alternative offered. A declared parameter is for a value the trader DECLINED
to fix; these are fixed, so a knob here would invent discretion the strategy does not have.
Reading them from the pinned registry rather than typing them as literals makes that
structural: changing the split means changing the contract, which is a reviewed act, and no
call site can pass a different one because no signature accepts one.

WHAT THE MODEL DELIBERATELY DOES NOT DO — EXIT-003 IS `OPEN`
"Move the remaining 30% according to the active trade management rules" names rules that do
not exist. `EXIT-003` is status OPEN and the schema says `PASSIVE` is the only attributable
value until they are defined. So **the runner does not trail, does not scale, and does not
move its stop.** It carries the original stop to one of the three terminal conditions. That
is not a simplification; it is the only reading that is attributable.

WHY A TICK IS ONE PRICE AND NOT AN OHLC BAR
When a bar's high touches the target and its low touches the stop, which fired first is not
recoverable from the bar, and the doctrine says nothing about intrabar precedence. Inventing
one would be a threshold of ours presented as his. `paper.py:on_tick` already takes a single
mark price, so a one-price tick is both the honest shape and the shape the live path uses if
this is ever wired.

THE SCHEMA'S `reason` ENUM IS A SUPERSET OF THIS RULE'S, WHICH IS WHY THE CHECK IS OURS
`TELEMETRY_SCHEMA.json`'s `exit_event.reason` permits six values — the four EXIT-001 names
plus `LIQUIDATION` (SIZE-003 keeps it separate so a margin liquidation is never counted as
the strategy's stop working) and `MANUAL_OVERRIDE` (a human act, outside any model). Both
belong in the schema and neither belongs in EXIT-001's output. **So schema validation cannot
enforce criterion 1** — a record carrying `LIQUIDATION` validates. The vocabulary check has
to live here, in the rule, and `ExitEvent` refuses anything outside the four at construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Iterable, Sequence

from app.services.rules.base import RuleImplementation
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.ny_time import NY, iso_ny, to_ny
from app.services.telemetry.records import (
    RuleEvaluation,
    derived,
    from_declared,
    from_registry,
)

LONG = "LONG"
SHORT = "SHORT"

#: The partial. NOT a terminal condition — it is the event that CREATES the runner, and
#: counting it as one is how "70% at 2R" becomes "close at 2R".
PARTIAL_2R = "PARTIAL_2R"

#: The three, and only three, ways the runner ends. The statement enumerates them with
#: "either ... or ... or", and criterion 1 makes a fourth a defect.
FINAL_TARGET = "FINAL_TARGET"
STOP_HIT = "STOP_HIT"
SESSION_CLOSE = "SESSION_CLOSE"
TERMINAL_REASONS: tuple[str, ...] = (FINAL_TARGET, STOP_HIT, SESSION_CLOSE)

#: Everything EXIT-001 may emit. Four values: three terminal plus the partial.
EXIT_001_REASONS: tuple[str, ...] = (PARTIAL_2R, *TERMINAL_REASONS)

#: In the telemetry schema's enum and NOT in this rule's. Named rather than merely omitted
#: so that the gap is a documented fact instead of something a later reader discovers by
#: diffing. An exit carrying one of these did not come from the v1 model.
SCHEMA_ONLY_REASONS: tuple[str, ...] = ("LIQUIDATION", "MANUAL_OVERRIDE")


def _doctrine() -> dict[str, float]:
    """The three fixed fractions, from the pinned registry. See the module docstring."""
    return contract.rule("EXIT-001")["values"]


#: Bound at import so a typo is an ImportError, not a wrong number in a stored record.
PARTIAL_FRACTION: float = float(_doctrine()["partial_fraction"])
PARTIAL_AT_R: float = float(_doctrine()["partial_at_r"])
RUNNER_FRACTION: float = float(_doctrine()["runner_fraction"])

# The registry is pinned, but it is also edited by people. A split that does not add to the
# whole position would silently leak size, and the leak would look like a rounding artefact
# in the telemetry rather than a contract edit.
if abs((PARTIAL_FRACTION + RUNNER_FRACTION) - 1.0) > 1e-9:
    raise ValueError(
        "EXIT-001's partial_fraction + runner_fraction must be exactly 1.0; the registry "
        f"gives {PARTIAL_FRACTION} + {RUNNER_FRACTION}. A split that does not close the "
        "whole position leaks size into a tranche nothing accounts for."
    )


@dataclass(frozen=True)
class DeclaredSessionClose:
    """The 19:00 New York close, carried as OURS and UNRATIFIED.

    ITS OWN TYPE, not GATE-040's `DeclaredDuration` or GATE-038's `DeclaredWindow`. Those
    carry a duration and a percentage; this carries a LOCAL TIME OF DAY IN A NAMED ZONE,
    which is a different thing with a different failure mode — an offset, not a magnitude.
    Sharing a carrier would dissolve one rule's substance into another's.

    WHY THIS IS DECLARED WHEN THE RULE STATES A NUMBER
    The number is not in doubt; its APPLICABILITY is. `GATE-022` records that 19:00 enters
    the codex only through the EURUSD / algo HT v2.0 strand — "70% of position 2RR, 30%
    (EOD; 19:00)" — and that the two-strand question is "answered by adoption, never by
    argument". Our instrument is BTC and ETH, which trade 24/7, and the Magic Strategy has
    no session-end concept at all. It is question 4 in the pack sent to Salim on 2026-08-15
    and it has not been answered.

    So: implemented as the rule states, defaulting ON, and stamped unratified. NOT defaulted
    off because 24/7 makes it look wrong — a session close that never fires generates no
    evidence, and the evidence is what should answer the question.
    """

    name: str
    local_time: time
    zone: str
    source: str
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        return {
            self.name: self.local_time.strftime("%H:%M"),
            f"{self.name}_zone": self.zone,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_source": self.source,
        }


#: OURS. Unratified. See the class docstring for why a stated number is still declared.
DECLARED_SESSION_CLOSE = DeclaredSessionClose(
    name="session_close_ny",
    local_time=time(19, 0),
    zone="America/New_York",
    source=(
        "EXIT-001 states 'the end of the trading session (19:00 New York time)'. GATE-022 "
        "records that 19:00 enters the codex ONLY through the EURUSD / algo HT v2.0 strand "
        "('70% of position 2RR, 30% (EOD; 19:00)'), and that the two-strand question is "
        "'answered by adoption, never by argument'. Our instrument is BTC/ETH, which trade "
        "24/7, and the Magic Strategy has no session-end concept. Question 4 of the pack "
        "sent to Salim 2026-08-15 — UNANSWERED as of this record. "
        "THE VALUE IS HIS RULING; THE APPLICABILITY TO A 24/7 INSTRUMENT IS QUESTION 4 — "
        "authority_class O tells you a ruling's authority, not its scope. "
        "WHY IT IS ON, REWRITTEN AT T-0050 BECAUSE THE OLD REASON EXPIRED: it used to read "
        "'defaulted ON so that shadow produces the evidence the ruling should rest on', which "
        "held only while it was OFF the deciding path. T-0050 converted shadow into "
        "ENFORCEMENT — this now CLOSES POSITIONS — so evidence-gathering is no longer why it "
        "is on. It is on because Malek authorised the exit cutover and because the 30% runner "
        "has NO final target (TARGET-001 cannot select one), so without a session close the "
        "remainder rides indefinitely, which is worse than closing it on a time whose scope is "
        "unsettled. The daily position-wide close is carried to Malek explicitly: he "
        "authorised the cutover, not separately a hard daily flatten on a EURUSD-derived time."
    ),
)


@dataclass(frozen=True)
class DeclaredFlattenSwitch:
    """OURS. Gates the ACTION only; `GATE-022` keeps evaluating and keeps being recorded."""

    name: str
    enabled: bool
    authority: str
    source: str
    retirement_condition: str
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        return {
            self.name: self.enabled,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_authority": self.authority,
            f"{self.name}_source": self.source,
            f"{self.name}_retirement_condition": self.retirement_condition,
        }


#: OFF BY DEFAULT, and the default is Malek's operating decision rather than a doctrine claim.
#:
#: **The 19:00 flatten is HIS for the EURUSD / algo HT v2.0 strand. THIS FLAG IS OURS.** Salim's
#: question 4 — does a 24/7 instrument flatten daily? — is UNANSWERED, and starting the engine
#: with the flatten live would apply an unratified default to a live paper balance.
#:
#: **AND THE CONSEQUENCE OF TURNING IT OFF IS STATED HERE RATHER THAN DISCOVERED:** `T-0050` built
#: `SESSION_CLOSE` precisely because the 30% runner has NO final target (`TARGET-001` cannot select
#: one). With this flag off, a runner's only terminal condition is `STOP_HIT` — it rides until the
#: stop or until the engine is stopped. *That is the trade Malek chose: an unratified daily flatten
#: on one side, an indefinitely-riding remainder on the other.* Both are recorded; neither is safe
#: in the sense of being obviously right.
DECLARED_SESSION_FLATTEN = DeclaredFlattenSwitch(
    name="session_flatten_enabled",
    enabled=False,
    authority=(
        "[ENGINEERING] OURS. GATE-022's 19:00 flatten is Salim's for EURUSD; whether it applies to "
        "a 24/7 instrument is his question 4 and is UNANSWERED. This switch gates the ORDER, never "
        "the rule: GATE-022 still evaluates, still reaches a verdict, and still lands on the trace."
    ),
    source="Malek's operating decision 2026-08-19, taken so the engine could be STARTED at all",
    retirement_condition=(
        "A CONDITION, NOT A DATE: when Salim rules on whether a 24/7 instrument flattens daily, "
        "THIS FLAG IS DELETED and the ruling decides. The flag must not become the answer — a "
        "default that outlives the question it was waiting on has silently become doctrine."
    ),
)


class SessionClose(RuleImplementation):
    """GATE-022: any position still open at 19:00 New York time is closed.

    **CLAIMED AT T-0050 BECAUSE THE ENGINE STARTED ENFORCING IT.** Until this task nothing
    closed positions on a clock, so the id was legitimately unimplemented. `crypto_loop.
    _close_at_session_end` now performs exactly this rule's statement — *"any position still
    open at 19:00 New York time is closed … exit_reason = SESSION_CLOSE"* — daily and
    position-wide.

    > **A PRODUCER WITH NO DECLARATION is the mirror of `T-0033`'s declared-with-no-producer**,
    > and it is worse in one respect: `check_rule_coverage.py` would report `GATE-022`
    > unimplemented while the engine closed real positions by it, so every coverage figure we
    > publish would UNDERSTATE what the engine does. *An unclaimed enforcement is invisible to
    > the instrument built to find exactly that.*

    The rule DECIDES nothing here — the loop owns the clock, because the loop is the only thing
    that has one. This class carries the id, the declared value and the verdict, so the
    behaviour is attributable to a rule rather than to a method.
    """

    RULE_ID = "GATE-022"

    COVERAGE_NOTE = (
        "Claimed at T-0050, the task that made it ENFORCED. crypto_loop._close_at_session_end "
        "closes every open position at DECLARED_SESSION_CLOSE (19:00 NY), which is this rule's "
        "statement verbatim. The VALUE is Salim's ruling (authority_class O); its APPLICABILITY "
        "to a 24/7 instrument is question 4 of the round-3 pack and is UNANSWERED -- 19:00 "
        "enters the codex only through the EURUSD / algo HT v2.0 strand. Enforced anyway "
        "because the 30% runner has no final target and an indefinitely-riding remainder is "
        "worse; the default's ownership is recorded on DECLARED_SESSION_CLOSE and carried to "
        "Malek. The rule does not own the clock -- the loop does, being the only thing that "
        "has one -- so this reports the verdict and the declared value rather than acting."
    )

    @classmethod
    def evaluate(cls, now_ny: datetime | None = None) -> Any:
        """PASS while the session is open; FAIL once 19:00 NY has passed.

        `now_ny=None` is NOT ASKED and returns `NOT_APPLICABLE` — distinct from "asked, and the
        session is open". A gate that answered PASS for a caller that never supplied a clock
        would be reporting the session open on no evidence.
        """
        values: dict[str, Any] = {
            **DECLARED_SESSION_CLOSE.as_values(),
            "now_ny": iso_ny(now_ny) if now_ny is not None else None,
            "enforced_by": "crypto_loop._close_at_session_end",
        }
        provenance = {
            DECLARED_SESSION_CLOSE.name: from_declared(DECLARED_SESSION_CLOSE.name),
            f"{DECLARED_SESSION_CLOSE.name}_ratified": derived(
                "the VALUE is his ruling; the APPLICABILITY to a 24/7 instrument is question 4"
            ),
            f"{DECLARED_SESSION_CLOSE.name}_zone": derived(
                "America/New_York — the clock the ruling is stated in, DST-aware. Emitted "
                "because '19:00' without a zone is not a time"
            ),
            f"{DECLARED_SESSION_CLOSE.name}_source": derived("GATE-022 statement + GATE-022 note"),
            "now_ny": derived("caller's clock; None means NOT ASKED"),
            "enforced_by": derived("the loop owns the clock; this rule owns the id"),
        }
        if now_ny is None:
            return cls.evaluation("NOT_APPLICABLE", values=values, value_provenance=provenance)
        past = now_ny.timetz().replace(tzinfo=None) >= DECLARED_SESSION_CLOSE.local_time
        values["session_closed"] = past
        provenance["session_closed"] = derived("now_ny at or after the declared close")
        return cls.evaluation("FAIL" if past else "PASS",
                              values=values, value_provenance=provenance)


def next_session_close_after(ts: datetime) -> datetime:
    """The first 19:00 New York instant STRICTLY after `ts`.

    A BOUNDARY CROSSING, NOT A TIME-OF-DAY COMPARISON, and the difference is a real defect
    rather than a refinement. `to_ny(tick).time() >= 19:00` looks equivalent and fails
    whenever the feed has a gap across the boundary: a runner whose last tick before the gap
    is 18:55 and whose next is 01:00 the following morning reads 01:00 < 19:00, no close
    fires, and the position survives an extra full day. On a 24/7 instrument the path does
    not stop at the session boundary, so this is the normal case rather than a pathology.

    THE DAY IS ADDED ON THE WALL CLOCK, NOT AS 24 HOURS. Adding `timedelta(days=1)` to an
    aware New York datetime adds 24 absolute hours, which across a DST change lands on 18:00
    or 20:00 local — the exact class of bug GATE-023 exists to prevent, reintroduced one
    layer up from the conversion it forbids. So the day is added to the naive wall clock and
    re-localised.

    THAT RE-LOCALISATION IS SAFE BECAUSE OF THE CONSTANT, NOT BECAUSE OF THE TECHNIQUE, and
    the distinction matters to whoever changes the constant next. Spring-forward DELETES
    02:00–03:00 and fall-back DUPLICATES 01:00–02:00; a naive wall-clock time inside either
    window has no unique instant, and `replace(tzinfo=NY)` would silently return a
    nonexistent or ambiguous one. 19:00 is in neither window, so it is unambiguous every day
    of the year. **Move the session close to anything between 01:00 and 03:00 and this
    function needs a fold/gap policy before it is correct again.**
    """
    local = to_ny(ts)
    close = DECLARED_SESSION_CLOSE.local_time
    boundary = local.replace(
        hour=close.hour, minute=close.minute, second=0, microsecond=0
    )
    if boundary <= local:
        naive = boundary.replace(tzinfo=None) + timedelta(days=1)
        boundary = naive.replace(tzinfo=NY)
    return boundary


class DegenerateRunner(ValueError):
    """The final target is INSIDE the 2R partial level, so the runner would run backwards.

    STILL RAISED, and the scope is now narrower than it was — see `TradePlan.__post_init__`.

    **Salim ruled the EQUALITY case in round 3** — *"Take it, flag `DEGENERATE_RUNNER`, log 70%
    + 30% both closing at 2R (i.e. 100% out at target). No invented minimum gap."* — so a target
    sitting exactly ON the 2R level is now TAKEN and FLAGGED rather than refused.

    **He did not rule the target-inside case, and it is a different fact:** at equality the
    runner runs zero distance, and inside it would have to run in the wrong direction to reach
    a target already passed. **Extending his ruling to cover it would be inventing the treatment
    of a case he did not address**, which is the same move `GATE-031` forbids one step over —
    so that case still refuses the plan.
    """


@dataclass(frozen=True)
class TradePlan:
    """The inputs EXIT-001 declares: entry price, stop price, and a final target.

    THE TARGET IS AN INPUT AND IS NOT CHOSEN HERE. EXIT-004 / TARGET-001 / TARGET-003 select
    and constrain it and are the next task; EXIT-001 CONSUMES one. The 2R level is derived,
    not supplied, because it is a function of entry and stop and nothing else.
    """

    side: str
    entry: float
    stop: float
    final_target: float

    def __post_init__(self) -> None:
        if self.side not in (LONG, SHORT):
            raise ValueError(f"side must be {LONG} or {SHORT}, got {self.side!r}")
        if self.r_distance <= 0:
            raise ValueError(
                f"a {self.side} entry at {self.entry} with a stop at {self.stop} has "
                "non-positive risk — R is the unit every level here is measured in, so a "
                "zero or inverted stop makes 2R meaningless rather than merely wrong"
            )
        # THE BOUNDARY MOVED IN ROUND 3, AND ONLY THE EQUALITY CASE MOVED.
        #
        # This used to refuse `<= 0` — target at OR inside the 2R level. Salim ruled the
        # EQUALITY case: "Take it, flag DEGENERATE_RUNNER, log 70% + 30% both closing at 2R
        # (i.e. 100% out at target). No invented minimum gap." So `== 0` is now a legal plan
        # that carries a flag, and `simulate()` emits both events at one price and one
        # timestamp in a deterministic order.
        #
        # `< 0` STILL REFUSES, and the distinction is not caution. At equality the runner runs
        # zero distance; inside, it would have to run BACKWARDS to reach a target price has
        # already passed. He ruled the first and not the second, and extending a ruling to a
        # case it does not name is inventing the treatment — GATE-031's own prohibition, one
        # step over.
        gap = (self.final_target - self.partial_level) * self.sign
        if gap < 0:
            raise DegenerateRunner(
                f"final target {self.final_target} is INSIDE the 2R level "
                f"{self.partial_level} for a {self.side} — the runner would have to run "
                "backwards. Round 3 ruled the EQUALITY case (take it, flag it); this is not "
                "that case, and GATE-031 says the engine must not silently invent a "
                "treatment for one it does not cover."
            )

    # -- geometry ------------------------------------------------------------------
    @property
    def sign(self) -> float:
        """+1 for a long, -1 for a short. Every level below is entry + sign * distance."""
        return 1.0 if self.side == LONG else -1.0

    @property
    def r_distance(self) -> float:
        """One R, in price. Always positive."""
        return (self.entry - self.stop) * self.sign

    @property
    def partial_level(self) -> float:
        """Where the 70% comes off. `partial_at_r` is doctrine, read from the registry."""
        return self.entry + self.sign * PARTIAL_AT_R * self.r_distance

    def _beyond(self, price: float, level: float) -> bool:
        """Has `price` reached or passed `level` in the trade's favourable direction?"""
        return (price - level) * self.sign >= 0

    def _at_or_worse(self, price: float, level: float) -> bool:
        """Has `price` reached or passed `level` in the trade's ADVERSE direction?"""
        return (level - price) * self.sign >= 0

    def realised_r(self, price: float) -> float:
        """P&L at `price`, in R. Negative below entry for a long, above it for a short."""
        return (price - self.entry) * self.sign / self.r_distance

    @property
    def runner_distance(self) -> float:
        """How far the 30% has to run, in price. Zero is the degenerate case."""
        return (self.final_target - self.partial_level) * self.sign

    @property
    def degenerate_runner(self) -> bool:
        """`computed_rr.degenerate_runner` — the schema field at `TELEMETRY_SCHEMA.json:2553`.

        **THE COLLAPSE AND THE FLAG ARE DIFFERENT PREDICATES, and Salim's round-3 ruling says
        so:** *the epsilon governs the FLAG only, not the collapse.*

            collapse   `runner_distance == 0` — exact. Both events fire at one price because
                       the two levels ARE one price. No epsilon can widen an identity.
            flag       `runner_distance <= eps` — this property.

        **The eps is READ from `GATE-029`'s existing `DECLARED_EPS`, not redeclared here.** A
        second declaration of one parameter is `GATE-011`'s shape, and that one already carries
        its authority (`ENGINEERING — this engine, T-0030. Not ratified by Salim`) and its
        reasoning.

        **At its current value of `0.0` the two predicates coincide**, so today the flag fires
        exactly when the collapse happens. A ratification to a positive eps widens the FLAG and
        leaves the collapse untouched — which is why the split costs nothing to build now.

        *(The round-3 pack cites `K-14`'s `planned_rr <= 2.05` as background. `K-14` does not
        exist in this repository — measured, with `K-24` as the control arm proving the search
        works — so it is a candidate RATIFICATION of this same parameter rather than a second
        one, and adopting it silently would install a value under Salim's name that he may not
        have aimed at this engine.)*
        """
        from app.services.rules.gate_029_stop_flags import DECLARED_EPS  # noqa: PLC0415

        return self.runner_distance <= float(DECLARED_EPS.value)


@dataclass(frozen=True)
class ExitEvent:
    """One tranche leaving the position, labelled with which condition fired.

    `reason` IS VALIDATED HERE AND THE VALIDATION IS THE POINT. The telemetry schema permits
    six reasons and EXIT-001 permits four, so a record carrying `LIQUIDATION` validates
    against the schema and violates the rule. Criterion 1's "a fifth reason is a defect" can
    therefore only be enforced at construction, which is what this does.
    """

    timestamp: datetime
    fraction: float
    price: float
    reason: str
    realised_r: float | None = None

    def __post_init__(self) -> None:
        if self.reason not in EXIT_001_REASONS:
            extra = (
                " — it is in the telemetry schema's enum but NOT in EXIT-001's; the schema "
                "is deliberately wider (SIZE-003 keeps LIQUIDATION separate from STOP_HIT, "
                "and MANUAL_OVERRIDE is a human act outside any model)"
                if self.reason in SCHEMA_ONLY_REASONS
                else ""
            )
            raise ValueError(
                f"{self.reason!r} is not one of EXIT-001's four exit reasons "
                f"{EXIT_001_REASONS}{extra}"
            )
        if self.timestamp.tzinfo is None:
            raise ValueError(
                "naive timestamp on an exit event. The record's timestamp_ny is a NY local "
                "time WITH offset and GATE-023 forbids acquiring a zone implicitly."
            )
        if not 0.0 < self.fraction <= 1.0:
            raise ValueError(
                f"exit fraction {self.fraction} is outside (0, 1]; an exit of zero size is "
                "not an exit and the schema bounds the field at 1"
            )

    def as_dict(self) -> dict[str, Any]:
        """The schema's `exit_event` shape. `rule_id` names which rule produced it."""
        out: dict[str, Any] = {
            "timestamp_ny": iso_ny(self.timestamp),
            "fraction": self.fraction,
            "price": self.price,
            "reason": self.reason,
            "rule_id": V1ExitModel.RULE_ID,
        }
        if self.realised_r is not None:
            out["realised_r"] = round(self.realised_r, 4)
        return out

    @property
    def is_terminal(self) -> bool:
        return self.reason in TERMINAL_REASONS


@dataclass(frozen=True)
class ExitSimulation:
    """What the model did over one price path.

    `runner_open` DISTINGUISHES "the path ran out" FROM "the runner ended". A path that stops
    while the position is still open has produced no terminal condition, and that is not the
    same as a runner ending without one — the first is an incomplete observation, the second
    is criterion 1's defect. Collapsing them would make an unfinished trade read as a broken
    rule, which is this project's signature failure in the opposite direction.
    """

    plan: TradePlan
    events: tuple[ExitEvent, ...]
    runner_open: bool
    remaining_fraction: float
    session_close_active: bool
    #: HOW MANY TICKS THE MODEL ACTUALLY SAW. The denominator (B90).
    #:
    #: Without it, a zero-tick path and a 500-tick path where nothing ever fires emit a
    #: BYTE-IDENTICAL `NOT_APPLICABLE` record: same empty `exit_events`, same
    #: `runner_open=True`, same `remaining_fraction=1.0`. So "the path ran out" and "there
    #: was no path" are one record, and B84's remedy — report the number of records examined
    #: and make ZERO a distinct outcome — was applied in EXIT-002 (`tranche_count`) and
    #: missed here, in the same commit.
    #:
    #: It bites on precisely what the session close was built to produce. Criterion 5's
    #: rationale is a measurable record of HOW OFTEN a runner would have been cut, and how
    #: often is a RATE: `runner_cut_by_session_close` is the numerator, and "47 runners were
    #: cut" cannot ratify B87's parameter without "out of how many observed."
    ticks_seen: int = 0

    @property
    def partial(self) -> ExitEvent | None:
        return next((e for e in self.events if e.reason == PARTIAL_2R), None)

    @property
    def terminal(self) -> ExitEvent | None:
        return next((e for e in self.events if e.is_terminal), None)

    def as_exit_events(self) -> list[dict[str, Any]]:
        """The `exits` array of a `trade_execution` record."""
        return [e.as_dict() for e in self.events]


class V1ExitModel(RuleImplementation):
    """EXIT-001: 70% at 2R, a 30% runner, and exactly three ways the runner ends."""

    RULE_ID = "EXIT-001"

    COVERAGE_NOTE = (
        "THE MODEL AND ITS TELEMETRY, NOT A WIRED EXIT PATH. Nothing under live/ or broker/ "
        "imports this module; `broker/paper.py:on_tick` still closes positions WHOLE at "
        "sl/tp, and `PaperPosition` has a single `units`/`sl`/`tp` with no way to represent "
        "a tranched position. Wiring is a live behaviour change and a separate task. "
        "The runner is PASSIVE — it does not trail, scale or move its stop — because "
        "'the active trade management rules' the statement defers to are EXIT-003, which is "
        "status OPEN and has no attributable value but PASSIVE. The 19:00 New York session "
        "close is implemented AS STATED and carried as a DECLARED PARAMETER marked "
        "UNRATIFIED: GATE-022 records that 19:00 reaches the codex only through the EURUSD "
        "strand, our instrument trades 24/7, and Salim was asked on 2026-08-15 and has not "
        "answered. A final target at or inside the 2R level raises DegenerateRunner rather "
        "than being silently widened — GATE-031 governs that gap and needs GATE-025."
    )

    @classmethod
    def simulate(
        cls,
        plan: TradePlan,
        ticks: Iterable[tuple[datetime, float]],
        *,
        session_close_active: bool = True,
    ) -> ExitSimulation:
        """Walk a price path and emit the exit events the model produces.

        `session_close_active` is the ONE knob, and it exists because the 19:00 close is a
        declared parameter whose applicability to a 24/7 instrument is an open question. It
        defaults to ON — implemented as the rule states. There is deliberately no parameter
        for the 70/30 split or the 2R level; see the module docstring.

        ORDER WITHIN A TICK, AND WHY IT IS THIS WAY:
        1. The partial, if 2R has been reached and it has not already fired. It is the
           earlier level, and it CREATES the runner rather than ending it.
        2. The price terminals — stop or target. With a single mark price these are on
           opposite sides of entry and cannot both be true, so no precedence is invented.
        3. The session close, last, because the statement says "any REMAINING position is
           closed". What price did at 19:00 is what happened; the close sweeps the rest.

        THE CLOSE IS STAMPED WITH THE TICK THAT CLOSED IT, NOT THE BOUNDARY IT CROSSED.
        When a feed gap carries the path from 18:55 straight to 01:00, the boundary crossed
        is 19:00 but the only price that exists is the 01:00 one. Stamping 19:00 while
        carrying the 01:00 price would put a fill in the record at an instant when that
        price was not available — LOOKAHEAD IN THE TELEMETRY rather than in the engine, and
        invisible to any test that only asserts a close fired. So `timestamp` and `price`
        always come from the same tick, and a reconstruction from telemetry sees a fill it
        could actually have got.

        A TICK EXACTLY AT 19:00 OPENS A FULL SESSION, IT DOES NOT CLOSE IMMEDIATELY.
        `next_session_close_after` is strictly-after, so a position whose first tick is
        19:00:00 NY runs to the NEXT 19:00. The alternative — `>=`, closing on the entry
        tick for a zero-length hold — is equally defensible from the text and differs by a
        whole session of exposure. Nothing in the doctrine settles it; this is a choice, and
        it is pinned by a test rather than left to be rediscovered.
        """
        events: list[ExitEvent] = []
        remaining = 1.0
        partial_taken = False
        #: Fixed from the first tick — the moment the position is being carried from. A
        #: boundary recomputed per tick would never be crossed, because every tick is
        #: trivially before its own next 19:00.
        next_close: datetime | None = None
        ticks_seen = 0

        for ts, price in ticks:
            ticks_seen += 1
            if remaining <= 0.0:
                break
            price = float(price)
            if next_close is None:
                next_close = next_session_close_after(ts)

            # 1. The partial. `partial_taken` is what makes a second one unconstructible by
            #    this model — EXIT-002's check covers sequences built anywhere else.
            if not partial_taken and plan._beyond(price, plan.partial_level):
                partial_taken = True
                remaining -= PARTIAL_FRACTION
                events.append(
                    ExitEvent(
                        timestamp=ts,
                        fraction=PARTIAL_FRACTION,
                        price=price,
                        reason=PARTIAL_2R,
                        realised_r=plan.realised_r(price),
                    )
                )

            # 2. The price terminals, against whatever remains.
            terminal: str | None = None
            if plan._at_or_worse(price, plan.stop):
                terminal = STOP_HIT
            elif plan._beyond(price, plan.final_target):
                terminal = FINAL_TARGET

            # 3. The session close, on what is left. A REAL zone conversion: 19:00 NY is
            #    23:00 UTC in EDT and 00:00 UTC in EST, and comparing UTC hours against a
            #    constant would be right for half the year. GATE-023 forbids exactly that.
            if terminal is None and session_close_active and ts >= next_close:
                terminal = SESSION_CLOSE

            if terminal is not None:
                events.append(
                    ExitEvent(
                        timestamp=ts,
                        fraction=round(remaining, 10),
                        price=price,
                        reason=terminal,
                        realised_r=plan.realised_r(price),
                    )
                )
                remaining = 0.0
                break

        return ExitSimulation(
            plan=plan,
            events=tuple(events),
            runner_open=remaining > 0.0,
            ticks_seen=ticks_seen,
            remaining_fraction=round(remaining, 10),
            session_close_active=session_close_active,
        )

    @classmethod
    def evaluate(cls, sim: ExitSimulation) -> RuleEvaluation:
        """EXIT-001's telemetry for one simulated exit.

        PASS  — the position fully closed and did so on one of the three terminal conditions.
        FAIL  — it closed on something else, or a reason outside the four appeared.
        NOT_APPLICABLE — the price path ended with the position still open. Silence is not a
        pass (C-04): no terminal condition fired, so there is nothing to assert about which
        one did, and saying PASS here would report an unfinished trade as a conforming exit.
        """
        plan = sim.plan
        terminal = sim.terminal
        reasons = [e.reason for e in sim.events]

        values: dict[str, Any] = {
            "exit_events": sim.as_exit_events(),
            "partial_fraction": PARTIAL_FRACTION,
            "partial_at_r": PARTIAL_AT_R,
            "runner_fraction": RUNNER_FRACTION,
            "entry": plan.entry,
            "stop": plan.stop,
            "final_target": plan.final_target,
            "r_distance": round(plan.r_distance, 10),
            "partial_level": round(plan.partial_level, 10),
            "partial_taken": sim.partial is not None,
            "runner_open": sim.runner_open,
            "ticks_seen": sim.ticks_seen,
            "remaining_fraction": sim.remaining_fraction,
            "terminal_reason": terminal.reason if terminal is not None else None,
            "terminal_conditions": list(TERMINAL_REASONS),
            "session_close_active": sim.session_close_active,
            **DECLARED_SESSION_CLOSE.as_values(),
        }
        # The R the runner was carrying when the session cut it. This is the number the
        # ratification question needs (criterion 5-ii) and it is worthless if it is only
        # recoverable by re-deriving the trade, so it is named rather than implied.
        if terminal is not None and terminal.reason == SESSION_CLOSE:
            values["runner_cut_by_session_close"] = True
            values["runner_r_at_session_close"] = round(
                terminal.realised_r if terminal.realised_r is not None else 0.0, 4
            )

        provenance: dict[str, Any] = {
            "exit_events": derived("EXIT-001 model walked over the supplied price path"),
            "partial_fraction": from_registry("EXIT-001", "values.partial_fraction"),
            "partial_at_r": from_registry("EXIT-001", "values.partial_at_r"),
            "runner_fraction": from_registry("EXIT-001", "values.runner_fraction"),
            "entry": derived("trade plan input"),
            "stop": derived("trade plan input"),
            "final_target": derived("trade plan input — EXIT-004/TARGET-001 select it"),
            "r_distance": derived("(entry - stop) * sign"),
            "partial_level": derived("entry + sign * partial_at_r * r_distance"),
            "partial_taken": derived("a PARTIAL_2R event is present in exit_events"),
            "runner_open": derived("remaining_fraction > 0 after the path ended"),
            "ticks_seen": derived(
                "count of ticks the model observed — the DENOMINATOR, without which a "
                "zero-tick path and a long path where nothing fired are one record (B90)"
            ),
            "remaining_fraction": derived("1.0 - sum(exit_events[].fraction)"),
            "terminal_reason": derived("the terminal event's reason, or null if still open"),
            "terminal_conditions": from_registry("EXIT-001", "output"),
            "session_close_active": derived(
                "declared parameter session_close_ny — OURS, unratified"
            ),
            **{
                k: derived("EXIT-001 declared session close — OURS, unratified")
                for k in DECLARED_SESSION_CLOSE.as_values()
            },
            "runner_cut_by_session_close": derived("terminal_reason == SESSION_CLOSE"),
            "runner_r_at_session_close": derived(
                "(exit price - entry) * sign / r_distance at the session close"
            ),
            # The two keys the verdict branches add. Declared HERE rather than beside each
            # branch because `set(values) == set(value_provenance)` is a contract every
            # record must meet, and a branch that adds a value is exactly where it gets
            # forgotten — this rule's NOT_APPLICABLE record failed that check until a
            # mutation run surfaced it on an unrelated test.
            "not_applicable_reason": derived("no terminal condition fired on this path"),
            "violations": derived("EXIT-001 conformance check over exit_events"),
        }

        def emit(verdict: str) -> RuleEvaluation:
            """Filter provenance to the keys actually present, at the moment of return."""
            return cls.evaluation(
                verdict,
                values=values,
                value_provenance={k: v for k, v in provenance.items() if k in values},
                declared_parameter_used=DECLARED_SESSION_CLOSE.name,
            )

        bad_reasons = [r for r in reasons if r not in EXIT_001_REASONS]
        if bad_reasons:
            # Unreachable through `simulate` — ExitEvent refuses these at construction — so
            # this is the guard for a sequence assembled elsewhere and handed to us.
            values["violations"] = [
                f"reason {r!r} is not one of EXIT-001's four" for r in bad_reasons
            ]
            return emit("FAIL")

        if sim.runner_open:
            values["not_applicable_reason"] = (
                "the price path ended with the position still open — no terminal condition "
                "fired, so there is nothing to attribute. NOT a runner that ended without "
                "one of the three, which would be a violation."
            )
            return emit("NOT_APPLICABLE")

        if terminal is None:
            values["violations"] = [
                "the position is fully closed but no terminal condition is recorded — "
                "criterion 1's 'a runner that ends without one of the three'"
            ]
            return emit("FAIL")

        return emit("PASS")


def ticks_from_prices(
    start: datetime, prices: Sequence[float], *, step_minutes: int = 5
) -> list[tuple[datetime, float]]:
    """Fixture helper: evenly spaced ticks from `start`. Aware datetimes only."""
    from datetime import timedelta

    if start.tzinfo is None:
        raise ValueError("ticks_from_prices needs an aware start (GATE-023)")
    return [
        (start + timedelta(minutes=step_minutes * i), float(p))
        for i, p in enumerate(prices)
    ]
