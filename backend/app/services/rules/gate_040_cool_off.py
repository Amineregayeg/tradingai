"""GATE-040 — a sweep alone never authorises a reversal; a cool-off is a prerequisite.

    "A liquidity sweep alone never authorises a reversal: a cool-off — a slowdown in
    momentum, consolidation, a range — is a prerequisite."
    output: cool_off{satisfied, elapsed_duration, consolidation_evidence}

GRADE-035 IS AN ALIAS OF THIS RULE, AND THE ALIAS IS WHY THIS MODULE IS CAREFUL
`base.py` refuses a class claiming an alias id directly, so GATE-040 is the only
implementable id and GRADE-035 is registered automatically. **But the pair declares
DIFFERENT inputs**, so registering this rule marks GRADE-035 covered while some of its
declared dependencies do not exist. The union is recorded per input below rather than
assumed satisfied — this is the one place where "the alias is free" would otherwise buy
coverage without work.

THE TWO DURATIONS ARE UNOPPOSED, NOT RATIFIED
The statement quotes *"around 2 days"* and *"around 24H"*, and the registry says both that
they are *"observations from worked examples, not a stated threshold — DO NOT HARDEN THEM
INTO A RULE WITHOUT A RULING"* and that the canon *"does not retire them, it OMITS them, so
24H / ~2 days STAND UNOPPOSED as the only quantities the corpus has."*

Both bind. So `if elapsed >= timedelta(hours=24)` is forbidden — it is exactly what an
implementer reading only the statement writes, because the number is in quotation marks —
and pretending no quantity exists is equally wrong. **A declared parameter citing the
workspace observation, stamped ours and unratified, is the honest third option**, and
`cool_off_elapsed` is emitted as an OUTPUT whether or not it is compared to anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.services.rules.base import (
    ConditionReading,
    RuleImplementation,
    quorum_blocked,
)
from app.services.rules.consolidation import (
    DECLARED_THRESHOLD,
    ConsolidationWindow,
)
from app.services.telemetry.records import RuleEvaluation, derived, from_record

#: The default when the cool-off cannot be established. FORWARD, not REVERSE: the whole
#: statement is that a sweep alone does NOT authorise a reversal, so an unreadable
#: prerequisite must leave the mode where it was.
FORWARD = "FORWARD"
REVERSE = "REVERSE"


@dataclass(frozen=True)
class DeclaredDuration:
    """A cool-off duration that carries its provenance and its unratified status.

    Separate from GRADE-031's `DeclaredQuorum` on purpose: that carrier is GRADE-031's own
    CONTENT — it is the declared-parameter rule — while this is a duration belonging to
    GATE-040. Sharing the type would dissolve one rule's substance into another's.
    """

    name: str
    value: timedelta
    source: str
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        return {
            self.name: int(self.value.total_seconds()),
            f"{self.name}_source": self.source,
            f"{self.name}_ratified": self.ratified,
        }


#: OURS. Cited from the corpus, never hardened into a comparison by default.
DECLARED_COOL_OFF = DeclaredDuration(
    name="cool_off_min_seconds",
    value=timedelta(hours=24),
    source=(
        "workspace worked examples quote 'around 24H' and 'around 2 days'. The canon OMITS "
        "them rather than retiring them, so they stand UNOPPOSED as the only quantities the "
        "corpus offers — unopposed is not ratified. Used only when explicitly enabled."
    ),
)

#: The UNION of both declared input lists, with the producer for each — or None where none
#: exists. GATE-040's three come first, then GRADE-035's four.
INPUT_UNION: tuple[tuple[str, str | None], ...] = (
    # -- GATE-040's declared inputs -------------------------------------------------
    ("time_since_sweep", "engine clock + PRIM-004 sweeps"),
    ("structure_since_sweep", "PRIM-005"),
    ("seven_confirmation_conditions", "GATE-041"),
    ("htf_directional_bias", "fixed_config.BIAS_TF"),
    # -- GRADE-035's declared inputs, which the alias does NOT inherit ---------------
    ("price_action_since_sweep", "PRIM-001"),
    # EXISTS as of T-0014 part 1 — this is the input that had no producer at all.
    ("consolidation_detector", "rules/consolidation.py"),
    ("absence_of_fresh_old_direction_gaps", "PRIM-002"),
    # NO PRODUCER ANYWHERE. `ny_time.py` is conversion helpers only — NY, to_ny, iso_ny,
    # tz_offset_used, now_ny. Deriving 09:30 from the clock here would invent a session
    # boundary the codebase does not have.
    ("ny_930_open_marker", None),
)

#: Momentum slowdown — one of the three cool-off forms the statement names. GRADE-028 is
#: SOFT_PREFERENCE and unimplemented, so this form is unreadable and no proxy is built.
MOMENTUM_PRODUCER = None


class CoolOffBeforeReversal(RuleImplementation):
    """GATE-040 (alias GRADE-035): no reversal without a cool-off."""

    RULE_ID = "GATE-040"

    #: PROXIMATE, not root-cause. GATE-040 consumes GATE-041's seven confirmation
    #: conditions, and GATE-041 is what cannot reach a verdict. Declaring ("GRADE-028",)
    #: here — as this rule originally did — is a claim about ANOTHER rule's dependency:
    #: true today only because both block on the same producer, and silently false the
    #: day GATE-041 blocks on something else, while still looking maintained. Nothing
    #: local could catch that. `check_rule_coverage.resolve_block_chain` now follows the
    #: graph, so the proximate form is the checkable one and the root cause is COMPUTED:
    #: GATE-040 <- GATE-041 <- GRADE-028.
    CANNOT_FIRE_WITHOUT = ("GATE-041",)

    COVERAGE_NOTE = (
        "REGISTERS GRADE-035 BY ALIAS WHILE NOT ALL OF ITS DECLARED INPUTS EXIST, and that "
        "is reported per input rather than assumed. Of the union of the two lists: the "
        "consolidation detector now EXISTS (T-0014 part 1, ours and unratified); "
        "`absence_of_fresh_old_direction_gaps` has a producer (PRIM-002 carries direction "
        "and bar_time) that nothing wires, so it reads NOT_READ; and the NY 09:30 open "
        "marker has NO producer anywhere — ny_time.py is conversion helpers only — so it "
        "reads NOT_EVALUABLE. The momentum-slowdown cool-off form needs GRADE-028, which "
        "is SOFT_PREFERENCE and outside this programme. The two durations ('around 24H', "
        "'around 2 days') are UNOPPOSED, NOT RATIFIED: they are carried as a declared "
        "parameter and are NOT compared by default."
    )

    @classmethod
    def evaluate(
        cls,
        *,
        consolidation: ConsolidationWindow | None = None,
        elapsed_since_sweep: timedelta | None = None,
        enforce_duration: bool = False,
        readings: list[ConditionReading] | None = None,
    ) -> RuleEvaluation:
        """Decide whether a cool-off is established.

        `enforce_duration` defaults to FALSE. Comparing against the declared 24H by default
        would harden a quotation into a rule, which both registry entries forbid; the
        elapsed time is emitted as an output regardless, which is what the statement's
        `cool_off{elapsed_duration}` actually asks for.
        """
        # `readings` exists ONLY so a fixture can reach the satisfied path. Live, the NY
        # 09:30 marker has no producer, so this rule can never leave NOT_APPLICABLE — and
        # a rule whose PASS branch is unreachable even in a test is indistinguishable from
        # one that is broken. Criterion 7's mutation needs a door; this is it.
        if readings is not None:
            return cls._decide(
                readings, consolidation, elapsed_since_sweep, enforce_duration
            )
        readings = []
        for name, producer in INPUT_UNION:
            if producer is None:
                readings.append(
                    ConditionReading(
                        name, "NOT_EVALUABLE",
                        missing_producer="no producer exists anywhere under app/",
                    )
                )
            elif name == "consolidation_detector":
                # The one input this task built. TRUE/FALSE is honest here because the
                # detector was actually run — when a window was supplied.
                if consolidation is None:
                    readings.append(
                        ConditionReading(name, "NOT_READ", unread_producer=producer)
                    )
                else:
                    readings.append(
                        ConditionReading(
                            name, "TRUE" if consolidation.is_consolidation else "FALSE"
                        )
                    )
            else:
                # A producer exists and nothing wires it. NOT FALSE — that would assert
                # the producer ran and found nothing.
                readings.append(
                    ConditionReading(name, "NOT_READ", unread_producer=producer)
                )

        # The momentum-slowdown form, recorded separately because it is a cool-off FORM
        # rather than one of the declared inputs.
        readings.append(
            ConditionReading(
                "momentum_slowdown", "NOT_EVALUABLE",
                missing_producer="GRADE-028 (SOFT_PREFERENCE, unimplemented)",
            )
        )

        return cls._decide(
            readings, consolidation, elapsed_since_sweep, enforce_duration
        )

    @classmethod
    def _decide(
        cls,
        readings: list[ConditionReading],
        consolidation: ConsolidationWindow | None,
        elapsed_since_sweep: timedelta | None,
        enforce_duration: bool,
    ) -> RuleEvaluation:
        elapsed_s = (
            int(elapsed_since_sweep.total_seconds())
            if elapsed_since_sweep is not None
            else None
        )
        values: dict[str, Any] = {
            "inputs": {r.name: r.state for r in readings},
            "cool_off_elapsed_seconds": elapsed_s,
            "consolidation_evidence": (
                {
                    "is_consolidation": consolidation.is_consolidation,
                    "price_high": consolidation.price_high,
                    "price_low": consolidation.price_low,
                    "span_over_avg_bar_range": round(consolidation.ratio, 3),
                    "k_used": consolidation.k_used,
                    "k_ratified": DECLARED_THRESHOLD.ratified,
                }
                if consolidation is not None
                else None
            ),
            "duration_enforced": enforce_duration,
            **DECLARED_COOL_OFF.as_values(),
        }
        provenance: dict[str, Any] = {
            "inputs": derived("union of GATE-040 and GRADE-035 declared input lists"),
            "cool_off_elapsed_seconds": from_record("primitives.sweeps"),
            "consolidation_evidence": derived(
                f"rules/consolidation.py k={DECLARED_THRESHOLD.k} — OURS, unratified"
            ),
            **{
                k: derived("GATE-040 declared duration — OURS, unratified")
                for k in DECLARED_COOL_OFF.as_values()
            },
        }

        blocked = quorum_blocked(readings, default_outcome=FORWARD)
        if blocked is not None:
            unreadable, default_mode = blocked
            values["unreadable_inputs"] = unreadable
            values["not_evaluable"] = {
                r.name: r.missing_producer
                for r in readings
                if r.state == "NOT_EVALUABLE"
            }
            values["not_read"] = {
                r.name: r.unread_producer for r in readings if r.state == "NOT_READ"
            }
            values["cool_off"] = {
                "satisfied": False,
                "elapsed_duration": elapsed_s,
                "consolidation_evidence": values["consolidation_evidence"],
                # WHY satisfied IS FALSE. Without this, a blocked GATE-040 and a working
                # GATE-040 on a trending market emit an IDENTICAL record: both FORWARD,
                # both satisfied=False. The verdict differs (NOT_APPLICABLE vs FAIL) but
                # that makes the reader infer the distinction from a convention instead
                # of reading it. Both defaults point the same way, so the record has to
                # say which case produced the mode.
                "determination": "NOT_EVALUATED_BLOCKED",
            }
            values["mode"] = default_mode
            provenance["unreadable_inputs"] = derived("inputs with no producer or unwired")
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance
            )

        # Reachable only once every input has a producer AND is wired.
        duration_ok = (
            elapsed_since_sweep is not None
            and elapsed_since_sweep >= DECLARED_COOL_OFF.value
        ) if enforce_duration else True
        satisfied = bool(
            consolidation is not None and consolidation.is_consolidation and duration_ok
        )
        values["cool_off"] = {
            "satisfied": satisfied,
            "elapsed_duration": elapsed_s,
            "consolidation_evidence": values["consolidation_evidence"],
            "determination": "EVALUATED",
        }
        values["mode"] = REVERSE if satisfied else FORWARD
        return cls.evaluation(
            "PASS" if satisfied else "FAIL", values=values, value_provenance=provenance
        )
