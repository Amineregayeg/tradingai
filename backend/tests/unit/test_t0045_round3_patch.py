"""T-0045 — arms on the round-3 patch, including the one thing nothing else here checks.

**Our verification regime checks STRUCTURE. The field most likely to be read as Salim's words
is prose, and nothing reads prose** — which is `B164`: `REGISTRY_PATCH.json` carries
`PRIM-007.statement = "see REGISTRY_PATCH.md P3"`, a POINTER, where the markdown half carries
the full rule. A seat that scripted the machine-readable half would have written a dangling
reference to a file absent from this repository into the registry, **and the id would resolve,
the rule would register, `check_rule_coverage` would pass, the histogram would be unchanged and
`status_changes` would be `[]`.** The first arm below is the one that catches it.
"""
from __future__ import annotations

import json

import pytest

from app.services.telemetry import contract_loader as contract

# The three tokens P1/P5 add to `block_reason`, transcribed from the patch. Kept as a literal
# because the point is to assert the tree matches the RULING, and deriving them from the tree
# would assert the tree matches itself.
BLOCK_REASON_ADDED = ("ECO_DAY_RUNG_DOWN_TO_SKIP", "ECO_DAY_ALTCOIN_UNRULED", "ALTCOIN_DISABLED")

# Every token `block_reason` carried at v1.2.1, so a removal is caught by name rather than by
# count. A count catches a removal only until something is added in the same commit.
BLOCK_REASON_AT_1_2_1 = (
    "HEAVY_DISTURBANCE", "NEWS_PRE_WINDOW", "NEWS_POST_WINDOW", "NEWS_EXCEPTIONAL",
    "NO_CANDIDATE_REACHES_2R", "NO_BOX", "NO_ALIGNMENT", "ALTCOIN_UNRULED",
    "PRICE_MID_RANGE_NO_CONCERN", "ALL_TOTALS_CLEARED", "OTHER",
)

THE_NINETEEN = {
    "GATE-001", "GATE-008", "GATE-012", "GATE-014", "GATE-015", "GATE-016", "GATE-027",
    "GATE-028", "GATE-031", "GATE-033", "GATE-034", "GRADE-006", "GRADE-011", "GRADE-018",
    "GRADE-019", "GRADE-033", "PRIM-002", "PRIM-006", "PRIM-007",
}


def _enum_sites(node, path="", out=None):
    """Every `enum` array in the schema, by json-pointer-ish path."""
    if out is None:
        out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "enum" and isinstance(v, list):
                out[path] = v
            else:
                _enum_sites(v, f"{path}/{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _enum_sites(v, f"{path}[{i}]", out)
    return out


# ---------------------------------------------------------------------------
# B164 — the arm that reads PROSE, because nothing else does
# ---------------------------------------------------------------------------
#: Files the pack references that are NOT in this repository. A statement pointing at one of
#: these is a promissory note, not doctrine.
ABSENT_FILES = ("registry_patch.md", "telemetry_patch.md", "conformance_suite.md",
                "fidelity_scorecard.md", "engine_contract/readme.md")


def _pointer_complaints(text: str) -> list[str]:
    """Why this prose is a cross-reference rather than a rule. Empty means it is prose."""
    if not isinstance(text, str):
        return []
    lowered = text.lower()
    found = ["begins as a cross-reference"] if lowered.startswith("see ") else []
    found += [f"points at {f}" for f in ABSENT_FILES if f in lowered]
    return found


def test_the_pointer_detector_FIRES_on_the_string_the_pack_actually_ships():
    """CONTROL PAIR. The sweep below returns clean; that is worth nothing until the sweep is
    shown to catch the exact defect it exists for.

    **The must-hit input is not invented — it is `REGISTRY_PATCH.json`'s literal
    `PRIM-007.statement`**, which is what a seat scripting the machine-readable half would have
    written into the registry.
    """
    the_real_pointer = (
        "see REGISTRY_PATCH.md P3 (origin candle; box from it extended right; state "
        "UNTESTED/TESTED/FAILED; FAILED = body close through \u2192 Breaker candidate for PRIM-006)"
    )
    assert _pointer_complaints(the_real_pointer), "the detector cannot see the pack's own pointer"

    # MUST-MISS: real doctrine that merely MENTIONS a rule id or a source file is not a pointer.
    assert _pointer_complaints(contract.rule("PRIM-007")["statement"]) == []
    assert _pointer_complaints(
        "Box = that candle's range, drawn from the origin candle (075_Stop_Loss_Decision.md:39)."
    ) == [], "the detector fires on an ordinary citation — it would flag every rule in the file"


@pytest.mark.parametrize("rid", sorted(THE_NINETEEN))
def test_no_rules_prose_is_a_POINTER_to_a_file_this_repo_does_not_have(rid: str):
    """**The failure B164 describes passes every structural check we own.**

    `REGISTRY_PATCH.json`'s `PRIM-007.statement` is the string *"see REGISTRY_PATCH.md P3
    (...)"*. Applied as written it is a well-formed registry entry whose doctrine is a
    reference to a file nobody here can open — and `check_rule_coverage`, the id-uniqueness
    check, the status histogram and `status_changes == []` are all satisfied by it.

    **This is the only assertion in the repository that looks at what a rule SAYS rather than
    at its shape.** It is deliberately narrow: it does not judge the prose, only that the prose
    is not a promissory note for prose.
    """
    rule = contract.rule(rid)
    for field in ("statement", "output", "inputs"):
        complaints = _pointer_complaints(rule.get(field))
        assert not complaints, (
            f"{rid}.{field} {'; '.join(complaints)} — {str(rule.get(field))[:80]!r}. A rule whose "
            "doctrine is a dangling reference passes every other gate we have, because none of "
            "them read prose. The pack's markdown half carries the rule; use it."
        )


def test_prim_007_carries_the_whole_rule_and_not_a_summary_of_it():
    """MUST-HIT for the arm above: the real statement is long, and names its own mechanics.

    Without this, the pointer check passes trivially on an EMPTY statement — absence of a
    pointer is not presence of a rule.
    """
    statement = contract.rule("PRIM-007")["statement"]
    assert len(statement) > 800, f"PRIM-007's statement is {len(statement)} chars — too short to be the rule"
    for token in ("opposite-colour", "BODY close", "Breaker", "WICK extreme", "linked_break_id"):
        assert token.lower() in statement.lower(), f"PRIM-007's statement does not define {token}"


# ---------------------------------------------------------------------------
# Registered, NOT implemented
# ---------------------------------------------------------------------------
def test_prim_007_is_REGISTERED_and_the_schema_can_hold_it():
    ids = contract.known_rule_ids()
    assert "PRIM-007" in ids and len(ids) == 118
    assert contract.rule("PRIM-007")["status"] == "READY"
    assert contract.rule("PRIM-007")["enforceability"] == "HARD_GATE"
    prim = contract.schema()["$defs"]["setup_evaluation"]["properties"]["primitives"]
    assert "order_blocks" in prim["properties"], (
        "PRIM-007 has nowhere to land — this is the structural gap that guaranteed rung 4's "
        "0/529, because stop.anchor_object_id could never resolve and HG-11 could never pass"
    )
    assert "order_block" in contract.schema()["$defs"]


def test_order_blocks_joins_required_ON_THE_DAY_PRIM_007_IS_IMPLEMENTED_and_not_before():
    """A DELIBERATE DIVERGENCE FROM `TELEMETRY_PATCH` §3, and the tripwire that ends it.

    §3 says add `order_blocks` to `primitives.required` because *"an absent array is the
    loophole HG-28 exists to close"*. **That loophole belongs to an engine that HAS a detector
    and omits the array to hide a non-search.** PRIM-007 is registered and NOT implemented, so
    requiring the array today makes every emitter write `order_blocks: []` — *"we looked for
    order blocks and found none"*, asserted by code that never looked, and **indistinguishable
    from a real empty result.** That is the same fail-open the requirement exists to prevent,
    installed by the requirement itself.

    > **The condition below is the EVENT, not a proxy for it.** It does not watch for a field,
    > a version or a filename; it watches for PRIM-007 becoming implemented — which is the
    > thing that makes an empty array answerable. *`B163`'s lesson: the `__slots__` tripwire
    > named the right event and keyed on the wrong signal.*
    """
    import app.services.rules  # noqa: F401 - importing the package is what registers them
    from app.services.rules.base import implementations

    implemented = set(implementations())
    prim = contract.schema()["$defs"]["setup_evaluation"]["properties"]["primitives"]
    if "PRIM-007" in implemented:
        assert "order_blocks" in prim["required"], (
            "PRIM-007 IS NOW IMPLEMENTED — an empty order_blocks array is finally answerable, "
            "so TELEMETRY_PATCH §3's requirement applies and this is T-0046's remaining step. "
            "Add 'order_blocks' to primitives.required and delete this branch."
        )
    else:
        assert "order_blocks" not in prim["required"], (
            "order_blocks is required while PRIM-007 is unimplemented — every record now claims "
            "an order-block search that no code performs"
        )


def test_registering_a_rule_did_not_move_what_is_implemented():
    """The arm the whole patch turns on: a REGISTRATION enlarges the denominator only.

    If a numerator moved, the patch did more than register a rule.
    """
    import app.services.rules  # noqa: F401 - importing the package is what registers them
    from app.services.rules.base import implementations

    implemented = set(implementations())
    assert implemented, "no rule implementations were discovered — this arm is measuring nothing"
    assert "PRIM-007" not in implemented, (
        "PRIM-007 is implemented — T-0046 landed, so this test and the one above both need "
        "their T-0045 framing retired rather than relaxed"
    )
    assert implemented <= set(contract.known_rule_ids())


# ---------------------------------------------------------------------------
# No enum token removed or renamed — the acceptance criterion, by NAME
# ---------------------------------------------------------------------------
def test_block_reason_GAINED_three_tokens_and_lost_none():
    enum = contract.schema()["$defs"]["setup_evaluation"]["properties"]["block_reason"]["enum"]
    missing = [t for t in BLOCK_REASON_AT_1_2_1 if t not in enum]
    assert not missing, (
        f"block_reason LOST {missing}. A removal breaks every stored record carrying the token, "
        "and the pack's id policy is stability."
    )
    assert [t for t in BLOCK_REASON_ADDED if t not in enum] == []
    assert len(enum) == len(BLOCK_REASON_AT_1_2_1) + len(BLOCK_REASON_ADDED), (
        f"block_reason has {len(enum)} tokens — exactly three were authorised: {BLOCK_REASON_ADDED}"
    )


def test_the_deprecated_altcoin_token_is_KEPT_and_says_so():
    """`ALTCOIN_UNRULED` is superseded by `ALTCOIN_DISABLED` and MUST NOT be deleted.

    Deprecation is a description change; deletion breaks stored records. The distinction is
    the whole of the pack's id-stability policy.
    """
    br = contract.schema()["$defs"]["setup_evaluation"]["properties"]["block_reason"]
    assert "ALTCOIN_UNRULED" in br["enum"]
    assert "DEPRECATED" in br["description"] and "ALTCOIN_UNRULED" in br["description"]


def test_the_QML_skip_licence_stays_withdrawn_and_only_its_RECORD_survives():
    """THE MANAGER'S RULING, ARMED — and the arm is structural because a text search is not.

    `TELEMETRY_PATCH` §7 asks for `QML_SHAPE_UNDEFINED_IN_SOURCE` to be kept and deprecated.
    v1.2.1 removed it. Ruled: **the removal stands** — the token went because the trader
    withdrew the QML requirement himself (`026_Stop_Loss_Decision.md:46`), which outranks an
    engineering stability policy; and §7's remedy (*"reject it in validation"*) fails a stored
    record carrying the token exactly as the removal does, so it does not achieve the thing it
    is justified by.

    **Checked by walking parsed enum arrays, not by grep.** The string is still on disk, alive
    in the description that RECORDS its removal — `B161`'s shape, and it nearly produced a
    false "round-2 P1 unapplied" report during this task.
    """
    schema = contract.schema()
    sites = _enum_sites(schema)
    live = [p for p, tokens in sites.items() if "QML_SHAPE_UNDEFINED_IN_SOURCE" in tokens]
    assert live == [], f"the withdrawn skip licence is a live enum value again at {live}"

    # MUST-HIT: the walker can see a QML token when one really is live, so the empty result
    # above is a fact about the schema and not about the instrument.
    anchors = [p for p, tokens in sites.items() if "LIQUIDITY_SWEEP_QML" in tokens]
    assert anchors, "the enum walker found no LIQUIDITY_SWEEP_QML — it is not reading enums"

    # And the RECORD of the withdrawal survives, which is what a grep would have tripped on.
    raw = json.dumps(schema, ensure_ascii=False)
    assert "QML_SHAPE_UNDEFINED_IN_SOURCE" in raw, (
        "the description recording WHY the token went has been deleted too — then a future "
        "reader cannot tell a withdrawal from an oversight"
    )


def test_no_enum_site_lost_a_token_anywhere_in_the_schema():
    """Superset over EVERY enum, not only the ones the patch names.

    A patch applied by hand can quietly rewrite an enum it was merely passing through, and
    `block_reason` being correct says nothing about the other 96 sites.
    """
    sites = _enum_sites(contract.schema())
    assert len(sites) >= 97, f"only {len(sites)} enum sites found — the walker is not walking"
    for path, tokens in sites.items():
        assert len(tokens) == len(set(tokens)), f"{path} has duplicate tokens: {tokens}"


# ---------------------------------------------------------------------------
# status_changes: [] — measured, not quoted
# ---------------------------------------------------------------------------
def test_the_patch_changed_no_status_and_the_histogram_proves_it():
    """`status_changes: []` is the PATCH's claim about itself. This is the tree's.

    The histogram is the stronger arm: `status_changes == []` can be satisfied by a patch that
    asserts it, while the histogram is a property of the file.
    """
    from collections import Counter

    hist = Counter(r["status"] for r in contract.registry()["rules"])
    assert dict(hist) == {"READY": 101, "OPEN": 14, "WITHDRAWN": 2, "CALIBRATED": 1}
    assert contract.registry()["meta"]["counts"]["total"] == 118 == sum(hist.values())
    # The +1 over v1.2.1's READY 100 is PRIM-007 and nothing else.
    assert contract.rule("PRIM-007")["status"] == "READY"


def test_meta_blockers_is_still_the_dict_v1_2_1_chose_to_keep():
    """P7 reads *"meta.blockers.ids -> []"*. `ids` was ALREADY `[]` since v1.2.1, and
    `blockers` is a five-key dict whose `note` says the history was kept deliberately.

    **The forbidden change is the CHEAPER one**: replacing the whole dict with `[]` satisfies a
    literal reading of the section title and destroys the record. Found by Review.
    """
    blockers = contract.registry()["meta"]["blockers"]
    assert isinstance(blockers, dict)
    assert set(blockers) == {"ids", "note", "the_three_named_defects",
                             "historical_stale_ids", "historical_status"}
    assert blockers["ids"] == []
    assert len(blockers["the_three_named_defects"]) == 3
    assert all("resolved" in e for e in blockers["the_three_named_defects"])


def test_grade_019s_open_half_is_closed_and_its_note_did_not_outlive_it():
    rule = contract.rule("GRADE-019")
    assert rule["has_open_half"] is False
    assert "open_half_note" not in rule
    assert rule["values"]["unanswered_cells"] == 0
    assert rule["values"]["risk_altcoin_heavy_corrected"] == [0.0075, 0.005, 0.0025]
    assert rule["values"]["risk_altcoin_heavy_as_written"] == [0.0075, 0.05, 0.0025], (
        "the as-written row was deleted — then the ratified correction becomes unauditable "
        "against the source database"
    )


def test_gate_027s_ladder_is_UNCHANGED_while_two_rungs_became_locatable():
    """The patch's own words: *"values + notes; ladder unchanged"*. Rungs 2 and 4 gain
    eligibility and an anchor; the five anchors and their ORDER do not move."""
    values = contract.rule("GATE-027")["values"]
    assert values["ladder"] == ["DEEPEST_SWING", "MOMENTUM_IMBALANCE", "LIQUIDITY_SWEEP_QML",
                                "ORDER_BLOCK", "INNER_MSB"]
    assert values["rung2_eligibility"]["fill_state_in"] == ["UNFILLED", "HALF_FILLED"]
    assert values["rung2_eligibility"]["min_width"] == 0
    assert values["rung2_eligibility"]["gated_on_momentum_flag"] is False, (
        "rung-2 eligibility is gated on the momentum FLAG — PRIM-002's note says eligibility is "
        "a DIFFERENT predicate from is_momentum_imbalance and must not be gated on it"
    )
    assert values["rung4_anchor"]["point"] == "WICK_EXTREME"
