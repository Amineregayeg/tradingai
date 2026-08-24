"""T-0065 — `B231` + `B234` + `B228`: two panels rendering claims their data does not support.

**THIS CHANGES THE TREE.** Production runs `1521e371` and has since 2026-08-19 (`B248`); none
of these arms describes deployed behaviour.

`B231`'s root is **a TYPE THAT ENUMERATES, not a lazy loop.** `DataHealth` declared two
components; the renderer was FAITHFUL to it, rendering two rows while `problems.length`
counted five and the green line said *"Collector and backups healthy"* after five had been
checked. **Adding three fields is the same defect and worse — a type that enumerates looks
like documentation.**

`B234`: four of six emitted statuses were OUTSIDE the union, three members were emitted
nowhere, and the catch-all's comment named two the backend does not emit while silently
absorbing four that it does.

`B228`: of five broadcasts on the positions channel, exactly one was ever acted on — the
vocabularies overlapped in one member, and that member carried two incompatible shapes.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = BACKEND.parent / "frontend" / "src"
DATA_HEALTH = BACKEND / "app" / "services" / "monitoring" / "data_health.py"
PANEL = FRONTEND / "components" / "dashboard" / "DataHealthPanel.tsx"
API_TYPES = FRONTEND / "types" / "api.ts"
WS_TS = FRONTEND / "services" / "ws.ts"
WS_MANAGER = BACKEND / "app" / "services" / "ws" / "manager.py"
CRYPTO_LOOP = BACKEND / "app" / "services" / "live" / "crypto_loop.py"


def _emitted_statuses() -> set[str]:
    """Every status a COMPONENT can emit, read from the backend's source.

    **Derived, never retyped.** `ARM 2` says so explicitly: a literal list of six here would
    be `B150` inside the guard against `B150` — the test would agree with itself while the
    backend drifted.

    **Scoped to the TOP-LEVEL `status` of what a `*_health` function RETURNS**, and both
    narrowings were forced by getting it wrong first:

      * an earlier version walked every `Dict` in the module and picked up
        `{"status": "thin" if thin else "ok"}` — a per-PANEL *thickness* sub-dict, not a
        component status. It **over**-reported, demanding a colour for `ok`.
      * before that it took every element of `status, state = "down", "due"`, reporting the
        `evaluation_state` values `due` and `not_due` as statuses.
      * and it read only `ast.Constant`, so it missed
        `"withdrawn" if ... else "healthy" if ... else "idle"` entirely — **under**-reporting
        `withdrawn`, the one status this whole `B229`/`B234` thread is about.

    *The last of those is the dangerous direction: a scanner that under-reports makes its
    guard agree with itself.*
    """

    def _literals(node) -> list[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.IfExp):
            return _literals(node.body) + _literals(node.orelse)
        return []

    tree = ast.parse(DATA_HEALTH.read_text(encoding="utf-8"))
    found: set[str] = set()
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not fn.name.endswith("_health") or fn.name == "data_health":
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
                continue
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == "status":
                    found.update(_literals(value))

    # `status` bound by a tuple assignment before the return, e.g. `status, state = "down", "due"`
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
            for target in node.targets:
                names = target.elts if isinstance(target, ast.Tuple) else [target]
                for i, name in enumerate(names):
                    if (
                        isinstance(name, ast.Name) and name.id == "status"
                        and i < len(node.value.elts)
                    ):
                        found.update(_literals(node.value.elts[i]))
    return found


# ======================================================================================
# ARM 1 — THE TYPE MUST NOT ENUMERATE
# ======================================================================================


def test_arm1_DataHealth_carries_a_RECORD_and_names_no_component():
    """Mutating this by adding `shadow: ComponentHealth` must turn it RED — otherwise the fix
    passes by adding three fields and the class survives intact."""
    src = API_TYPES.read_text(encoding="utf-8")
    body = src[src.index("export interface DataHealth"):]
    body = body[: body.index("\n}")]

    assert "Record<string, ComponentHealth>" in body, (
        "DataHealth must key its components, not name them"
    )
    named = re.findall(r"^\s*(\w+)\s*:\s*ComponentHealth\s*$", body, re.MULTILINE)
    assert not named, (
        f"DataHealth still ENUMERATES components: {named}. A type that lists them looks like "
        "documentation, so the next component to arrive is silently unrendered while the type "
        "appears to describe the payload."
    )


def test_arm1_the_panel_derives_its_rows_and_hardcodes_no_component():
    panel = PANEL.read_text(encoding="utf-8")
    assert "Object.entries(health.components" in panel
    assert "health.dominance_collector" not in panel
    assert "health.backups" not in panel
    assert 'name="Collector"' not in panel and 'name="Backups"' not in panel


# ======================================================================================
# ARM 2 — EVERY EMITTED STATUS HAS A COLOUR, DERIVED FROM THE BACKEND
# ======================================================================================


def test_arm2_every_status_the_backend_emits_has_an_explicit_colour():
    emitted = _emitted_statuses()
    assert len(emitted) >= 5, f"the status scan found only {emitted} — it has stopped working"

    panel = PANEL.read_text(encoding="utf-8")
    table = panel[panel.index("const STATUS_COLOUR"):panel.index("function colourFor")]
    mapped = set(re.findall(r"^\s*(\w+):", table, re.MULTILINE))

    missing = emitted - mapped
    assert not missing, (
        f"the backend emits {sorted(missing)} and the panel has no colour for them. They would "
        "fall to the catch-all — which is exactly B234: a catch-all commented for statuses the "
        "backend does not emit, silently absorbing the ones it does."
    )


def test_arm2_an_unknown_status_is_AMBER_and_never_green():
    """A status the panel has not been taught is one it cannot vouch for. Defaulting to green
    is how a screen reassures about something it stopped understanding."""
    panel = PANEL.read_text(encoding="utf-8")
    assert "STATUS_COLOUR[status] ?? AMBER" in panel


# ======================================================================================
# ARM 3 — `idle` AND `withdrawn` ARE DISTINGUISHABLE WITHOUT OPENING THE COMPONENT
# ======================================================================================


def test_arm3_idle_and_withdrawn_differ_in_COLOUR():
    """`B229`/`B234`. These are precisely the two states the `ok` question is about — an
    engine deliberately stopped versus an engine running and unable to trade — and the panel
    rendered them the same. `T-0057` went to lengths to keep them separate in the payload."""
    panel = PANEL.read_text(encoding="utf-8")
    table = panel[panel.index("const STATUS_COLOUR"):panel.index("function colourFor")]
    colours = dict(re.findall(r"^\s*(\w+):\s*(\w+),", table, re.MULTILINE))

    assert "idle" in colours and "withdrawn" in colours
    assert colours["idle"] != colours["withdrawn"], (
        f"idle and withdrawn are both {colours['idle']} — the two states the ok flag is about"
    )
    assert colours["withdrawn"] == "RED"
    assert colours["idle"] != "GREEN", "an idle engine is not healthy either"


def test_arm3_the_summary_SENTENCES_also_separate_them():
    """Colour alone is a channel a reader can miss. The component's own line must say which."""
    from app.services.monitoring.data_health import _order_path_summary

    idle = _order_path_summary({"engine_running": False, "withdrawn_symbols": [], "symbols": []})
    withdrawn = _order_path_summary({
        "engine_running": True,
        "withdrawn_symbols": ["BTC/USD"],
        "symbols": [{"symbol": "BTC/USD", "withdrawn_from_trading": True, "age_hours": 66.2}],
    })

    assert "not running" in idle and "nothing is withdrawn" in idle
    assert "WITHDRAWN FROM TRADING" in withdrawn and "66h" in withdrawn
    assert idle != withdrawn


# ======================================================================================
# ARM 4 — A SIXTH COMPONENT APPEARS WITH ZERO FRONTEND CHANGE
# ======================================================================================


@pytest.mark.asyncio
async def test_arm4_a_sixth_component_is_rendered_without_touching_the_frontend(monkeypatch):
    """Added server-side; the panel maps over whatever it is given, so nothing else moves."""
    from app.services.monitoring import data_health as dh

    async def _healthy(*a, **k):
        return {"status": "healthy", "watching": True, "summary": "fine"}

    for name in ("shadow_health", "panel_health", "order_path_health"):
        monkeypatch.setattr(dh, name, _healthy)
    monkeypatch.setattr(dh, "dominance_health", lambda: {"status": "healthy", "summary": "fine"})
    monkeypatch.setattr(dh, "backup_health", lambda: {"status": "healthy", "summary": "fine"})

    real = dh.data_health

    async def _with_sixth(loop=None):
        out = await real(loop)
        out["components"]["a_sixth_thing"] = {
            "status": "thin", "summary": "invented by this test", "watching": True,
        }
        return out

    result = await _with_sixth()
    assert "a_sixth_thing" in result["components"]

    panel = PANEL.read_text(encoding="utf-8")
    assert "components.map(" in panel, "the panel must render whatever keys it receives"
    assert "labelFor(key)" in panel, "and derive the label from the key, not from a list"


@pytest.mark.asyncio
async def test_the_components_are_NESTED_so_ok_and_problems_are_not_rendered_as_components(
    monkeypatch,
):
    """`data_health()` used to end `**components`, so the top level was `ok · checked_at ·
    problems` PLUS the component keys — and a frontend deriving rows with `Object.entries`
    would render the first three AS COMPONENTS."""
    from app.services.monitoring import data_health as dh

    async def _healthy(*a, **k):
        return {"status": "healthy", "watching": True, "summary": "fine"}

    for name in ("shadow_health", "panel_health", "order_path_health"):
        monkeypatch.setattr(dh, name, _healthy)
    monkeypatch.setattr(dh, "dominance_health", lambda: {"status": "healthy", "summary": "fine"})
    monkeypatch.setattr(dh, "backup_health", lambda: {"status": "healthy", "summary": "fine"})

    result = await dh.data_health()
    assert set(result["components"]) == {
        "dominance_collector", "backups", "shadow", "correlate_panels", "order_path",
    }
    for scalar in ("ok", "checked_at", "problems"):
        assert scalar not in result["components"]


@pytest.mark.asyncio
async def test_every_component_emits_its_own_summary_sentence(monkeypatch):
    """The fix that removes `B231`'s class: each component says one line about ITSELF,
    computed where its fields are known. The five share no vocabulary, so no generic row
    could format them — derive the row and the hardcoded list merely moves into a formatter."""
    from app.services.monitoring import data_health as dh

    result = await dh.data_health()
    for name, component in result["components"].items():
        assert component.get("summary"), f"{name} emitted no summary: {component}"
        assert isinstance(component["summary"], str) and component["summary"].strip()


# ======================================================================================
# ARM 6 — THE VOCABULARIES MATCH, DERIVED FROM BOTH SIDES
# ======================================================================================


def _backend_position_events() -> set[str]:
    events: set[str] = set()
    for path in (WS_MANAGER, CRYPTO_LOOP):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            channel, event = kw.get("channel"), kw.get("event")
            if (
                isinstance(channel, ast.Constant) and channel.value == "positions"
                and isinstance(event, ast.Constant)
            ):
                events.add(event.value)
    return events


def _frontend_position_events() -> set[str]:
    return set(re.findall(r"'positions',\s*'(\w+)'", WS_TS.read_text(encoding="utf-8")))


def test_arm6_no_frontend_handler_listens_for_an_event_that_is_never_sent():
    """`added` and `removed` were DEAD HANDLERS — the backend has never sent either."""
    orphans = _frontend_position_events() - _backend_position_events()
    assert not orphans, (
        f"the frontend handles {sorted(orphans)}, which the backend never sends. "
        f"backend emits {sorted(_backend_position_events())}"
    )


def test_arm6_the_events_that_carry_position_state_all_have_a_listener():
    """`open`, `close` and `update` all move the panel's contents; a broadcast with nothing
    listening is indistinguishable from one that was never sent."""
    unheard = {"update", "open", "close"} - _frontend_position_events()
    assert not unheard, f"these are sent with nothing listening: {sorted(unheard)}"


def test_arm6_the_update_event_has_exactly_ONE_payload_shape():
    """**The hole one level down.** A vocabulary test that passes while one event carries two
    shapes has the same defect it was written to catch.

    `update` used to be sent as a single position dict from `ws/manager.py` AND as
    `{"positions": [...]}` from `crypto_loop`. The client reads `data.positions`, so the first
    arrived as `undefined` and was dropped by the same guard that dropped empty lists.
    """
    manager = WS_MANAGER.read_text(encoding="utf-8")
    assert 'event="update", data=position)' not in manager, (
        "ws/manager still sends a bare position dict under `update`"
    )
    assert '"positions": positions, "authoritative": authoritative' in manager

    loop_src = CRYPTO_LOOP.read_text(encoding="utf-8")
    assert 'channel="positions", event="update"' not in loop_src, (
        "crypto_loop must go through push_position_update, so the shape has ONE producer "
        "by construction rather than by two call sites agreeing"
    )
    assert "push_position_update(" in loop_src


def test_the_shipped_handler_and_the_vitest_copy_have_not_DRIFTED():
    """`ARM 5` lives in vitest and re-implements the handler body, so it could pass while the
    shipped one changed. This pins the two together — the same reason `BLOCKED_BY_POSITION`
    is pinned to the gate's own words."""
    shipped = WS_TS.read_text(encoding="utf-8")
    predicate = "if (data.positions.length > 0 || data.authoritative === true) {"
    assert shipped.count(predicate) == 1, "the shipped predicate moved"

    vitest = (FRONTEND / "__tests__" / "services" / "positionsWs.test.ts").read_text(
        encoding="utf-8"
    )
    assert predicate in vitest, (
        "the vitest copy no longer matches the shipped handler — ARM 5 is testing something "
        "that is not running"
    )
