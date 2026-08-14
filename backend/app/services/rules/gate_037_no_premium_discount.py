"""GATE-037 — premium/discount and OTE MUST NOT gate a trade (T-0019).

The registry entry:

    Negative gate. "The bot should not use a premium/discount (equilibrium or OTE) entry
    filter. Although I understand the concepts, they are not part of my entry criteria… The
    engine should therefore ignore premium/discount or OTE as an entry condition… it should
    not influence whether a trade is taken or rejected. It is neither a required
    confirmation nor a filtering criterion." The geometry survives as READING VOCABULARY
    only. Conformance test: no accept/reject decision record may cite premium, discount,
    equilibrium, or OTE.
    inputs: n/a — a negative constraint on the decision record.
    output: conformance assertion pass/fail, via rule_evaluation.banned_input_check and the
    HG-16 key regex. The geometry may be RECORDED (primitives.ranges) as reading vocabulary;
    it may never appear on an accept/reject path.

RECORDED IS NOT THE SAME AS DECIDING, AND THAT DISTINCTION IS THE ENTIRE RULE
The statement explicitly PERMITS the geometry to be recorded and forbids it from influencing
the outcome. So a check that fails on the mere presence of the token would forbid the reading
vocabulary this rule exists to protect — it would enforce the opposite of the doctrine while
looking strict. This rule therefore scans the DECISION PATH and leaves `primitives.ranges`
alone, and both directions are mutated in the tests: an OTE value recorded -> PASS, the same
value routed into an accept/reject -> FAIL.

THIS IS A SECOND CONSUMER OF AN EXISTING MECHANISM, NOT A NEW ONE
`banned_input_check` already exists (`gate_002_disturbance.py:314` and `:396`, wired at
`evaluator.py:386`) and this rule reuses its shape: `{checked: [...], present: [...]}`. A
second mechanism doing the same job is how two conformance surfaces drift.

THE TOKEN LIST IS THE RULE, SO IT IS PRINTED RATHER THAN IMPLIED
"Premium/discount", "equilibrium" and "OTE" are three vocabularies for one prohibited
concept, and a check covering two of the three passes while the third walks through. The
checked list travels on every record — B33's shape, and this rule is made entirely of
vocabulary.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from app.services.rules.base import RuleImplementation
from app.services.telemetry.records import RuleEvaluation, derived

#: The three vocabularies, enumerated. Every token this rule can catch is here — nothing is
#: matched by a cleverness that the record cannot report.
BANNED_TOKENS: tuple[str, ...] = (
    "premium",
    "discount",
    "equilibrium",
    "ote",
    # The abbreviations the workspace uses for the same geometry. Listed explicitly rather
    # than pattern-matched, so `checked` is the truth about what was looked for.
    "optimal_trade_entry",
    "eq_level",
)

#: Word-boundary matching on a normalised key. `ote` must not fire on `quote` or `note`, and
#: `premium` must fire on `premium_discount_zone`. Both are asserted in the tests.
_TOKEN_RE = re.compile(
    r"(?:^|[^a-z0-9])(" + "|".join(re.escape(t) for t in BANNED_TOKENS) + r")(?:[^a-z0-9]|$)"
)

#: Where the geometry IS allowed to appear. The statement names `primitives.ranges` as
#: reading vocabulary, so a path under it is exempt BY NAME rather than by a predicate.
RECORDING_ONLY_PATHS = ("primitives.ranges",)


def _walk(node: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    """Every (dotted path, value) in a nested record, keys and scalars alike."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            yield child, value
            yield from _walk(value, child)
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            child = f"{path}[{i}]"
            yield child, value
            yield from _walk(value, child)


def _hits(text: str) -> list[str]:
    return sorted({m.group(1) for m in _TOKEN_RE.finditer(text.lower())})


def _is_recording_only(path: str) -> bool:
    return any(
        path == allowed or path.startswith(allowed + ".") or path.startswith(allowed + "[")
        for allowed in RECORDING_ONLY_PATHS
    )


class NoPremiumDiscountOrOTEFilter(RuleImplementation):
    """GATE-037: the geometry may be recorded; it may never decide."""

    RULE_ID = "GATE-037"

    #: The same shape as GATE-002/GATE-005's, deliberately — one conformance vocabulary.
    BANNED = BANNED_TOKENS

    COVERAGE_NOTE = (
        "Scans the DECISION PATH of a record and deliberately exempts `primitives.ranges`, "
        "because the statement permits the geometry to be RECORDED as reading vocabulary "
        "while forbidding it from influencing the outcome — a check failing on mere "
        "presence would enforce the opposite of the doctrine while looking stricter. The "
        "checked token list is printed on every record: premium/discount, equilibrium and "
        "OTE are three vocabularies for one concept and a regex covering two of three "
        "passes while the third walks through."
    )

    @classmethod
    def banned_input_check(cls, present: Sequence[str] = ()) -> dict[str, Any]:
        """The existing mechanism's shape, so both conformance surfaces read alike."""
        return {"checked": list(cls.BANNED), "present": list(present)}

    #: The record sections that constitute an accept/reject path.
    #:
    #: KEYED TO THE LIVE VOCABULARY, NOT INVENTED. `decision` and `deciding_rule_id` are real
    #: `TelemetryRecord` columns and are what a trade actually passes through (T-0013);
    #: `entry` and `rule_evaluations` are payload sections that appear in TELEMETRY_SCHEMA.
    #:
    #: AN EARLIER VERSION NAMED `gates`, WHICH EXISTS NOWHERE — zero hits in the schema and
    #: zero in the model. **A named path that cannot match is indistinguishable from a path
    #: that is clean**, so the check advertised four sections and could only ever scan three,
    #: silently. That is this register's opening sentence appearing inside the check whose
    #: entire subject is a prohibited input reaching a decision. Found by the Manager against
    #: the schema and the model, before it landed.
    DECISION_PATHS: tuple[str, ...] = (
        "decision",
        "deciding_rule_id",
        "entry",
        "rule_evaluations",
    )

    @classmethod
    def evaluate(
        cls,
        decision_record: Mapping[str, Any] | None = None,
        *,
        decision_paths: Sequence[str] | None = None,
    ) -> RuleEvaluation:
        """PASS when no banned token appears on an accept/reject path.

        FAIL, NOT NOT_APPLICABLE, when a record is absent: this rule's `inputs` are `n/a`, so
        there is nothing that can be missing. An empty record has no violation in it, which
        is a PASS about an empty record and is reported with `paths_examined 0` so nobody
        reads it as a clean audit of a real decision.
        """
        record = decision_record or {}
        decision_paths = tuple(
            decision_paths if decision_paths is not None else cls.DECISION_PATHS
        )
        violations: list[dict[str, str]] = []
        recorded_only: list[str] = []
        examined = 0

        # THE DENOMINATOR DISCIPLINE, APPLIED TO PATH NAMES. A section this record does not
        # have is reported as not-scanned rather than counted as scanned-and-clean, so a
        # typo or a schema rename reduces coverage LOUDLY. Without this the check can only
        # ever say how many places it looked, never how many it meant to.
        all_paths = {p for p, _ in _walk(record)}
        paths_present = [
            p for p in decision_paths
            if p in all_paths or any(q.startswith(p + ".") or q.startswith(p + "[") for q in all_paths)
        ]
        paths_absent = [p for p in decision_paths if p not in paths_present]

        for path, value in _walk(record):
            on_decision_path = any(
                path == p or path.startswith(p + ".") or path.startswith(p + "[")
                for p in decision_paths
            )
            text = f"{path} {value}" if isinstance(value, (str, int, float, bool)) else path
            found = _hits(text)
            if not found:
                continue
            if _is_recording_only(path):
                recorded_only.append(path)
                continue
            if on_decision_path:
                examined += 1
                violations.append({"path": path, "tokens": ", ".join(found)})

        present = sorted({t for v in violations for t in v["tokens"].split(", ")})
        values: dict[str, Any] = {
            "banned_input_check": cls.banned_input_check(present),
            "violations": violations,
            # THE PERMITTED HALF, REPORTED. Without it a PASS cannot distinguish "the
            # geometry was recorded and correctly ignored" from "the geometry was never
            # computed" — and the first is the doctrine working.
            "recorded_but_not_deciding": sorted(recorded_only),
            "decision_paths_named": list(decision_paths),
            "decision_paths_scanned": paths_present,
            # NAMED BUT NOT PRESENT IN THIS RECORD. Reported rather than skipped: a section
            # that cannot match looks exactly like a section that is clean.
            "decision_paths_not_present": paths_absent,
            "decision_path_coverage": f"{len(paths_present)} of {len(decision_paths)} named",
            "recording_only_paths_exempt": list(RECORDING_ONLY_PATHS),
            "paths_examined": len(list(_walk(record))),
            "violating_paths": examined,
        }
        provenance: dict[str, Any] = {
            "banned_input_check": derived(
                "GATE-037 statement — premium/discount, equilibrium, OTE"
            ),
            "violations": derived("banned tokens found on an accept/reject path"),
            "recorded_but_not_deciding": derived(
                "banned tokens under primitives.ranges — permitted reading vocabulary"
            ),
            "decision_paths_named": derived(
                "TelemetryRecord columns `decision`/`deciding_rule_id` plus the payload "
                "sections TELEMETRY_SCHEMA carries"
            ),
            "decision_paths_scanned": derived("named paths actually present in this record"),
            "decision_paths_not_present": derived(
                "named paths absent from this record — NOT scanned, and not clean either"
            ),
            "decision_path_coverage": derived("scanned / named"),
            "recording_only_paths_exempt": derived(
                "GATE-037 output — 'the geometry may be RECORDED (primitives.ranges)'"
            ),
            "paths_examined": derived("count of (path, value) pairs walked in the record"),
            "violating_paths": derived("count of decision-path locations carrying a token"),
        }
        return cls.evaluation(
            "FAIL" if violations else "PASS",
            values=values,
            value_provenance=provenance,
        )
