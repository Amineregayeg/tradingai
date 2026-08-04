"""What may be configured for an engine run — and what may not (task 2.2).

Configuration belongs to a RUN, not to the engine. Changing the timeframe or the
symbol set halfway through makes the result uninterpretable, so applying a new
configuration always starts a new run (see models/engine_run.py). That is why
this validates a config for a reset rather than mutating a running engine.

`risk_pct` IS DELIBERATELY ABSENT, and this is the only interesting decision in
the file.

    ROI ≈ risk_pct × n × avg_R

is an exact algebraic identity — the engine literally computes
``pnl_pct = r_multiple * risk_pct``. So risk_pct carries no information about
whether a strategy works: raising it scales the equity curve and the drawdown by
the same factor and teaches you nothing. The feedback loop already refuses to
propose tuning it (`feedback.FIXED_KNOBS`), the acceptance criteria pre-register
it at 1%, and the handoff calls tuning-to-hit-an-ROI-number an explicit
anti-goal.

Putting it in a settings form would quietly undo all of that: it would become
the most tempting control on the page, because it is the one that most obviously
moves the number everyone looks at. A request that names it is REFUSED with that
reason rather than ignored — silently dropping it would leave the caller
believing it had been applied.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Pairs the engine knows how to trade, mapped to their Binance symbol. Adding
#: one means confirming the venue actually quotes it — an unknown symbol would
#: otherwise fail per-bar inside the loop rather than at configuration time.
SUPPORTED_SYMBOLS: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
}

#: Entry timeframes. The trader's documented method is 5/15/30m while the engine
#: has always run 1H — that gap is recorded in KNOWN_ISSUES, and making the
#: shorter frames selectable is what allows it to be tested rather than argued
#: about.
SUPPORTED_ENTRY_TF: tuple[str, ...] = ("5m", "15m", "30m", "1H", "4H")
SUPPORTED_BIAS_TF: tuple[str, ...] = ("4H", "D", "W")

SUPPORTED_BROKER_MODES: tuple[str, ...] = ("paper", "sim")
SUPPORTED_PRICE_SOURCES: tuple[str, ...] = ("binance", "cft")

#: Guard rails on the balance. Not a strategy constraint — a sanity one. A
#: balance of 0 makes every position size zero and the engine silently stops
#: trading while still looking healthy.
MIN_BALANCE = 100.0
MAX_BALANCE = 10_000_000.0

#: Parameters that are pre-registered and must never be set from a request.
FORBIDDEN_FIELDS: dict[str, str] = {
    "risk_pct": (
        "risk_pct is pre-registered FIXED at 1% and is not a tunable knob. "
        "ROI ≈ risk_pct × n × avg_R is an exact identity, so changing it only "
        "rescales the equity curve and the drawdown together — it cannot make a "
        "strategy better, only louder. The feedback loop refuses to tune it for "
        "the same reason."
    ),
}


class ConfigError(ValueError):
    """A configuration that must be refused, with the reason."""


@dataclass
class RunConfig:
    """A validated configuration for a new run."""

    symbols: dict[str, str]
    entry_tf: str
    bias_tf: str
    starting_balance: float
    broker_mode: str
    price_source: str
    max_concurrent: int
    label: str | None = None
    note: str | None = None

    def as_dict(self) -> dict:
        return {
            "symbols": list(self.symbols),
            "entry_tf": self.entry_tf,
            "bias_tf": self.bias_tf,
            "starting_balance": self.starting_balance,
            "broker_mode": self.broker_mode,
            "price_source": self.price_source,
            "max_concurrent": self.max_concurrent,
            "label": self.label,
            "note": self.note,
        }


def reject_forbidden(payload: dict | None) -> None:
    """Refuse pre-registered fields. Needs no engine, so it can run before one
    is available — a request naming risk_pct deserves that answer even while
    the engine is down."""
    for field, reason in FORBIDDEN_FIELDS.items():
        if field in (payload or {}):
            raise ConfigError(reason)


def validate(payload: dict | None, current) -> RunConfig:
    """Build a validated RunConfig, falling back to the engine's current values.

    Every unknown value is REFUSED rather than coerced. Silently substituting a
    default would start a run whose stored config does not describe what
    actually ran — and the whole reason configs are snapshotted per run is so a
    result can never be read against the wrong settings.
    """
    payload = dict(payload or {})
    reject_forbidden(payload)

    # -- symbols ---------------------------------------------------------
    requested = payload.get("symbols")
    if requested is None:
        symbols = dict(current.symbols)
    else:
        if not isinstance(requested, list) or not requested:
            raise ConfigError("symbols must be a non-empty list, e.g. ['BTC/USD']")
        unknown = [s for s in requested if s not in SUPPORTED_SYMBOLS]
        if unknown:
            raise ConfigError(
                f"unsupported symbol(s): {', '.join(unknown)}. "
                f"Supported: {', '.join(SUPPORTED_SYMBOLS)}"
            )
        symbols = {s: SUPPORTED_SYMBOLS[s] for s in requested}

    # -- timeframes ------------------------------------------------------
    entry_tf = payload.get("entry_tf", current.entry_tf)
    if entry_tf not in SUPPORTED_ENTRY_TF:
        raise ConfigError(
            f"unsupported entry timeframe {entry_tf!r}. "
            f"Supported: {', '.join(SUPPORTED_ENTRY_TF)}"
        )
    bias_tf = payload.get("bias_tf", current.bias_tf)
    if bias_tf not in SUPPORTED_BIAS_TF:
        raise ConfigError(
            f"unsupported bias timeframe {bias_tf!r}. "
            f"Supported: {', '.join(SUPPORTED_BIAS_TF)}"
        )
    if _tf_minutes(bias_tf) <= _tf_minutes(entry_tf):
        # The method is "higher-timeframe bias, lower-timeframe entry". Inverted,
        # the engine would still run and produce numbers that mean nothing.
        raise ConfigError(
            f"bias timeframe ({bias_tf}) must be higher than the entry "
            f"timeframe ({entry_tf}) — the strategy takes its direction from the "
            "higher timeframe"
        )

    # -- balance ---------------------------------------------------------
    balance = payload.get("starting_balance", current.starting_balance)
    try:
        balance = float(balance)
    except (TypeError, ValueError):
        raise ConfigError("starting_balance must be a number") from None
    if not (MIN_BALANCE <= balance <= MAX_BALANCE):
        raise ConfigError(
            f"starting_balance must be between {MIN_BALANCE:,.0f} and "
            f"{MAX_BALANCE:,.0f} (got {balance:,.2f})"
        )

    # -- broker / prices -------------------------------------------------
    broker_mode = str(payload.get("broker_mode", current.broker_mode)).lower()
    if broker_mode not in SUPPORTED_BROKER_MODES:
        raise ConfigError(
            f"broker_mode must be one of {', '.join(SUPPORTED_BROKER_MODES)} "
            "('paper' = plain simulation, 'sim' = prop-firm rules enforced)"
        )
    price_source = str(
        payload.get("price_source", getattr(current, "price_source_name", "binance"))
    ).lower()
    if price_source not in SUPPORTED_PRICE_SOURCES:
        raise ConfigError(
            f"price_source must be one of {', '.join(SUPPORTED_PRICE_SOURCES)}"
        )

    max_concurrent = payload.get("max_concurrent", current.max_concurrent)
    try:
        max_concurrent = int(max_concurrent)
    except (TypeError, ValueError):
        raise ConfigError("max_concurrent must be a whole number") from None
    if not (1 <= max_concurrent <= 20):
        raise ConfigError("max_concurrent must be between 1 and 20")

    return RunConfig(
        symbols=symbols,
        entry_tf=entry_tf,
        bias_tf=bias_tf,
        starting_balance=balance,
        broker_mode=broker_mode,
        price_source=price_source,
        max_concurrent=max_concurrent,
        label=payload.get("label"),
        note=payload.get("note"),
    )


def _tf_minutes(tf: str) -> int:
    return {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1H": 60, "4H": 240, "D": 1440, "W": 10080,
    }.get(tf, 0)


def options() -> dict:
    """What the UI may offer. Served from here so the form can never present a
    choice the backend would refuse — the defect the broker connection form had.
    """
    return {
        "symbols": list(SUPPORTED_SYMBOLS),
        "entry_tf": list(SUPPORTED_ENTRY_TF),
        "bias_tf": list(SUPPORTED_BIAS_TF),
        "broker_mode": [
            {"value": "paper", "label": "Paper (plain simulation)"},
            {"value": "sim", "label": "Prop-firm sim (challenge rules enforced)"},
        ],
        "price_source": [
            {"value": "binance", "label": "Binance (more history)"},
            {"value": "cft", "label": "Crypto Fund Trader (the venue we would trade)"},
        ],
        "starting_balance": {"min": MIN_BALANCE, "max": MAX_BALANCE},
        "max_concurrent": {"min": 1, "max": 20},
        "fixed": {
            "risk_pct": {
                "value": 0.01,
                "reason": FORBIDDEN_FIELDS["risk_pct"],
            }
        },
    }
