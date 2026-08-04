"""Configuring a run (task 2.2) — and what must stay unconfigurable.

Settings belong to a RUN. Changing the timeframe or symbol set mid-run would
make the result uninterpretable, so applying a configuration always starts a new
run and the config is snapshotted with it.

THE MOST IMPORTANT TEST IN THIS FILE IS THAT `risk_pct` IS REFUSED.

    ROI ≈ risk_pct × n × avg_R

is an exact identity — the engine computes `pnl_pct = r_multiple * risk_pct`. So
risk_pct carries no information about whether a strategy works: raising it
scales the equity curve and the drawdown by the same factor. It is pre-registered
at 1%, the feedback loop refuses to tune it, and the handoff names
tuning-to-hit-an-ROI-number as an explicit anti-goal.

A settings form would make it the most tempting control on the page, because it
is the one that most obviously moves the number everyone looks at. Refusing it
loudly — rather than ignoring it — is the point: a silently dropped field leaves
the caller believing it was applied.
"""
from __future__ import annotations

import pytest

from app.services.live.crypto_loop import LiveCryptoLoop
from app.services.live.run_config import (
    MAX_BALANCE,
    MIN_BALANCE,
    ConfigError,
    options,
    validate,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def loop():
    return LiveCryptoLoop()


# ---------------------------------------------------------------------------
# What must never be configurable
# ---------------------------------------------------------------------------
def test_risk_pct_is_refused(loop):
    with pytest.raises(ConfigError) as err:
        validate({"risk_pct": 0.05}, loop)
    msg = str(err.value)
    assert "pre-registered" in msg
    assert "identity" in msg, "the refusal must explain WHY, not just say no"


def test_risk_pct_is_refused_even_at_its_current_value(loop):
    """Accepting 0.01 would make it a settable field that happens to match —
    and the next request could set anything."""
    with pytest.raises(ConfigError):
        validate({"risk_pct": 0.01}, loop)


def test_the_engine_keeps_its_risk_pct_through_a_configured_reset(loop):
    cfg = validate({"starting_balance": 25_000}, loop)
    before = loop.risk_pct
    loop.apply_config(cfg)
    assert loop.risk_pct == before == 0.01


def test_options_names_what_is_fixed_and_why(loop):
    """The UI should be able to SHOW that risk is fixed, not just omit it —
    an absent field looks like an oversight, a stated one looks deliberate."""
    fixed = options()["fixed"]
    assert fixed["risk_pct"]["value"] == 0.01
    assert "identity" in fixed["risk_pct"]["reason"]


# ---------------------------------------------------------------------------
# Validation refuses rather than coerces
# ---------------------------------------------------------------------------
def test_unknown_symbols_are_refused_not_dropped(loop):
    """Silently dropping one would start a run whose stored config does not
    describe what actually ran."""
    with pytest.raises(ConfigError) as err:
        validate({"symbols": ["BTC/USD", "DOGE/USD"]}, loop)
    assert "DOGE/USD" in str(err.value)
    assert "Supported" in str(err.value)


def test_an_unsupported_timeframe_is_refused(loop):
    with pytest.raises(ConfigError) as err:
        validate({"entry_tf": "3m"}, loop)
    assert "3m" in str(err.value)


def test_bias_timeframe_must_be_higher_than_entry(loop):
    """Inverted, the engine still runs and produces numbers that mean nothing —
    the strategy takes its direction from the higher timeframe."""
    with pytest.raises(ConfigError) as err:
        validate({"entry_tf": "4H", "bias_tf": "4H"}, loop)
    assert "higher" in str(err.value)


@pytest.mark.parametrize("bad", [0, -100, MIN_BALANCE - 1, MAX_BALANCE + 1])
def test_implausible_balances_are_refused(loop, bad):
    """A balance of zero makes every position size zero: the engine stops
    trading while still reporting itself healthy."""
    with pytest.raises(ConfigError):
        validate({"starting_balance": bad}, loop)


def test_unknown_broker_mode_is_refused(loop):
    with pytest.raises(ConfigError) as err:
        validate({"broker_mode": "live"}, loop)
    assert "paper" in str(err.value) and "sim" in str(err.value)


def test_unknown_price_source_is_refused(loop):
    with pytest.raises(ConfigError):
        validate({"price_source": "coinbase"}, loop)


def test_an_empty_config_keeps_the_current_settings(loop):
    cfg = validate({}, loop)
    assert cfg.entry_tf == loop.entry_tf
    assert cfg.starting_balance == loop.starting_balance
    assert list(cfg.symbols) == list(loop.symbols)


# ---------------------------------------------------------------------------
# Applying it
# ---------------------------------------------------------------------------
def test_a_valid_config_is_applied(loop):
    cfg = validate({
        "symbols": ["BTC/USD"], "entry_tf": "15m", "bias_tf": "4H",
        "starting_balance": 25_000, "broker_mode": "sim", "max_concurrent": 1,
    }, loop)
    loop.apply_config(cfg)

    assert list(loop.symbols) == ["BTC/USD"]
    assert loop.entry_tf == "15m" and loop.bias_tf == "4H"
    assert loop.starting_balance == 25_000
    assert loop.broker_mode == "sim"
    assert loop.max_concurrent == 1


def test_switching_the_price_source_swaps_the_source_object(loop):
    """This is how PRICE_SOURCE=cft becomes reachable without an env change —
    see KNOWN_ISSUES A5."""
    from app.services.market_data.sources.cft import CFTSource

    loop.apply_config(validate({"price_source": "cft"}, loop))
    assert isinstance(loop.source, CFTSource)
    assert loop.price_source_name == "cft"


async def test_a_configured_reset_snapshots_what_it_will_run(engine, monkeypatch):
    """The config is stored with the run so a result can never be read against
    the wrong settings — which means it must record the NEW settings, not the
    ones being replaced."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession
    from app.models.engine_run import EngineRun

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)

    loop = LiveCryptoLoop()
    await loop.ensure_run()
    cfg = validate({"symbols": ["ETH/USD"], "entry_tf": "15m", "bias_tf": "4H",
                    "starting_balance": 10_000, "label": "15m test"}, loop)
    await loop.reset_run(config=cfg)

    async with maker() as db:
        run = (await db.execute(
            select(EngineRun).where(EngineRun.id == loop.run_id))).scalar_one()
    assert run.config["entry_tf"] == "15m", "the run recorded the OLD settings"
    assert run.config["starting_balance"] == 10_000
    assert run.config["symbols"] == ["ETH/USD"]
    assert run.label == "15m test"


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------
async def test_reset_rejects_a_bad_config_with_the_reason(client, monkeypatch):
    # Resetting genuinely needs an engine; without one the endpoint correctly
    # answers 503. Provide one so the CONFIG refusal is what gets tested.
    from app.api.routers import engine as engine_router

    monkeypatch.setattr(engine_router, "_loop", lambda _req: LiveCryptoLoop())
    resp = await client.post("/api/engine/reset", json={"entry_tf": "3m"})
    assert resp.status_code == 400
    assert "3m" in resp.json()["detail"]


async def test_reset_rejects_risk_pct_over_the_api(client):
    """The safety property, end to end."""
    resp = await client.post("/api/engine/reset", json={"risk_pct": 0.1})
    assert resp.status_code == 400
    assert "pre-registered" in resp.json()["detail"]


async def test_config_options_are_served_for_the_form(client):
    """Serving the options means the form cannot offer a choice the backend
    would refuse — the defect the broker connection form had."""
    body = (await client.get("/api/engine/config-options")).json()
    assert "BTC/USD" in body["symbols"]
    assert "1H" in body["entry_tf"]
    assert body["fixed"]["risk_pct"]["value"] == 0.01
