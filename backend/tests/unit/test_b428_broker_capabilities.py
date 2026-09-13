"""B428a — a broker that cannot manage positions must say so LOUDLY, not once per symbol per poll.

**The defect was not only that the Alpaca tick path is broken. It is that it fails as a WARNING
while `status()` reports health.**

```
crypto_loop.py:2051   for ev in self.paper.on_tick(pair, price):      UNGUARDED
base.py               on_tick is NOT in the BrokerAdapter contract
defines on_tick       paper.py and cft_sim.py ONLY — AlpacaAdapter has none
crypto_loop.py:2062   the strategy evaluation, i.e. BELOW :2051
_loop                 except Exception -> logger.warning -> next symbol, next poll
```

So on the Alpaca venue `_tick_symbol` raised `AttributeError` before any signal was evaluated, and
the engine reported `running=True`, `paused=False`, `halt_reason=None` — **healthy, forever, and
unable to place a single order.** An operator watching a running engine take no trades reads a
quiet market. That is `B179`'s signature on the order path.

**WHY THIS HALF FIRST, and why it arms nothing.** Making the tick path WORK is the switch: the
moment it lands, `B429` (no stop is sent to the venue and none is enforced in process), `T-0130`
and `B427` all become live at once, because each is latent only because the path dies first.
Making the failure LOUD cannot cause a trade and removes the condition where we are lied to.

**IT CANNOT FIRE TODAY AND THAT IS THE POINT.** `BROKER_MODE` is a `Final` `"sim"` in
`fixed_config`, `main.py` constructs `LiveCryptoLoop()` with no argument, and `broker_mode` appears
zero times in `app/schemas/` and `app/api/` — so `_select_venue()` cannot return `"alpaca"` without
a source change. **This guard exists to fire at exactly that moment**, which is the one moment
nobody will be watching a log.

**THE LIST IS DERIVED, NOT REMEMBERED.** `on_tick` was never in the base class and nothing required
it to be; the next missing member will arrive the same way. So the first arm below walks the loop's
own source for every `self.paper.X` and fails if one is neither in the contract, nor declared, nor
explicitly exempt — rather than trusting the three names someone typed.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.services.broker.base import Account, BrokerAdapter
from app.services.live import crypto_loop as mod
from app.services.live.crypto_loop import (
    BLOCK_HALT,
    BLOCK_SKIP,
    REQUIRED_BROKER_CAPABILITIES,
    LiveCryptoLoop,
)

#: Touched on `self.paper` but NOT required, each for a stated reason. `_IMPORT_EXEMPT`'s shape:
#: an exemption nobody can see the size of is an unbounded hole, so it is pinned and an arm below
#: fails if it grows.
_EXEMPT = {
    # ASSIGNED by `_bind_broker`, never read before it is written — assignment creates it, so a
    # broker that lacks it is not thereby incapable. Two assignments, zero reads.
    "_on_settle",
    # WARM-UP ONLY. Every use is inside `warmup()`, which returns at `if venue != "paper"` before
    # reaching them, and `status()`'s fallback reads `_closed` through a guarded getattr WITH A
    # DESIGNED REPORT for its absence. **Both were in the required list in the first version of
    # this entry** — which would have contradicted that report and refused a venue adapter that
    # implements `on_tick` perfectly well. Caught by review; the author of the required list had
    # written the guarded fallback an hour earlier.
    "_closed",
    "balance",
}


def _paper_uses() -> set[str]:
    """Every `self.paper.X` in the loop's source, derived rather than listed."""
    tree = ast.parse(inspect.getsource(mod))
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute):
            if n.value.attr == "paper" and isinstance(n.value.value, ast.Name):
                if n.value.value.id == "self":
                    out.add(n.attr)
    return out


def _contract() -> set[str]:
    """What `BrokerAdapter` promises. Read off the class, so it tracks the contract."""
    return {n for n in dir(BrokerAdapter) if not n.startswith("__")}


class _ContractOnly:
    """Everything `BrokerAdapter` PROMISES and nothing more — `AlpacaAdapter`'s shape for this
    question: order placement, no position management.

    **The two doubles differ in exactly one thing.** Both satisfy the contract, so any arm below
    that fires does so because of the position-management members and not because a double was too
    thin to be driven — which is what the first version of these doubles did, and it failed inside
    `_has_position` rather than at the property under test.
    """
    broker_name = "contract-only-double"

    async def get_positions(self):
        return []

    async def get_account(self):
        return Account(account_id="x", broker="double", balance=10_000.0, equity=10_000.0,
                       currency="USD")

    def order_path_status(self):
        return None

    def simulation_source(self):
        return "double"


class _Capable(_ContractOnly):
    """The same, plus the three members the loop needs and the contract does not promise."""
    broker_name = "capable-double"

    def __init__(self):
        self._closed: list = []
        self.balance = 10_000.0

    def on_tick(self, pair, price, ts=None):
        return []


class _Incapable(_ContractOnly):
    """Named for what it is missing, so a failure message points at the variable."""
    broker_name = "incapable-double"


# =====================================================================================
# THE REQUIREMENT IS DERIVED FROM THE CODE
# =====================================================================================

def test_every_self_paper_USE_is_accounted_for():
    """**The arm that makes this durable.** A new `self.paper.X` outside the contract must be
    declared or exempted — it cannot simply appear and become the next `on_tick`."""
    uses = _paper_uses()

    # THE DENOMINATOR, AND IT NAMES A MEMBER RATHER THAN COUNTING. `assert uses` would pass on a
    # scan that found one incidental attribute; what must be present is the member this entry is
    # about, because its absence means the walk has stopped seeing what the loop does.
    assert "on_tick" in uses, (
        f"the scan no longer sees self.paper.on_tick, so it is not reading what the loop calls "
        f"and its verdict about everything else is worthless. Saw: {sorted(uses)}"
    )

    unaccounted = uses - _contract() - set(REQUIRED_BROKER_CAPABILITIES) - _EXEMPT
    assert not unaccounted, (
        f"the loop uses {sorted(unaccounted)} on its broker, and the BrokerAdapter contract does "
        f"not promise them. Nothing requires an adapter to have them, so a broker without one "
        f"fails at the call site — which is how on_tick became a per-symbol warning forever. "
        f"Add to REQUIRED_BROKER_CAPABILITIES (and the guard covers it) or to _EXEMPT with a "
        f"reason."
    )


def test_the_declared_capabilities_are_the_ones_the_CONTRACT_DOES_NOT_PROMISE():
    """A declared capability that is already in the contract is noise — every adapter has it by
    construction. The declaration must describe the GAP, or it stops describing anything."""
    assert REQUIRED_BROKER_CAPABILITIES, "nothing is declared, so the guard checks nothing"
    overlap = set(REQUIRED_BROKER_CAPABILITIES) & _contract()
    assert not overlap, (
        f"{sorted(overlap)} are promised by BrokerAdapter, so declaring them here tests nothing "
        f"and dilutes a list whose whole value is that every member is genuinely unpromised"
    )


def test_the_EXEMPTION_is_bounded_and_does_not_silently_GROW():
    """An exemption list is a hole in the arm above."""
    assert _EXEMPT == {"_on_settle", "_closed", "balance"}, (
        f"the exemption list changed: {_EXEMPT}. Each member needs a reason that says why a "
        f"broker without it is NOT incapable — assigned-not-read, or reached only on a path "
        f"gated to a venue that has it."
    )


# =====================================================================================
# THE CHECK ITSELF
# =====================================================================================

def test_the_check_DISCRIMINATES_between_a_capable_and_an_incapable_broker():
    """Both directions. A check that answers "incapable" to everything refuses the simulators
    too, and a check that answers "capable" to everything is the defect."""
    assert LiveCryptoLoop._missing_capabilities(_Capable()) == ()
    assert set(LiveCryptoLoop._missing_capabilities(_Incapable())) == set(REQUIRED_BROKER_CAPABILITIES)


def test_the_check_asks_the_INSTANCE_and_not_the_CLASS():
    """**A measured instrument bug, kept as an arm after the thing that exposed it moved.**

    The first version of this check asked `hasattr(type(broker), ...)` and reported `PaperBroker`
    missing `balance` and `_closed` — both assigned in `__init__` — answering confidently and
    wrongly about the broker we actually run. Those two are no longer REQUIRED, so the mistake can
    no longer reach the list that way; the check is still generic, so the property still needs
    pinning. **An arm whose discriminating input has been fixed away tests nothing** — so this
    builds the input instead of borrowing it.
    """
    class _InstanceLevel(_ContractOnly):
        """A broker that satisfies the requirement with an INSTANCE attribute, which is legitimate
        — an adapter may bind a callable in `__init__` rather than define a method."""
        def __init__(self):
            self.on_tick = lambda pair, price, ts=None: []

    broker = _InstanceLevel()
    assert LiveCryptoLoop._missing_capabilities(broker) == (), (
        "a broker satisfying the requirement on the INSTANCE is reported incapable — the check is "
        "asking the class"
    )
    class_form = tuple(n for n in REQUIRED_BROKER_CAPABILITIES if not hasattr(_InstanceLevel, n))
    assert class_form, (
        "the fixture no longer distinguishes the two forms, so this arm cannot fail for the "
        "reason it exists"
    )


def test_the_REAL_simulators_satisfy_the_requirement():
    """The control that keeps every arm above from being satisfied by a permanently-failing check:
    the brokers this engine actually runs must pass."""
    loop = LiveCryptoLoop()
    assert loop.broker_missing == (), (
        f"the bound simulator is reported incapable — {loop.broker_missing}. Every refusal arm "
        f"below would then be passing for the wrong reason."
    )


def test_AlpacaAdapter_is_MISSING_on_tick_which_is_the_whole_finding():
    """Asserted against the real class, not a double. If Alpaca ever grows position management
    this arm fails and the entry gets re-read, which is the right outcome."""
    from app.services.broker.alpaca import AlpacaAdapter

    assert not hasattr(AlpacaAdapter, "on_tick"), (
        "AlpacaAdapter now has on_tick — B428's mechanism has changed and B429 (no stop is sent "
        "to the venue and none is enforced in process) must be re-read before this is relaxed"
    )


# =====================================================================================
# IT REACHES A CONSUMER — B394's TEST, WHICH IS THE ENTRY
# =====================================================================================

async def test_status_REPORTS_an_incapable_broker():
    """The condition had NO reader at all: the payload said running, unpaused and unhalted while
    the loop could not complete one tick."""
    loop = LiveCryptoLoop()
    assert "broker_missing" in (await loop.status()), (
        "the condition is stored where status() cannot show it — B394, a mechanism with no consumer"
    )
    assert (await loop.status())["broker_missing"] == [], "a healthy bind must report empty"

    loop.paper = _Incapable()
    loop.broker_missing = LiveCryptoLoop._missing_capabilities(loop.paper)
    assert set((await loop.status())["broker_missing"]) == set(REQUIRED_BROKER_CAPABILITIES)


async def test_the_ENTRY_GATE_refuses_and_classifies_it_as_a_HALT_not_a_SKIP():
    """**A halt, because it is not a reason to wait — it is a reason to not trade.** A broker that
    cannot sweep SL/TP cannot enforce a stop, and `B429` establishes none is sent to the venue
    either. `B415`: a block whose seriousness is guessed from its text is how a named halt becomes
    a routine skip."""
    loop = LiveCryptoLoop()
    assert await loop._entry_block_reason("BTC/USD") is None, (
        "a fresh loop already blocks, so this arm could not tell the refusal from the baseline"
    )

    loop.broker_missing = ("on_tick",)
    block = await loop._entry_block_reason("BTC/USD")

    assert block is not None
    assert block.kind == BLOCK_HALT, f"an unmanageable position is a {block.kind}, not a halt"
    assert "on_tick" in str(block), f"the refusal does not name what is missing: {block!r}"
    assert BLOCK_SKIP != BLOCK_HALT, "the two kinds must discriminate for the assert above to mean anything"


async def test_the_gate_refuses_WITHOUT_reading_a_position_or_the_venue():
    """Like the `B413` halt beside it: a refusal this absolute must not depend on a venue call
    succeeding, or a timeout turns it into a pass."""
    loop = LiveCryptoLoop()
    loop.broker_missing = ("on_tick",)

    async def _explode(*a, **k):
        raise AssertionError("the refusal read a position before refusing")

    loop._has_position = _explode
    loop._open_count = _explode

    assert await loop._entry_block_reason("BTC/USD") is not None


async def test_START_refuses_rather_than_running_blind():
    """The loud half. Before this, start() succeeded and the loop ran, failing every tick."""
    loop = LiveCryptoLoop()
    acts: list[tuple[str, str]] = []

    async def _act(kind, msg):
        acts.append((kind, msg))

    loop._act = _act
    loop.paper = _Incapable()
    loop.broker_missing = LiveCryptoLoop._missing_capabilities(loop.paper)

    result = await loop.start()

    assert result.get("started") is False, f"start did not refuse: {result}"
    assert "on_tick" in str(result.get("broker_missing")), result
    assert loop._running is False, "the loop started anyway"
    assert any("NOT started" in m for _, m in acts), (
        f"the refusal never reached the operator's activity feed: {acts}"
    )


async def test_a_CAPABLE_broker_is_NOT_refused_by_the_new_check():
    """**The control for the arm above**, and the one that would catch a guard that refuses
    everything. Driven only as far as the new refusal: a capable broker passes it and start()
    proceeds to `order_path_status`, which is a different question and not this entry's.
    """
    loop = LiveCryptoLoop()
    loop.paper = _Capable()
    loop.broker_missing = LiveCryptoLoop._missing_capabilities(loop.paper)
    assert loop.broker_missing == ()

    # The refusal is keyed on `broker_missing` alone, so an empty tuple cannot reach it.
    block = await loop._entry_block_reason("BTC/USD")
    assert block is None or "cannot manage positions" not in str(block), (
        f"a capable broker is being refused as incapable: {block!r}"
    )


async def test_STATUS_SURVIVES_the_condition_it_exists_to_REPORT():
    """**Found by an arm failing for its own reason rather than the code's.**

    `status()`'s DB-down fallback read `self.paper._closed` — a simulator-only member. So on an
    incapable broker, with the database unreachable, `status()` raised: **the one surface that
    would have told anyone the broker was incapable died of the thing it had to report.** The
    `except` above it exists so the panel never 500s, and this walked straight past it.

    Driven with no database available, which is what makes the fallback the path under test.
    """
    loop = LiveCryptoLoop()
    loop.paper = _Incapable()                      # missing _closed, on_tick and balance
    loop.broker_missing = LiveCryptoLoop._missing_capabilities(loop.paper)

    payload = await loop.status()                  # must not raise

    assert set(payload["broker_missing"]) == set(REQUIRED_BROKER_CAPABILITIES), (
        "status() returned without naming what is missing, so it survived and said nothing"
    )
    # AND THE ZERO IS EXPLAINED. `closed_trades == 0` here means "cannot count", not "no trades" —
    # B179's conflation. `broker_missing` on the same payload is what tells them apart, so an arm
    # that accepted the zero alone would be accepting the reassuring reading.
    assert payload["broker_missing"], (
        "a zero trade count with an empty broker_missing is indistinguishable from a quiet day"
    )


def test_no_REQUIRED_member_hides_behind_a_getattr_WITHOUT_A_DEFAULT():
    """**A hole in the arm that derives the list, closed by measurement.**

    `_paper_uses()` walks `ast.Attribute`, so `getattr(self.paper, "x", default)` is invisible to
    it — correctly, because a getattr WITH a default is optional by construction. A getattr with
    NO default is the opposite: a hard requirement the derivation cannot see. All ten such calls
    in the loop carry a default today, and this fails the moment one does not.
    """
    import ast as _ast
    tree = _ast.parse(inspect.getsource(mod))
    bare = []
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) and n.func.id == "getattr":
            a = n.args
            if a and isinstance(a[0], _ast.Attribute) and a[0].attr == "paper" and len(a) < 3:
                bare.append((n.lineno, getattr(a[1], "value", "?")))

    # THE DENOMINATOR: this arm is worthless if the walk finds no getattr at all.
    total = sum(1 for n in _ast.walk(tree)
                if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
                and n.func.id == "getattr" and n.args
                and isinstance(n.args[0], _ast.Attribute) and n.args[0].attr == "paper")
    assert total >= 5, f"only {total} getattr(self.paper, ...) calls seen — the walk is not reading the module"

    assert not bare, (
        f"{bare} read a broker member with NO default, which makes it a hard requirement that "
        f"test_every_self_paper_USE_is_accounted_for cannot see. Give it a default, or add it to "
        f"REQUIRED_BROKER_CAPABILITIES so the guard covers it."
    )


def test_REQUIRED_and_EXEMPT_are_DISJOINT():
    """**A member cannot be both required of every broker and excused on every broker.**

    Noticed while building the kill set for this entry: a row that added `_closed` back to
    REQUIRED killed nothing, because every other arm subtracts REQUIRED and _EXEMPT together and
    cannot tell which side a name came from. So the exact mistake review had just corrected could
    be reintroduced silently. The two lists make opposite claims; overlapping them means the file
    no longer states which one is true.
    """
    overlap = set(REQUIRED_BROKER_CAPABILITIES) & _EXEMPT
    assert not overlap, (
        f"{sorted(overlap)} appear in BOTH lists. REQUIRED says a broker without it cannot run; "
        f"_EXEMPT says a broker without it is fine. Decide which, with the reason."
    )


# =====================================================================================
# HAND-OFF — the broker escapes this module, and a subset check is only half a check
# =====================================================================================

#: Callees that take `self.paper` WITHOUT retaining it: they read one member or the type and
#: return. Passing the broker to these hands nothing over.
_NON_RETAINING = {"getattr", "type", "_missing_capabilities", "isinstance"}

#: Everything that genuinely receives the broker object. **Pinned, because a subset check on a
#: known receiver says nothing about a receiver nobody has looked at** — review's correction, and
#: it is `assert sites` one level up: half one is *what I found is clean*, half two is *what I
#: found is everything*, and only the pair is a check.
_HANDOFF_RECEIVERS = {"ExecutionService"}


def _handoff_callees() -> list[tuple[int, str]]:
    """Every call that takes `self.paper` as an argument, with its callee name."""
    tree = ast.parse(inspect.getsource(mod))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            for a in list(n.args) + [k.value for k in n.keywords]:
                if isinstance(a, ast.Attribute) and a.attr == "paper":
                    out.append((n.lineno, getattr(n.func, "id", None) or getattr(n.func, "attr", "?")))
    return out


def test_the_HANDOFF_POPULATION_is_pinned_not_merely_sampled():
    """**Half two, and without it half one rots.**

    `_paper_uses()` walks attribute access on `self.paper`; an object handed to a constructor
    escapes that walk entirely and can call anything it likes on the broker. Checking the one
    receiver we know about is a claim about that receiver, not about the module — so the set of
    receivers is pinned and this fails when it grows.
    """
    sites = _handoff_callees()
    assert len(sites) >= 5, (
        f"only {len(sites)} sites pass self.paper to anything — the walk is not reading the "
        f"module, and its verdict below would be a zero over nothing"
    )
    receivers = {name for _, name in sites if name not in _NON_RETAINING}
    assert receivers == _HANDOFF_RECEIVERS, (
        f"the set of things RECEIVING the broker object changed to {sorted(receivers)}. Each one "
        f"can call anything on it, outside the reach of test_every_self_paper_USE_is_accounted_for. "
        f"Add it to _HANDOFF_RECEIVERS and give it an arm like the one below."
    )


def test_the_ONE_RECEIVER_only_uses_what_the_CONTRACT_promises():
    """Half one. `ExecutionService` gets the broker and is free to call anything on it; if it
    reaches for a simulator-only member, that member is a hidden requirement of this loop that
    no capability list mentions."""
    from app.services.execution import service as exec_mod

    tree = ast.parse(inspect.getsource(exec_mod))
    used = {
        n.attr for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
        and n.value.attr == "broker" and isinstance(n.value.value, ast.Name)
        and n.value.value.id == "self"
    }
    assert used, "the scan found no self.broker use in ExecutionService, so it is reading nothing"

    escapes = used - _contract() - set(REQUIRED_BROKER_CAPABILITIES)
    assert not escapes, (
        f"ExecutionService reaches for {sorted(escapes)} on the broker, which BrokerAdapter does "
        f"not promise — a requirement of this engine that the capability guard cannot see, "
        f"because the object was handed over rather than accessed through self.paper"
    )


def test_the_HANDOFF_CHECK_can_actually_FLAG_something():
    """The control. Both arms above are non-empty-set assertions and would pass over a scan that
    matched nothing or a contract that contained everything."""
    fake_contract = _contract() | {"place_order"}
    assert {"on_tick"} - fake_contract == {"on_tick"}, (
        "the set difference the arms above rely on is not discriminating"
    )
    # And a planted receiver must be caught by the population arm's comparison.
    planted = {"ExecutionService", "SomeNewThingThatKeepsTheBroker"}
    assert planted != _HANDOFF_RECEIVERS, "the population comparison cannot detect a new receiver"
