"""T-0038 half 2 — the tranche plan `EXIT-001` WOULD produce, recorded and executed by nothing.

`EXIT-001` is ratified: 70% at 2R, a 30% runner. **The live path has never produced a tranche** —
`broker/paper.py:on_tick` settled positions whole until `T-0038` half 1, and nothing has ever asked
it for a partial. This records what the rule would do, on the order path, **so the count exists
before the behaviour does.**

> **Nothing here calls `close_position`.** Stage A of a live behaviour change records; Stage B
> enforces, and only once the record is non-empty and a human has read it.

## AND THE FIRST THING IT RECORDS IS THAT THERE IS NEVER A RUNNER

    strategy_step:  tp = entry + p.rr_partial * risk     with Params.rr_partial = 2.0
    EXIT-001:       partial_level = entry + PARTIAL_AT_R * r_distance   with PARTIAL_AT_R = 2.0

**Identical. Every live signal's take-profit sits EXACTLY on the 2R partial level**, on both sides —
verified numerically for LONG and SHORT. So under `EXIT-001` every live trade is the DEGENERATE
RUNNER: the 70% and the 30% close at one price, `100%` out at target, and **the ratified 30% runner
cannot exist on the live path as configured.**

**That is a finding about the engine's configuration, not a defect in this recorder** — and it is
exactly what a shadow stage is for. *Before Salim's round-3 ruling this would have raised
`DegenerateRunner` on every signal; the ruling landed in time for the seam to be buildable at all.*

## WHERE NO PLAN CAN BE BUILT IT RECORDS WHY

A signal with no take-profit, or one whose target sits inside the 2R level, produces no plan. **Those
are recorded with their reason rather than skipped** — the `NOT_READ` discipline: a bar with no
tranche plan and a bar nobody looked at must not share a representation.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.services.rules.exit_001_v1_model import (
    PARTIAL_AT_R,
    PARTIAL_FRACTION,
    RUNNER_FRACTION,
    DegenerateRunner,
    TradePlan,
)

#: The name the shadow record is filed under on `DecisionTrace`.
GATE_NAME = "exit_tranche_plan"


def tranche_plan(signal: Any) -> dict[str, Any]:
    """What `EXIT-001` would do with this signal. **Executes nothing.**

    Returns a record in every case — including the cases where no plan exists, which carry
    `planned: False` and a `reason`. *A bar with no plan and a bar nobody looked at must not
    share a representation.*
    """
    entry = getattr(signal, "entry", None)
    stop = getattr(signal, "sl", None)
    target = getattr(signal, "tp", None)
    side = getattr(getattr(signal, "direction", None), "value", None)

    if entry is None or stop is None or side is None:
        return {"planned": False, "reason": "signal carries no entry/stop/direction"}
    if target is None:
        # STAGE B CHANGED WHAT "NO TARGET" MEANS, and this branch had to move with it.
        #
        # Through T-0050 a signal without a take-profit had no plan to record. Now `tp` is None
        # on EVERY signal BY DESIGN — the 2R price moved to `partial_price` and the 30% runner
        # has no final target because TARGET-001 cannot select one. So a signal carrying an
        # explicit partial IS planned, and the runner's terminal reasons are STOP_HIT and
        # SESSION_CLOSE rather than a price.
        partial_price = getattr(signal, "partial_price", None)
        partial_fraction = getattr(signal, "partial_fraction", None)
        if partial_price is None or partial_fraction is None:
            return {"planned": False, "reason": "signal carries neither a final target nor an "
                                                "EXIT-001 partial — nothing to plan"}
        return {
            "planned": True,
            "side": side,
            "entry": float(entry),
            "stop": float(stop),
            "final_target": None,
            "partial_level": float(partial_price),
            "partial_at_r": PARTIAL_AT_R,
            "partial_fraction": float(partial_fraction),
            "runner_fraction": RUNNER_FRACTION,
            # NO FINAL TARGET EXISTS, so there is no runner DISTANCE to compute and the
            # degeneracy question does not arise. `None`, never 0.0 — a zero here would say the
            # runner has nowhere to go, which is a different and false claim.
            "runner_distance": None,
            "degenerate_runner": None,
            "runner_terminates_on": ["STOP_HIT", "SESSION_CLOSE"],
            # AND THIS IS NO LONGER A SHADOW. T-0050 made the loop execute this plan.
            "executed": True,
        }

    try:
        plan = TradePlan(side=side, entry=float(entry), stop=float(stop),
                         final_target=float(target))
    except DegenerateRunner as exc:
        # The target is INSIDE the 2R level. Salim ruled the EQUALITY case in round 3 and not
        # this one, so the model still refuses it — recorded rather than swallowed.
        return {"planned": False, "reason": f"target inside the 2R level: {exc}"}
    except ValueError as exc:
        return {"planned": False, "reason": f"{type(exc).__name__}: {exc}"}

    return {
        "planned": True,
        "side": side,
        "entry": plan.entry,
        "stop": plan.stop,
        "final_target": plan.final_target,
        "partial_level": plan.partial_level,
        "partial_at_r": PARTIAL_AT_R,
        "partial_fraction": PARTIAL_FRACTION,
        "runner_fraction": RUNNER_FRACTION,
        # THE TWO FIELDS THE FINDING LIVES IN. `runner_distance == 0` on every live signal,
        # because strategy_step sets tp at exactly `rr_partial * risk` and `rr_partial` is 2.0
        # — the same 2.0 EXIT-001 takes its partial at.
        "runner_distance": plan.runner_distance,
        "degenerate_runner": plan.degenerate_runner,
        "executed": False,
    }


def record_on(trace: Any, signal: Any) -> dict[str, Any]:
    """Attach the tranche plan to a `DecisionTrace` as an UNENFORCED observation.

    `trace.observe`, never `trace.gate`: this decides nothing and stops nothing. `would_block`
    is `False` because a tranche plan is not a verdict about whether to trade — recording it as
    a would-block would put it in `would_block_by`, which is a different rule's numerator.
    """
    record = tranche_plan(signal)
    if record["planned"]:
        detail = (
            f"70% at {record['partial_level']} then a "
            f"{int(RUNNER_FRACTION * 100)}% runner to {record['final_target']}"
        )
        if record["degenerate_runner"]:
            detail += " — DEGENERATE: the target IS the 2R level, so 100% closes at target"
    else:
        detail = f"no tranche plan — {record['reason']}"

    trace.observe(GATE_NAME, False, detail, **record)
    return record


def record_from_loop(trace: Any, signal: Any) -> dict[str, Any] | None:
    """`record_on` with failure isolation, for the order path.

    **A shadow that can crash the trading loop is worse than no shadow.** Everything is caught
    and logged; the decision has already been made by the time this runs and must not be
    disturbed by an observer.
    """
    try:
        return record_on(trace, signal)
    except Exception as exc:  # noqa: BLE001 - the observer may never reach the decision
        logger.warning("Exit tranche shadow failed; decision unaffected", error=str(exc))
        return None
