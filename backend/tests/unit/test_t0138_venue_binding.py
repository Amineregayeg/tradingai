"""T-0138 — one venue selection, one binder, and the two paths must produce EQUIVALENT brokers.

**`M-1` AND `M-2` ARE DISSOLVED BY CONSTRUCTION, AND THAT IS REPORTED RATHER THAN COUNTED AS A
KILL.** Those rows mutate *"fix the initialiser only"* and *"fix the reconfigure path only"* — they
require the fix to exist at two sites. Collapsing both into `_bind_broker()` removes the class
instead of patching it, so there is no longer a site to mutate independently. **A row that cannot
be mutated because its target no longer exists is *dissolved*, not *killed*.**

**THE HAZARD MOVES RATHER THAN DISAPPEARING.** When two near-identical blocks are collapsed, the
DIFFERENCES between them are what gets silently dropped — and near-identical is exactly the case
nobody checks, because the blocks look the same at a glance. Diffing the two originals at `a212f5d`
found one that matters:

```
initialiser   self.mode = "PROP_FIRM_SIM" / "PAPER"     SET
reconfigure   -- absent --                              NEVER SET
```

**`self.mode` is a key in `_config_snapshot()` and `RunHistoryPanel` renders it.** So a reset that
changed `broker_mode` left the run's config naming the PREVIOUS broker — `B393`'s defect on a
different key, present long before `T-0138` armed `B393` itself. Driven at `a212f5d`: reset from
`sim` to `paper` left `mode='PROP_FIRM_SIM'` against a `PaperBroker`.

So the arms below are EQUIVALENCE arms, not site arms: drive both paths and assert the brokers agree
in every property that must follow the rebuild — policy, settle callback, price source, and mode.
**A closure's captured scope will not show up in a diff at all**, which is why the price source is
resolved rather than compared.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.broker.alpaca import ALPACA_CRYPTO_LONG_ONLY
from app.services.broker.cft_sim import SimPropFirmBroker
from app.services.broker.live_loop_proxy import LiveLoopBrokerProxy
from app.services.broker.paper import PaperBroker
from app.services.live.crypto_loop import LiveCryptoLoop

pytestmark = pytest.mark.asyncio


def _fingerprint(loop: LiveCryptoLoop) -> dict:
    """Everything that must follow the rebuild. **Not the object — what the object must carry.**

    ⚠ **`settle_wired` USED `is` AND WAS FALSE ON BOTH SIDES, AND THE EQUIVALENCE ARM PASSED
    ANYWAY.** `loop._on_settle_cb` is a BOUND METHOD, so every attribute access mints a new object
    and `is` is never true. Two identically-wrong values compare equal — which is the mirror of the
    differential trap: an `A != B` arm passes on incidental difference, an `A == B` arm passes on
    identical brokenness. **Equality is not evidence unless the values are also CHECKED.**

    So the arm below asserts the fingerprint's CONTENT as well as its agreement, and this uses
    `==` (bound methods compare equal when the function and the instance match).
    """
    return {
        "type": type(loop.paper).__name__,
        "policy": loop.paper.direction_policy,
        "settle_wired": loop.paper._on_settle == loop._on_settle_cb,
        "execution_holds_it": loop.execution.broker is loop.paper,
        "mode": loop.mode,
        "venue": loop._select_venue(),
    }


# =====================================================================================
# THE EQUIVALENCE — what replaces M-1 and M-2
# =====================================================================================

async def test_the_initialiser_and_the_reconfigure_path_produce_EQUIVALENT_brokers():
    """**Both paths, one binder, and the fingerprint must agree.**

    Under the old two-block arrangement this was not merely unverified — it was FALSE, because the
    reconfigure path never set `self.mode`.
    """
    loop = LiveCryptoLoop()
    from_initialiser = _fingerprint(loop)

    before = id(loop.paper)
    await loop._reset_broker_state()
    from_reconfigure = _fingerprint(loop)

    assert id(loop.paper) != before, "the broker was not rebuilt; the arm proves nothing"
    assert from_initialiser == from_reconfigure

    # AND THE VALUES MUST BE RIGHT, NOT MERELY EQUAL. Two identically-wrong fingerprints agree,
    # which is how the first version of this arm passed with `settle_wired` False on both sides.
    assert from_reconfigure["settle_wired"] is True
    assert from_reconfigure["execution_holds_it"] is True
    assert from_reconfigure["policy"] is not None
    assert from_reconfigure["mode"] == "PROP_FIRM_SIM"


async def test_the_settle_callback_is_wired_on_BOTH_paths():
    """**Called out separately because nothing else would notice.** `_on_settle` fires on every
    close — SL/TP tick, manual DELETE, kill switch — and a broker rebuilt without it loses every
    close from the DB and leaves DecisionRecords stuck OPEN.

    `B215`'s neighbourhood: **it only settles on an open position**, so a run with no fills looks
    identical either way and the suite stays green.
    """
    loop = LiveCryptoLoop()
    assert loop.paper._on_settle == loop._on_settle_cb

    await loop._reset_broker_state()
    assert loop.paper._on_settle == loop._on_settle_cb, (
        "the rebuilt broker has no settle hook — every close would be lost silently"
    )


async def test_the_price_source_RESOLVES_on_both_paths_rather_than_merely_existing():
    """**A closure's captured scope does not appear in a diff**, so comparing the two blocks as
    text could never have caught a price source closing over the wrong thing. This drives it."""
    loop = LiveCryptoLoop()
    loop._marks["BTC/USD"] = 70_000.0

    assert await loop.paper.reference_price("BTC/USD") == 70_000.0

    await loop._reset_broker_state()
    loop._marks["BTC/USD"] = 71_000.0
    assert await loop.paper.reference_price("BTC/USD") == 71_000.0, (
        "the rebuilt broker's price source is closed over a stale scope"
    )


async def test_the_mode_TRACKS_THE_REBUILT_BROKER():
    """**The silent difference the collapse fixed.** `self.mode` is a `_config_snapshot()` key and
    `RunHistoryPanel.settingsLine` renders it, so a stale value is a run labelled with the broker
    it stopped using."""
    loop = LiveCryptoLoop()
    assert loop.mode == "PROP_FIRM_SIM" and isinstance(loop.paper, SimPropFirmBroker)

    loop.broker_mode = "paper"
    await loop._reset_broker_state()

    assert isinstance(loop.paper, PaperBroker) and not isinstance(loop.paper, SimPropFirmBroker)
    assert loop.mode == "PAPER", "the mode still names the broker the run stopped using"
    assert loop._config_snapshot()["mode"] == "PAPER"


# =====================================================================================
# M-3 — ONE FACT, ONE PLACE
# =====================================================================================

async def test_the_venue_selection_is_CONSISTENT_wherever_it_is_asked():
    """`broker_mode` was read at three sites and the switch gained a third option. A per-site
    literal is `B184` — one fact in four places — and it fails by selecting the SIMULATOR
    somewhere nobody looks, which is the quiet direction."""
    loop = LiveCryptoLoop()
    for mode, expected in [("sim", "sim"), ("paper", "paper"), ("alpaca", "alpaca"),
                           ("alpaca_paper", "alpaca"), ("ALPACA", "alpaca"), ("", "paper")]:
        loop.broker_mode = mode
        assert loop._select_venue() == expected, f"{mode!r} selected the wrong venue"


async def test_the_warm_start_REFUSES_a_real_venue_and_not_only_the_prop_firm_sim():
    """**The third read, and it is NOT the same question as the other two.**

    It used to be `broker_mode == "sim"` — equivalent only while `sim` and `paper` were the whole
    vocabulary. The real predicate is *can fabricated history be seeded into this broker at all*,
    and for a REAL venue the answer is no, for a different reason. Leaving this read spelled the
    old way would have **posted backtest trades at a live venue.**
    """
    loop = LiveCryptoLoop()
    loop.broker_mode = "alpaca"
    acts: list = []
    loop._act = lambda kind, msg: acts.append(msg) or asyncio.sleep(0)  # type: ignore[assignment]

    await loop.warmup(days=1)

    assert acts, "the warm start did not refuse at all"
    assert "skipped" in acts[0].lower()
    assert "alpaca" in acts[0].lower(), "the refusal must name WHICH venue it declined to seed"


# =====================================================================================
# THE ATTRIBUTE NAME — a rename would orphan the kill switch in silence
# =====================================================================================

async def test_the_broker_is_bound_to_the_attribute_the_PROXY_reads():
    """**`B221`'s mechanism returning by a new route.** `LiveLoopBrokerProxy._resolve()` does
    `getattr(self._loop, "paper", None)` at call time and `main.py:242` registers that proxy as the
    manager's `paper` adapter. Renaming this attribute during a tidy-up would orphan the kill
    switch, the aggregate position view and close-routing — **and `B221` is the finding where the
    switch reported a clean trigger and closed nothing.**
    """
    loop = LiveCryptoLoop()
    proxy = LiveLoopBrokerProxy(loop)

    assert proxy._resolve() is loop.paper
    await loop._reset_broker_state()
    assert proxy._resolve() is loop.paper, "the proxy no longer follows the rebind"
    assert proxy.unavailable_reason is None


async def test_the_proxy_forwards_order_path_status():
    """The class docstring promises it forwards EVERY member, and it did not forward this one —
    `B238`, and mine, from an hour after I added the member."""
    loop = LiveCryptoLoop()
    proxy = LiveLoopBrokerProxy(loop)
    assert proxy.order_path_status() == loop.paper.order_path_status()

    class Blocked(PaperBroker):
        def order_path_status(self) -> str | None:
            return "part D"

    loop.paper = Blocked(starting_balance=1000.0)
    assert proxy.order_path_status() == "part D", (
        "the manager's `paper` adapter answers permissively while the real broker refuses"
    )

    assert LiveLoopBrokerProxy(object()).order_path_status() is None, (
        "an unbound proxy must not block callers on a venue it cannot even name"
    )


# =====================================================================================
# THE VENUE ITSELF — Alpaca is selectable, and refuses honestly rather than falling back
# =====================================================================================

async def test_selecting_alpaca_WITHOUT_CREDENTIALS_refuses_rather_than_falling_back(monkeypatch):
    """**A silent downgrade is the defect, not the refusal.** Falling back to a simulator would run
    the engine on a different venue than the operator selected and record a config saying so —
    which is the class `B393` was filed for, produced deliberately."""
    from app.core.exceptions import BrokerError

    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    loop = LiveCryptoLoop()
    loop.broker_mode = "alpaca"
    with pytest.raises(BrokerError) as exc:
        loop._build_broker(5_000.0)

    assert "ALPACA_API_KEY" in str(exc.value)
    assert "fall back" in str(exc.value).lower()


async def test_selecting_alpaca_WITH_credentials_builds_the_adapter(monkeypatch):
    """The control — a refusal that never accepts anything is not a fix. The adapter checks its
    `paper` flag against the client's real endpoint (`B389`), so constructing it at all is also
    evidence the two agree."""
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")

    loop = LiveCryptoLoop()
    loop.broker_mode = "alpaca"
    broker = loop._build_broker(5_000.0)

    assert broker.broker_name == "alpaca"
    assert broker.is_simulation is True
    assert broker.simulation_source == "endpoint", (
        "a real client must be ASKED where it points, not taken at its flag"
    )
    assert broker.direction_policy is ALPACA_CRYPTO_LONG_ONLY
    assert loop.mode == "ALPACA_PAPER"


# =====================================================================================
# B395 — the run record says whether the safety flag was CHECKED or only BELIEVED
# =====================================================================================

async def test_the_base_RAISES_rather_than_answering_benignly():
    """**The amendment's whole point.** The first version read
    `getattr(broker, "simulation_source", "in-process ...")`, so every way of losing the value —
    a rename, a refactor, a wrapper that does not forward it — resolved to the most reassuring
    sentence in the vocabulary. **Absence rendered as health.**

    > When a fallback is one of the states a field exists to distinguish, the field cannot report
    > its own failure. If a default is unavoidable it must be the ALARMING state, never the benign
    > one.
    """
    from app.services.broker.base import BrokerAdapter

    class Forgetful(PaperBroker):
        pass

    Forgetful.simulation_source = BrokerAdapter.simulation_source  # undeclare it

    with pytest.raises(NotImplementedError) as exc:
        _ = Forgetful(starting_balance=1000.0).simulation_source
    assert "simulation_source" in str(exc.value)
    assert "gates every execution" in str(exc.value)


async def test_the_three_states_are_DISTINCT_and_only_one_is_a_warning():
    """A marker that fires on every run is the liveness-signal failure — routinely wrong,
    therefore ignored, therefore useless when it matters. The in-process case must NOT read as
    unverified."""
    from app.services.broker.alpaca import AlpacaAdapter

    in_process = PaperBroker(starting_balance=1000.0).simulation_source
    unreadable = AlpacaAdapter(object(), paper=True).simulation_source

    assert "in-process" in in_process
    assert "unreadable" in unreadable
    assert "unreadable" not in in_process, (
        "an in-process simulator would be marked unverified on every run"
    )


async def test_the_run_config_RECORDS_whether_the_flag_was_checked():
    """Until now this lived in the adapter's memory and died with the process: a run whose
    `is_simulation` was confirmed against the endpoint and a run where it was merely believed left
    identical records. Read with NO default — a missing value must raise, not reassure."""
    loop = LiveCryptoLoop()
    snap = loop._config_snapshot()

    assert snap["simulation_source"] == loop.paper.simulation_source
    assert "in-process" in snap["simulation_source"]

    class Unreadable(PaperBroker):
        @property
        def simulation_source(self) -> str:
            return "flag (client endpoint unreadable)"

    loop.paper = Unreadable(starting_balance=1000.0)
    assert "unreadable" in loop._config_snapshot()["simulation_source"]


async def test_the_unbound_proxy_answers_with_the_ALARM_not_the_all_clear():
    """**The opposite choice from `order_path_status`, deliberately.** There, refusing to answer
    blocks callers over a venue the proxy cannot name. Here, *not knowing whether the safety flag
    was ever checked* IS the alarming state."""
    src = LiveLoopBrokerProxy(object()).simulation_source
    assert "unreadable" in src
    assert "in-process" not in src


async def test_the_provenance_vocabulary_is_CLOSED():
    """**The UI matches these strings EXACTLY, so this is the arm that makes that safe.**

    `RunHistoryPanel.flagState` compares with `===` rather than `includes`, and it must: the
    unverified value **contains the substring `"endpoint"`**, so a positive match written
    `includes('endpoint')` would reclassify UNVERIFIED as VERIFIED — the defect in its worst form.

    Exact matching across a language boundary is brittle in one direction only, and this arm is
    what points the brittleness somewhere safe: **reword one of these and THIS goes red**, before
    the panel starts rendering `provenance UNRECOGNISED` at a user. The UI's fallthrough is the
    alarming state by design, so the failure mode without this arm is a false alarm rather than a
    false all-clear — but a false alarm that fires forever is the liveness-signal failure, which
    is the thing the three-state design exists to avoid.
    """
    from app.services.broker.alpaca import AlpacaAdapter
    from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker

    async def price(pair: str) -> float:
        return 70_000.0

    from alpaca.trading.client import TradingClient

    # The verified value comes from a REAL client being asked where it points.
    verified = AlpacaAdapter(TradingClient("k", "s", paper=True), paper=True).simulation_source
    unverified = AlpacaAdapter(object(), paper=True).simulation_source

    observed = {
        PaperBroker(starting_balance=1000.0).simulation_source,
        SimPropFirmBroker(PropFirmRules(starting_balance=1000.0), price).simulation_source,
        unverified,
        verified,
    }
    assert observed == {
        "endpoint",
        "in-process (no endpoint to check)",
        "flag (client endpoint unreadable)",
    }, f"the vocabulary changed: {sorted(observed)}"

    # ⚠ THIS WAS `assert "endpoint" in "flag (client endpoint unreadable)"` — TWO LITERALS I
    # TYPED, which is `assert True` with a paragraph attached. It went green and could never have
    # done otherwise. **The same shape I had caught in this very arm an hour earlier**, written
    # again four lines below the fix, because the sentence was about the code while the assertion
    # was about my transcription of it. Reading the values the code produced is what makes the
    # sentence true OF THE CODE rather than of this file.
    assert verified in unverified, (
        "the unverified value CONTAINS the verified one as a substring — that is why the UI must "
        "compare with `===` and not `includes()`. If this ever stops being true, that constraint "
        "relaxes and `RunHistoryPanel.flagState` can be simplified."
    )
