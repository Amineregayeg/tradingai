"""T-0137 — the long-only refusal: a SHORT is REFUSED, RECORDED, and COUNTED.

Malek ruled 2026-09-10 that the platform trades **Alpaca, LONG ONLY**, because Alpaca crypto is
non-marginable and not shortable. Measured on real executed trades: **147 shorts against 146
longs**, so roughly half of every decision this engine has ever made cannot be placed.

**THE PROPERTY THESE ARMS EXIST FOR, IN ONE SENTENCE:**

> A run that produced no shorts and a run that produced 147 and had every one refused must be
> DISTINGUISHABLE.

They have the same trade list, the same P&L, the same win rate and the same R-multiples. Every
value assertion available agrees across the two, which is why the load-bearing arm here is a
**differential** (`test_a_long_only_run_and_a_both_directions_run_DIFFER`) rather than a check on
any single number — `B90`'s form: two simulations producing byte-identical telemetry is the
defect, and no assertion about a value catches it.

---

**SCOPE: THE PROPERTY IS `ExecMode.PAPER`-ONLY, AND THAT IS A RULING, NOT AN OVERSIGHT.**

`ExecutionService.execute()` returns two shapes chosen at construction. In `OBSERVE` it returns
**above** `place_order` (`service.py:155`), so a SHORT is never sent and therefore never refused —
it is reported as *observed*, with a size. Recording a venue refusal there would record an event
that did not occur, which is `B215`'s shape: a value nobody observed, written as though someone
had. So the arms below drive `PAPER`, deliberately.

The `OBSERVE` half is not left silent, because silence is the other failure — *observed* and
*refused by the venue* are precisely the two readings this property exists to keep apart. It is
covered by `test_OBSERVE_states_the_venue_capability_as_a_COUNTERFACTUAL`, which asserts the
scope is DECLARED rather than assumed.

---

**WHERE THE REFUSAL ACTUALLY FIRES, AND WHY IT IS NOT IN `alpaca.py`.** The live loop does not
execute against `AlpacaAdapter`. It builds `PaperBroker` or `SimPropFirmBroker`
(`crypto_loop.py:158`/`:166`, and again at `:786`/`:790`) and hands THAT to `ExecutionService`. A
refusal implemented only in the Alpaca module would be unreachable in every paper run — all arms
green, and 147 shorts still filling in a simulation of a venue that cannot take one. The venue
owns the *reason*; the simulators enforce it; `fixed_config` wires the two together.
"""
from __future__ import annotations

import pytest

from app.core.exceptions import BrokerConnectionError, DirectionNotSupported
from app.db.enums import DirectionType, OrderType
from app.services.broker.alpaca import ALPACA_CRYPTO_LONG_ONLY, AlpacaAdapter
from app.services.broker.base import DirectionPolicy, OrderRequest
from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker
from app.services.broker.paper import PaperBroker
from app.services.execution.service import ExecMode, ExecutionService, Signal
from app.services.live import fixed_config as fixed

pytestmark = pytest.mark.asyncio


BTC = "BTC/USD"


def _req(direction: DirectionType, lot: float = 0.001, sl: float = 69_900.0) -> OrderRequest:
    """A request small enough that the PROP-FIRM RULES never fire.

    The defaults are load-bearing: at 0.5 BTC with a 10,000-point stop the potential loss is
    $5,000 on a $5,000 challenge account, so `SimPropFirmBroker` refuses it for
    `would_breach_daily_loss` — a true refusal, for a reason that has nothing to do with the
    venue. An arm measuring the venue constraint against an order the account would refuse
    anyway measures the account.
    """
    return OrderRequest(pair=BTC, direction=direction, order_type=OrderType.MARKET,
                        lot_size=lot, sl=sl)


def _broker(policy: DirectionPolicy | None) -> PaperBroker:
    b = PaperBroker(starting_balance=10_000.0, price_fn=lambda p: 70_000.0,
                    direction_policy=policy)
    b.on_tick(BTC, 70_000.0)
    return b


def _signal(direction: DirectionType) -> Signal:
    """A signal whose stop is on the correct side for its direction.

    Both directions must be able to SIZE, or the differential below would measure the sizing
    guard rather than the venue: `execute()` rejects an entry already through its stop
    (`service.py:144`), and a SHORT with a stop *below* price is exactly that.
    """
    sl = 69_000.0 if direction == DirectionType.LONG else 71_000.0
    return Signal(symbol=BTC, direction=direction, entry=70_000.0, sl=sl, approved=True)


# =====================================================================================
# M-1 — THE REASON IS THE VENUE'S, AND IT NAMES THE CONSTRAINT
# =====================================================================================

async def test_the_refusal_reason_NAMES_THE_VENUE_CONSTRAINT_not_the_refusal():
    """**The mutation this exists for replaces the reason with a generic one.**

    A reason that merely restates the refusal — *"order rejected"* — is indistinguishable from a
    transport failure in `DecisionRecord.rejection_reason` months later (`B375`), and the two
    demand opposite responses: a transport failure is worth retrying, a venue that cannot short
    will refuse the same order forever.

    Asserted as SUBSTANCE rather than as an exact string, so rewording the sentence does not
    turn this red while replacing it with a generic one does.
    """
    reason = ALPACA_CRYPTO_LONG_ONLY.refusal(DirectionType.SHORT)
    assert reason is not None
    low = reason.lower()
    assert "alpaca" in low, "the reason must name the VENUE it belongs to"
    assert "non-marginable" in low and "not shortable" in low, (
        "the reason must name the CONSTRAINT — why this venue cannot take the order"
    )
    assert "not a transient failure" in low or "permanent" in low, (
        "a reader must be able to tell this from an outage without asking anyone"
    )


async def test_the_venue_owns_the_sentence_and_nothing_else_composes_one():
    """One source for the text. A second copy is `B184` with a string, and it drifts the first
    time either is edited — while both keep reading plausibly."""
    assert fixed.VENUE_DIRECTION_POLICY is ALPACA_CRYPTO_LONG_ONLY, (
        "the engine must wire the venue's own policy OBJECT, not a copy of its reason"
    )
    b = _broker(fixed.VENUE_DIRECTION_POLICY)
    assert b.direction_policy is ALPACA_CRYPTO_LONG_ONLY


async def test_the_reason_reaches_the_execution_result_UNALTERED():
    """The value that ends up in `DecisionRecord.rejection_reason` is the venue's, character for
    character. Any layer that summarises it on the way is the defect."""
    svc = ExecutionService(_broker(ALPACA_CRYPTO_LONG_ONLY), ExecMode.PAPER)
    res = await svc.execute(_signal(DirectionType.SHORT))
    assert res["reason"] == ALPACA_CRYPTO_LONG_ONLY.reason


# =====================================================================================
# M-2 — THE REFUSAL IS RECORDED, AND CARRIES ITS DIRECTION
# =====================================================================================

async def test_a_refused_SHORT_produces_a_rejection_the_loop_will_RECORD():
    """`crypto_loop.py:1553` routes any non-FILLED status into `_record_rejected_signal` with
    `res["reason"]`. **So the shape is the contract**, and this asserts the pieces that member
    reads: a status that is not FILLED, a reason, and the direction.

    The recorded ROW is asserted in `tests/integration/test_t0137_refusal_recorded.py` — this
    arm covers the half that can be measured without a database.
    """
    svc = ExecutionService(_broker(ALPACA_CRYPTO_LONG_ONLY), ExecMode.PAPER)
    res = await svc.execute(_signal(DirectionType.SHORT))

    assert res["status"] != "FILLED", "a FILLED status would take the loop's entry branch"
    assert res["reason"], "the loop records `res['reason']`; an empty one records nothing useful"
    assert res["direction"] == "SHORT"
    assert res["venue"] == "alpaca"
    assert "position_id" not in res, "nothing was opened; a position id would be fabricated"
    assert "fill" not in res, "there is no fill price for an order the venue never took"


async def test_the_refusal_happens_BEFORE_anything_is_opened():
    """A refusal that leaves a position behind is worse than no refusal: the record says
    refused and the book says otherwise."""
    broker = _broker(ALPACA_CRYPTO_LONG_ONLY)
    await ExecutionService(broker, ExecMode.PAPER).execute(_signal(DirectionType.SHORT))
    assert await broker.get_positions() == []
    assert broker._fill_log == [], "a refused order must not appear in the fill log"


# =====================================================================================
# M-5 — THE PROPERTY ITSELF: THE TWO RUNS MUST DIFFER
# =====================================================================================

async def _run_strategy(policy: DirectionPolicy | None) -> list[dict]:
    """The SAME sequence of signals against a venue with `policy`. Alternating directions, so a
    long-only venue refuses exactly half."""
    svc = ExecutionService(_broker(policy), ExecMode.PAPER)
    out = []
    for direction in (DirectionType.LONG, DirectionType.SHORT,
                      DirectionType.LONG, DirectionType.SHORT):
        out.append(await svc.execute(_signal(direction)))
    return out


def _outcome_shape(results: list[dict]) -> list[tuple]:
    """THE PROJECTION THE DIFFERENTIAL IS TAKEN OVER, AND CHOOSING IT IS THE WHOLE ARM.

    **`A != B` over whole objects is the wrong shape.** Two runs always differ somewhere — a
    client order id, a timestamp, an ordering — so an arm asserting merely *that the outputs
    differ* collects that for free and passes while the property is broken. This projects onto
    the property and nothing else: what happened to each signal, and why.

    `_negative_control` below is what proves the projection is narrow enough: two runs made
    identical IN THE PROPERTY while still differing incidentally must compare EQUAL here. If
    they do not, this projection is reading noise and every differential built on it is
    decoration.
    """
    return [(r["status"], r.get("reason")) for r in results]


async def test_the_differential_projection_IGNORES_incidental_difference():
    """**THE NEGATIVE CONTROL FOR THE ARM BELOW.** Same venue, same signals, run twice.

    The two runs differ incidentally and unavoidably — each `execute()` mints a fresh
    `client_order_id` and a fresh position id — so if the projection collected those, the
    differential would pass no matter what the venue did.
    """
    a = await _run_strategy(ALPACA_CRYPTO_LONG_ONLY)
    b = await _run_strategy(ALPACA_CRYPTO_LONG_ONLY)

    assert a != b, (
        "the two runs are wholly identical, so this control cannot demonstrate anything — "
        "the raw results must differ incidentally for the projection to be worth testing"
    )
    assert _outcome_shape(a) == _outcome_shape(b), (
        "the projection collects incidental difference, so the differential below would pass "
        "on noise while the long-only property was broken"
    )


async def test_a_long_only_run_and_a_both_directions_run_DIFFER():
    """**THE PROPERTY'S OWN SENTENCE, AND THE REASON THIS ARM IS A DIFFERENTIAL.**

    `B90`'s form. Run the same strategy twice — once against a long-only venue, once against one
    that takes both — and the two outputs must differ IN THE PROPERTY. A value assertion cannot
    catch this: under the collapse being tested, every individual number agrees.

    Paired with `test_the_differential_projection_IGNORES_incidental_difference`, which is the
    negative control: without it, this arm passes on a run id.
    """
    long_only = await _run_strategy(ALPACA_CRYPTO_LONG_ONLY)
    both = await _run_strategy(None)

    shape = _outcome_shape

    assert shape(long_only) != shape(both), (
        "a long-only run and a both-directions run produced byte-identical telemetry — "
        "the two are then indistinguishable to every consumer downstream"
    )
    assert [r["status"] for r in both] == ["FILLED"] * 4
    assert [r["status"] for r in long_only] == ["FILLED", "REJECTED", "FILLED", "REJECTED"]


async def test_the_difference_is_VISIBLE_IN_THE_REFUSALS_not_only_in_the_trade_count():
    """A reader must be able to say WHICH direction was refused and HOW MANY times.

    Counting non-fills is not enough: a run with two entry-drift rejections and a run with two
    venue refusals have the same total, and only one of them means the strategy was never given
    a chance to trade half its signals.
    """
    long_only = await _run_strategy(ALPACA_CRYPTO_LONG_ONLY)
    refused = [r for r in long_only if r["status"] == "REJECTED"]

    assert len(refused) == 2
    assert {r["direction"] for r in refused} == {"SHORT"}, (
        "the direction of each refusal is what makes the split countable at all"
    )
    assert all(r["reason"] == ALPACA_CRYPTO_LONG_ONLY.reason for r in refused)


# =====================================================================================
# M-6 — THE MUST-MISS: THE LONG PATH IS UNAFFECTED
# =====================================================================================

async def test_a_LONG_is_still_taken_sized_and_filled():
    """**Without this, "refuse shorts and record them" is satisfied by refusing everything.**

    `B376-B`'s shape: a raise-on-anything satisfies raise-on-unrecognised and proves nothing
    about the discrimination. The mutation this exists for refuses EVERY direction with the
    venue's reason — every other arm in this file stays green under it.
    """
    broker = _broker(ALPACA_CRYPTO_LONG_ONLY)
    res = await ExecutionService(broker, ExecMode.PAPER).execute(_signal(DirectionType.LONG))

    assert res["status"] == "FILLED"
    assert res["sized_units"] > 0, "a long must still be SIZED, not merely permitted"
    assert res["fill"] == 70_000.0
    assert "reason" not in res
    positions = await broker.get_positions()
    assert len(positions) == 1 and positions[0].direction == DirectionType.LONG


async def test_the_policy_permits_LONG_and_refuses_SHORT_and_the_two_answers_are_different():
    """The discrimination at its source, with both answers asserted. A policy that returned a
    reason for everything would pass any arm that only checked the SHORT."""
    assert ALPACA_CRYPTO_LONG_ONLY.refusal(DirectionType.LONG) is None
    assert ALPACA_CRYPTO_LONG_ONLY.refusal(DirectionType.SHORT) is not None
    assert DirectionType.LONG in ALPACA_CRYPTO_LONG_ONLY.supported
    assert DirectionType.SHORT not in ALPACA_CRYPTO_LONG_ONLY.supported


# =====================================================================================
# M-7 — THE MODE-DEPENDENT HOLE, DECLARED RATHER THAN LEFT SILENT
# =====================================================================================

async def test_OBSERVE_states_the_venue_capability_as_a_COUNTERFACTUAL():
    """**THE PROPERTY IS `PAPER`-SCOPED. THIS ARM ASSERTS THAT THE SCOPE IS DECLARED.**

    In `OBSERVE`, `execute()` returns above `place_order`, so a SHORT is neither sent nor
    refused. Recording a venue refusal here would record an event that did not occur — so this
    does NOT assert one. What it asserts is that the result is not SILENT about it: *observed*
    and *refused by the venue* are the two readings the whole task exists to keep apart, and an
    OBSERVE row reading "would size 0.42 units SHORT" with nothing beside it reads as a trade
    the engine would have taken.

    `venue_would_refuse` is the venue's reason in the subjunctive. It claims nothing about what
    happened, because nothing happened.
    """
    svc = ExecutionService(_broker(ALPACA_CRYPTO_LONG_ONLY), ExecMode.OBSERVE)
    res = await svc.execute(_signal(DirectionType.SHORT))

    assert res["status"] == "observed", "OBSERVE must not start refusing — that is PAPER's job"
    assert res["would_size"] > 0, "the observation still sizes; that is what OBSERVE is for"
    assert res["venue_would_refuse"] == ALPACA_CRYPTO_LONG_ONLY.reason

    long_res = await svc.execute(_signal(DirectionType.LONG))
    assert long_res["venue_would_refuse"] is None, (
        "a counterfactual that fired for both directions would state nothing"
    )


async def test_OBSERVE_against_a_both_directions_venue_says_nothing_at_all():
    """`None` policy means the question was never asked. The key must still be present and
    empty rather than absent, so a consumer cannot read *missing* as *permitted*."""
    svc = ExecutionService(_broker(None), ExecMode.OBSERVE)
    res = await svc.execute(_signal(DirectionType.SHORT))
    assert res["venue_would_refuse"] is None


# =====================================================================================
# BOTH SIMULATORS, BECAUSE `broker_mode` CHOOSES BETWEEN THEM
# =====================================================================================

async def test_the_prop_firm_simulator_refuses_a_SHORT_WITH_THE_SAME_REASON():
    """`crypto_loop.py:152` picks `SimPropFirmBroker` when `broker_mode == "sim"` — **which is
    the production setting** (`fixed_config.BROKER_MODE`). A constraint implemented in only one
    simulator would hold or not hold depending on a setting that has nothing to do with the
    venue.
    """
    assert fixed.BROKER_MODE == "sim", (
        "if this changed, the OTHER simulator is now the production one — check both"
    )
    async def price(pair: str) -> float:
        return 70_000.0

    sim = SimPropFirmBroker(PropFirmRules(starting_balance=5_000.0), price,
                            direction_policy=ALPACA_CRYPTO_LONG_ONLY)
    sim.on_tick(BTC, 70_000.0)

    refused = await sim.place_order(_req(DirectionType.SHORT))
    assert refused["status"] == "REJECTED"
    assert refused["reason"] == ALPACA_CRYPTO_LONG_ONLY.reason

    filled = await sim.place_order(_req(DirectionType.LONG))
    assert filled["status"] == "FILLED"


async def test_the_venue_answer_does_not_depend_on_the_account_being_HEALTHY():
    """A halted account refusing a SHORT would file *"daily loss limit breached"* against an
    order the venue could never have taken — and the direction split would then under-count the
    refusals the ruling caused. The venue's answer comes first.
    """
    async def price(pair: str) -> float:
        return 70_000.0

    sim = SimPropFirmBroker(PropFirmRules(starting_balance=5_000.0), price,
                            direction_policy=ALPACA_CRYPTO_LONG_ONLY)
    sim.on_tick(BTC, 70_000.0)
    sim._halted = True
    sim._breach_reason = "daily loss limit breached"

    refused = await sim.place_order(_req(DirectionType.SHORT))
    assert refused["reason"] == ALPACA_CRYPTO_LONG_ONLY.reason, (
        "the halt reason would misattribute a venue refusal to the account's state"
    )


# =====================================================================================
# THE ADAPTER — TWO REFUSALS THAT MUST NOT COLLAPSE INTO ONE
# =====================================================================================

async def test_the_adapter_refuses_a_SHORT_with_the_venue_reason():
    adapter = AlpacaAdapter(object(), paper=True)
    with pytest.raises(DirectionNotSupported) as exc:
        await adapter.place_order(_req(DirectionType.SHORT))
    assert exc.value.reason == ALPACA_CRYPTO_LONG_ONLY.reason
    assert exc.value.venue == "alpaca"
    assert exc.value.direction == "SHORT"


async def test_the_adapter_refuses_a_LONG_as_UNIMPLEMENTED_and_says_so_differently():
    """**The two refusals must stay distinguishable.** Order placement is not built yet (part C
    of `ALPACA_PROGRAMME.md`); that is a fact about the MEMBER. Long-only is a fact about the
    VENUE. Collapsing them files a permanent venue reason against an order Alpaca would accept.
    """
    adapter = AlpacaAdapter(object(), paper=True)
    with pytest.raises(NotImplementedError) as exc:
        await adapter.place_order(_req(DirectionType.LONG))
    assert "not shortable" not in str(exc.value), (
        "a LONG refused with the venue's short reason is a false statement about the venue"
    )
    assert not isinstance(exc.value, DirectionNotSupported)


async def test_the_adapter_checks_the_VENUE_before_the_UNIMPLEMENTED_refusal():
    """Order matters. Reversed, every SHORT would report *not implemented* — a true statement
    that hides the permanent one, and the record would tell a reader to try again later."""
    adapter = AlpacaAdapter(object(), paper=True)
    with pytest.raises(DirectionNotSupported):
        await adapter.place_order(_req(DirectionType.SHORT))


# =====================================================================================
# THE TYPE ITSELF — WHY A DEDICATED EXCEPTION AND NOT `BrokerError`
# =====================================================================================

async def test_execution_catches_ONLY_the_capability_refusal_and_not_a_broken_connection():
    """**Widening the catch to `BrokerError` would fold an outage into "the venue refused".**

    That is the confusion the dedicated type exists to prevent, and it fails in the expensive
    direction: a network failure filed with a permanent-sounding reason, against a condition
    that clears on its own.
    """
    class Broken(PaperBroker):
        async def place_order(self, request):
            raise BrokerConnectionError("alpaca unreachable", broker="alpaca")

    broker = Broken(starting_balance=10_000.0, price_fn=lambda p: 70_000.0,
                    direction_policy=ALPACA_CRYPTO_LONG_ONLY)
    broker.on_tick(BTC, 70_000.0)
    svc = ExecutionService(broker, ExecMode.PAPER)

    with pytest.raises(BrokerConnectionError):
        await svc.execute(_signal(DirectionType.LONG))


async def test_DirectionNotSupported_is_a_BrokerError_so_existing_handlers_still_see_it():
    """It is narrower, not separate. An API layer that already maps `BrokerError` must not stop
    handling this one."""
    from app.core.exceptions import BrokerError

    exc = DirectionNotSupported(venue="alpaca", direction="SHORT", reason="because")
    assert isinstance(exc, BrokerError)
    assert exc.broker == "alpaca"
