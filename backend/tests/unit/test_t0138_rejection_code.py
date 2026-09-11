"""T-0138 part 3 — `B392`: a structured `rejection_code` so the count is not keyed on prose.

`GROUP BY signal_dir` over `REJECTED` cannot answer *M shorts refused by venue*: `rejection_reason`
is free `Text`, so a count matching it would be keyed on **a sentence the venue chose**, returning a
confident zero the day the wording changes rather than failing.

**THE CODE IS ASSIGNED AT THE DECISION SITE AND NEVER DERIVED FROM THE PROSE**, and the strongest
argument for that is arithmetic rather than principle: `service.py:130` and `:153` emit the
BYTE-IDENTICAL string `"non-positive size / stop"` for two different decisions with opposite
remedies. **The text cannot separate them even in principle.**
"""
from __future__ import annotations

import pytest

from app.db.enums import DirectionType, OrderType
from app.models.decision_record import (
    REJECTION_BROKER_UNAVAILABLE,
    REJECTION_CODES,
    REJECTION_CODES_UNKNOWN,
    REJECTION_DEGENERATE_STOP,
    REJECTION_ENTRY_DRIFT,
    REJECTION_NON_POSITIVE_SIZE,
    REJECTION_PROP_FIRM_TARGET_REACHED,
    REJECTION_PROP_FIRM_WOULD_BREACH_DAILY_LOSS,
    REJECTION_THROUGH_STOP,
    REJECTION_UNCLASSIFIED,
    REJECTION_UNCODED_LEGACY,
    REJECTION_VENUE_DIRECTION_UNSUPPORTED,
)
from app.services.broker.alpaca import ALPACA_CRYPTO_LONG_ONLY
from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker
from app.services.broker.base import OrderRequest
from app.services.broker.live_loop_proxy import LiveLoopBrokerProxy
from app.services.broker.paper import PaperBroker
from app.services.execution.service import ExecMode, ExecutionService, Signal

pytestmark = pytest.mark.asyncio

BTC = "BTC/USD"


def _broker(policy=None, **kw):
    b = PaperBroker(starting_balance=10_000.0, price_fn=lambda p: 70_000.0,
                    direction_policy=policy, **kw)
    b.on_tick(BTC, 70_000.0)
    return b


def _sig(direction=DirectionType.LONG, entry=70_000.0, sl=69_000.0):
    return Signal(symbol=BTC, direction=direction, entry=entry, sl=sl, approved=True)


async def _execute(sig, policy=None, broker=None):
    return await ExecutionService(broker or _broker(policy), ExecMode.PAPER).execute(sig)


# =====================================================================================
# M-1 — THE CODE COMES FROM THE DECISION, NOT FROM THE TEXT
# =====================================================================================

async def test_two_decision_sites_emitting_ONE_IDENTICAL_STRING_get_DIFFERENT_codes():
    """**`M-1`'s must-miss, and the material is real rather than contrived.**

    An arm that only reads the code's VALUE survives a prose-derived implementation whenever the
    text happens to contain the matchable word. So this drives two decisions whose prose is
    **byte-identical** and requires the codes to differ — which no text match can do.

        :130  intended_risk <= 0  entry == sl      DEGENERATE_STOP   (a strategy defect)
        :153  lot_size <= 0       equity vs width  NON_POSITIVE_SIZE (size down)
    """
    degenerate = await _execute(_sig(entry=70_000.0, sl=70_000.0))
    # A stop so wide the size rounds to zero — the other site, same sentence.
    tiny = await _execute(_sig(entry=70_000.0, sl=70_000.0 - 1e12))

    assert degenerate["reason"] == tiny["reason"], (
        "the premise of this arm is that the PROSE is identical; if it is not, the arm is no "
        "longer testing what it says"
    )
    assert degenerate["rejection_code"] == REJECTION_DEGENERATE_STOP
    assert tiny["rejection_code"] == REJECTION_NON_POSITIVE_SIZE
    assert degenerate["rejection_code"] != tiny["rejection_code"], (
        "one identical sentence, two decisions — no text match could ever separate these"
    )


async def test_a_refusal_whose_PROSE_LACKS_the_keyword_is_still_coded():
    """The other half of `M-1`'s must-miss: the code must not depend on the reason containing a
    matchable word. The venue's sentence is long prose about margin, and nothing in it is the
    code."""
    res = await _execute(_sig(DirectionType.SHORT, sl=71_000.0), policy=ALPACA_CRYPTO_LONG_ONLY)

    assert res["rejection_code"] == REJECTION_VENUE_DIRECTION_UNSUPPORTED
    assert REJECTION_VENUE_DIRECTION_UNSUPPORTED not in res["reason"], (
        "the code appears verbatim in the prose, so this arm cannot distinguish an assigned code "
        "from a parsed one — pick a different fixture"
    )


async def test_every_ordinary_decision_site_carries_its_own_code():
    """One member per DECISION, not per sentence."""
    no_price = await _execute(_sig(), broker=PaperBroker(starting_balance=10_000.0,
                                                        price_fn=lambda p: 0.0))
    drift = await _execute(_sig(entry=60_000.0, sl=59_900.0))
    through = await _execute(_sig(entry=70_000.0, sl=70_500.0))

    assert no_price["rejection_code"] == "NO_REFERENCE_PRICE"
    assert drift["rejection_code"] == REJECTION_ENTRY_DRIFT
    assert through["rejection_code"] == REJECTION_THROUGH_STOP


# =====================================================================================
# M-8 — THE PROP-FIRM FAMILY MUST NOT COLLAPSE INTO ONE BUCKET
# =====================================================================================

async def test_a_PASSED_challenge_is_not_counted_as_a_rejection_of_the_same_kind_as_a_breach():
    """**A single `PROP_FIRM_RULE` code would be LOSSIER THAN THE STRING IT REPLACES** — the one
    direction a structuring change must never go.

    `profit_target_reached` is a **SUCCESS**. Bucketing a passed challenge with a drawdown breach
    is not merely lossy, it is wrong in the flattering direction. *Already halted* and *would
    breach* also carry opposite remedies — stop the engine against size down.
    """
    async def price(pair: str) -> float:
        return 70_000.0

    req = OrderRequest(pair=BTC, direction=DirectionType.LONG, order_type=OrderType.MARKET,
                       lot_size=0.001, sl=69_900.0)

    passed = SimPropFirmBroker(PropFirmRules(starting_balance=5_000.0), price)
    passed.on_tick(BTC, 70_000.0)
    passed._halted, passed._passed = True, True

    breached = SimPropFirmBroker(PropFirmRules(starting_balance=5_000.0), price)
    breached.on_tick(BTC, 70_000.0)
    breached._halted, breached._breach_reason = True, "max_drawdown"

    a = await passed.place_order(req)
    b = await breached.place_order(req)

    assert a["rejection_code"] == REJECTION_PROP_FIRM_TARGET_REACHED
    assert b["rejection_code"] == "PROP_FIRM_HALTED_MAX_DRAWDOWN"
    assert a["rejection_code"] != b["rejection_code"], (
        "a PASSED challenge and a DRAWDOWN BREACH landed in one bucket — the success reads as a "
        "failure, which is the flattering direction"
    )


async def test_HALTED_and_WOULD_BREACH_are_different_codes():
    """Opposite remedies: halted means stop the engine, would-breach means size down."""
    async def price(pair: str) -> float:
        return 70_000.0

    sim = SimPropFirmBroker(PropFirmRules(starting_balance=5_000.0), price)
    sim.on_tick(BTC, 70_000.0)
    huge = OrderRequest(pair=BTC, direction=DirectionType.LONG, order_type=OrderType.MARKET,
                        lot_size=10.0, sl=60_000.0)
    would = await sim.place_order(huge)

    sim._halted, sim._breach_reason = True, "daily_loss_limit"
    halted = await sim.place_order(huge)

    assert would["rejection_code"] == REJECTION_PROP_FIRM_WOULD_BREACH_DAILY_LOSS
    assert halted["rejection_code"] == "PROP_FIRM_HALTED_DAILY_LOSS"
    assert would["rejection_code"] != halted["rejection_code"]


# =====================================================================================
# M-2 / M-3 — THE DEFAULT ALARMS, AND THE TWO UNKNOWNS STAY APART
# =====================================================================================

async def test_the_two_unknowns_are_DIFFERENT_values():
    """`UNCODED_LEGACY` predates the field — finite, shrinking, a migration marker that decays to
    zero. `UNCLASSIFIED` is a decision site that set no code — a defect that must ALARM.

    Collapsing them means the shrinking bucket never decays, so the alarm never fires and the
    failure is invisible for exactly as long as the legacy rows exist."""
    assert REJECTION_UNCODED_LEGACY != REJECTION_UNCLASSIFIED
    assert REJECTION_UNCODED_LEGACY in REJECTION_CODES_UNKNOWN
    assert REJECTION_UNCLASSIFIED in REJECTION_CODES_UNKNOWN
    assert len(set(REJECTION_CODES_UNKNOWN)) == 2


async def test_the_idle_broker_path_does_NOT_alarm():
    """**The liveness-signal failure arriving through the ENUMERATION rather than the default.**

    Every fallback here was hardened so absence alarms. A REAL idle path left off the vocabulary
    would then land in `UNCLASSIFIED` and fire whenever the engine is idle and something asks it
    to trade — routinely wrong, therefore ignored, therefore useless when it matters."""
    proxy = LiveLoopBrokerProxy(object())
    res = await proxy.place_order(OrderRequest(
        pair=BTC, direction=DirectionType.LONG, order_type=OrderType.MARKET, lot_size=0.1))

    assert res["rejection_code"] == REJECTION_BROKER_UNAVAILABLE
    assert res["rejection_code"] not in REJECTION_CODES_UNKNOWN, (
        "a legitimate idle state is being reported as a classifier failure"
    )
    assert res["reason"], "and it gives `unavailable_reason` its first reader"


async def test_the_vocabulary_is_CLOSED_and_every_code_is_distinct():
    assert len(REJECTION_CODES) == len(set(REJECTION_CODES)) == 16
    for code in REJECTION_CODES:
        assert code.isupper(), f"{code} breaks the vocabulary's shape"


# =====================================================================================
# M-4 — THE DIFFERENTIAL, AND ITS NEGATIVE CONTROL
# =====================================================================================

def _shape(results: list[dict]) -> list[tuple]:
    """Project onto the PROPERTY: which decision, in which direction. Not the whole dict.

    `A != B` over whole results is the vacuous form — two rejections always differ somewhere (a
    client order id, a price, a timestamp), so an arm asserting merely THAT they differ collects
    that for free. This is the same trap that made my part-2 `_fingerprint` pass on identical
    brokenness, from the other side.
    """
    return [(r.get("rejection_code"), r.get("direction")) for r in results]


async def test_the_projection_IGNORES_incidental_difference():
    """**`M-4`'s negative control, and it is the row review said they would check hardest.**

    Two rejections identical IN THE PROPERTY — both venue refusals — while differing incidentally
    in symbol, price and stop. **The differential below must FAIL on these**, or it is reading
    noise and always was.
    """
    # BOTH MUST ACTUALLY REACH THE VENUE CHECK. My first fixture used entry=61_234.5 against a
    # 70_000 mark — 11R of drift — so it was rejected as ENTRY_DRIFT and never saw the venue at
    # all. The control was comparing a venue refusal with a drift rejection and reporting that
    # the projection was broken. **The control found a flaw in itself, which is the only reason
    # to run one.** Both entries now sit within the drift tolerance.
    a = await _execute(_sig(DirectionType.SHORT, entry=70_000.0, sl=71_000.0),
                       policy=ALPACA_CRYPTO_LONG_ONLY)
    b = await _execute(_sig(DirectionType.SHORT, entry=70_050.0, sl=71_100.0),
                       policy=ALPACA_CRYPTO_LONG_ONLY)

    assert a != b, (
        "the two results are wholly identical, so this control demonstrates nothing — they must "
        "differ incidentally for the projection to be worth testing"
    )
    assert _shape([a]) == _shape([b]), (
        "the projection collects incidental difference, so the differential passes on noise"
    )


async def test_a_venue_refusal_and_a_drift_rejection_are_DISTINGUISHABLE():
    """**`M-4` itself.** A constant code passes any arm run over a population of one kind, so the
    population must contain BOTH."""
    venue = await _execute(_sig(DirectionType.SHORT, sl=71_000.0), policy=ALPACA_CRYPTO_LONG_ONLY)
    drift = await _execute(_sig(entry=60_000.0, sl=59_900.0))

    assert _shape([venue]) != _shape([drift])
    assert venue["rejection_code"] == REJECTION_VENUE_DIRECTION_UNSUPPORTED
    assert drift["rejection_code"] == REJECTION_ENTRY_DRIFT


# =====================================================================================
# M-9 — EVERY REJECTION SITE CARRIES A CODE, AND THE POPULATION COMES FROM THE CODE
# =====================================================================================

def _rejection_returns(path) -> list[tuple[int, bool]]:
    """Every `return {...}` whose dict carries a rejection status, and whether it sets a code.

    **THE POPULATION IS SWEPT FROM THE SOURCE, NEVER FROM `REJECTION_CODES`.** An enumeration
    cannot see a member that was never on it — that is `B398`, which this session produced by
    writing a contract arm over `BrokerAdapter`'s members while the member it was built to catch
    lived only on a subclass. **The arm passed while the omission sat in the tree.** A sweep keyed
    on the vocabulary would have the identical hole: a new rejection site with no code is exactly
    the thing missing from the vocabulary.

    **BOTH SPELLINGS.** Brokers return `"REJECTED"`, `execution/service.py` returns `"rejected"`.
    The loop escapes the difference only because it reads `reason` first; a sweep must not.
    """
    import ast

    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        keys = {k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        status = next(
            (v.value for k, v in zip(node.value.keys, node.value.values)
             if isinstance(k, ast.Constant) and k.value == "status"
             and isinstance(v, ast.Constant)),
            None,
        )
        if isinstance(status, str) and status.lower() == "rejected":
            out.append((node.lineno, "rejection_code" in keys))
    return out


async def test_every_rejection_RETURN_site_sets_a_code():
    """`M-9`. Fails on the day a rejection site is ADDED, not the day someone reads a wrong count."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    missing: list[str] = []
    total = 0
    for path in sorted(root.rglob("*.py")):
        for lineno, has_code in _rejection_returns(path):
            total += 1
            if not has_code:
                missing.append(f"{path.relative_to(root)}:{lineno}")

    assert total >= 8, (
        f"only {total} rejection sites found; the sweep has gone blind and a clean result from a "
        f"blind scan is worth nothing"
    )
    assert not missing, (
        f"these rejection sites return no `rejection_code`: {missing}. A rejection with no code "
        f"is recorded as UNCLASSIFIED, which alarms — correctly, but the alarm belongs on the "
        f"classifier, not in production."
    )


async def test_a_RAISING_rejection_still_leaves_a_row():
    """**`M-10`, and `M-9` cannot see this by construction** — a rejection that raises never
    returns a dict, so a sweep over returned dicts is blind to it. That is not a flaw in `M-9`;
    it is why both rows exist.

    ⚠ **STRUCTURAL, AND THE LIMITATION IS THE POINT OF SAYING SO.** The catch lives inside
    `_tick_symbol`, which fetches a live ticker price and 320 bars, so driving it here would be a
    network test wearing a unit test's clothes. My first version of this arm asserted
    `recorded == []` under a comment calling it a sanity check — **a name promising a property the
    body did not test**, which is the class this task has spent the night removing. Replaced
    rather than renamed.

    So the connection is asserted over the AST: the `execute()` call must sit in a `try` whose
    handler calls `_record_rejected_signal` with `REJECTION_VENUE_RAISED` and then re-raises, so
    `_loop`'s blanket handler still sees it and one bad pair still cannot stop the engine.
    """
    import ast
    import inspect
    import pathlib

    from app.services.live.crypto_loop import LiveCryptoLoop

    tree = ast.parse(pathlib.Path(inspect.getfile(LiveCryptoLoop)).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_tick_symbol")

    guarded = [
        t for t in ast.walk(fn)
        if isinstance(t, ast.Try)
        and any(isinstance(c, ast.Attribute) and c.attr == "execute"
                for c in ast.walk(ast.Module(body=t.body, type_ignores=[])))
    ]
    assert guarded, "the execute() call is not inside a try; a raise aborts the bar with no row"

    handler = ast.Module(body=[h for t in guarded for h in t.handlers], type_ignores=[])
    assert any(
        isinstance(c, ast.Attribute) and c.attr == "_record_rejected_signal"
        for c in ast.walk(handler)
    ), "the handler does not record the abort — the row this row exists for is still missing"
    assert any(
        isinstance(n, ast.Name) and n.id == "REJECTION_VENUE_RAISED"
        for n in ast.walk(handler)
    ), "the abort is recorded without the code that identifies it"
    assert any(isinstance(n, ast.Raise) for n in ast.walk(handler)), (
        "the handler swallows instead of re-raising. `_loop`'s blanket handler is CORRECT — one "
        "bad pair must not stop the engine — and narrowing it trades a silent gap for a dead "
        "engine. The defect was that the abort was not RECORDED, not that it was caught."
    )
