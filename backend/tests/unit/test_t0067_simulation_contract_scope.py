"""T-0067 — `B238`: the `is_simulation` contract named three enforcers and has one.

`base.py`'s contract said *"Safety-critical chokepoints (ExecutionService, the kill switch,
position-close routing) read this and refuse to send writes to a non-simulation broker."*
**Two of the three named do not read the flag at all.**

**The claim was load-bearing in the wrong direction.** A reader checking whether the close
path was guarded found a contract saying it was — which is worse than silence, because
silence sends you to the source.

**NOTHING IS ENFORCED HERE, AND THAT IS THE FINDING RATHER THAN A LIMITATION.** A kill switch
that REFUSES to close a real position is `B221` with a different report — *"reports refusal,
closes nothing"* against *"reports success, closes nothing"* — firing exactly when a real book
is the thing you most want flat. And it would be keyed on the wrong flag (`B241`):
`is_simulation` describes the VENUE, `observe_only` is the WRITE GATE, and they have come
apart.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
BASE = APP / "services" / "broker" / "base.py"

#: The one site that actually refuses on the flag. Named here so the arm below has something
#: to be wrong about — and DERIVED independently in `_modules_that_refuse`.
KNOWN_ENFORCER = "app/services/execution/service.py"

#: Named in the old contract and asserted NOT to enforce. If either of these ever starts
#: refusing, this arm goes red and the contract must be rewritten in the other direction.
DELIBERATELY_UNGUARDED = (
    APP / "services" / "broker" / "manager.py",
    APP / "api" / "routers" / "positions.py",
)


def _modules_that_refuse() -> set[str]:
    """Every module under `app/` that RAISES on `is_simulation`, by AST.

    **Derived, not retyped** — and derived on the RAISE rather than on the read, because
    reading the flag to report it (`manager.py:522`) or to skip reconciliation
    (`manager.py:484`) is not refusing a write, and a scan that counted reads would have
    reported the manager as an enforcer and agreed with the sentence being corrected.
    """
    refusers: set[str] = set()
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if "is_simulation" not in ast.unparse(node.test):
                continue
            if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
                refusers.add(str(path.relative_to(APP.parent)))
    return refusers


def test_exactly_one_site_refuses_on_the_flag():
    refusers = _modules_that_refuse()
    assert refusers == {KNOWN_ENFORCER}, (
        f"the set of sites that REFUSE on is_simulation is now {sorted(refusers)}. The "
        "contract in base.py names one; if a second appeared, the contract is stale in the "
        "other direction and must be rewritten rather than this arm relaxed."
    )


def test_the_contract_names_ONLY_what_enforces():
    """**The arm.** The sentence may name the enforcer; it may not claim the others enforce."""
    contract = _contract_text()

    assert "ExecutionService` refuses" in contract or "ExecutionService refuses" in contract
    assert "execution/service.py" in contract, "the enforcer must be locatable, not just named"
    assert "DO NOT\n    # CHECK THIS" in contract or "DO NOT CHECK THIS" in contract.replace(
        "\n    #", ""
    ), "the non-enforcement must be stated, not left to silence"


def test_the_contract_no_longer_claims_the_close_paths_refuse():
    """The exact false sentence, pinned so it cannot come back by a rewrite."""
    contract = _contract_text().replace("\n", " ")
    assert "chokepoints (ExecutionService, the kill switch, position-close routing) read" \
        not in contract
    assert not (
        "kill switch" in contract
        and "refuse to send writes" in contract.split("kill switch")[1][:200]
    ), "the kill switch must not be described as refusing anything"


def test_the_scope_note_carries_its_REASON():
    """**A scope without its reason is what rots into the next `B238`.**

    The next seat reads *"does not check"* as an oversight and closes it. It is not an
    oversight, and the sentence has to say why — otherwise the correction invites the defect.
    """
    contract = _contract_text()
    assert "closing is the safe direction" in contract
    assert "B221" in contract, "the reason must name what a refusal would rebuild"
    assert "B241" in contract and "observe_only" in contract, (
        "and that a refusal would be keyed on the VENUE flag rather than the WRITE gate"
    )


def test_the_deliberately_unguarded_paths_really_are_unguarded():
    """The claim is checked against the code, not merely written down.

    *If one of these ever starts refusing, the contract is wrong again — in the other
    direction — and this arm is what says so.*
    """
    for path in DELIBERATELY_UNGUARDED:
        assert path.exists(), path
        assert str(path.relative_to(APP.parent)) not in _modules_that_refuse(), (
            f"{path.name} now refuses on is_simulation; base.py says it does not"
        )


def test_a_NON_SIMULATION_adapter_is_registerable_and_this_is_not_hypothetical():
    """`B241`. `crypto_loop`'s *"both are is_simulation=True"* is true of the LOOP's brokers
    and says nothing about `_adapters`, which also holds every broker-connection adapter."""
    from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter
    from app.services.broker.paper import PaperBroker

    assert PaperBroker(starting_balance=1.0).is_simulation is True
    assert CryptoFundTraderAdapter.is_simulation.fget(  # type: ignore[union-attr]
        object.__new__(CryptoFundTraderAdapter)
    ) is False, "a registerable adapter reports is_simulation False"

    main_src = (APP / "main.py").read_text(encoding="utf-8")
    assert "broker_manager.load_from_db(db)" in main_src, (
        "the DB-backed adapters are loaded into _adapters at startup — which is what makes "
        "the non-simulation case present rather than merely possible"
    )


def _contract_text() -> str:
    src = BASE.read_text(encoding="utf-8")
    start = src.index("# Simulation contract (SAFETY)")
    return src[start : src.index("    @property", start)]
