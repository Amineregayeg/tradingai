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


def _loop_at_halt():
    loop = LiveCryptoLoop()
    loop.halt_reason = HALT_PARTIAL_UNSIZED       # the halt is ALREADY in force (M-7)
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
    assert (await loop.status())["halt_record_failed"] is None

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
