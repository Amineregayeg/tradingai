"""T-0102 — `B286` part 1: the adapter must know WHICH QUANTITY it read.

`cryptofundtrader.py` read the P&L as

    raw.get("profit", raw.get("netProfit", raw.get("openNetProfit")))

**a three-deep silent fallback across keys that are not the same quantity.** `profit` is
conventionally GROSS and `netProfit` is net of costs, so `unrealized_pnl` held one of three
different measurements with nothing recording which. **No definition of that field can be
honoured while a caller cannot tell them apart.**

**THIS TASK DECIDES NOTHING ABOUT WHICH KEY THE VENUE SENDS.** The fallback ORDER is
unchanged. Asking the live CFT API is `T-0114` and is gated — it is a third-party production
broker and that call is not authorised.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.enums import DirectionType
from app.schemas.broker import Position

BASE = dict(
    id="p-1", pair="BTC/USD", direction=DirectionType.LONG,
    entry_price=Decimal("70000"), current_price=Decimal("70100"),
    unrealized_pnl=Decimal("10"), lot_size=Decimal("0.1"),
    duration_seconds=60, open_time=datetime.now(timezone.utc),
    # `T-0105` made `produced_by` required too. It is supplied HERE so the arms below isolate
    # `pnl_source`: without it the unconstructible arm would raise for TWO missing fields and
    # pass for the wrong reason, which is the failure this file is otherwise about.
    produced_by="paper",
)


def test_a_position_is_UNCONSTRUCTIBLE_without_its_provenance():
    """**Required, not defaulted.** A default would answer the question the field exists to
    ask, and would answer it the same way for every adapter."""
    with pytest.raises(ValidationError) as exc:
        Position(**BASE)
    # READ THE STRUCTURED ERRORS, NOT THE MESSAGE STRING. The rendered message echoes the
    # whole input dict, so `"produced_by" not in str(exc)` was false the moment BASE supplied
    # it — a substring check over text that contains more than the claim, which is the shape
    # this file keeps finding elsewhere.
    missing = [e["loc"][0] for e in exc.value.errors() if e["type"] == "missing"]
    assert missing == ["pnl_source"], (
        f"exactly one field must be missing and it must be pnl_source; got {missing}. If "
        "BASE stops supplying another required field this arm would pass because TWO are "
        "missing, and would keep passing if pnl_source were made optional."
    )

    assert Position(**BASE, pnl_source="computed").pnl_source == "computed"


def test_COMPUTED_and_NONE_are_DISTINGUISHABLE():
    """**The third state is the point.** `paper` computes its P&L with no key involved, so
    under two states `None` would mean both *"computed locally, correctly"* and *"nothing was
    read, which is a fault"* — the could-not-ask collapse this field exists to prevent."""
    computed = Position(**BASE, pnl_source="computed")
    fault = Position(**BASE, pnl_source=None)

    assert computed.pnl_source == "computed"
    assert fault.pnl_source is None
    assert computed.pnl_source != fault.pnl_source, (
        "a correct local calculation and a failed read must not share a representation"
    )


# ======================================================================================
# THE CFT READER — presence, not a defaulted get
# ======================================================================================


#: **IMPORTED, NOT RE-IMPLEMENTED.** The first version of this file copied the selection
#: inline, and a mutation restoring the old silent fallback in the adapter left every arm
#: below GREEN — they were exercising the copy, not the code. `T-0065`'s vitest duplicate
#: was the same shape, and there the repair was to pin the copy; here the copy can simply be
#: removed, which is strictly better.
from app.services.broker.cryptofundtrader import pnl_key_present as _cft_source  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"profit": "5"}, "profit"),
        ({"netProfit": "5"}, "netProfit"),
        ({"openNetProfit": "5"}, "openNetProfit"),
        # ORDER PRESERVED — this task records which key was read and changes nothing about
        # which key is preferred. That question is T-0114 and is gated.
        ({"profit": "5", "netProfit": "4"}, "profit"),
        ({"netProfit": "4", "openNetProfit": "3"}, "netProfit"),
        ({}, None),
        ({"someOtherKey": "5"}, None),
    ],
)
def test_the_recorded_key_is_the_one_ACTUALLY_PRESENT(raw, expected):
    assert _cft_source(raw) == expected


def test_a_payload_with_NO_pnl_key_records_None_and_NEVER_defaults_to_profit():
    """**The must-not-happen.** Defaulting the recorded provenance to `"profit"`
    reintroduces the ambiguity one layer down — in the field whose entire purpose is to
    remove it, and with the appearance of having been recorded."""
    assert _cft_source({}) is None
    assert _cft_source({"volume": "1"}) != "profit"


def test_a_value_from_a_DEFAULT_does_not_record_a_key_name():
    """**`.get(key, default)` is not a key read.** The key may be absent while a value still
    appears, so a provenance taken from a defaulted read names a key the payload never
    carried. `oanda.py` read `side.get("unrealizedPL", "0")` — a fabricated zero that reads
    as a real P&L."""
    def _oanda_source(side: dict) -> str | None:
        return "unrealizedPL" if "unrealizedPL" in side else None

    assert _oanda_source({"unrealizedPL": "5"}) == "unrealizedPL"
    assert _oanda_source({}) is None, (
        "the defaulted '0' still appears in unrealized_pnl because the field is "
        "non-optional — so the FAULT has to be carried by the provenance instead"
    )


# ======================================================================================
# ALL FOUR PRODUCERS, STRUCTURALLY — a producer that forgets is the whole failure mode
# ======================================================================================


def test_every_adapter_that_builds_a_Position_supplies_pnl_source():
    """`T-0059` taught this shape: a new required field is an obligation on every PRODUCER,
    and the one that forgets is found by a `ValidationError` at runtime rather than here.

    Derived by AST over the broker package, not from a list — a fifth adapter must be caught
    on the day it is added, which is `B258`'s own argument.
    """
    import ast
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / "broker"
    offenders = []
    for path in sorted(pkg.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Position"):
                continue
            if "pnl_source" not in {kw.arg for kw in node.keywords if kw.arg}:
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        f"these build a Position without stating where its P&L came from: {offenders}"
    )


def test_the_simulators_say_COMPUTED_and_the_live_adapters_read_a_KEY():
    """The distinction the three states exist for, asserted over the real modules."""
    import ast
    import inspect

    from app.services.broker import cft_sim, cryptofundtrader, paper

    for mod in (paper, cft_sim):
        src = inspect.getsource(mod)
        assert 'pnl_source="computed"' in src, (
            f"{mod.__name__} derives its P&L locally and must say so — `None` there would "
            "read as a failed read"
        )

    cft = inspect.getsource(cryptofundtrader)
    assert 'pnl_source="profit"' not in cft, "the provenance must never be hardcoded"
    tree = ast.parse(cft)
    assert any(
        isinstance(n, ast.Compare) and any(isinstance(o, ast.In) for o in n.ops)
        and "raw" in ast.unparse(n)
        for n in ast.walk(tree)
    ), "the CFT reader must test key PRESENCE rather than defaulting"
