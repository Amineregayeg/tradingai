"""End-to-end: the decision log + feedback-loop API endpoints.

Proves the wiring — DecisionRecord rows -> /engine/decisions serialization and
-> /engine/feedback (expected-vs-actual + corrections) — actually works over
HTTP, not just as a library.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.decision_record import (
    COHORT_PAPER,
    OUTCOME_LOSS,
    OUTCOME_OPEN,
    OUTCOME_WIN,
    DecisionRecord,
)


def _rec(i: int, outcome: str, realized_r: float | None) -> DecisionRecord:
    entry, sl, tp = 100.0, 99.0, 102.0  # expected_r = 2.0
    return DecisionRecord(
        symbol="BTC/USD",
        timeframe="1H",
        inputs_hash=f"in{i}",
        code_path_hash="cp1",
        abstained=False,
        signal_dir="LONG",
        signal_entry=Decimal("100.0"),
        signal_sl=Decimal("99.0"),
        signal_tp=Decimal("102.0"),
        sized_units=Decimal("500.0"),
        expected_r=Decimal("2.0"),
        realized_r=Decimal(str(realized_r)) if realized_r is not None else None,
        outcome=outcome,
        cohort=COHORT_PAPER,
    )


@pytest.mark.asyncio
async def test_decisions_endpoint_returns_rows(client, db_session):
    db_session.add_all([_rec(0, OUTCOME_OPEN, None), _rec(1, OUTCOME_WIN, 2.0)])
    await db_session.commit()

    resp = await client.get("/api/engine/decisions?limit=10")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    r = rows[0]
    # JSON-safe: numbers are floats/None, not Decimal strings
    assert isinstance(r["signal_entry"], float)
    assert r["symbol"] == "BTC/USD"
    assert r["cohort"] == "paper"


@pytest.mark.asyncio
async def test_feedback_abstains_on_thin_evidence(client, db_session):
    db_session.add_all([_rec(i, OUTCOME_WIN, 2.0) for i in range(3)])
    await db_session.commit()

    resp = await client.get("/api/engine/feedback?min_evidence=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["abstained"] is True
    assert body["corrections"] == []
    assert "insufficient evidence" in body["abstain_reason"]


@pytest.mark.asyncio
async def test_feedback_measures_gap_with_enough_evidence(client, db_session):
    # 40 closed records: realized R systematically below the targeted 2.0 (a real
    # gap), so the loop has something to measure and can propose corrections.
    recs = []
    for i in range(40):
        outcome, r = (OUTCOME_WIN, 1.0) if i % 2 == 0 else (OUTCOME_LOSS, -1.0)
        recs.append(_rec(i, outcome, r))
    db_session.add_all(recs)
    await db_session.commit()

    resp = await client.get("/api/engine/feedback?min_evidence=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["abstained"] is False
    assert body["n"] == 40
    ev = body["expected_vs_actual"]
    assert ev["mean_expected_r"] == pytest.approx(2.0, abs=1e-6)
    # mean realized R = mean(1.0, -1.0) = 0.0
    assert ev["mean_realized_r"] == pytest.approx(0.0, abs=1e-6)
    # LIKE-FOR-LIKE gap: winners realize 1.0 vs the 2.0 they targeted = -1.0
    assert ev["n_winners"] == 20
    assert body["gaps"]["winner_realized_minus_target_r"] == pytest.approx(-1.0, abs=1e-6)
    # any corrections must never target risk_pct
    for c in body["corrections"]:
        assert c["target_param"] != "risk_pct"
