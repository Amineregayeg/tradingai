"""The proxy's docstring says it forwards EVERY member. This is the arm that means it.

**FORWARDING MEMBERS ONE AT A TIME HAS NOW HAPPENED TWICE.** `order_path_status` was the first —
added to `BrokerAdapter` and silently not forwarded, under a class docstring promising *"forwards
every member to `loop.paper` at call time"*. `simulation_source` was the second, and it was worse:
the missing forward resolved to a DEFAULT that was the most reassuring value in the vocabulary, so
the alarm became the all-clear.

**Both fixes forwarded THAT MEMBER, which is why the lesson did not generalise.** The third omission
is predictable and nobody will be watching for it.

`LiveLoopBrokerProxy` defines no `__getattr__`, so anything not explicitly listed is simply absent —
and absence on a proxy is invisible: the attribute resolves on the base class instead, answering with
a default that describes *no broker at all* while a broker is right there.

**`B267` is the precedent** — `pkgutil.iter_modules` does not recurse, so an adapter one directory
deep was invisible to the discovery walk while the suite stayed green. A contract asserted by a
docstring is a contract nothing checks.
"""
from __future__ import annotations

import inspect

import pytest

from app.services.broker.base import BrokerAdapter
from app.services.broker.live_loop_proxy import LiveLoopBrokerProxy

#: Members the proxy deliberately does NOT forward, each with the reason it is exempt.
#:
#: **An allow-list, not a filter.** A predicate ("skip private members", "skip properties") would
#: silently absorb the next omission — the failure this arm exists to catch. Adding a name here is
#: a decision someone has to write down.
DELIBERATELY_NOT_FORWARDED = {
    # Class-level vocabulary, not behaviour: the same constants whatever broker is held.
    "CLOSED": "ruled kill-switch disposition constant",
    "FAILED": "ruled kill-switch disposition constant",
    "NOT_ATTEMPTED": "ruled kill-switch disposition constant",
    "last_close_all_report": "written by whoever ran the switch; the proxy holds no report",
    "direction_policy": "read off the held broker directly by ExecutionService, not via the proxy",
}


def _public_members(cls) -> set[str]:
    return {
        name for name, _ in inspect.getmembers(cls)
        if not name.startswith("_")
    }


def test_the_proxy_forwards_every_member_it_claims_to():
    """**The whole point: this fails the day a member is ADDED, not the day a field reads wrong.**

    Two members have already slipped through — `order_path_status`, then `simulation_source`. The
    second one's absence resolved to the calmest string in its vocabulary, which is how a missing
    forward turns into a safety claim nobody made.
    """
    declared = _public_members(BrokerAdapter) - set(DELIBERATELY_NOT_FORWARDED)
    forwarded = set(vars(LiveLoopBrokerProxy))

    missing = sorted(declared - forwarded)
    assert not missing, (
        f"LiveLoopBrokerProxy does not forward {missing}. Its docstring promises every member at "
        f"call time, and it defines no __getattr__ — so each of these silently answers from "
        f"BrokerAdapter's default, describing NO broker while one is held. Forward it, or add it "
        f"to DELIBERATELY_NOT_FORWARDED with the reason."
    )


def test_the_exemptions_still_EXIST_on_the_contract():
    """**The allow-list must not outlive what it exempts.** A name removed from `BrokerAdapter` but
    left here would quietly exempt nothing forever, and the next reader would trust a list that no
    longer describes the class — the same rot as a scope note whose reason has expired."""
    declared = _public_members(BrokerAdapter)
    stale = sorted(set(DELIBERATELY_NOT_FORWARDED) - declared)
    assert not stale, (
        f"{stale} are exempted from forwarding but no longer exist on BrokerAdapter"
    )


def test_the_arm_can_FAIL():
    """The control. An arm that enumerates nothing passes trivially, and this one's whole value is
    that it fires on a member added tomorrow."""
    declared = _public_members(BrokerAdapter) - set(DELIBERATELY_NOT_FORWARDED)
    assert len(declared) >= 10, (
        f"only {len(declared)} members enumerated; the contract has eleven-plus and this arm "
        f"would pass while checking almost nothing"
    )
    assert "place_order" in declared and "is_simulation" in declared
