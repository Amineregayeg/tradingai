"""M9 Stage A — the contract engine evaluates every bar and decides nothing.

WHAT THIS IS FOR
The engine has 34 of 117 rules implemented and 0 of them has ever influenced a
trade. That gap is architectural: `_tick_symbol` calls the pre-contract ICT
function and nothing else. Building more rules does not close it, and switching
over in one step would replace a strategy we can measure with one we cannot.

So the rule engine runs alongside, on the same bars, at the same moment, and its
verdict is **recorded and discarded**. Two things come out of that which nothing
else can produce:

  * a `setup_evaluation` with a real `deciding_rule_id`, emitted from live data
    rather than from a fixture — the exit criterion for the whole cutover;
  * a measurement of what the contract engine WOULD have done, on the identical
    bars the ICT engine acted on, which is the only honest basis for deciding
    whether to hand it the wheel.

IT MUST NOT BE ABLE TO AFFECT A TRADE
Every call is wrapped, every failure is swallowed and logged, and the return value
is never read by the trading path. A shadow that can break the engine is worse
than no shadow: it converts an observability feature into an outage.

WHAT IT HONESTLY CANNOT DO YET, AND WHY THAT IS THE POINT
Most of the 34 rules cannot be evaluated from bars alone. GATE-008's roster needs
TOTAL and USDT.D from CryptoCap, which we do not have (KNOWN_ISSUES B11), and the
disturbance grader and the risk matrix read from it. Those rules are recorded as
`NOT_APPLICABLE` with the reason in `values` — never as PASS.

That is deliberate and it is the most useful thing this module does on day one.
"Silence is not a pass" is the contract's own words (C-04): a rule that cannot run
must say so in every record, so the missing dependency shows up as production
evidence accumulating hourly rather than as a line in a planning document.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from app.core.logging import logger
from app.services.rules.gate_023_timezone import NewYorkTimestamps
from app.services.rules.gate_036_stand_aside import Decision, StandAside
from app.services.rules.prim_001_swings import Bar, SwingPoints
from app.services.rules.prim_002_imbalances import ImbalanceInventory
from app.services.rules.prim_003_liquidity import LiquidityPools
from app.services.rules.prim_004_sweeps import SweepEvents
from app.services.rules.prim_005_breaks import BreakEvents
from app.services.rules.prim_006_sr_flips import SRFlipZones
from app.services.live import fixed_config as fixed
from app.services.telemetry import records as rec
from app.services.telemetry.ny_time import iso_ny

#: Rules that are implemented but cannot be evaluated from bar data alone, with the
#: reason each one is blocked. Emitted as NOT_APPLICABLE on every record.
#:
#: This list is a liability ledger, not a configuration. Every entry is a rule the
#: coverage report counts as implemented and that has never decided anything, and
#: the right response to a line here is to remove its cause — not to widen what
#: counts as evaluated.
BLOCKED_ON_CORRELATES: dict[str, str] = {
    "GATE-008": "roster panels TOTAL and USDT.D are unavailable (CryptoCap not wired)",
    "GATE-002": "disturbance grade needs the correlate panels GATE-008 could not read",
}


def declared_parameters() -> rec.DeclaredParameters:
    """OUR choices, stamped on every record so they can never be read as his.

    Each field is either a value the corpus settled by behaviour or one the trader
    explicitly declined to fix. `reverse_quorum` stays None because it is the
    latter: the source never quantifies "multiple", and K-13 asserts that any
    quorum we applied equals a DECLARED one — an invented integer here would be
    hard-coded doctrine.

    `virtual_account_size` is read from `fixed_config` rather than restated, so
    the number the engine sizes with and the number the record claims cannot
    diverge.
    """
    return rec.DeclaredParameters(
        virtual_account_size=fixed.STARTING_BALANCE,
        evaluation_order_id="tradingai-shadow-v1",
        # M0 section 5. Every closed bar on every execution TF for every roster
        # symbol — chosen because it is the emission policy easiest to audit, not
        # the cheapest one.
        emission_policy_id="every-closed-bar-roster-v1",
        layout_size_frozen=True,
        # Settled from the corpus: every statement of the disturbance rule says
        # CORRELATED assets, and a main asset disagreeing with its own setup is an
        # absent setup rather than a disturbance.
        main_asset_counts=False,
        box_scope="ENTRY_BOX_EXEC_TF",
        # Ratification R3: his own walkthrough stops at the 3R rung, and his four
        # real trades came in at 3.6, 3.05, 4.0 and 3.15. "Largest" is dead text.
        stop_selection_reading="CLOSEST_TO_3R_TIES_TO_LARGER",
        runner_management_policy="70_30_partial_then_runner",
        reverse_quorum=None,
        execution_tf_set=("30M", "15M", "5M"),
    )


#: GATE-018's legal execution set. Anything below 5M is a FLAGGED EXTENSION, not
#: a violation — "Settled by behaviour; we flag rather than exclude", and the
#: trader's own bracketed charts are 6 trades on 1M and 2 on 3M against zero on
#: 30M. HG-12 bans only the ANALYSIS timeframes, which is a different list.
RULED_EXECUTION_TFS: frozenset[str] = frozenset({"30M", "15M", "5M"})

#: 1H and above are analysis only (GATE-017/019). A signal from one of these is a
#: CRITICAL violation under HG-12, not a flag — there is no flag for it, and
#: inventing one would soften a hard gate into a preference.
ANALYSIS_ONLY_TFS: frozenset[str] = frozenset({"1H", "2H", "4H", "1D", "1W", "1MO"})


def _tf_flags(signal_tf: str) -> list[str]:
    """SOFT_PREFERENCE deviations carried on the record.

    Only the below-the-set case produces a flag. The analysis-timeframe case is
    deliberately absent: it is a hard-gate violation and the conformance suite
    must catch it as one, not find it pre-labelled as an acceptable deviation.
    """
    tf = signal_tf.upper()
    if tf not in RULED_EXECUTION_TFS and tf not in ANALYSIS_ONLY_TFS:
        return ["SIGNAL_TF_OUTSIDE_RULED_SET"]
    return []


def _bars_from_frame(df) -> list[Bar]:
    """The engine's OHLC frame, as the primitives' minimal Bar.

    Deliberately a copy rather than a view: a primitive that mutated the frame the
    live path is about to use would be a shadow with a side effect, which is the
    one thing this module may not have.
    """
    out: list[Bar] = []
    for ts, row in df.iterrows():
        moment = ts.to_pydatetime()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        # open/close are carried, not optional: PRIM-002 separates a gap from a
        # volume imbalance by the BODIES ("the only difference is the wicks") and
        # raises on a body-less bar rather than substituting the wick and quietly
        # detecting a different object.
        out.append(Bar(
            time=moment,
            high=float(row["high"]), low=float(row["low"]),
            open=float(row["open"]), close=float(row["close"]),
        ))
    return out


def _blocked_evaluations() -> list[rec.RuleEvaluation]:
    """One NOT_APPLICABLE per blocked rule, each carrying why.

    NOT_APPLICABLE rather than FAIL: the rule did not refuse the trade, it could
    not be asked. Reporting it as a failure would inflate the gate-violation rate
    with our own missing plumbing and make a real refusal harder to find.
    """
    return [
        rec.RuleEvaluation(
            rule_id=rule_id,
            verdict="NOT_APPLICABLE",
            values={"not_evaluated_because": reason},
            value_provenance={"not_evaluated_because": rec.derived("engine capability")},
        )
        for rule_id, reason in BLOCKED_ON_CORRELATES.items()
    ]


def evaluate(
    pair: str,
    df,
    *,
    signal_tf: str,
    declared: rec.DeclaredParameters,
    sequence_no: int,
    scan_id: str,
) -> dict[str, Any] | None:
    """Run the contract engine over `df` and return a `setup_evaluation`.

    Returns None if anything at all goes wrong. The caller must not care why —
    that is what keeps a shadow evaluation incapable of affecting a trade.
    """
    try:
        bars = _bars_from_frame(df)
        if len(bars) < 10:
            return None

        now = bars[-1].time

        # -- primitives, in dependency order --------------------------------
        swings = SwingPoints.detect(bars, tf=signal_tf)
        breaks = BreakEvents.detect(bars, swings, tf=signal_tf)
        SwingPoints.classify_strength(swings, breaks)
        imbalances = ImbalanceInventory.detect(bars, tf=signal_tf)
        pools = LiquidityPools.detect(bars, swings, tf=signal_tf)
        sweeps = SweepEvents.detect(pools, bars, breaks, tf=signal_tf)
        flips = SRFlipZones.detect(bars, swings, breaks, imbalances, tf=signal_tf)

        # -- rules that CAN be evaluated from bars ---------------------------
        evaluations: list[rec.RuleEvaluation] = [NewYorkTimestamps.evaluate(now)]
        evaluations.extend(_blocked_evaluations())

        # A setup is "in play" only if the primitives produced something to judge.
        # This is what separates SKIP from STAND_ASIDE, and it is a fact about the
        # bars rather than a preference (GATE-036).
        setup_in_play = bool(imbalances) and bool(breaks)

        causes: list[str] = []
        if not imbalances:
            causes.append("no imbalance on this bar to enter from")
        if not breaks:
            causes.append("no structure break to trade with or against")
        causes.extend(BLOCKED_ON_CORRELATES.values())

        # THE LAYOUT IS UNREADABLE, SO THE ANSWER IS ALWAYS STAND_ASIDE.
        #
        # Not a limitation worked around — the correct output. Without the roster
        # panels there is no alignment to grade, and the schema agrees: a TAKE
        # additionally requires `stop_evaluation`, `target_selection` and
        # `entry_criteria`, none of which exists before M6. A shadow that emitted
        # TAKE would be claiming a trade it cannot substantiate, and the record
        # would be rejected by the very validator meant to keep it honest.
        #
        # `setup_in_play` is still computed and still carried in the causes,
        # because "there was no imbalance" and "we could not read the layout" are
        # different reasons to stand aside and the difference is the whole point
        # of the census this run produces.
        decision: Decision = StandAside.unreadable(causes, evaluations)

        # `deciding_rule_id` is required by the schema and the folder returns None
        # when nothing FAILED — which is our case, since a rule we could not ask
        # is NOT_APPLICABLE rather than a refusal. GATE-036 is then the honest
        # citation: standing aside IS its output, and borrowing the id of a rule
        # that merely passed would misattribute the decision.
        deciding = decision.deciding_rule_id or "GATE-036"

        return rec.setup_evaluation(
            timestamp=now,
            declared=declared,
            scan_context={
                "scan_id": scan_id,
                "sequence_no": sequence_no,
                "candidate_origin": "SCHEDULED_BAR_CLOSE",
                "bar_close_time_ny": iso_ny(now),
                "data_as_of_ny": iso_ny(datetime.now(tz=timezone.utc)),
                "pre_filters_applied": [],
            },
            instrument={
                "symbol": pair,
                "instrument_class": "ALIGNED_MAJOR",
                # The venue we actually read, not the one GATE-008 names. Recorded
                # truthfully so the spot/perpetual deviation (A3) is visible in the
                # telemetry rather than assumed away by a hopeful constant.
                "venue": "BINANCE_SPOT",
            },
            mode={"trading_mode": "DAY_TRADE", "direction_mode": "FORWARD"},
            timeframes={
                "signal_tf": signal_tf,
                "alignment_tf": signal_tf,
                "analysis_tfs_scanned": [signal_tf],
            },
            session={
                "ny_local_time": iso_ny(now),
                "tz_offset_used": NewYorkTimestamps.evaluate(now).values["tz_offset_used"],
                "in_magic_zone": False,
                "minutes_from_nyo": 0,
            },
            primitives={
                "swing_points": [s.as_dict() for s in swings[-40:]],
                "structure_boxes": [],
                "imbalances": [i.as_dict() for i in imbalances[-40:]],
                "liquidity_pools": [p.as_dict() for p in pools[-40:]],
                "sweeps": [s.as_dict() for s in sweeps[-20:]],
                "breaks": [b.as_dict() for b in breaks[-20:]],
            },
            # `disturbance_grade` is forced to one of NONE/LIGHT/HEAVY — the schema
            # offers no value for "the layout was never read", which is a real gap
            # in it and is recorded as such (KNOWN_ISSUES). NONE is written because
            # something must be, and every other field in this record contradicts
            # any reading of it as "checked, and nothing was disturbed":
            # layout_size is 0, states is empty, GATE-008 and GATE-002 are
            # NOT_APPLICABLE with their reasons, and the decision is STAND_ASIDE
            # citing the missing panels.
            correlates={
                "layout_size": 0,
                "disturbed_count": 0,
                "disturbance_grade": "NONE",
                "states": [],
                "main_asset_counted": False,
            },
            rule_evaluations=evaluations,
            decision=decision.decision,
            decision_path=decision.decision_path,
            deciding_rule_id=deciding,
            # No risk is assessed because no box is graded: the 3x3 matrix reads a
            # box grade and a disturbance grade, and neither exists without the
            # correlate panels. A number here would be an invention.
            # NONE, and 0.0 risk. The 3x3 matrix reads a box grade and a
            # disturbance grade; neither exists without the correlate panels, so
            # any percentage here would be invented. The record carries no
            # position size because no position was authorised.
            risk_assessment={"box_grade": "NONE", "risk_pct": 0.0},
            # NO_ALIGNMENT is the schema's own word for it — there is no alignment
            # to grade, as distinct from an alignment that came out weak.
            block_reason="NO_ALIGNMENT",
            notes="; ".join(causes),
            flags=_tf_flags(signal_tf) or None,
        )
    except Exception as exc:  # noqa: BLE001 - a shadow may never reach the trader
        logger.warning("Shadow evaluation failed", pair=pair, error=str(exc))
        return None
