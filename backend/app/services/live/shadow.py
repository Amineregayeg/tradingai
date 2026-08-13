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

from datetime import datetime, timedelta, timezone
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
BLOCKED_ON_CORRELATES: dict[str, str] = {}
#: GATE-008 and GATE-002 left this dict on 2026-08-13 (T-0006). They are now evaluated
#: against real panel reads. The reason they carried — "TOTAL and USDT.D are unavailable
#: (CryptoCap not wired)" — had become false: we replaced CryptoCap with our own collector
#: and nothing updated the code still waiting for it.
#:
#: WHAT IS ACTUALLY MISSING NOW, because the answer changed rather than disappeared.
#: GATE-008's roster is four panels by NAME — BTCUSDT.P · ETHUSDT.P · TOTAL · USDT.D, and
#: `gate_008_roster.py:38-42` is deliberate that the first two are the Binance PERPETUALS,
#: "not spot". We have TOTAL and USDT.D from our own collector. We do NOT have the other
#: two: `BinanceSource` reaches only spot (`/api/v3/klines` on api.binance.com), and no
#: code in this repo calls `fapi.binance.com`.
#:
#: So the layout is read with two of four panels and **GATE-008 fails, naming the two that
#: are absent**. That is the honest steady state and it is a better one: the engine's
#: verdict stops being "I cannot see anything" and becomes "these two named feeds do not
#: exist", which is a one-line requirement rather than a research question.
#:
#: SPOT WAS NOT SUBSTITUTED FOR PERPETUAL, DELIBERATELY. Mapping BTC/USD onto BTCUSDT.P
#: would make GATE-008 emit PASS over a layout whose panels are instruments the rule does
#: not name, and that grade feeds GATE-002's 2-of-3 count, which keys the risk matrix. It
#: would be a plausible disturbance grade computed from the wrong instruments — and
#: KNOWN_ISSUES A3 measures venue divergence on this repo as large enough to create or
#: erase an FVG, so the distinction is consequential here rather than pedantic.

#: The panels this engine can actually source today, and where each comes from.
#: Keyed by the roster's canonical name so a panel can never be silently renamed into
#: existence — if the key is not the roster's, `LayoutReadability` counts it missing.
SOURCEABLE_PANELS: dict[str, str] = {"TOTAL": "TOTAL", "USDT.D": "USDT.D"}

#: The other two, from a different host and a different instrument family (T-0008).
#: Kept as a separate dict rather than merged, because they come from a separate source
#: on purpose: GATE-008 names the Binance PERPETUALS and `BinanceSource` serves spot.
#: Merging them would put "which market is this" back into a symbol string, which is the
#: one thing that cannot carry it — Binance names the perpetual `BTCUSDT` too.
PERPETUAL_PANELS: tuple[str, ...] = ("BTCUSDT.P", "ETHUSDT.P")


def _read_panels(
    signal_tf: str, *, source: Any = None, perp_source: Any = None
) -> tuple[dict, dict, list[str]]:
    """The roster panels we can source, as bars, on ONE timeframe.

    Returns `(panel_bars, sample_counts, notes)`. Never raises: a panel that cannot be
    read is simply absent, and `LayoutReadability` derives what is missing from the
    roster rather than from this dict (`gate_008_roster.py:189`), so an empty return
    degrades to "all four missing" rather than to a smaller layout.

    GATE-007 requires every panel on the same timeframe and fails otherwise
    (`AlignmentTimeframe.check_all`), so `signal_tf` is passed through unchanged rather
    than chosen here.
    """
    from app.services.market_data.sources.dominance import DominanceSource

    panel_bars: dict[str, list[Bar]] = {}
    sample_counts: dict[str, int | None] = {}
    notes: list[str] = []

    src = source if source is not None else DominanceSource()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)

    for roster_name, dominance_symbol in SOURCEABLE_PANELS.items():
        try:
            frame = src.fetch_ohlcv_with_samples(
                dominance_symbol, signal_tf, start, end, drop_partial=True
            )
            if frame.empty:
                notes.append(f"{roster_name}: no bars in the last 30d")
                continue
            panel_bars[roster_name] = [
                Bar(time=idx.to_pydatetime(), open=float(r.open), high=float(r.high),
                    low=float(r.low), close=float(r.close))
                for idx, r in frame.iterrows()
            ]
            # THE DECISION BAR'S COUNT, not the window's minimum.
            #
            # An earlier version used `.min()` over the whole 30-day window on the
            # reasoning that the thinnest bar should decide. It made GATE-007 fail with
            # `thin_panels: [TOTAL, USDT.D]` at 1H, where a complete bar holds 360
            # samples against a minimum of 20 — because the thinnest bar in the window is
            # the collector's own first partial hour from 2026-08-04, a boundary artefact
            # rather than a bar anyone would trade off. A mean would have been wrong for
            # the opposite reason; both answer a question GATE-007 is not asking.
            #
            # GATE-007 asks whether the layout is readable *for this confirmation*, so the
            # only bar whose thickness matters is the one being confirmed on — the last
            # complete bar, `drop_partial` having already removed the still-forming one.
            sample_counts[roster_name] = int(frame["samples"].iloc[-1])
        except Exception as exc:  # noqa: BLE001 - a shadow may never break the engine
            notes.append(f"{roster_name}: unreadable ({type(exc).__name__})")

    # -- the two perpetual panels, from the OTHER host ---------------------------
    # Separate source, separate failure mode: if fapi is unreachable these panels are
    # simply absent and GATE-008 fails naming them. Never a spot fallback — that is the
    # substitution `binance_perp` exists to make impossible — and never a raise, because
    # a shadow that can break the engine is worse than no shadow.
    #
    # `bar_sample_count` stays None for these. They are EXCHANGE bars, not resampled
    # point observations, so there is no sample count to carry and GATE-007's thinness
    # check does not apply — `LayoutReadability` skips panels whose count is None, which
    # is the correct distinction rather than a special case: a real candle is a candle.
    try:
        from app.services.market_data.sources.binance_perp import BinancePerpetualSource

        psrc = perp_source if perp_source is not None else BinancePerpetualSource()
        for roster_name in PERPETUAL_PANELS:
            frame, identity = psrc.fetch_with_identity(roster_name, signal_tf, start, end)
            if frame.empty:
                notes.append(f"{roster_name}: no bars from {identity.venue}")
                continue
            if identity.instrument_family != "PERPETUAL":
                # Refuse rather than accept the wrong market under the right name. This
                # is the runtime half of the mutation in test_binance_perp_identity.
                notes.append(
                    f"{roster_name}: source served {identity.instrument_family}, not "
                    f"PERPETUAL — panel refused rather than substituted"
                )
                continue
            panel_bars[roster_name] = [
                Bar(time=idx.to_pydatetime(), open=float(r.open), high=float(r.high),
                    low=float(r.low), close=float(r.close))
                for idx, r in frame.iterrows()
            ]
            sample_counts[roster_name] = None
            notes.append(
                f"{roster_name}: {len(frame)} bars from {identity.venue} "
                f"({identity.instrument_family}, symbol {identity.symbol_requested})"
            )
    except Exception as exc:  # noqa: BLE001 - never break the engine
        notes.append(f"perpetual panels unreadable ({type(exc).__name__})")

    return panel_bars, sample_counts, notes


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


def _correlates_block(grade: Any) -> dict:
    """The disturbance summary, from the grader when it ran and honestly empty when not.

    `layout_size` is the discriminator a reader should use: 0 means the layout was
    never graded, whatever `disturbance_grade` says. The schema has no value for
    "not read", so NONE is written on the ungraded path because something must be —
    but it is paired with a zero layout size rather than standing alone.
    """
    if grade is None:
        return {"layout_size": 0, "disturbed_count": 0, "disturbance_grade": "NONE",
                "states": [], "main_asset_counted": False}
    # `Disturbance.as_dict()` is the grader's own serialisation — used rather than
    # rebuilt, so this block cannot drift from what GATE-002 actually decided. An
    # earlier version of this helper reconstructed it from attribute names I had
    # guessed (`verdicts`, `states`); the real ones are `panels` and `layout_size`,
    # and guessing an interface instead of reading it is how the hardcoded literal
    # got here in the first place.
    d = grade.as_dict()
    return {
        "layout_size": d["layout_size"],
        "disturbed_count": d["disturbed_count"],
        "disturbance_grade": d["disturbance_grade"],
        "states": d["panels"],
        "main_asset_counted": d["main_asset_counted"],
    }


def _evaluate_layout(
    main_bars: Sequence[Bar], *, signal_tf: str, panel_source: Any = None,
    perp_source: Any = None, extra_panels: dict | None = None,
) -> tuple[list[rec.RuleEvaluation], list[str], Any]:
    """GATE-008, GATE-007 and GATE-002 against real panel reads.

    `extra_panels` exists for tests only — it lets a fixture stand in for the perpetual
    series we cannot source, so the wiring can be proven to emit PASS with four panels
    present. **That is legitimate in a test and would not be in production**: the whole
    point of reading two panels rather than four is that a fixture must never reach a
    record. Under route 3 a broken wiring and a missing feed emit the identical
    `GATE-008 FAIL, panels_missing: [BTCUSDT.P, ETHUSDT.P]`, so the PASS-with-four case
    is the only thing that distinguishes working plumbing from none at all.
    """
    from app.services.rules.evaluator import build_correlate_reads
    from app.services.rules.gate_002_disturbance import DisturbanceClassifier
    from app.services.rules.gate_008_roster import LayoutReadability

    causes: list[str] = []
    grade_obj = None
    try:
        panel_bars, sample_counts, notes = _read_panels(
            signal_tf, source=panel_source, perp_source=perp_source)
        if extra_panels:
            for asset, series in extra_panels.items():
                panel_bars[asset] = series
                sample_counts.setdefault(asset, None)
        causes.extend(notes)

        reads = build_correlate_reads(
            panel_bars, signal_tf=signal_tf, as_of_index=len(main_bars),
            sample_counts=sample_counts,
        )
        evaluations, layout_causes = LayoutReadability.evaluate(
            reads, signal_tf=signal_tf, instrument="BTC"
        )
        causes.extend(layout_causes)

        readable = all(e.verdict == "PASS" for e in evaluations)
        if readable:
            # Direction is the main panel's own order flow: the disturbance question is
            # whether the correlates agree with what the main asset is doing, so the
            # setup direction a main-asset break implies is the one to grade against.
            # Declared rather than inferred silently — there is no proposed setup to read
            # a direction from until M6 selects one.
            main = next((r for r in reads if r.asset == "BTCUSDT.P"), None)
            direction = "SHORT" if main and main.observed_order_flow == "BEARISH" else "LONG"
            grade_obj = grade = DisturbanceClassifier.classify(
                reads, direction=direction, instrument="BTC", main_asset_counts=False
            )
            evaluations.append(rec.RuleEvaluation(
                rule_id="GATE-002",
                verdict="PASS",
                values={"grade": getattr(grade, "grade", str(grade)),
                        "direction_graded": direction,
                        "panels_read": sorted(panel_bars)},
                value_provenance={
                    "grade": rec.derived("GATE-002 over the four-panel layout"),
                    "direction_graded": rec.derived("main panel observed order flow"),
                    "panels_read": rec.derived("panel reads actually obtained"),
                },
            ))
        else:
            missing = []
            for e in evaluations:
                if e.rule_id == "GATE-008":
                    missing = list(e.values.get("panels_missing") or [])
            reason = (
                f"layout unreadable: no read for {', '.join(missing)}" if missing
                else "layout unreadable: " + "; ".join(causes or ["reason not recorded"])
            )
            evaluations.append(rec.RuleEvaluation(
                rule_id="GATE-002",
                verdict="NOT_APPLICABLE",
                values={"not_evaluated_because": reason},
                value_provenance={"not_evaluated_because": rec.derived("GATE-008 result")},
            ))
        return evaluations, causes, grade_obj
    except Exception as exc:  # noqa: BLE001 - never break the engine
        logger.warning("shadow layout read failed", error=str(exc))
        return [rec.RuleEvaluation(
            rule_id="GATE-008",
            verdict="NOT_APPLICABLE",
            values={"not_evaluated_because": f"panel read raised {type(exc).__name__}"},
            value_provenance={"not_evaluated_because": rec.derived("engine fault")},
        )], [f"panel read raised {type(exc).__name__}"], None


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

        # -- GATE-008 / GATE-007 / GATE-002: the correlate layout, actually read ------
        # Wrapped separately from the outer try so a panel-read failure degrades this
        # section to "unreadable, and here is which panel" rather than killing the whole
        # record. A shadow that emits nothing teaches nothing.
        layout_evaluations, layout_causes, layout_grade = _evaluate_layout(
            bars, signal_tf=signal_tf)
        evaluations.extend(layout_evaluations)

        # A setup is "in play" only if the primitives produced something to judge.
        # This is what separates SKIP from STAND_ASIDE, and it is a fact about the
        # bars rather than a preference (GATE-036).
        setup_in_play = bool(imbalances) and bool(breaks)

        causes: list[str] = []
        if not imbalances:
            causes.append("no imbalance on this bar to enter from")
        if not breaks:
            causes.append("no structure break to trade with or against")
        causes.extend(layout_causes)

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
            # MEASURED WHEN THERE IS SOMETHING TO MEASURE, HARDCODED NEVER.
            #
            # This block used to be the literal {0, 0, "NONE", []}, and that was
            # defensible while the layout could not be read: the schema forces
            # `disturbance_grade` to NONE/LIGHT/HEAVY with no value for "never read",
            # so NONE was written because something had to be, and every neighbouring
            # field contradicted any reading of it as a measurement — layout_size 0,
            # states empty, GATE-008 and GATE-002 NOT_APPLICABLE.
            #
            # T-0006 and T-0008 removed every one of those safeguards. GATE-008 now
            # PASSes and GATE-002 grades four real panels, so a hardcoded NONE beside
            # them reads as measured — and a HEAVY layout, which GATE-001 turns into a
            # hard skip, would be recorded as NONE. That is exactly B13's shape: a
            # not-measured state rendering as a plausible number, and this time keying
            # something that matters.
            correlates=_correlates_block(layout_grade),
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
