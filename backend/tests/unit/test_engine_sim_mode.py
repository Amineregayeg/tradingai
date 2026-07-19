"""The live loop can run against the prop-firm simulator (mandate: Agent B tests
a strategy in prop-firm sim mode, not real money)."""
from __future__ import annotations

from app.services.broker.cft_sim import SimPropFirmBroker
from app.services.broker.paper import PaperBroker
from app.services.live.crypto_loop import LiveCryptoLoop


def test_paper_mode_is_default():
    loop = LiveCryptoLoop()
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
