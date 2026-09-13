"""T-0141 — a partial fill is a REAL POSITION, or a HALT when we cannot size it (`B413`).

Against `agents/tasks/T-0141/KILL_SET.md`, 8 mutations and 2 prohibitions, registered before this
file existed.

**THE RULING** (manager, on a question raised rather than defaulted in code): a fill above zero is
a real position and is tracked at the **FILLED** size, never the asked size; a partial whose size we
cannot read **HALTS the run with a named reason**; reconciliation is **not** built here.

---

**ONE CORRECTION TO `B413`'s PREMISE, measured, because it changes what the fix has to do.** The
register said a partial fill leaves the engine with *no row*. It does not — it left a **FALSE**
one. Driven by evaluating the loop's own `else` expressions against the dict the real adapter
returns for a real `PARTIALLY_FILLED` order:

```
res.get('status') == 'FILLED'   ->  False, so the else ran
reason = res.get('reason') or res.get('status') or 'rejected'   ->  'PARTIALLY_FILLED'
code   = res.get('rejection_code')                              ->  None
_record_rejected_signal wrote  outcome=REJECTED  code=UNCLASSIFIED
```

So the engine recorded **a refusal of an order the venue had partly filled**. Better than nothing
in exactly one way — `UNCLASSIFIED` alarms, so the hole was visible rather than silent. Worse in
the way `B399` names: a row of the wrong shape reads as coverage. **The fix therefore has to STOP
the false row, not merely add a true one**, and `M-8` had to be written to assert the partial's
record is a POSITION at the filled size — asserting only that it *differs* from a full fill's
record is satisfied by the defect itself.

⚠ **`M-10`, THE PROHIBITION — WIDER THAN IT LOOKS.** This account has placed **zero** orders.
**Three shapes in this file are OURS, not Alpaca's:** that a partial reports `PARTIALLY_FILLED`,
that `filled_qty` is present-or-null, and that the remainder is abandoned rather than left resting.
**Nothing here has met a real Alpaca partial fill**, and the manager has ruled that the
remainder's fate is an assumption we have no right to. No arm below says otherwise; the register
says *untested against the venue*, not *covered*.
"""
from __future__ import annotations

import pytest

from app.services.live.crypto_loop import (
    BLOCK_HALT,
    BLOCK_SKIP,
    HALT_PARTIAL_UNSIZED,
    BlockReason,
    LiveCryptoLoop,
)

pytestmark = pytest.mark.asyncio

_units = LiveCryptoLoop._position_units


# =====================================================================================
# M-1 / M-5 — WHICH QUANTITY IS THE POSITION, and zero is not one
# =====================================================================================

async def test_a_PARTIAL_is_sized_from_the_FILLED_quantity_not_the_ASKED_one():
    """**`M-1`, and the fixture makes the two DIFFER on purpose.**

    Every result reaching this code in a realistic fixture has them EQUAL — a full fill fills what
    was asked — so a mutation that reads the asked size is **inert** unless the fixture separates
    them. `T-0140`'s `M-6` rule, and `B411c`'s survival was the same shape.

    It matters beyond the record: `sized_units` is what the partial-close accounting reads
    (`crypto_loop.py:1579`, `:1624`), so the asked size here would make the exit ladder try to
    close more than exists.
    """
    got = _units({"status": "PARTIALLY_FILLED", "filled_units": 0.004, "units": 0.01})

    assert got == 0.004, f"sized from {got} — 0.01 is what we ASKED for, not what we hold"


async def test_a_PARTIAL_never_falls_back_to_the_SUBMITTED_quantity():
    """The fallback exists for `FILLED` and must not reach here — for Alpaca `units` is what we
    SUBMITTED, so falling back to it on a partial rebuilds `B411`'s defect deliberately."""
    assert _units({"status": "PARTIALLY_FILLED", "filled_units": None, "units": 0.01}) is None


@pytest.mark.parametrize("filled", [0.0, -0.0])
async def test_a_ZERO_fill_is_NOT_a_position(filled):
    """**`M-5`.** *Above zero* is the ruling, so the boundary is pinned: a zero fill recorded as a
    position is a phantom the engine then tries to exit."""
    assert _units({"status": "PARTIALLY_FILLED", "filled_units": filled, "units": 0.01}) is None
    assert _units({"status": "FILLED", "filled_units": filled, "units": 0.01}) is None


async def test_a_NEGATIVE_fill_is_not_a_position_either():
    """Not in the kill set, and it is the same predicate: `> 0` must not become `!= 0`."""
    assert _units({"status": "FILLED", "filled_units": -0.004, "units": 0.01}) is None


# =====================================================================================
# M-3 — THE MUST-MISS: the brokers the engine ACTUALLY runs on must still fill
# =====================================================================================

async def test_a_FULL_fill_from_a_broker_that_reports_NO_filled_quantity_still_OPENS():
    """**`M-3`, THE MUST-MISS, and it is live rather than hypothetical.**

    `paper.py` and `cft_sim.py` return `units` and **no `filled_units` at all** — measured from
    their `place_order` return dicts, not assumed — and those two are what the engine runs on
    today. **A fix that requires `filled_units` halts every paper and sim entry** and destroys the
    order path while satisfying every other row in the kill set.

    A paper fill fills what was asked, so `units` IS the filled size there.
    """
    assert _units({"status": "FILLED", "units": 0.01}) == 0.01


async def test_the_paper_and_sim_brokers_really_DO_omit_the_field_this_fallback_exists_for():
    """**The control for the arm above** — it would pass against a fallback nothing needs.

    Read off the brokers' own `place_order` returns by AST, so if either ever starts reporting a
    filled quantity this goes red and the fallback can be narrowed instead of being carried
    forever on a premise nobody rechecked.
    """
    import ast
    import pathlib

    broker_dir = pathlib.Path(LiveCryptoLoop.__module__.replace(".", "/")).parents[1] / "broker"
    if not broker_dir.exists():                       # running from a different cwd
        broker_dir = pathlib.Path("app/services/broker")

    for name in ("paper.py", "cft_sim.py"):
        tree = ast.parse((broker_dir / name).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                  and n.name == "place_order")
        keys = {k.value for d in ast.walk(fn) if isinstance(d, ast.Dict)
                for k in d.keys if isinstance(k, ast.Constant)}
        assert "units" in keys, f"{name} no longer reports `units`; the fallback has no source"
        assert "filled_units" not in keys, (
            f"{name} now reports `filled_units` — the FILLED fallback is no longer needed for it, "
            f"and carrying it hides which brokers actually depend on it"
        )


async def test_a_non_fill_status_is_not_a_position_at_all():
    """The other half of the must-miss: the resolver must not turn a rejection into a position."""
    for status in ("REJECTED", "submitted", "SUBMITTED", "new", None):
        assert _units({"status": status, "units": 0.01, "filled_units": 0.004}) is None, status


# =====================================================================================
# M-6 / M-7 — THE HALT CARRIES A NAME, AND A CONSUMER CHANGES BEHAVIOUR BECAUSE OF IT
# =====================================================================================

async def test_the_halt_reason_REACHES_A_CONSUMER_rather_than_merely_existing():
    """**`M-6`, and the second half is the one that matters.**

    `self.paused` is a bare bool and `status()` had no reason key, so an unnamed halt was
    indistinguishable from an operator pause, from the order-path gate and from a prop-firm halt —
    **three causes, one flag.** But a reason stored where nothing reads it is `B394`, a mechanism
    with no consumer, which this register has filed four instances of in one night.

    So this drives the CONSUMER: `_entry_block_reason` must refuse entry *because of* the reason,
    and the reason must be in what it returns.
    """
    loop = LiveCryptoLoop()

    assert await loop._entry_block_reason("BTC/USD") is None, (
        "a fresh loop already blocks, so this arm could not tell the halt from the baseline"
    )

    loop._declare_halt(HALT_PARTIAL_UNSIZED)
    block = await loop._entry_block_reason("BTC/USD")

    assert block is not None, "the halt does not block entry, so it is not a halt"
    assert HALT_PARTIAL_UNSIZED in block, f"the block does not carry the reason: {block!r}"


async def test_the_halt_blocks_WITHOUT_reading_a_position_or_the_venue():
    """The halt means a position of unknown size may exist, which outranks every other reason not
    to enter — and, like the direction refusal in `alpaca.place_order`, it must not depend on a
    position read succeeding. Otherwise a venue timeout turns the halt into a pass."""
    loop = LiveCryptoLoop()
    loop._declare_halt(HALT_PARTIAL_UNSIZED)

    async def _explode(pair):
        raise AssertionError("the halt read a position before refusing")

    loop._has_position = _explode
    loop._open_count = _explode

    assert await loop._entry_block_reason("BTC/USD") is not None


async def test_the_halt_is_classified_as_a_HALT_and_a_routine_block_as_a_SKIP():
    """**`B415`.** The activity kind used to come from `block.startswith("KILL SWITCH")` — a prose
    prefix — so **any halt added later was a `skip` by default**, which is how this task's named
    halt would have arrived, defeating `M-6` through the back door."""
    loop = LiveCryptoLoop()
    loop._declare_halt(HALT_PARTIAL_UNSIZED)
    halt = await loop._entry_block_reason("BTC/USD")
    assert halt.kind == BLOCK_HALT

    # **A FRESH LOOP, not `halt_reason = None`.** Nothing in production lifts a halt — it survives
    # `reset` and `stop` by ruling, and it is a read-only property now — so clearing it here was
    # asserting the discrimination against a state the engine cannot reach.
    unhalted = LiveCryptoLoop()
    assert unhalted.halt_reason is None
    unhalted.paused = True
    pause = await unhalted._entry_block_reason("BTC/USD")
    assert pause.kind == BLOCK_SKIP, (
        "an operator pause is now reported as a halt — the classification changed for a reason "
        "this task did not rule on"
    )
    assert halt.kind != pause.kind, "the two kinds must DISCRIMINATE"


async def test_the_halt_reason_DOES_NOT_COLLIDE_with_any_existing_block_reason():
    """**`M-7`.** *Halted because a partial fill could not be sized* and *an operator stopped it*
    must not share a value, or no count and no panel can separate them."""
    loop = LiveCryptoLoop()
    others = []

    loop.paused = True
    others.append(str(await loop._entry_block_reason("BTC/USD")))
    loop.paused = False

    from app.services.compliance.kill_switch import kill_switch

    kill_switch.arm(reason="prop firm daily loss")
    try:
        others.append(str(await loop._entry_block_reason("BTC/USD")))
    finally:
        kill_switch.disarm()

    loop._declare_halt(HALT_PARTIAL_UNSIZED)
    ours = str(await loop._entry_block_reason("BTC/USD"))

    assert ours not in others, f"the halt reuses an existing reason: {ours!r}"
    for other in others:
        assert HALT_PARTIAL_UNSIZED not in other, (
            f"an unrelated block already carries our reason, so a count keyed on it would "
            f"attribute {other!r} to a partial fill"
        )


async def test_status_SHOWS_the_halt_reason_and_shows_NOTHING_when_there_is_none():
    """`M-6`'s reader, and the negative half: a key that is always populated cannot report health.

    `status()` is what the operator panel reads, so this is where *stopped because of a partial we
    could not size* becomes distinguishable from *stopped by hand* without reading the source.
    """
    loop = LiveCryptoLoop()

    assert "halt_reason" in (await loop.status()), (
        "the reason is stored where status() cannot show it — B394, a mechanism with no consumer"
    )
    assert (await loop.status())["halt_reason"] is None

    loop._declare_halt(HALT_PARTIAL_UNSIZED)
    assert (await loop.status())["halt_reason"] == HALT_PARTIAL_UNSIZED


async def test_the_halt_SURVIVES_a_stop_and_a_reset():
    """**Deliberate, and it is the ruling's direction rather than an oversight.**

    `paused` is cleared by both `stop` and `reset`, because an operator pause is resolved by the
    operator. This is not: it says a position of unknown size may exist AT THE VENUE, and
    restarting the engine does not make that position known. **Clearing it silently on the next
    start re-enters the hole it exists to stop us trading into.**

    Asserted over the source of both methods, because driving them needs a database and a run —
    and what must be true is that neither one touches the field.
    """
    import ast
    import inspect

    for name in ("stop", "reset_run"):
        method = getattr(LiveCryptoLoop, name, None)
        if method is None:
            continue
        src = inspect.getsource(method)
        tree = ast.parse("".join(src.splitlines(keepends=True)).lstrip())
        cleared = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "halt_reason" for t in n.targets)
        ]
        assert not cleared, (
            f"`{name}` clears halt_reason, so restarting the engine silently resumes trading "
            f"around a position we could not size"
        )
        assert "self.paused = False" in src, (
            f"`{name}` no longer clears `paused`, so this arm is no longer comparing the two "
            f"lifetimes and its point is gone"
        )


# =====================================================================================
# M-9 — THE PROHIBITION, MADE CHECKABLE
# =====================================================================================

async def test_the_fill_handler_makes_NO_FURTHER_VENUE_CALLS():
    """**`M-9`.** *Do not build reconciliation here* is untestable as an intention, so what is
    asserted is the checkable consequence: the fill-handling branch calls nothing on the broker.

    Polling for the remainder falls under the same prohibition — a market order's remainder is the
    venue's business, and **assuming it will fill is an assumption about Alpaca we have no right
    to** (`M-10`). `reconcile_positions` already exists and runs at connect; wiring the partial
    path into it is the next task, not this one.
    """
    import ast
    import inspect

    from app.services.live import crypto_loop as mod

    fn = next(
        n for n in ast.walk(ast.parse(inspect.getsource(mod)))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_tick_symbol"
    )
    # The branch that handles a fill-bearing status, located structurally — by `FILL_OUTCOMES` since
    # `T-0130`, where the branch stopped testing the status and started testing its CLASS (K-11).
    forks = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and any(isinstance(c, ast.Name) and c.id == "FILL_OUTCOMES"
                for c in ast.walk(n.test))
    ]
    assert forks, "the fill-bearing branch is gone; this arm is pinning nothing"

    FORBIDDEN = {"get_positions", "get_orders", "get_asset", "place_order", "close_position",
                 "get_account", "reconcile_positions", "submit_order", "execute"}
    offenders = []
    for fork in forks:
        for node in ast.walk(ast.Module(body=fork.body, type_ignores=[])):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN:
                    offenders.append(node.func.attr)

    assert not offenders, (
        f"the fill handler calls the venue: {sorted(set(offenders))}. Reconciliation is the next "
        f"task, and polling for the remainder is the same prohibition"
    )


# =====================================================================================
# M-2 / M-8 — DRIVEN THROUGH THE REAL BRANCH, not asserted over its shape
# =====================================================================================
#
# The existing integration arm for this branch says driving `_tick_symbol` "would be a network
# test wearing a unit test's clothes", and it was right about the method as a whole — it fetches a
# ticker, pulls 320 bars and runs the strategy. But the two things it needs from outside are both
# module-level seams: `_fetch_bars` on the instance and `evaluate_latest_bar_traced` at
# `crypto_loop`'s module scope. Stubbing those two and the execution RESULT leaves the branch under
# test — the fill handling, the recorder call, the halt and the activity line — running for real.
#
# That matters here specifically: `M-8`'s property is about what lands in the RECORD, and a
# structural assertion cannot tell `opened_units` holding the filled size from it holding the asked
# one. Only driving it can.


class _Recorded:
    """Captures which recorder the branch chose and what it was handed."""

    def __init__(self):
        self.decisions: list[dict] = []
        self.rejections: list[dict] = []
        self.acts: list[tuple[str, str]] = []


def _driven_loop(monkeypatch, result: dict) -> tuple[LiveCryptoLoop, _Recorded]:
    """A loop whose strategy always signals and whose execution returns `result`."""
    import pandas as pd

    from app.db.enums import DirectionType
    from app.services.live import crypto_loop as mod

    loop = LiveCryptoLoop()
    seen = _Recorded()

    base = [100.0 + i for i in range(60)]
    bars = pd.DataFrame({
        "open": base, "high": [b + 1 for b in base],
        "low": [b - 1 for b in base], "close": base, "volume": [10.0] * 60,
    })

    class _Sig:
        symbol, direction = "BTC/USD", DirectionType.LONG
        entry, sl, tp = 100.0, 99.0, None
        risk_pct, approved, client_order_id = 0.01, True, "sig-x"
        partial_price = partial_fraction = None

    class _Trace:
        reasons = ["t0141"]
        would_block_by = None

        def __getattr__(self, _):
            return None

    async def _fetch(*a, **k):
        return bars

    async def _exec(sig):
        return dict(result)

    async def _decision(pair, entry_df, sig, position_units, **kw):
        seen.decisions.append({"units": position_units, **kw})

    async def _reject(pair, entry_df, sig, reason, trace, code=None):
        seen.rejections.append({"reason": reason, "code": code})

    async def _act(kind, msg):
        seen.acts.append((kind, msg))

    monkeypatch.setattr(mod, "evaluate_latest_bar_traced",
                        lambda *a, **k: (_Sig(), _Trace()))
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_record_signal_decision", _decision)
    monkeypatch.setattr(loop, "_record_rejected_signal", _reject)
    monkeypatch.setattr(loop, "_act", _act)
    monkeypatch.setattr(loop, "_shadow_evaluate", lambda *a, **k: _noop())
    monkeypatch.setattr(loop, "_maybe_emit_census", lambda *a, **k: _noop())
    monkeypatch.setattr(loop, "_news_context", lambda *a, **k: _noop())
    monkeypatch.setattr(loop, "_has_position", lambda *a, **k: _false())
    monkeypatch.setattr(loop, "_open_count", lambda *a, **k: _zero())
    monkeypatch.setattr(loop.execution, "execute", _exec)
    return loop, seen


async def _noop():
    return None


async def _false():
    return False


async def _zero():
    return 0


async def test_a_PARTIAL_FILL_OPENS_A_POSITION_at_the_filled_size(monkeypatch):
    """**`M-2`, driven.** A partial leaves real exposure, and before this the engine recorded a
    REJECTION of it."""
    loop, seen = _driven_loop(monkeypatch, {
        "status": "PARTIALLY_FILLED", "filled_units": 0.004, "units": 0.01,
        "sized_units": 0.01, "fill": 100.5, "position_id": "p1",
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert len(seen.decisions) == 1, (
        f"a partial fill recorded {len(seen.decisions)} position(s); the venue holds one"
    )
    assert seen.decisions[0]["units"] == 0.004, (
        f"recorded {seen.decisions[0]['units']} — the asked size, not what we hold"
    )
    assert loop.halt_reason is None, "a partial we COULD size must not halt the run"


async def test_a_PARTIAL_FILL_NO_LONGER_WRITES_A_REJECTION_ROW(monkeypatch):
    """**The correction to `B413`, driven.** The register said a partial left no row; it left a
    row saying `outcome=REJECTED`, `rejection_code=UNCLASSIFIED` for an order the venue had partly
    filled. Widening the gate alone would have produced BOTH rows."""
    loop, seen = _driven_loop(monkeypatch, {
        "status": "PARTIALLY_FILLED", "filled_units": 0.004, "units": 0.01,
        "sized_units": 0.01, "fill": 100.5, "position_id": "p1",
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert seen.rejections == [], (
        f"the partial was ALSO recorded as a refusal: {seen.rejections}. One event, two "
        f"contradictory rows, and the rejection one is false"
    )


async def test_a_PARTIAL_WE_CANNOT_SIZE_HALTS_AND_RECORDS_NEITHER(monkeypatch):
    """**`M-4` driven through the branch, and the fixture ABSENTS the field on purpose.**

    A fixture that always reports a size never reaches this path — exactly how `B411c` survived
    its first mutation run.

    And it must record neither: a position we cannot size is not a position we can describe, and
    a REJECTED row for it is the false record this task removes.
    """
    loop, seen = _driven_loop(monkeypatch, {
        "status": "PARTIALLY_FILLED", "filled_units": None, "units": 0.01,
        "sized_units": 0.01, "fill": 100.5, "position_id": "p1",
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert loop.halt_reason == HALT_PARTIAL_UNSIZED, (
        "the run did not halt — a could-not-ask must fail CLOSED, because a position may exist "
        "that we cannot size and trading around it is worse than stopping"
    )
    assert seen.decisions == [], "a position of unknown size was recorded with a made-up size"
    assert seen.rejections == [], "the halt still wrote a rejection row for a partly-filled order"
    assert any(kind == BLOCK_HALT for kind, _ in seen.acts), (
        f"the operator-visible line is not a halt: {seen.acts}"
    )
    assert any(HALT_PARTIAL_UNSIZED in msg for _, msg in seen.acts), (
        "the halt is surfaced without its reason, so it looks like any other stop"
    )


async def test_a_FULL_FILL_STILL_OPENS_A_FULL_POSITION(monkeypatch):
    """**`M-3`, THE MUST-MISS, driven through the branch on the shape the engine really runs.**

    `paper.py` returns `units` and no `filled_units`. A fix that halts on every fill satisfies
    `M-2` and `M-4` and destroys the order path — and this is the arm that dies when it does.
    """
    loop, seen = _driven_loop(monkeypatch, {
        "status": "FILLED", "units": 0.01, "sized_units": 0.01,
        "fill": 100.5, "position_id": "p1",
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert loop.halt_reason is None, "a full fill halted the run"
    assert len(seen.decisions) == 1 and seen.decisions[0]["units"] == 0.01
    assert seen.rejections == []


async def test_a_REJECTION_still_routes_to_the_rejection_recorder(monkeypatch):
    """The fourth outcome, unchanged — the branch this task adds must not swallow the one that
    was already there (`B403`: a refused signal that leaves no row is absent from the
    denominator, not merely unclassified)."""
    loop, seen = _driven_loop(monkeypatch, {
        "status": "REJECTED", "reason": "venue said no",
        "rejection_code": "VENUE_TRANSPORT", "sized_units": 0.01,
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert len(seen.rejections) == 1
    assert seen.rejections[0]["code"] == "VENUE_TRANSPORT"
    assert seen.decisions == [] and loop.halt_reason is None


async def test_a_PARTIAL_and_a_FULL_fill_are_DISTINGUISHABLE_BY_THE_POSITION_SIZE(monkeypatch):
    """**`M-8`, written to the CORRECTED property.**

    The kill set says a partial and a full fill must be distinguishable in the record. **They
    already were, before the fix** — full wrote `outcome=FILLED`, partial wrote
    `REJECTED`/`UNCLASSIFIED`. So an arm asserting merely that the two records DIFFER passes
    against the unfixed code: `A != B` satisfied by incidental difference, where the incidental
    difference is the defect itself.

    What must be true is stronger and is what this asserts: **both are positions, and the sizes
    differ because the FILLS differed.**
    """
    same_ask = {"units": 0.01, "sized_units": 0.01, "fill": 100.5, "position_id": "p1"}

    full_loop, full = _driven_loop(monkeypatch, {"status": "FILLED", **same_ask})
    await full_loop._tick_symbol("BTC/USD", "BTCUSDT")

    part_loop, part = _driven_loop(monkeypatch, {
        "status": "PARTIALLY_FILLED", "filled_units": 0.004, **same_ask})
    await part_loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert len(full.decisions) == len(part.decisions) == 1, "one of them is not a position"
    assert full.decisions[0]["units"] == 0.01
    assert part.decisions[0]["units"] == 0.004
    assert full.decisions[0]["units"] != part.decisions[0]["units"]


async def test_TWO_FULL_FILLS_differing_only_INCIDENTALLY_are_NOT_distinguished(monkeypatch):
    """**`M-8`'s negative control, and the row review said they would check hardest.**

    Two runs identical in the property but differing incidentally must NOT satisfy the arm above.
    Measured in `T-0138` part 2: two sim runs differing only in starting balance made a naive
    differential pass vacuously, so the projection has to be onto the position size and nothing
    else.
    """
    a_loop, a = _driven_loop(monkeypatch, {
        "status": "FILLED", "units": 0.01, "sized_units": 0.01,
        "fill": 100.5, "position_id": "p1"})
    await a_loop._tick_symbol("BTC/USD", "BTCUSDT")

    b_loop, b = _driven_loop(monkeypatch, {
        "status": "FILLED", "units": 0.01, "sized_units": 0.01,
        # A DIFFERENT fill price and a different position id — incidental to the property.
        "fill": 101.75, "position_id": "p2-completely-different"})
    await b_loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert a.decisions[0]["units"] == b.decisions[0]["units"], (
        "two full fills of the same size were given different position sizes, so the arm above "
        "would pass on incidental difference"
    )


# =====================================================================================
# B415 — THE CONSUMER, not just the producer. Both survivors of the first harness run.
# =====================================================================================

async def test_the_ACTIVITY_LINE_for_a_halt_is_labelled_halt_not_skip(monkeypatch):
    """**THE GAP THE FIRST MUTATION RUN FOUND, and it was mine rather than the code's.**

    `test_the_halt_is_classified_as_a_HALT_and_a_routine_block_as_a_SKIP` asserts that
    `_entry_block_reason` ATTACHES a kind — the PRODUCER. Both `B415` mutations live in the
    CONSUMER (`_tick_symbol`'s `kind = …`), so restoring the prose prefix
    `block.startswith("KILL SWITCH")` **survived the whole suite**: every arm agreed the reason
    carried its classification and none checked that anything read it.

    That is `B394` from the other end — a field with a consumer that ignores it — and it is the
    exact failure `M-6` names, so it deserved an arm rather than a note. The operator's activity
    feed is the consumer, and this drives it.
    """
    loop, seen = _driven_loop(monkeypatch, {"status": "FILLED", "units": 0.01})
    loop._declare_halt(HALT_PARTIAL_UNSIZED)

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    blocked = [(kind, msg) for kind, msg in seen.acts if "skipped" in msg]
    assert blocked, f"the gate did not block, so this arm measures nothing: {seen.acts}"
    assert all(kind == BLOCK_HALT for kind, _ in blocked), (
        f"a HALT is surfaced to the operator as {[k for k, _ in blocked]} — the prose prefix is "
        f"back, and any halt that does not begin 'KILL SWITCH' reads as a routine skip"
    )


async def test_an_operator_PAUSE_is_still_labelled_skip(monkeypatch):
    """The control for the arm above — a classifier that answers `halt` to everything answers
    nothing, and it would bury a real halt in a feed of false ones."""
    loop, seen = _driven_loop(monkeypatch, {"status": "FILLED", "units": 0.01})
    loop.paused = True

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    blocked = [(kind, msg) for kind, msg in seen.acts if "skipped" in msg]
    assert blocked, f"the gate did not block: {seen.acts}"
    assert all(kind == BLOCK_SKIP for kind, _ in blocked), (
        f"an operator pause is reported as a halt: {[k for k, _ in blocked]}"
    )


async def test_EVERY_block_reason_the_gate_produces_carries_its_own_kind():
    """**Why the second `B415` mutation was INERT, stated rather than papered over.**

    Flipping the consumer's fallback from `BLOCK_HALT` to `BLOCK_SKIP` changes nothing while every
    block reason is a `BlockReason`, because the fallback is only reached by a plain `str` — **a
    shape `_entry_block_reason` cannot produce.** Its survival measures nothing, which is the same
    verdict the `M-6` swap earned in `T-0140`: an inert mutation is a fixture problem, and here the
    fixture would have to be a value production cannot build.

    So the checkable property is this one — the gate classifies on EVERY path — and the fallback
    stays as belt-and-braces for a future producer that forgets. It is deliberately the ALARMING
    side: a block whose seriousness we cannot establish should read as a halt, because a stopped
    engine that looks idle is the failure this codebase keeps filing (`B179`).
    """
    from app.services.compliance.kill_switch import kill_switch

    loop = LiveCryptoLoop()

    async def _no_position(pair):
        return False

    async def _none_open():
        return 0

    loop._has_position = _no_position
    loop._open_count = _none_open

    seen = []

    # **A SECOND LOOP FOR THE HALT, because a halt cannot be lifted.** It is checked first and
    # masks every other reason, which is why the original cleared it to move on. That clear is not
    # available any more and should not have been: nothing in production un-halts.
    halted = LiveCryptoLoop()
    halted._has_position = _no_position
    halted._open_count = _none_open
    halted._declare_halt(HALT_PARTIAL_UNSIZED)
    seen.append(await halted._entry_block_reason("BTC/USD"))

    kill_switch.arm(reason="daily loss")
    try:
        seen.append(await loop._entry_block_reason("BTC/USD"))
    finally:
        kill_switch.disarm()

    loop.paused = True
    seen.append(await loop._entry_block_reason("BTC/USD"))
    loop.paused = False

    async def _holding(pair):
        return True

    loop._has_position = _holding
    seen.append(await loop._entry_block_reason("BTC/USD"))
    loop._has_position = _no_position

    loop.max_concurrent = 0

    async def _one_open():
        return 1

    loop._open_count = _one_open
    seen.append(await loop._entry_block_reason("BTC/USD"))

    assert len(seen) == 5, "a block path stopped producing a reason"
    for block in seen:
        assert isinstance(block, BlockReason), (
            f"{str(block)!r} is a plain {type(block).__name__}, so its seriousness has to be "
            f"guessed from its text — which is exactly B415"
        )
        assert block.kind in (BLOCK_HALT, BLOCK_SKIP)

    kinds = {str(b): b.kind for b in seen}
    assert len({*kinds.values()}) == 2, (
        f"every block has the same kind, so the classification discriminates nothing: {kinds}"
    )


# =====================================================================================
# UNPARSEABLE IS UNSIZEABLE — found by driving the resolver, not by reading it
# =====================================================================================

@pytest.mark.parametrize("garbage", ["not a number", float("nan"), float("inf"),
                                     float("-inf"), object()])
async def test_an_UNUSABLE_filled_quantity_takes_the_HALT_path_not_the_fallback(garbage):
    """**A broker that reported garbage SPOKE, and absence is a different answer.**

    `float()` raising here would abort the bar into `_loop`'s blanket handler and leave NO row,
    which is `B403`'s shape. *We cannot establish the size* is exactly what an unparseable
    quantity means, so it takes the same path as an absent one — the halt.

    **And it must NOT fall back to the submitted quantity.** That is the distinction this arm
    exists for: `paper.py` never reports a filled quantity, so absence is its normal and `units`
    is the fill; a venue that answered `NaN` has said something unusable, and substituting the
    size we asked for would reach `B411`'s defect through the fallback instead of the field.
    """
    assert _units({"status": "FILLED", "filled_units": garbage, "units": 0.01}) is None
    assert _units({"status": "PARTIALLY_FILLED", "filled_units": garbage, "units": 0.01}) is None


async def test_an_ABSENT_filled_quantity_on_a_FULL_fill_still_uses_units():
    """The other half, and the one that keeps the order path alive — the control for the arm
    above, which would otherwise be satisfied by treating every full fill as unsizeable."""
    assert _units({"status": "FILLED", "units": 0.01}) == 0.01


# =====================================================================================
# B417 — a size that prints as zero
# =====================================================================================

async def test_a_crypto_size_is_not_rendered_as_ZERO():
    """**`B417`.** The activity line used `:.3f`. Measured against the venue's own numbers
    (`T-0139`): BTC's minimum order is `0.000012941` and a 1% risk entry is `1e-4` to `1e-3` — so
    **every BTC entry the engine has ever logged read `Entered BTC/USD LONG 0.000`.**

    The trade was real and the number in front of the operator was zero, which is
    indistinguishable from the `NON_POSITIVE_SIZE` refusal this codebase has a rejection code for.
    """
    from app.services.live.crypto_loop import _fmt_units

    assert f"{0.000012941:.3f}" == "0.000", "the defect this guards is gone; simplify the format"

    assert _fmt_units(0.000012941) == "0.000012941"
    assert _fmt_units(0.0001) == "0.0001"
    assert float(_fmt_units(0.004)) == 0.004


async def test_the_rendered_size_keeps_whole_lots_readable_and_says_when_it_has_none():
    """The must-miss: nine decimals everywhere would print `0.500000000` for a half lot, and a
    formatter that answers `0` to an unknown size is `B411c`'s default all over again."""
    from app.services.live.crypto_loop import _fmt_units

    assert _fmt_units(0.5) == "0.5"
    assert _fmt_units(1.0) == "1"
    assert _fmt_units(None) == "unknown", (
        "an unknown size rendered as a number is a size we are claiming to know"
    )
    assert _fmt_units(None) != "0"


async def test_the_ENTRY_line_shows_a_real_crypto_size_end_to_end(monkeypatch):
    """Driven through the branch, because the formatter being right does not mean it is used —
    `B417`'s two call sites were the point, not the helper."""
    loop, seen = _driven_loop(monkeypatch, {
        "status": "PARTIALLY_FILLED", "filled_units": 0.000012941, "units": 0.01,
        "sized_units": 0.01, "fill": 70_000.0, "position_id": "p1",
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    entered = [msg for kind, msg in seen.acts if "Entered" in msg]
    assert entered, f"no entry line was emitted: {seen.acts}"
    assert "0.000012941" in entered[0], f"the size is unreadable: {entered[0]!r}"
    assert " 0.000 " not in entered[0]


async def test_the_ENTRY_line_names_WHAT_was_entered_with_AND_without_an_exit_plan(monkeypatch):
    """**`B417`'s second half.** The conditional bound over the whole implicit concatenation, so
    the `else` branch emitted only `"@ 70000 (SL 99, no exit plan)"` — **an entry line that does
    not say what was entered.**

    Both branches are driven, because the bug was in the one a realistic signal never takes:
    `strategy_step.py` sets `partial_price` on every signal it produces, so the defect was
    reachable only from a hand-built one. A fixture exercising just the live shape would have
    reported this line healthy.
    """
    for partial_price, partial_fraction in ((None, None), (72_000.0, 0.7)):
        loop, seen = _driven_loop(monkeypatch, {
            "status": "FILLED", "units": 0.004, "sized_units": 0.004,
            "fill": 70_000.0, "position_id": "p1",
        })
        # The signal the branch keys on — set on the instance the stub returns.
        from app.services.live import crypto_loop as mod

        sig, trace = mod.evaluate_latest_bar_traced()
        sig.partial_price = partial_price
        sig.partial_fraction = partial_fraction
        monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (sig, trace))

        await loop._tick_symbol("BTC/USD", "BTCUSDT")

        entry = [msg for kind, msg in seen.acts if kind == "entry"]
        assert entry, f"no entry line for partial_price={partial_price}: {seen.acts}"
        assert "BTC/USD" in entry[0], f"the entry line does not name the pair: {entry[0]!r}"
        assert "LONG" in entry[0], f"the entry line does not name the direction: {entry[0]!r}"
        assert "0.004" in entry[0], f"the entry line does not name the size: {entry[0]!r}"


# =====================================================================================
# B419 — "KEY ABSENT" AND "KEY PRESENT AND None" ARE THE TWO CASES THIS FUNCTION SEPARATES
# =====================================================================================

async def test_a_FULL_fill_whose_VENUE_REPORTED_NOTHING_does_not_record_the_submitted_size():
    """**`B419`, found by review in the function this task added, and it is `B411` by another
    route.**

    `.get()` collapses *key absent* and *key present and `None`* to the same answer, and those are
    exactly the two cases the `FILLED` fallback exists to distinguish. My ten fixtures could not
    reach it: they all went through `.get()`, which had already erased the difference.

    ```
    paper/cft_sim   omit `filled_units` entirely   -> fall back to `units`. correct.
    alpaca          ALWAYS emits it, None = the venue did not say  -> MUST NOT fall back.
    ```

    **And `alpaca.py` refuses this three lines above the key it sets** — *"never defaulted to the
    submitted quantity, which would report a fill we have no evidence of"* — while the loop did it
    on the adapter's behalf. I wrote both sides and the second undid the first.
    """
    absent = {"status": "FILLED", "units": 0.01}
    present_none = {"status": "FILLED", "filled_units": None, "units": 0.01}

    # The premise, stated so the arm cannot pass for the wrong reason: these two are the SAME
    # through `.get()` and different through membership.
    assert absent.get("filled_units") == present_none.get("filled_units") is None
    assert ("filled_units" in absent) != ("filled_units" in present_none)

    assert _units(absent) == 0.01, "the paper/sim fallback broke — M-3's must-miss"
    assert _units(present_none) is None, (
        "a venue that reported NO filled quantity had the SUBMITTED size recorded as the position"
    )


async def test_WHICH_BROKERS_EMIT_THE_KEY_is_pinned_because_the_fix_depends_on_it():
    """**The fallback is only correct while `paper`/`cft_sim` OMIT the key and `alpaca` sets it.**

    That is a fact about three files this one does not own, so it is measured rather than assumed —
    and if any of them changes, the membership test silently starts meaning something else.
    """
    import ast
    import pathlib

    broker = pathlib.Path("app/services/broker")
    if not broker.exists():                       # running from the repo root
        broker = pathlib.Path("backend/app/services/broker")

    def emits(name: str, builders=("place_order",)) -> bool:
        tree = ast.parse((broker / name).read_text(encoding="utf-8"))
        fns = [n for n in ast.walk(tree)
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in builders]
        assert fns, f"{name} has none of {builders}; this scan is reading nothing"
        return any(isinstance(k, ast.Constant) and k.value == "filled_units"
                   for fn in fns for d in ast.walk(fn) if isinstance(d, ast.Dict) for k in d.keys)

    assert not emits("paper.py"), (
        "paper.py now reports a filled quantity — the `FILLED` fallback is no longer for it, and "
        "the membership test's meaning has changed under it"
    )
    assert not emits("cft_sim.py"), "cft_sim.py now reports a filled quantity"
    # `B427`/`B440` moved Alpaca's result dict out of `place_order` into the two methods that build it.
    assert emits("alpaca.py", ("_verdict_for_placed", "_unconfirmed_submission")), (
        "alpaca.py no longer emits `filled_units`, so an unreported venue fill is now "
        "indistinguishable from a paper fill and takes the submitted size"
    )


async def test_the_HALT_names_the_POSITION_it_warns_about(monkeypatch):
    """**The halt named the situation and not the OBJECT.**

    `res` carries the venue's own id for the position it just opened. Without it the operator is
    told a position of unknown size may exist and given no way to go and look at it — and this
    halt exists precisely because we cannot describe that position ourselves.
    """
    loop, seen = _driven_loop(monkeypatch, {
        "status": "PARTIALLY_FILLED", "filled_units": None, "units": 0.01,
        "sized_units": 0.01, "position_id": "venue-pos-7", "client_order_id": "sig-x",
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert loop.halt_reason == HALT_PARTIAL_UNSIZED
    halts = [msg for kind, msg in seen.acts if kind == BLOCK_HALT]
    assert halts, f"no halt line: {seen.acts}"
    assert "venue-pos-7" in halts[0], (
        f"the halt does not name the position it warns about: {halts[0]!r}"
    )


async def test_the_halt_says_UNREPORTED_rather_than_inventing_an_id(monkeypatch):
    """The must-miss: a missing id must read as missing. An empty string in that slot would render
    as `venue position ` and look like a truncated value rather than an absent one."""
    loop, seen = _driven_loop(monkeypatch, {
        "status": "PARTIALLY_FILLED", "filled_units": None, "units": 0.01, "sized_units": 0.01,
    })

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    halts = [msg for kind, msg in seen.acts if kind == BLOCK_HALT]
    assert "UNREPORTED" in halts[0], f"{halts[0]!r}"


async def test_the_HALT_LOG_carries_the_fields_an_operator_would_grep(monkeypatch):
    """**`B414`'s LESSON, REPRODUCED IN THE SAME TASK AND CAUGHT BY THE HARNESS.**

    Removing `position_id` from this `logger.error` call killed **nothing**: every arm drove the
    line and none read the log. That is exactly what `B414` was — *"a side effect nothing asserts
    on is not covered by the test that triggers it"* — and `B414` was mine, three hours earlier, on
    this same log statement.

    The log is not decoration here. The activity deque is in memory and the websocket push is
    transient, so **after a restart the log is the only trace of this halt that survives** — which
    makes its structured fields the durable record of a position we could not size. `setup_logging`
    serialises `extra` to JSON, so these are grep-able keys rather than prose.
    """
    from loguru import logger

    captured: list[dict] = []
    sink = logger.add(lambda m: captured.append(dict(m.record["extra"])), level="ERROR")
    try:
        loop, seen = _driven_loop(monkeypatch, {
            "status": "PARTIALLY_FILLED", "filled_units": None, "units": 0.01,
            "sized_units": 0.01, "position_id": "venue-pos-7", "client_order_id": "sig-x",
        })
        await loop._tick_symbol("BTC/USD", "BTCUSDT")
    finally:
        logger.remove(sink)

    assert captured, "the halt emitted no ERROR record at all"
    # SELECT the halt's own record rather than taking the last one. The halt now also writes two
    # durable records, and a FAILING write emits its own ERROR — so `[-1]` was the alert failure,
    # not the halt. An index is not a selector.
    halts = [e for e in captured if e.get("status") is not None]
    assert halts, f"no halt record among {len(captured)} ERROR records: {captured}"
    extra = halts[0]

    # THE OBJECT, not just the situation — an operator has to be able to find the position.
    assert extra.get("position_id") == "venue-pos-7", (
        f"the halt log does not identify the position it warns about: {extra}"
    )
    # And the numbers that say WHY it could not be sized.
    assert extra.get("status") == "PARTIALLY_FILLED"
    assert extra.get("filled_units") is None, "the venue's own (absent) answer must be recorded"
    assert extra.get("submitted_units") == 0.01
    assert extra.get("pair") == "BTC/USD"
