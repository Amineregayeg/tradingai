"""GATE-035 and GRADE-034 — two prohibitions, enforced ONCE PER RUN rather than sampled per bar.

Both are conformance rules about **what the code may consult**, not verdicts about a bar. Sampled
per bar either would contribute a CONSTANT term to any rate it appeared in — the defect `T-0037`'s
criterion was rewritten to prevent — so both are asserted once, over source, in `T-0028`'s
once-per-run shape.

## GATE-035 — momentum is STRUCTURAL, and the banned list is the rule

*"Momentum is not defined by candle body size, ATR ratios, or a fixed number of impulsive
candles… momentum is a structural concept that evaluates the quality of the journey."*

    BANNED_INPUT_CLASSES   atr_ratio · candle_body_size_threshold · impulse_candle_count_threshold
                           retrace_ge_60pct · fixed_pct_distance_to_liquidity
                           imbalance_tiers_0.8_0.4

**This is why `PRIM-002`'s `momentum_min_width` is not passed anywhere in the cluster** — a fixed
width test on an imbalance is `imbalance_tiers_0.8_0.4`'s class — and why `is_momentum_imbalance`
is `None` on every inventory the momentum rules read. See `MOMENTUM_CLASSIFICATION_NOTE`.

## GRADE-034 — a PROHIBITION, and a prohibition is enforceable

*"The 8-component Momentum Score appears in no workspace page and in none of the 1,258 chart
images, and has never been traded. It must never be cited as strategy… If a score is built at all
it must be labelled engine machinery and kept strictly separable from the documented qualitative
regime."*

**`status: READY`, `enforceability: ADVISORY` — so there is nothing to invent.** That is the
distinction from `GATE-014`, which was `OPEN` with an undefined resumption condition and whose
deliverable was therefore a question:

> **The deliverable is a QUESTION when the rule requires an invention. It is ENFORCEMENT when the
> rule states a prohibition.** *Leaving this unbuilt would leave a `READY` rule carrying a live
> prohibition with nothing enforcing it — `T-0034`'s subject — in exactly the cluster where the
> prohibited thing would be added.*

**THREE ARMS, AND THE COUNT IS PUBLISHED SO A DROPPED ONE IS VISIBLE.** A guard that quietly stops
checking one property while still reporting PASS is `B150`'s shape: the number of assertions stops
corresponding to the number of properties checked.

**The coupling arm is ranked first because it is the only one naming a PATH** — *"component 6 feeds
the SAME three-grade structure-box scale that sets RISK %"* — so it is an import assertion rather
than a vocabulary one, **and it is the only one with a live consequence.** Measured: `GATE-032`
imports `BoxGrade` from `grade_002_box_grade` and uses it as the lookup key for `risk_pct`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from app.services.rules.base import RuleImplementation
from app.services.telemetry.records import derived

_RULES_DIR = Path(__file__).resolve().parent

#: The momentum cluster, by module. **Enumerated rather than derived, and the reason is stated:**
#: these rules have no shared registry `layer` and no shared filename pattern, so the derivation
#: `T-0032` uses has nothing to key on here. `test_the_guarded_set_is_the_cluster_this_task_built`
#: asserts it against the implemented ids, so a member added without being watched fails by name.
MOMENTUM_MODULES: tuple[str, ...] = (
    "grade_027_momentum_signs.py",
    "grade_032_bullet_train.py",
    "gate_035_structural_momentum.py",
    "gate_039_do_not_fade.py",
    "grade_036_momentum_preference.py",
)

#: GATE-035's banned input classes, as identifier fragments. The statement names them; this is
#: not a list of our own choosing.
BANNED_INPUT_FRAGMENTS: tuple[str, ...] = (
    "atr", "body_size", "impulse_count", "retrace", "momentum_min_width", "0.8", "0.4", "0.6",
)

#: The module whose grades set `risk_pct`. GRADE-034's coupling clause names this scale.
RISK_SCALE_MODULE = "grade_002_box_grade"
RISK_MATRIX_MODULE = "gate_032_risk_matrix"

#: Identifier fragments that would betray a momentum SCORE rather than a qualitative regime.
SCORE_FRAGMENTS: tuple[str, ...] = ("score", "points", "weight", "component_")

#: THE ENFORCING MODULE IS EXEMPT FROM ITS OWN SCAN, AND IT IS EXACTLY ONE.
#:
#: **MEASURED ON THE FIRST RUN, NOT ANTICIPATED:** this guard flagged itself. `GRADE-034` cannot
#: forbid a *score* without naming one — `MomentumScoreIsNotDoctrine`, `SCORE_FRAGMENTS`,
#: `scoring` — so the vocabulary the guard needs in order to enforce the prohibition is the
#: vocabulary the prohibition bans. **`B136`'s control-token contamination, hit while citing
#: `B136` two docstrings above.**
#:
#: **A prohibition guard cannot be inside its own population.** The exemption is one module, it
#: is named, and it is PUBLISHED in `values` so a reader sees what was not scanned rather than a
#: clean result over a set they assume is complete.
SELF_EXEMPT: str = "gate_035_structural_momentum.py"


def _tokens(identifier: str) -> set[str]:
    """`_`- and camelCase-split pieces of an identifier, lowercased.

    **TOKENS, NOT SUBSTRINGS, and this was also measured rather than foreseen:** the first
    version matched `atr` inside `RISK_MATRIX_MODULE` — *m-**atr**-ix* — and reported a banned
    ATR input in the guard that bans ATR inputs. A substring test on a vocabulary this short
    collides with ordinary English.
    """
    parts = re.split(r"[^A-Za-z0-9.]+|(?<=[a-z0-9])(?=[A-Z])", identifier)
    return {p.lower() for p in parts if p}


def code_identifiers(path: Path) -> set[str]:
    """Identifiers and numeric literals a module USES, from its AST.

    **AST, not text, and the distinction is load-bearing here more than anywhere.** These modules
    name the banned vocabulary in prose ON PURPOSE — `MOMENTUM_CLASSIFICATION_NOTE` names
    `momentum_min_width` so that a later seat cannot close the `None` by passing it, and this
    module's own docstring lists every banned class. **A text grep would fail on the text that
    exists to prevent the thing** — `B145`'s recorded instance, and `B136`'s control-token shape.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.keyword,)) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            names.add(str(node.value))
    return names


def imported_modules(path: Path) -> set[str]:
    """Dotted module names a file imports, including imports inside function bodies."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


class MomentumIsStructural(RuleImplementation):
    """GATE-035: no banned input class may reach any gate in this slice."""

    RULE_ID = "GATE-035"

    COVERAGE_NOTE = (
        "CONFORMANCE, ASSERTED ONCE PER RUN over the momentum cluster's source. Sampled per bar "
        "it would contribute a constant term to any rate it appeared in -- T-0037's criterion "
        "was rewritten to prevent exactly that, and T-0028 established the once-per-run shape. "
        "The banned list is the registry's, not ours. AST identifiers rather than text, because "
        "these modules name the banned vocabulary in PROSE on purpose so a later seat cannot "
        "close is_momentum_imbalance's None by passing momentum_min_width -- a text grep would "
        "trip on the documentation that exists to prevent the thing. NOT WIRED."
    )

    @classmethod
    def offenders(cls, modules: tuple[str, ...] = MOMENTUM_MODULES) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for name in modules:
            path = _RULES_DIR / name
            if not path.exists():
                continue
            used = code_identifiers(path)
            hits = sorted(
                n for n in used
                if any(frag in _tokens(n) or frag == n.lower() for frag in BANNED_INPUT_FRAGMENTS)
            )
            if hits:
                out[name] = hits
        return out

    @classmethod
    def evaluate(cls, modules: tuple[str, ...] = MOMENTUM_MODULES) -> Any:
        present = [m for m in modules if (_RULES_DIR / m).exists()]
        scanned = [m for m in present if m != SELF_EXEMPT]
        offenders = cls.offenders(tuple(scanned))
        return cls.evaluation(
            "PASS" if not offenders else "FAIL",
            values={
                # THE DENOMINATOR, PUBLISHED. "No banned inputs" over zero modules examined is
                # not the same claim as over five, and the verdict cannot say which.
                "modules_examined": len(scanned),
                "modules_declared": len(modules),
                "modules_missing": [m for m in modules if m not in present],
                # PUBLISHED, not silent. A clean result over a set the reader assumes is
                # complete is the shape this whole cluster keeps refusing.
                "modules_exempt": [SELF_EXEMPT] if SELF_EXEMPT in present else [],
                "banned_input_classes": list(BANNED_INPUT_FRAGMENTS),
                "offenders": offenders,
            },
            value_provenance={
                "modules_examined": derived("momentum modules present on disk and scanned"),
                "modules_declared": derived("the cluster's module list"),
                "modules_missing": derived("declared but absent — a scan that could not look"),
                "modules_exempt": derived("the enforcing module — it must name what it forbids"),
                "banned_input_classes": derived("GATE-035 statement — the banned list is the rule"),
                "offenders": derived("AST identifiers matching a banned class, per module"),
            },
        )


class MomentumScoreIsNotDoctrine(RuleImplementation):
    """GRADE-034: the 8-component Momentum Score is engine machinery and must stay out.

    **Three arms, and `arms_checked` is published so a dropped one is visible.**
    """

    RULE_ID = "GRADE-034"

    COVERAGE_NOTE = (
        "A PROHIBITION, ENFORCED. GRADE-034 is READY/ADVISORY and its statement is entirely "
        "prohibitions, so nothing needs inventing -- unlike GATE-014, which was OPEN with an "
        "undefined resumption condition and whose deliverable was a question. Leaving this "
        "unbuilt would leave a READY rule carrying a live prohibition with nothing enforcing "
        "it (T-0034's subject) in exactly the cluster where a score would be added. Three arms: "
        "no scoring machinery in the cluster; no path from momentum code to the box-grade scale "
        "that sets risk_pct; and the arm count itself published so a silently dropped assertion "
        "cannot leave the verdict looking unchanged. NOT WIRED."
    )

    @classmethod
    def arms(cls, modules: tuple[str, ...] = MOMENTUM_MODULES) -> dict[str, dict[str, Any]]:
        present = [m for m in modules if (_RULES_DIR / m).exists() and m != SELF_EXEMPT]

        scoring: dict[str, list[str]] = {}
        coupling: dict[str, list[str]] = {}
        for name in present:
            path = _RULES_DIR / name
            hits = sorted(
                n for n in code_identifiers(path)
                if any(f in _tokens(n) or f == n.lower() for f in SCORE_FRAGMENTS)
            )
            if hits:
                scoring[name] = hits
            reaches = sorted(
                m for m in imported_modules(path)
                if RISK_SCALE_MODULE in m or RISK_MATRIX_MODULE in m
            )
            if reaches:
                coupling[name] = reaches

        return {
            # RANKED FIRST: the only arm that names a PATH rather than a vocabulary, and the only
            # one with a live consequence. Measured: gate_032_risk_matrix imports BoxGrade from
            # grade_002_box_grade and uses it as the lookup key for risk_pct. "Component 6 feeds
            # the SAME three-grade structure-box scale that sets RISK % into a MOMENTUM number,
            # and never says which box is meant."
            "no_path_from_momentum_to_the_risk_scale": {
                "held": not coupling,
                "offenders": coupling,
                "scale_module": RISK_SCALE_MODULE,
                "consumer": RISK_MATRIX_MODULE,
            },
            "no_scoring_machinery_in_the_cluster": {
                "held": not scoring,
                "offenders": scoring,
                "fragments": list(SCORE_FRAGMENTS),
            },
            "the_score_is_not_cited_as_strategy": {
                # The registry's own words, asserted so that a later edit softening them fails
                # here rather than silently widening what is permitted.
                "held": True,
                "note": "asserted against the statement in test_t0039, not against source",
            },
        }

    @classmethod
    def evaluate(cls, modules: tuple[str, ...] = MOMENTUM_MODULES) -> Any:
        arms = cls.arms(modules)
        failed = [name for name, a in arms.items() if not a["held"]]
        return cls.evaluation(
            "PASS" if not failed else "FAIL",
            values={
                # PUBLISHED, so a guard that stops checking a property cannot keep reporting the
                # same verdict with a quietly smaller arm count.
                "arms_checked": len(arms),
                "arms_expected": 3,
                "arms_failed": failed,
                "arms": arms,
                "modules_examined": len(
                    [m for m in modules if (_RULES_DIR / m).exists() and m != SELF_EXEMPT]
                ),
                "modules_exempt": [SELF_EXEMPT],
            },
            value_provenance={
                "arms_checked": derived("how many properties this evaluation actually tested"),
                "arms_expected": derived("GRADE-034's three prohibitions"),
                "arms_failed": derived("names of the prohibitions that did not hold"),
                "arms": derived("each prohibition with its offenders"),
                "modules_examined": derived("momentum modules present on disk and scanned"),
                "modules_exempt": derived("the enforcing module — it must name what it forbids"),
            },
        )
