"""T-0105 — a `Position` names the adapter that built it, and the name must be RIGHT.

`B286` found two adapter-specific meanings while asking about P&L; `B289` found a third while
asking about staleness. **Neither was looking for the pattern.** They are not three bugs:

    unrealized_pnl     paper = gross price movement | CFT = whichever key arrived
    r_multiple         paper = a price ratio        | CFT = derived from the P&L
    duration_seconds   oanda/CFT = computed         | paper/cft_sim = the literal 0

`Position` had **no notion of who produced it**, so every field was free to mean something
adapter-specific because nothing ever had to agree. `produced_by` is that missing property.

**THE ARM HAS TO GUARD CORRECTNESS AND NOT PRESENCE, AND THIS IS THE WHOLE FILE.** *"Every
adapter constructs a valid `Position`"* and *"`produced_by` is populated by every adapter"* are
**both satisfied by every adapter hardcoding `produced_by="paper"`** — under which a row built
by CFT is read entirely under paper's conventions, through a green suite. `B290`'s shape one
week later: that entry found the sizing arms guarding *presence* where the subject was
*provenance*, and here the field **is** provenance.

> **A missing value is a gap; a wrong one is a lie.**

So: for each adapter discovered from the tree, the `produced_by` it writes must identify **that
adapter** — not merely be non-empty.

WHAT THIS FILE DOES NOT COVER
-----------------------------
* The two live adapters are checked **structurally** (their `get_positions` needs a venue on the
  other end of an HTTP client). The two simulators are checked **structurally and by running
  them.** A structural pass on `cryptofundtrader` says the source names the right value; only
  the simulator arms prove a value reaches the object.
* A site written as `produced_by=self.broker_name` is correct **by construction** — that half of
  the structural arm cannot fail while it is written that way, and its teeth are on the literal
  sites. Stated rather than left to be discovered: the arm's strength is uneven across the
  population, and the mutation below is what measures where it actually bites.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.db.enums import DirectionType, OrderType
from app.schemas.broker import Position
from app.services.broker.base import OrderRequest

# NAMED, NOT RE-DERIVED — both of them. `_all_adapters` descends the subclass tree (`B296` made
# it transitive); `SIM_ADAPTERS` carries the zero-credential factories that let a simulator be
# driven for real. Re-deriving either would re-enter a trap already paid for once.
from tests.unit.test_broker_contract import SIM_ADAPTERS
from tests.unit.test_t0038_partial_close_contract import _all_adapters

_PACKAGE = pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / "broker"


# ======================================================================================
# The derivation: which adapter CLASS builds a Position, and what does it write
# ======================================================================================


def _sites_by_class() -> dict[str, list[ast.Call]]:
    """Every `Position(...)` call, keyed by the adapter class whose body contains it.

    **Keyed by CLASS and not by MODULE.** A module holding two adapters would attribute one
    class's construction site to the other, and this arm's entire subject is which class a row
    came from — an instrument that can misattribute is the defect it is looking for.
    """
    found: dict[str, list[ast.Call]] = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "Position":
                    found.setdefault(node.name, []).append(inner)
    return found


def _produced_by_value(call: ast.Call, cls: type) -> str | None:
    """Resolve what this site writes into `produced_by`, or `None` if it cannot be resolved.

    Two accepted forms, and both resolve to a NAME rather than to "something was passed":

        produced_by="cft_sim"        a literal, compared against the class's own broker_name
        produced_by=self.broker_name the class's own broker_name, by construction

    Anything else is unresolvable, and an unresolvable provenance is not a provenance — a
    reader cannot tell what a row will say without running the venue.
    """
    for kw in call.keywords:
        if kw.arg != "produced_by":
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
        if (
            isinstance(kw.value, ast.Attribute)
            and kw.value.attr == "broker_name"
            and isinstance(kw.value.value, ast.Name)
            and kw.value.value.id == "self"
        ):
            return getattr(cls, "broker_name", None)
        return None
    return None


_PRODUCERS = [c for c in _all_adapters() if c.__name__ in _sites_by_class()]


# ======================================================================================
# MUST-HIT — an arm over an empty or shrunken population passes and guards nothing
# ======================================================================================


def test_there_are_producers_to_check():
    """`B211`: publish the denominator. Four of the six discovered adapters build a `Position`.

    Pinned by NAME so a fifth producer fails here deliberately instead of joining the guarded
    set silently — and so a producer that DISAPPEARS from the population (the `B296` failure,
    where a class simply never enters the set) fails too.
    """
    assert {c.__name__ for c in _PRODUCERS} == {
        "PaperBroker",
        "SimPropFirmBroker",
        "CryptoFundTraderAdapter",
        "OANDAAdapter",
        # `T-0106`. THE FIFTH PRODUCER, NAMED DELIBERATELY — which is what this pin exists for.
        # It fired when the MT5 module landed, in the FULL suite rather than in `T-0106`'s own
        # baseline command, which named only `test_broker_contract` and
        # `test_t0038_partial_close_contract`. A new adapter touches three populations, not two.
        "MetaTrader5Adapter",
    }, (
        f"the set of Position producers changed: {sorted(c.__name__ for c in _PRODUCERS)}. "
        f"Discovered adapters: {sorted(c.__name__ for c in _all_adapters())}"
    )


# ======================================================================================
# THE ARM THAT MATTERS — correctness, not presence
# ======================================================================================


@pytest.mark.parametrize("cls", _PRODUCERS, ids=lambda c: c.__name__)
def test_produced_by_names_THE_ADAPTER_THAT_BUILT_THE_ROW(cls):
    """Not that the field is non-empty — that it is the right name.

    Every adapter hardcoding `produced_by="paper"` satisfies "populated" and fails here.
    """
    expected = cls.broker_name
    assert isinstance(expected, str) and expected, (
        f"{cls.__name__}.broker_name is not a plain string ({expected!r}), so there is nothing "
        "for a row to be checked against"
    )
    for call in _sites_by_class()[cls.__name__]:
        actual = _produced_by_value(call, cls)
        assert actual == expected, (
            f"{cls.__name__} builds a Position at line {call.lineno} whose produced_by is "
            f"{actual!r}, but this adapter is {expected!r}. A row naming the wrong producer is "
            "read under the wrong conventions on every field — the failure the field exists to "
            "prevent, with nothing raising."
        )


def test_a_row_built_by_a_REAL_simulator_names_that_simulator(sim_rows):
    """The structural arm reads source; this one reads an object that a broker actually built.

    Driven through `place_order` -> `on_tick` -> `get_positions` on the real adapter, so the
    value is checked where it lands rather than where it is written.
    """
    for name, row in sim_rows.items():
        assert row.produced_by == name, (
            f"a row from the {name} simulator says it was produced by {row.produced_by!r}"
        )


# ======================================================================================
# What a swap-free adapter reports — BY NAME, not "it did not raise"
# ======================================================================================


def test_a_swap_free_adapter_reports_None_and_NEVER_zero(sim_rows):
    """`B215`. A venue that CANNOT report a cost and one that reports zero cost must not share a
    representation. Both simulators are swap-free **by construction** — no cost field exists on
    either position record — so `0` would be a claim they charged nothing rather than an absence.

    `duration_seconds` is here for the same reason and is `B289` itself: it was a required
    `int`, so these two passed the literal `0`, the only value the type allowed, and every row
    said the position had been open for zero seconds.
    """
    for name, row in sim_rows.items():
        for field in ("swap", "commission", "duration_seconds"):
            value = getattr(row, field)
            assert value is None, (
                f"{name}.{field} is {value!r}. This adapter does not report it, and a zero "
                "there is indistinguishable from a venue that reported a genuine zero."
            )


def test_no_producer_HARDCODES_a_zero_cost():
    """The structural half, over the derived population rather than the two adapters we have.

    A literal `0` at a construction site is always wrong — not because zero is a wrong number,
    but because a *literal* is a claim rather than a reading. A venue that genuinely charges
    nothing passes a value it read.
    """
    offenders = []
    for calls in _sites_by_class().values():
        for call in calls:
            for kw in call.keywords:
                if kw.arg not in ("swap", "commission"):
                    continue
                if isinstance(kw.value, ast.Constant) and kw.value.value in (0, 0.0):
                    offenders.append(f"{kw.arg} at line {call.lineno}")
                # `Decimal("0")` / `Decimal(0)` — the same claim wearing a constructor.
                if (
                    isinstance(kw.value, ast.Call)
                    and getattr(kw.value.func, "id", None) == "Decimal"
                    and kw.value.args
                    and isinstance(kw.value.args[0], ast.Constant)
                    and str(kw.value.args[0].value) in ("0", "0.0", "0.00")
                ):
                    offenders.append(f"{kw.arg} at line {call.lineno}")
    assert not offenders, (
        f"these state a cost of zero rather than reporting one: {offenders}"
    )


# ======================================================================================
# The GROSS decision, ASSERTED — so a later adapter cannot quietly choose the other one
# ======================================================================================


def test_the_gross_decision_is_ASSERTED_and_not_merely_described(sim_rows):
    """`unrealized_pnl` is GROSS: the price movement times the size, with nothing folded in.

    Recomputed from the row's OWN columns, so it is a property of the row rather than of the
    fixture. Fold a cost into the P&L and this identity breaks by exactly that cost.

    **AND IT IS THE SAME FACT AS `swap=None` ABOVE, WHICH IS WHY THE TWO ARE ONE DECISION.**
    Gross-versus-net only exists where costs exist. These simulators are not gross rather than
    net — *they cannot be either*, and the identity below holds for the reason the cost fields
    are absent, not as a second coincidence that happens to agree.
    """
    for name, row in sim_rows.items():
        # MUST-HIT. With an unmoved price both sides are zero and the identity holds for any
        # adapter that returns a constant — green, and guarding nothing.
        assert row.current_price != row.entry_price, (
            f"the {name} fixture never moved the price, so this arm cannot fail"
        )
        assert row.unrealized_pnl != 0, f"the {name} row has no P&L to check the shape of"

        sign = 1 if row.direction == DirectionType.LONG else -1
        gross = sign * (row.current_price - row.entry_price) * row.lot_size
        assert row.unrealized_pnl == gross, (
            f"{name} reports unrealized_pnl={row.unrealized_pnl} where the gross movement is "
            f"{gross}. A difference of {gross - row.unrealized_pnl} is a cost folded into the "
            "P&L, and once it is folded a venue that reports no cost is indistinguishable from "
            "one that charges none."
        )


# ======================================================================================
# What `produced_by` is NOT — recorded so a reader does not over-read it
# ======================================================================================


def test_produced_by_names_A_VENUE_CONVENTION_and_not_a_CLASS():
    """Two classes reach CFT and both write `"cryptofundtrader"`, deliberately.

    `CFTBridgeAdapter` subclasses `CryptoFundTraderAdapter` to swap the transport (a real
    browser, because Cloudflare fingerprints the TLS handshake) and inherits `get_positions`
    unchanged. **The payload, the normalisation and therefore the conventions are identical**,
    so one name is the right answer — but it means a reader cannot recover the CLASS from this
    field, and this arm exists so that is a recorded property rather than an assumption someone
    makes later.
    """
    from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter
    from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter

    assert CFTBridgeAdapter.broker_name == CryptoFundTraderAdapter.broker_name
    assert CFTBridgeAdapter.__name__ not in _sites_by_class(), (
        "the bridge grew its own Position construction site; it now needs its own entry in the "
        "producer pin, and the shared name above is no longer inherited"
    )


def test_a_Position_is_UNCONSTRUCTIBLE_without_its_producer():
    """Required, not optional. A provenance field that can be absent reintroduces the problem
    it exists to solve: optional means nothing breaks and no adapter ever has to answer."""
    import pydantic

    from tests.unit.test_t0102_pnl_provenance import BASE

    with pytest.raises(pydantic.ValidationError) as exc:
        Position(**{k: v for k, v in BASE.items() if k != "produced_by"}, pnl_source="computed")
    missing = [e["loc"][0] for e in exc.value.errors() if e["type"] == "missing"]
    assert missing == ["produced_by"], (
        f"exactly one field must be missing and it must be produced_by; got {missing}"
    )


# ======================================================================================
# Fixture — the simulators, driven for real
# ======================================================================================


@pytest.fixture(scope="module")
def sim_rows() -> dict[str, Position]:
    """One real `Position` per simulator, opened through `place_order` and marked up.

    Keyed by the name the registry gives the adapter, which is the name the row must claim —
    **taken from the registry and not from the row**, so a row cannot satisfy the arm by
    agreeing with itself.
    """
    import asyncio

    async def _drive() -> dict[str, Position]:
        rows: dict[str, Position] = {}
        for name, _cls, factory in SIM_ADAPTERS:
            adapter = factory()
            adapter.on_tick("BTC/USDT", 100.0)   # seed the mark so the fill is deterministic
            await adapter.place_order(OrderRequest(
                pair="BTC/USDT", direction=DirectionType.LONG, order_type=OrderType.MARKET,
                lot_size=2.0, price=None, sl=50.0, tp=None, client_order_id=f"t0105-{name}",
            ))
            adapter.on_tick("BTC/USDT", 101.5)   # +1.5 on 2 units = 3.0 exactly at 4dp
            positions = await adapter.get_positions()
            assert len(positions) == 1, f"{name} did not open exactly one position"
            rows[name] = positions[0]
        assert rows, "no simulator could be driven, so every arm reading this fixture is vacuous"
        return rows

    return asyncio.run(_drive())
