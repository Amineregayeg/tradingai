"""(2d) — the kill switch's in-progress 409 must redact EVERY string in its rows, at any depth (`B404`).

Review measured at `32a7610`: the route redacted a row's top-level strings only, so a token planted in
`close.resolution.read_errors` — venue exception text, three levels down — reached the response body. Rows are
built by adapters from venue answers, and the 409 is new exposure a deploy would introduce.

Through the ROUTE (review's D-5), with `kill_switch.trigger` stubbed to answer "already in progress" with the rows
under test: deterministic, no concurrency, and nothing here depends on a live sweep.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

T1, T2, T3, T4, T5 = (f"sk-ant-PLANTED2d{i}secret0123456789" for i in range(1, 6))


async def _answer_409(client: AsyncClient, monkeypatch, rows, message="Kill switch ALREADY IN PROGRESS: 2 row(s)"):
    import importlib

    # the package re-exports the INSTANCE under the module's name, so the module is imported by its dotted path
    ks_module = importlib.import_module("app.services.compliance.kill_switch")

    created = await client.post("/api/prop-firm/profiles", json={"firm_name": "FTMO", "rules_json": {}})
    assert created.status_code == 201, created.text
    monkeypatch.setattr(ks_module.kill_switch, "trigger", AsyncMock(return_value={
        "already_in_progress": True, "in_progress_for_s": 1.5, "details": rows, "message": message}))
    resp = await client.post("/api/prop-firm/kill-switch",
                             json={"profile_id": created.json()["id"], "reason": "second"})
    assert resp.status_code == 409, (resp.status_code, resp.text)
    return resp


def _row(**extra):
    return {"pair": "BTCUSD", "disposition": "FAILED", "status": "failed", "reason": "venue said no", **extra}


async def test_D1_a_token_at_DEPTH_is_redacted_on_both_nesting_paths_and_inside_a_tuple(client, monkeypatch):
    rows = [_row(
        close={"resolution": {"read_errors": [f"APIError: bad header Bearer {T1}"]}},     # dict -> dict -> list -> str
        legs=[{"reason": f"leg refused: {T2}"}],                                          # dict -> list -> dict -> str
        pairs=("BTCUSD", f"tuple carried {T3}"),                                           # a tuple jsonable_encoder emits
    )]
    resp = await _answer_409(client, monkeypatch, rows)
    for token in (T1, T2, T3):
        assert token not in resp.text, f"a planted token reached the 409 body: {token}"
    row = resp.json()["rows_so_far"][0]
    assert "[REDACTED]" in row["close"]["resolution"]["read_errors"][0]
    assert "[REDACTED]" in row["legs"][0]["reason"]
    assert "[REDACTED]" in row["pairs"][1] and row["pairs"][0] == "BTCUSD"


async def test_D2_every_NON_STRING_value_and_every_container_SHAPE_comes_back_unchanged(client, monkeypatch):
    """The must-miss: `redact(str(container))` would hide the token and turn the row into a string."""
    nested = {"ints": [1, 2, 3], "float": 1.5, "flag": True, "none": None, "deep": {"k": [0, 2.5, False, None]}}
    rows = [_row(filled_units=0.004, terminal=True, reads=6, resolution=None, detailx=nested,
                 reason=f"planted {T4}")]
    resp = await _answer_409(client, monkeypatch, rows)
    body = resp.json()
    assert isinstance(body["rows_so_far"], list) and len(body["rows_so_far"]) == 1
    row = body["rows_so_far"][0]
    assert isinstance(row, dict) and row["pair"] == "BTCUSD"
    assert (row["filled_units"], row["terminal"], row["reads"], row["resolution"]) == (0.004, True, 6, None), row
    assert row["detailx"] == nested, row["detailx"]
    assert row["reason"] == "planted [REDACTED]" and T4 not in resp.text


async def test_D3_a_token_under_ANY_key_is_redacted_not_only_reason_or_error(client, monkeypatch):
    rows = [_row(x=f"odd key {T5}", detail={"deeper": {"note": f"also {T1}"}})]
    resp = await _answer_409(client, monkeypatch, rows)
    assert T5 not in resp.text and T1 not in resp.text, resp.text
    row = resp.json()["rows_so_far"][0]
    assert "[REDACTED]" in row["x"] and "[REDACTED]" in row["detail"]["deeper"]["note"]


async def test_D4_a_200_DEEP_row_and_a_SELF_REFERENTIAL_row_still_get_their_409_and_leak_nothing(client, monkeypatch):
    deep: object = f"bottom {T2}"
    for _ in range(200):
        deep = [deep]
    cyclic = _row(reason=f"cyclic {T3}")
    cyclic["self"] = cyclic
    resp = await _answer_409(client, monkeypatch, [_row(deep=deep), cyclic])
    assert T2 not in resp.text and T3 not in resp.text, "a token survived the bounded path"
    rows = resp.json()["rows_so_far"]
    assert len(rows) == 2 and rows[1]["self"] == "[CYCLE]", rows[1]
    assert "TRUNCATED" in resp.text


async def test_D6_the_409_DETAIL_is_redacted_too(client, monkeypatch):
    resp = await _answer_409(client, monkeypatch, [_row()], message=f"ALREADY IN PROGRESS {T4}")
    assert T4 not in resp.text and "[REDACTED]" in resp.json()["detail"], resp.text


def test_D2b_the_helper_keeps_each_container_KIND():
    """JSON cannot show a tuple from a list; the helper can. A tuple stays a tuple, a set a set, a list a list."""
    from app.api.routers.prop_firm import _redact_nested

    got = _redact_nested({"t": ("a", f"b {T1}"), "s": {"x"}, "l": [1, f"c {T2}"], "n": 7})
    assert type(got["t"]) is tuple and type(got["s"]) is set and type(got["l"]) is list and got["n"] == 7, got
    assert got["t"][1] == "b [REDACTED]" and got["l"] == [1, "c [REDACTED]"], got


async def test_D7_a_string_the_ENCODER_produces_from_an_OBJECT_is_redacted_too(client, monkeypatch):
    """The second pass: a row can carry an object (a model, a dataclass) that `jsonable_encoder` turns into a dict of
    strings AFTER the first pass has run."""
    from dataclasses import dataclass

    @dataclass
    class _VenueEcho:
        symbol: str
        message: str

    resp = await _answer_409(client, monkeypatch, [_row(echo=_VenueEcho("BTCUSD", f"object carried {T5}"))])
    assert T5 not in resp.text, resp.text
    assert resp.json()["rows_so_far"][0]["echo"] == {"symbol": "BTCUSD", "message": "object carried [REDACTED]"}
