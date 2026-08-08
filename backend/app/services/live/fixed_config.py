"""The engine's settings. All of them, in one place, not configurable at runtime.

WHY THERE IS NO FORM ANY MORE
The engine page used to ask which symbols, which timeframes, which broker, which
price source and what starting balance before a run could begin. Every one of
those questions still has to be answered — deleting the form does not delete the
questions — so they are answered here, once, and the engine page becomes Start
and Stop.

That trade is deliberate and it has a cost worth stating: changing any of these
now requires editing this file and redeploying. What it buys is that a run cannot
be started under settings nobody meant to choose, and that every run in the
history is directly comparable to every other one. A configurable engine whose
configuration is never revisited is just a slower way of running the defaults,
with the added risk that one run in twenty was different and nothing says which.

IT ALSO CLOSES KNOWN_ISSUES A9 BY CONSTRUCTION
A9: on restart the loop adopted the active run but never read its stored config,
so the engine came back on defaults while filing results under a row claiming
something else. With exactly one configuration in the system, there is no second
value for a restart to disagree with. The `config` snapshot on each run row stays
— it is still the record of what produced those trades — but it can no longer
diverge from what actually ran.

THE NUMBERS BELOW ARE NOT ARBITRARY, AND TWO OF THEM ARE CLAIMS ABOUT REALITY

`STARTING_BALANCE` is the size of the CryptoFundTrader challenge being simulated,
confirmed with the account holder on 2026-08-08. It is a ROUND CONSTANT and must
stay one. Prop-firm limits are percentages of the size you BOUGHT, not of what
the account is worth today: seeding from a live balance would make the drawdown
allowance drift every time the account moved, so a breach would be measured
against a base that had already moved with it. `PropFirmRules` says the same
thing in its own docstring — this is that rule honoured, not restated.

`RISK_PCT` is pre-registered at 1% and is not a knob. ROI ≈ risk_pct × n × avg_R
is an exact identity, so changing it rescales the equity curve and the drawdown
together — it cannot make a strategy better, only louder. It was never settable
from the form either; it is here for completeness, and the test suite asserts it.
"""
from __future__ import annotations

from typing import Final

#: Instruments watched, as pair -> Binance symbol.
SYMBOLS: Final[dict[str, str]] = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}

#: Timeframe the strategy looks for entries on — one evaluation per closed bar.
ENTRY_TF: Final[str] = "1H"

#: Timeframe the directional bias is read from. Must be higher than ENTRY_TF:
#: a bias taken from the same series it trades tells you nothing the entry did
#: not already say.
BIAS_TF: Final[str] = "D"

#: Where bars come from. Binance rather than CryptoFundTrader: CFT serves only
#: ~125 days of 1H history against the ~470 a corrected backtest needs, and the
#: CFT path depends on the browser bridge being up. The divergence is measured
#: and recorded in KNOWN_ISSUES A3 rather than assumed away.
PRICE_SOURCE: Final[str] = "binance"

#: "sim" = SimPropFirmBroker, which enforces the challenge rules below.
#: "paper" would be a plain simulation with no rules and no way to fail, which
#: is a comfortable thing to watch and not an informative one.
BROKER_MODE: Final[str] = "sim"

#: The challenge size being simulated. A round constant — see the module docstring.
STARTING_BALANCE: Final[float] = 5_000.0

#: Pre-registered. Not a tunable knob — see the module docstring.
RISK_PCT: Final[float] = 0.01

#: Most positions open at once.
MAX_CONCURRENT: Final[int] = 3

#: Seconds between polls of the live price.
POLL_INTERVAL: Final[float] = 10.0


def as_dict() -> dict:
    """The settings as the UI shows them, so the page cannot describe a
    configuration the engine is not running."""
    return {
        "symbols": list(SYMBOLS),
        "entry_tf": ENTRY_TF,
        "bias_tf": BIAS_TF,
        "price_source": PRICE_SOURCE,
        "broker_mode": BROKER_MODE,
        "starting_balance": STARTING_BALANCE,
        "risk_pct": RISK_PCT,
        "max_concurrent": MAX_CONCURRENT,
        # Percentages of STARTING_BALANCE, mirroring PropFirmRules' defaults.
        # Shown so the limits that can end a run are visible before it starts.
        "daily_loss_limit_pct": 5.0,
        "max_drawdown_pct": 10.0,
        "profit_target_pct": 10.0,
    }
