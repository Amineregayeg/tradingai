"""Units -> MT5 LOTS, as a pure function (`T-0097`).

**THIS IS THE SEAM WHERE A VOCABULARY MISMATCH STOPS BEING A WRONG REPORT AND BECOMES WRONG
SIZE.** Everything this platform computes is in UNITS — `size_position` returns
`(equity * risk%) / per-unit stop distance` and every broker so far has taken that number
directly. MetaApi's `volume` is **MT5 lots**, and `close_position_partially(position_id,
volume)` takes lots too, so the adapter must both convert and dispatch on it.

`B167` is the same class one field over: a token borrowed from one vocabulary and read in
another. Here the token is a NUMBER, and the failure is not a mislabelled record — it is an
order for the wrong quantity.

**NOTHING HERE IS WIRED.** `size_position` is untouched: it is correct and has been verified
against live rows twice. This is a new function beside it, and connecting the two is the
adapter's job.

**NO VENUE CONSTANT IS HARDCODED.** `contract_size`, `volume_min`, `volume_step` and
`volume_max` are per-instrument and broker-reported, so they are parameters. *A number
invented here would be a guess about a venue nobody has connected to.*

WHAT THIS FUNCTION DOES NOT COVER (`B240` — a coverage claim without its complement)
------------------------------------------------------------------------------------
**THE THREE BOUNDS ARE ASSUMED TO ARRIVE FROM THE BROKER, AND NOTHING HERE CHECKS THAT.**
The intended source is MetaApi's `get_symbol_specification()`, which reports `volumeMin`,
`volumeStep`, `volumeMax` and `contractSize` per instrument. **If a caller passes conventions
WE picked instead, this function is validating against itself** — every refusal and every
clamp would be correct with respect to numbers nobody at the venue ever stated. *That is the
assumption most worth stating, because it cannot be seen from inside.* No adapter calls this
yet, so it is untested against a real specification.

**NOT COVERED, named rather than implied:**

* **Anything about whether the resulting lot size is CORRECT for the account.** This converts
  and constrains; `size_position` decides the size, and the two are deliberately unwired.
* **Currency, leverage, margin and free-margin checks.** A volume can be legal for the
  instrument and still be refused by the broker for margin, and nothing here anticipates that.
* **`volume_min > volume_max`**, and other self-contradictory specifications. The clamp branch
  refuses when the bounds leave no legal multiple, which covers the case incidentally rather
  than by design.
* **Fractional-lot instruments whose step is not a decimal fraction** — a step of, say, 1/3 is
  representable in `Decimal` only approximately, and no venue is known to use one.
* **That MetaApi's `volume` field is lots at all.** It is documented as such and no adapter
  has confirmed it against a live specification; `T-0100` mapped it from documentation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

#: Why a conversion refused. **A caller that cannot tell TOO SMALL from TOO LARGE cannot
#: report either honestly**, so the bound is carried rather than collapsed into a boolean.
BOUND_MIN = "volume_min"
BOUND_STEP = "volume_step"
BOUND_NON_POSITIVE = "non_positive"
#: **WHY THIS DID NOT EXIST, so the next reader does not delete it as redundant.**
#:
#: Hitting `volume_max` in the ORDINARY case is a size REDUCTION, not a refusal: the order is
#: placeable, it is smaller than asked, and `clamped` carries that. So the maximum had no
#: refusal token and every branch reached for `BOUND_MIN`.
#:
#: **There is exactly one case where the maximum causes an actual refusal** — when clamping to
#: the largest legal multiple lands BELOW the minimum, i.e. the instrument's own bounds leave
#: no legal volume at all. That branch is caused by the maximum and used to report
#: `volume_min`.
BOUND_MAX = "volume_max"


@dataclass(frozen=True)
class LotConversion:
    """The outcome, as VALUES rather than a number that might mean nothing.

    **`lots` is `None` on a refusal and NEVER `0.0`.** A zero-lot order is rejected by the
    venue while the caller reports having placed one — *a success report over an action that
    did not happen*, which is `B221`'s shape and has cost this project once already.

    `clamped` is separate from `refused` because **a clamp is a SIZE REDUCTION, not a
    failure**: the order goes in, smaller than asked. A caller that cannot see it happened
    reports a position it did not take.
    """

    lots: float | None
    requested_lots: float
    refused: bool = False
    bound: str | None = None
    reason: str | None = None
    clamped: bool = False

    @property
    def ok(self) -> bool:
        return not self.refused


def _d(x) -> Decimal:
    return Decimal(str(x))


def units_to_lots(
    units: float,
    *,
    contract_size: float,
    volume_min: float,
    volume_step: float,
    volume_max: float,
) -> LotConversion:
    """Convert a unit size to a venue-legal lot volume, or refuse and say which bound.

    **THE STEP ROUNDS DOWN, AND THE DIRECTION IS THE DECISION.** A broker rejects a volume
    that is not a whole multiple of `volume_step`, so it must move — and rounding UP takes
    more risk than the ruled percentage. *The single property verified live twice is that a
    trade risks exactly 1%*; rounding up breaks it silently and in the direction that costs
    money. Rounding down risks slightly less than ruled, which is a smaller and safer error.

    **BELOW `volume_min` IS A REFUSAL, NOT A ROUND-UP**, and this is the common case on a
    small account. Rounding up to reach the minimum is the tempting repair and it is the same
    defect as rounding the step up, with a larger multiplier: a position the account was
    never sized for. **A refusal is correct; a slightly-too-big position is not.**

    **ABOVE `volume_max` IS A CLAMP AND IS RECORDED.** The order is placeable, so refusing
    would be wrong — but the caller asked for more than it got, and `clamped` is how it can
    say so rather than reporting the requested size.

    Arithmetic is `Decimal` throughout. `0.3 / 0.1` is `2.9999999999999996` in binary floats,
    which floors to 2 and silently halves an order; `B227` is the same hazard one module over,
    and here it would be a live size error rather than a misread record.
    """
    try:
        u, cs = _d(units), _d(contract_size)
        vmin, vstep, vmax = _d(volume_min), _d(volume_step), _d(volume_max)
    except (InvalidOperation, ValueError, TypeError):
        return LotConversion(
            lots=None, requested_lots=0.0, refused=True, bound=BOUND_NON_POSITIVE,
            reason=f"unreadable inputs: units={units!r} contract_size={contract_size!r}",
        )

    if cs <= 0 or vstep <= 0:
        return LotConversion(
            lots=None, requested_lots=0.0, refused=True, bound=BOUND_STEP,
            reason=(
                f"the instrument is unusable: contract_size={contract_size}, "
                f"volume_step={volume_step}. Both must be positive."
            ),
        )

    raw = u / cs
    requested = float(raw)

    if u <= 0:
        return LotConversion(
            lots=None, requested_lots=requested, refused=True, bound=BOUND_NON_POSITIVE,
            reason=f"non-positive size: {units} units",
        )

    # DOWN to the nearest whole step. See the docstring: up would exceed the ruled risk.
    stepped = (raw / vstep).to_integral_value(rounding=ROUND_FLOOR) * vstep

    if stepped < vmin:
        return LotConversion(
            lots=None, requested_lots=requested, refused=True, bound=BOUND_MIN,
            reason=(
                f"{requested:.8f} lots rounds down to {float(stepped):.8f}, below the "
                f"instrument minimum {volume_min}. Rounding UP would place a position the "
                f"account was not sized for — the risk percentage is ruled, so the trade is "
                f"refused instead."
            ),
        )

    clamped = False
    if stepped > vmax:
        # The largest legal multiple at or below the maximum. Still a whole step, because a
        # bare `vmax` need not be one.
        stepped = (vmax / vstep).to_integral_value(rounding=ROUND_FLOOR) * vstep
        clamped = True
        if stepped < vmin:
            # `B283`. THE CAUSE IS THE MAXIMUM. This reported `BOUND_MIN` while its own
            # reason string named `volume_max` — **the accurate prose hid the inaccurate
            # field**, so a reader who checked the message found the right cause and never
            # looked at the field. It survives a careful read and fails only where a caller
            # BRANCHES rather than reads, which is exactly what `T-0097`'s acceptance asked
            # the bound to be for.
            return LotConversion(
                lots=None, requested_lots=requested, refused=True, bound=BOUND_MAX,
                reason=(
                    f"volume_max {volume_max} leaves no legal multiple of {volume_step} at "
                    f"or above the minimum {volume_min}"
                ),
            )

    lots = float(stepped)
    if lots <= 0.0:
        # UNREACHABLE while volume_min > 0, and asserted anyway: a zero-lot order is a
        # success report over an action that did not happen.
        # `B283`. THE CAUSE IS THE STEP, not the minimum: the size was rounded down to zero
        # by `volume_step`. **Re-keyed even though this branch is UNREACHABLE while
        # `volume_min > 0`** — a one-line fix to the branch above would leave the identical
        # defect sitting here for the day an instrument reports a zero minimum, and the
        # comment saying it is unreachable is exactly what would stop anyone looking.
        return LotConversion(
            lots=None, requested_lots=requested, refused=True, bound=BOUND_STEP,
            reason=(
                f"{requested:.8f} lots rounds down to zero at step {volume_step}; a zero-lot "
                f"order would be rejected by the venue while the caller reported placing one"
            ),
        )

    return LotConversion(
        lots=lots,
        requested_lots=requested,
        clamped=clamped,
        reason=(
            f"clamped from {requested:.8f} to {lots:.8f} lots by volume_max {volume_max}"
            if clamped else None
        ),
    )
