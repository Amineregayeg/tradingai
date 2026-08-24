"""T-0072 — `ok` means NOTHING IS BROKEN. Malek's ruling, as an ALLOW-LIST.

`data_health()` derived `problems` from `status != "healthy"`, which made a deliberately
STOPPED engine a problem. Malek ruled that `ok` means nothing is broken, so `idle` joins
`healthy` — and everything else, including `unavailable`, does not.

**AN ALLOW-LIST, AND NEVER A DENY-LIST.** `status not in ("withdrawn",)` reads the same on
today's seven statuses and folds `unavailable` into `ok` — *a component we cannot SEE reading
as one that is fine*, which is `B215`'s shape at the level of the flag itself. An allow-list
fails CLOSED: a status nobody has thought about yet becomes a problem, loudly.

**AND EMITTING IS NOT WORKING.** An arm asserting the predicate produces the right shape is
not an arm asserting it DISCRIMINATES, so one arm below drives a component from passing to
problematic and back through the real `data_health()` and requires `ok` to move both ways.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from app.services.monitoring import data_health as dh

#: The seven statuses the backend can emit, DERIVED — the scanner lives in T-0065's file and
#: is imported rather than re-implemented, because two derivations of one set is `GATE-011`.
_T0065 = importlib.util.spec_from_file_location(
    "_t0065", pathlib.Path(__file__).with_name("test_t0065_health_panel_contract.py")
)
_t0065_mod = importlib.util.module_from_spec(_T0065)
_T0065.loader.exec_module(_t0065_mod)

#: **NAMED, NOT COUNTED (requirement 3).** A count of seven passes over a set that silently
#: swapped a member; naming them is the only form that fails for the right reason.
EXPECTED_STATUSES = (
    "healthy", "idle", "withdrawn", "unavailable", "down", "stale", "failing",
)
#: The five that must make `ok` False — derived from the NAMED seven minus the two Malek
#: ruled in, **as literals, not from `dh.OK_STATUSES`.**
#:
#: **The first version subtracted `dh.OK_STATUSES` and that made the arm unfalsifiable in the
#: exact direction it guards.** Admitting `unavailable` to the allow-list removed it from this
#: tuple, so its parametrisation VANISHED instead of failing — the mutation showed 1 failed
#: where it should show 2, and the one that survived was a different arm. *A guard whose
#: subjects are derived from the thing it is checking agrees with it by construction*, which
#: is `B250` one level up: not an under-reporting scanner, an under-reporting FIXTURE.
PROBLEM_STATUSES = tuple(s for s in EXPECTED_STATUSES if s not in ("healthy", "idle"))


@pytest.mark.parametrize("status", EXPECTED_STATUSES)
def test_each_of_the_seven_statuses_is_emitted_BY_NAME(status):
    """**Requirement 3.** Membership per member, not `len(...) == 7`.

    `failing` is the reason this is parametrised rather than counted: the scanner that fed the
    T-0065 arm missed it, because `status = "failing"` is a bare assignment to a variable that
    a returned dict then uses. Six looked as reasonable as seven.
    """
    derived = _t0065_mod._emitted_statuses()
    assert status in derived, (
        f"the backend no longer emits {status!r} — derived set is {sorted(derived)}. If it was "
        "removed deliberately, this arm is where that gets noticed; if the SCANNER stopped "
        "seeing it, the allow-list is now built on a narrower set than the truth (B250)."
    )


def test_the_derived_set_contains_NOTHING_the_arms_do_not_name():
    """The other direction: a new status must not slip in unnamed, because it would land on
    the problem side by construction and nobody would have decided that."""
    derived = _t0065_mod._emitted_statuses()
    unnamed = derived - set(EXPECTED_STATUSES)
    assert not unnamed, (
        f"the backend emits {sorted(unnamed)}, which no arm names. The allow-list makes it a "
        "PROBLEM by default — which is the safe direction and still a decision somebody "
        "should have taken deliberately."
    )


# ======================================================================================
# THE ALLOW-LIST ITSELF (requirement 4)
# ======================================================================================


def test_healthy_and_idle_are_the_WHOLE_of_the_allow_list():
    assert dh.OK_STATUSES == ("healthy", "idle"), (
        f"OK_STATUSES is {dh.OK_STATUSES}. Anything else here changes what Malek ruled."
    )


@pytest.mark.parametrize("status", PROBLEM_STATUSES)
def test_every_status_outside_the_allow_list_is_a_PROBLEM(status):
    """Delete any one of the five from the problem side — i.e. add it to `OK_STATUSES` — and
    this goes red for that member."""
    assert status not in dh.OK_STATUSES, (
        f"{status!r} has been admitted to the allow-list. `unavailable` means we cannot SEE a "
        "component; `failing` means one is actively failing; `withdrawn` means the platform "
        "is running and unable to trade. None of those is 'nothing is broken'."
    )


def test_the_predicate_is_an_ALLOW_LIST_in_the_source_not_a_deny_list():
    """A deny-list on `withdrawn` reads identically today and rebuilds `B215`."""
    import inspect

    src = inspect.getsource(dh.data_health)
    assert 'c.get("status") not in OK_STATUSES' in src
    assert '!= "healthy"' not in src, "the old single-status predicate is still there"
    assert '"withdrawn"' not in src, (
        "data_health must not name a status to EXCLUDE — that is a deny-list, and it folds "
        "every status nobody thought of into ok"
    )


# ======================================================================================
# THE MOVING ARM — emitting is not working
# ======================================================================================


@pytest.fixture
def all_healthy(monkeypatch, tmp_path):
    """Every component pinned healthy, so one component's status is the only variable."""
    async def _healthy(*a, **k):
        return {"status": "healthy", "watching": True, "summary": "pinned by the fixture"}

    for name in ("shadow_health", "panel_health", "order_path_health"):
        monkeypatch.setattr(dh, name, _healthy)
    monkeypatch.setattr(dh, "dominance_health", lambda: {"status": "healthy", "summary": "x"})
    monkeypatch.setattr(dh, "backup_health", lambda: {"status": "healthy", "summary": "x"})
    return monkeypatch


@pytest.mark.asyncio
@pytest.mark.parametrize("status", PROBLEM_STATUSES)
async def test_the_flag_MOVES_when_one_component_changes_status(all_healthy, status):
    """**The arm that shows the predicate DISCRIMINATES rather than merely exists.**

    An arm asserting the allow-list emits the right shape is not an arm asserting it moves.
    Drive one component from `healthy` to each problem status and back, through the real
    `data_health()`, and require `ok` to flip both ways.
    """
    baseline = await dh.data_health()
    assert baseline["ok"] is True and baseline["problems"] == [], baseline

    async def _sick(*a, **k):
        return {"status": status, "watching": True, "summary": f"forced {status}"}

    all_healthy.setattr(dh, "order_path_health", _sick)
    broken = await dh.data_health()
    assert broken["ok"] is False, f"{status!r} did not make ok False: {broken['problems']}"
    assert broken["problems"] == ["order_path"], broken["problems"]

    async def _well(*a, **k):
        return {"status": "healthy", "watching": True, "summary": "recovered"}

    all_healthy.setattr(dh, "order_path_health", _well)
    recovered = await dh.data_health()
    assert recovered["ok"] is True, "ok did not come back — the predicate latches"
    assert recovered["problems"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", dh.OK_STATUSES)
async def test_an_allow_listed_status_does_NOT_move_the_flag(all_healthy, status):
    """`idle` is the whole point of the ruling: a deliberately stopped engine is not broken.

    *And it is NOT green either* — the panel colours `idle` differently from `healthy`
    (`T-0065`), so the distinction survives at the place a reader sees it. The flag says
    "nothing is broken"; the component says "nothing is due".
    """
    async def _quiet(*a, **k):
        return {"status": status, "watching": status == "healthy", "summary": status}

    all_healthy.setattr(dh, "order_path_health", _quiet)
    result = await dh.data_health()
    assert result["ok"] is True, f"{status!r} is allow-listed and still made ok False"
    assert "order_path" not in result["problems"]
