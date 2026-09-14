"""T-0143 — the halt's DURABLE records, and what happens when writing them fails.

`B413`'s halt stops the engine because a position may exist at the venue whose size we cannot
establish. Until now that halt left no durable record: an ERROR line that rotates, an activity
deque held in memory, and a websocket push. **After a restart, nothing.**

It now writes two, and they answer different questions:

```
DecisionRecord  outcome=UNSIZED_FILL   the CORPUS — what the decision concluded
Alert           RISK_WARNING/CRITICAL  the OPERATOR — something needs doing by hand
```

**THE HARD PART IS NOT EITHER WRITE. IT IS THAT TWO REQUIREMENTS PULL AGAINST EACH OTHER:**

* **`M-5`** a failed write must NOT kill the loop — this is a safety path, and a database write is
  most likely to fail exactly when it is most needed, because a halt usually follows something
  already going wrong;
* **`M-6`** a failed write must NOT vanish — and the obvious reconciliation, `except Exception:
  logger.error(...)`, is **`B403` rebuilt inside the fix for `B413`**. The Alert exists *because a
  log line is not a record*, so satisfying "must not vanish" with a log line satisfies it with the
  thing already known to be insufficient.

The resolution is `B394`'s own test applied to our remedy: **which existing consumer changes
behaviour because of it?** `status()` — the surface the operator is on BECAUSE of the halt.
"""
from __future__ import annotations

import pytest

from app.services.live.crypto_loop import HALT_PARTIAL_UNSIZED, LiveCryptoLoop

pytestmark = pytest.mark.asyncio


class _Boom:
    """A session maker whose every use raises, like a database that has just gone away."""

    def __init__(self, exc=None):
        self.exc = exc or RuntimeError("the database is not there")
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise self.exc


#: What the engine says between declaring a halt and getting its record on disk.
NOT_YET_WRITTEN = "durable record NOT YET WRITTEN"


def _loop_at_halt():
    """A loop at the moment of halting — halt declared, record NOT yet written.

    **Both fields are set together on purpose.** `halt_record_failed` defaulted to `None`, which
    meant *both rows are on disk* AND *no write was attempted*, so a halt whose record never
    happened reported healthy. The arms below used to assert `None` here, which is to say they
    asserted that a halted engine with nothing recorded was fine — **the arms encoded the defect.**

    **AND IT NO LONGER SETS THEM BY HAND.** It used to, and the harness showed what that cost:
    removing the alarm-set from the production halt site killed nothing, because this fixture was
    doing the production code's work. `halt_reason` is now a read-only property, so the hand-set is
    not merely discouraged — it raises. Every arm below reaches the halted state the only way the
    engine can reach it, which means `_declare_halt` regressing takes them all with it.
    """
    loop = LiveCryptoLoop()
    loop._declare_halt(HALT_PARTIAL_UNSIZED)      # the halt is ALREADY in force (M-7)
    assert loop.halt_reason and NOT_YET_WRITTEN in (loop.halt_record_failed or ""), (
        "the fixture no longer reaches the state it is named for"
    )
    return loop


def _res():
    return {"status": "PARTIALLY_FILLED", "filled_units": None, "units": 0.01,
            "position_id": "venue-pos-7", "client_order_id": "sig-x"}


def _bars():
    import pandas as pd

    base = [100.0 + i for i in range(30)]
    return pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                         "low": [b - 1 for b in base], "close": base, "volume": [1.0] * 30})


class _Sig:
    from app.db.enums import DirectionType
    symbol, direction = "BTC/USD", DirectionType.LONG
    entry, sl, tp = 100.0, 99.0, None


# =====================================================================================
# M-5 — A FAILED WRITE MUST NOT KILL THE LOOP
# =====================================================================================

async def test_a_failing_DATABASE_does_not_raise_out_of_the_halt(monkeypatch):
    """**`M-5`.** The halt is a safety path. If recording it can raise, then the moment the
    database is unhealthy is the moment the engine stops halting correctly — and a halt that
    crashes the bar is worse than one that is merely unrecorded, because `_loop`'s blanket handler
    swallows it and the next bar proceeds."""
    from app.db import session as dbsession

    boom = _Boom()
    monkeypatch.setattr(dbsession, "async_session_maker", boom)

    loop = _loop_at_halt()
    await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())   # must not raise

    assert boom.calls >= 1, "the writer never tried the database, so this arm proves nothing"


# =====================================================================================
# M-6 — AND IT MUST NOT VANISH. A LOG LINE IS NOT ENOUGH.
# =====================================================================================

async def test_a_failed_write_REACHES_status_not_only_the_log(monkeypatch):
    """**`M-6`, and the row review sharpened after I challenged its first version.**

    Their first draft required the failure to "reach the log with its reason" — which is
    try/except/log/continue, the exact shape that made `B403`. We are adding a durable record
    BECAUSE a log line is not one.

    So the assertion is on the CONSUMER: `status()`, which the operator is already reading because
    the engine has halted. The halt then reports both facts — *a position of unknown size exists*
    and *its durable record could not be written*.
    """
    from app.db import session as dbsession

    monkeypatch.setattr(dbsession, "async_session_maker", _Boom())

    loop = _loop_at_halt()
    await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())

    status = await loop.status()
    assert "halt_record_failed" in status, "status() cannot report this at all — B394"
    assert status["halt_record_failed"], (
        "the write failed and status() says nothing, so the only trace is a log line that "
        "rotates — which is the insufficiency the Alert row exists to fix"
    )
    assert "reconcile" in status["halt_record_failed"].lower(), (
        "the operator is told the record is missing and not what to do about it"
    )


async def test_status_reports_NOTHING_when_the_writes_SUCCEED(monkeypatch):
    """The negative control, and without it the arm above is satisfied by a field that is always
    populated. A key that always says "failed" cannot report health."""
    loop = _loop_at_halt()
    # BEFORE the write: the alarming state, not silence. This is the assertion that used to say
    # `is None` — and changing it is the proof, because the old form passed against a halt that
    # had written nothing at all.
    assert NOT_YET_WRITTEN in (await loop.status())["halt_record_failed"], (
        "a declared halt with no record yet reports healthy — `None` cannot mean both 'written' "
        "and 'never attempted'"
    )

    # A session maker that works, so both writes complete.
    import contextlib

    from app.db import session as dbsession

    written = []

    class _OkSession:
        def add(self, obj):
            written.append(type(obj).__name__)

        async def commit(self):
            return None

    @contextlib.asynccontextmanager
    async def _ok():
        yield _OkSession()

    monkeypatch.setattr(dbsession, "async_session_maker", _ok)
    await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())

    assert (await loop.status())["halt_record_failed"] is None, (
        "both writes succeeded and status() is reporting a failure"
    )
    assert {"DecisionRecord", "Alert"} <= set(written), (
        f"the halt wrote {written} — it must leave BOTH the corpus row and the operator alert"
    )


# =====================================================================================
# M-7 — THE ALERT IS A RECORD *OF* THE HALT, NEVER THE HALT ITSELF
# =====================================================================================

async def test_the_HALT_SURVIVES_the_record_failing(monkeypatch):
    """**`M-7`.** If the halt depended on its own bookkeeping, a database outage would leave the
    engine trading around a position of unknown size — the exact condition the halt exists to
    prevent, reachable by the failure most likely to accompany it."""
    from app.db import session as dbsession

    monkeypatch.setattr(dbsession, "async_session_maker", _Boom())

    loop = _loop_at_halt()

    async def _no_position(pair):
        return False

    async def _none_open():
        return 0

    loop._has_position, loop._open_count = _no_position, _none_open

    await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())

    assert loop.halt_reason == HALT_PARTIAL_UNSIZED, "the halt was cleared by its record failing"
    block = await loop._entry_block_reason("BTC/USD")
    assert block is not None and HALT_PARTIAL_UNSIZED in block, (
        "the engine resumed taking entries because a database write failed"
    )
    assert (await loop.status())["halt_reason"] == HALT_PARTIAL_UNSIZED


async def test_ONE_write_failing_does_not_suppress_the_OTHER(monkeypatch):
    """Both records are written, so a failure in the first must not skip the second — they answer
    different questions and the operator-facing one is the more urgent."""
    import contextlib

    from app.db import session as dbsession

    seen = []

    class _Session:
        def add(self, obj):
            seen.append(type(obj).__name__)
            if type(obj).__name__ == "DecisionRecord":
                raise RuntimeError("corpus write fails, alert must still be attempted")

        async def commit(self):
            return None

    @contextlib.asynccontextmanager
    async def _maker():
        yield _Session()

    monkeypatch.setattr(dbsession, "async_session_maker", _maker)

    loop = _loop_at_halt()
    await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())

    assert "Alert" in seen, f"the alert was skipped because the corpus write failed: {seen}"
    assert (await loop.status())["halt_record_failed"], "the corpus failure is not reported"


# =====================================================================================
# THE DEFAULT IS THE ALARMING STATE — three distinct states, and `None` asserts a fact
# =====================================================================================

async def test_a_halt_whose_writer_NEVER_RAN_does_not_report_healthy(monkeypatch):
    """**The third time in this task that the defect class turned up inside its own fix.**

    ```
    M-6   the remedy for "a failure vanished into a log"   nearly became   log-and-continue
    M-9   the remedy for "justified one step short"        was justified   one step short
    here  the remedy for "the failure must not vanish"     defaulted to    "nothing failed"
    ```

    `_record_unsized_fill` guards `Exception`; `CancelledError` is a `BaseException`, so a shutdown
    between declaring the halt and writing its record skips the writer entirely. A `status()` call
    racing the write sees the same window, and any future halt site that forgets to call the writer
    inherits "healthy" for free.
    """
    loop = _loop_at_halt()          # halted, writer has NOT run

    status = await loop.status()
    assert status["halt_reason"] == HALT_PARTIAL_UNSIZED
    assert status["halt_record_failed"], (
        "the engine is halted and nothing has been written, and status() says all is well"
    )
    assert NOT_YET_WRITTEN in status["halt_record_failed"]


async def test_CancelledError_leaves_the_alarm_STANDING(monkeypatch):
    """The reachable route, driven rather than argued. `except Exception` does not catch it, so the
    writer aborts — and the alarm must survive that, which it does only because it was set with the
    halt rather than by the writer."""
    import contextlib

    from app.db import session as dbsession

    @contextlib.asynccontextmanager
    async def _cancelled():
        raise __import__("asyncio").CancelledError()
        yield  # pragma: no cover

    loop = _loop_at_halt()

    # Scoped to the WRITER only: `status()` reads the database too, so leaving this patched would
    # cancel the very call the assertion depends on — the arm would then fail for its own reason.
    original = dbsession.async_session_maker
    dbsession.async_session_maker = _cancelled
    try:
        with pytest.raises(BaseException):   # noqa: B017 — CancelledError is the point
            await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())
    finally:
        dbsession.async_session_maker = original

    status = await loop.status()
    assert status["halt_reason"] == HALT_PARTIAL_UNSIZED, "the halt was lost"
    assert status["halt_record_failed"], (
        "a CancelledError skipped the writer and status() reports the record as fine"
    )


async def test_the_three_states_are_DISTINCT(monkeypatch):
    """`None` must assert a positive fact — both rows on disk — or it cannot report health."""
    import contextlib

    from app.db import session as dbsession

    # 1. not yet written
    loop = _loop_at_halt()
    not_yet = (await loop.status())["halt_record_failed"]

    # 2. attempted and failed
    monkeypatch.setattr(dbsession, "async_session_maker", _Boom())
    await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())
    failed = (await loop.status())["halt_record_failed"]

    # 3. attempted and written
    class _Ok:
        def add(self, obj):
            return None

        async def commit(self):
            return None

    @contextlib.asynccontextmanager
    async def _ok():
        yield _Ok()

    monkeypatch.setattr(dbsession, "async_session_maker", _ok)
    await loop._record_unsized_fill("BTC/USD", _bars(), _Sig(), _res())
    written = (await loop.status())["halt_record_failed"]

    assert not_yet and failed and written is None, (
        f"not-yet={not_yet!r} failed={failed!r} written={written!r}"
    )
    assert not_yet != failed, "'never attempted' and 'attempted and failed' read the same"
    assert "reconcile" in failed.lower() and NOT_YET_WRITTEN in not_yet


async def test_the_HALT_SITE_sets_the_alarm_even_if_the_WRITER_never_runs(monkeypatch):
    """**THE ARM THAT MAKES THE OTHERS MEAN ANYTHING, and the harness is what demanded it.**

    Removing the alarm-set from the halt site killed NOTHING in the first control run. Every arm
    above used `_loop_at_halt()`, which hand-set `halt_record_failed` — **so the fixture was doing
    the work the production code is supposed to do**, and the arms asserted only that `status()`
    reports a field somebody had already set. That fixture now calls `_declare_halt`, so it can no
    longer stand in for the code; this arm stays regardless, because it is the only one that drives
    the halt through `_tick_symbol` rather than calling the declaration point directly.

    This one drives the REAL halt path through `_tick_symbol` and then prevents the writer from
    running at all — which is the `CancelledError` case, the concurrent-`status()` case, and the
    forgot-to-call-it case, all of which leave exactly this state.
    """
    from app.db.enums import DirectionType
    from app.services.live import crypto_loop as mod

    import pandas as pd

    loop = LiveCryptoLoop()
    acts: list[tuple[str, str]] = []

    class _S:
        symbol, direction = "BTC/USD", DirectionType.LONG
        entry, sl, tp = 100.0, 99.0, None
        risk_pct, approved, client_order_id = 0.01, True, "sig-x"
        partial_price = partial_fraction = None

    class _T:
        reasons = ["t0143"]

        def __getattr__(self, _):
            return None

    base = [100.0 + i for i in range(60)]
    bars = pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                         "low": [b - 1 for b in base], "close": base, "volume": [10.0] * 60})

    async def _noop(*a, **k):
        return None

    async def _fetch(*a, **k):
        return bars

    async def _exec(sig):
        # a partial the engine cannot size — the halt condition
        return {"status": "PARTIALLY_FILLED", "filled_units": None, "units": 0.01,
                "sized_units": 0.01, "position_id": "venue-pos-9"}

    async def _act(kind, msg):
        acts.append((kind, msg))

    async def _writer_never_runs(*a, **k):
        """Stands in for CancelledError, a racing status() call, or a halt site that forgets."""
        return None

    monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (_S(), _T()))
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_act", _act)
    monkeypatch.setattr(loop, "_shadow_evaluate", _noop)
    monkeypatch.setattr(loop, "_maybe_emit_census", _noop)
    monkeypatch.setattr(loop, "_news_context", _noop)
    monkeypatch.setattr(loop, "_has_position", lambda *a, **k: _false())
    monkeypatch.setattr(loop, "_open_count", lambda *a, **k: _zero())
    monkeypatch.setattr(loop, "_record_unsized_fill", _writer_never_runs)
    monkeypatch.setattr(loop.execution, "execute", _exec)
    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: 100.0)   # B432: the tick's ticker fetch, which this arm used to take from the live network

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert loop.halt_reason == HALT_PARTIAL_UNSIZED, f"the halt did not happen: {acts}"
    assert loop.halt_record_failed, (
        "the halt site did not raise the alarm, so a halt whose writer never runs — cancelled, "
        "raced, or simply not called — reports a healthy record"
    )
    assert NOT_YET_WRITTEN in loop.halt_record_failed


async def _false():
    return False


async def _zero():
    return 0
