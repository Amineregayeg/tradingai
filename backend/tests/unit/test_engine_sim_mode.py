"""The live loop can run against the prop-firm simulator (mandate: Agent B tests
a strategy in prop-firm sim mode, not real money)."""
from __future__ import annotations

from app.services.broker.cft_sim import SimPropFirmBroker
from app.services.broker.paper import PaperBroker
from app.services.live.crypto_loop import LiveCryptoLoop


def test_the_prop_firm_simulator_is_the_default():
    """Plain paper was the default for as long as the engine page could switch
    modes. With the settings frozen there is only one, and it is the one with
    rules: a simulation you cannot fail teaches nothing about a challenge you
    can."""
    loop = LiveCryptoLoop()
    assert isinstance(loop.paper, SimPropFirmBroker)
    assert loop.mode == "PROP_FIRM_SIM"
    assert loop.sim_state() is not None


def test_plain_paper_mode_still_works_when_asked_for():
    """The mode is not deleted, only unselected. Tests and any future comparison
    against a rule-free baseline still need it."""
    loop = LiveCryptoLoop(broker_mode="paper")
    assert isinstance(loop.paper, PaperBroker)
    assert loop.mode == "PAPER"
    assert loop.sim_state() is None


def test_sim_mode_uses_prop_firm_broker():
    loop = LiveCryptoLoop(broker_mode="sim")
    assert isinstance(loop.paper, SimPropFirmBroker)
    assert loop.paper.is_simulation is True
    assert loop.mode == "PROP_FIRM_SIM"
    st = loop.sim_state()
    assert st is not None
    for key in ("starting_balance", "balance", "halted", "status", "profit_target_pct"):
        assert key in st
    assert st["halted"] is False
    assert st["status"] == "active"


def test_sim_mode_execution_service_accepts_the_sim_broker():
    # ExecutionService hard-asserts is_simulation — construction must succeed.
    loop = LiveCryptoLoop(broker_mode="sim")
    assert loop.execution.broker is loop.paper
    assert loop.execution.broker.is_simulation is True
