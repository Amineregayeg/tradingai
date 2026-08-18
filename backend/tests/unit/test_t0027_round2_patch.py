"""T-0027 — the round-2 rulings are applied, and applied to the right rules.

WHAT THIS FILE CAN SEE, and it is deliberately less than "the patch was applied correctly":

  * the stale sentence each entry names is GONE          — exact substring, no normalisation
  * the ruling's citation anchors are PRESENT            — exact substring, no normalisation
  * NO status field moved                                — the patch declares status_changes: []
  * the 102 rules OUTSIDE the patch are byte-identical   — fingerprint pinned at f3bd716
  * every rule NAMED below carries at least one of those concrete checks

WHAT IT CANNOT SEE, stated so nobody mistakes green here for a verified application: it does
not check the prose BETWEEN the anchors. A note that dropped the stale sentence, carried the
right citations, and said something wrong in between passes every assertion below. That half
is a human read of the applied notes against RULINGS.md — which is what the package's own
`apply_mode: REVIEW_THEN_APPLY` asks for, and it is Review's, not this file's.

"Verbatim" was considered and REJECTED as the instrument. The patch text is wrapped markdown
blockquote; registry notes are JSON strings. A verbatim assertion has to cross that transform,
and the normalisation is where the fidelity would quietly go. Exact substrings on file:line and
image-path tokens need no transform on either side, so neither side can hide one.

The expectations below are TRANSCRIBED from REGISTRY_PATCH.json / TELEMETRY_PATCH.md, which are
not in this repository (see meta.source_availability). A transcription error is therefore
invisible to this file and is checked by Review against the shipped package bytes.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.services.telemetry import contract_loader as contract

# The nine patch ENTRIES cover FOURTEEN distinct rules: six entries carry `rule_id`, three
# carry `rule_ids`. A parser reading only `rule_id` returns 6 and silently drops 8 rules;
# reading the markdown headings returns 8 or 14, never 9. These are TRANSCRIPTIONS from a
# file this repo does not hold — counting them proves nothing, so nothing counts them.
THE_FOURTEEN = {
    "GATE-027", "GATE-022", "GATE-038", "ENTRY-004", "GATE-002", "GRADE-013",
    "GATE-004", "GRADE-016", "GATE-040", "GATE-003",
    "TARGET-005", "TARGET-006", "ENTRY-005", "GRADE-019",
}
# EXIT-003 is Priority 5 (raise, do not close) — touched, but not one of the stale-prose nine.
TOUCHED = THE_FOURTEEN | {"EXIT-003"}

# Each entry's `problem` field quotes the text that must no longer be there.
STALE_GONE = {
    "GATE-027": "Two unresolved sub-items",
    "GATE-022": "OPEN sub-question",
    "GATE-038": "Two open sub-items",
    "GRADE-013": "is unquantified while the source simultaneously bans",
    "GATE-004": "The engine must pick one behaviour and record which",
    "GRADE-016": "the source never says whether the MAIN asset counts toward it",
    "GATE-040": "is also absent from the Momentum Score's components",
    "GATE-003": "The PDF freezes nothing",
}

# file:line and image-path tokens. These cannot be produced by accident and they survive
# rewrapping, which is exactly why they were chosen over prose.
ANCHORS_PRESENT = {
    "GATE-027": ["026_Stop_Loss_Decision.md:46", "PRIM-006", "049_Examples.md:5"],
    "GATE-022": ["images/Examples/1197_663b46b1.png", "138_untitled.md:6/11/29"],
    "GATE-038": ["images/Magic_Amplifiers/0813_6b653ec8.png", "067_Magic_Amplifiers.md:46"],
    "ENTRY-004": ["B102", "GATE-038"],
    "GATE-002": ["065_Magic_Alignment_Entry.md:83"],
    "GRADE-013": ["066_Magic_Quadrant_For_Altcoins.md:9", "065_Magic_Alignment_Entry.md:19"],
    "GATE-004": ["images/Putting_All_Together/0443_05509bb4.png", "fd52295"],
    "GRADE-016": ["images/Putting_All_Together/0443_05509bb4.png"],
    "GATE-040": ["104_Examples.md:11", "100_Examples.md:21"],
    "TARGET-005": ["ENTRY-003"],
    "TARGET-006": ["answers Q4"],
    "ENTRY-005": ["answers Q8"],
    # ROUND 3 RETIRED THIS ANCHOR, IN ITS OWN WORDS. Round-2 grouped GRADE-019 with "the four
    # constants" and the Q8 hedge (~0.2% "an engineering guideline") came with that grouping.
    # Round-3 P5 says: "Round-2 REGISTRY_PATCH P2 mis-grouped GRADE-019 with 'the four
    # constants' — GRADE-019 carries no such constant; disregard that entry." So the anchor is
    # superseded by a later ruling rather than lost by an applier, and GRADE-019 is re-pinned
    # to the anchors ROUND 3 requires. **Recorded rather than deleted: the test still checks
    # GRADE-019, so it cannot drop out of THE_FOURTEEN's coverage requirement unnoticed.**
    "GRADE-019": ["053_untitled.md", "066:13"],
}

# sha256[:16] over (id, statement, notes, inputs, values, triage_note, resolution, status)
# of the 102 rules the patch does NOT touch, measured at f3bd716 — the tip before this
# task's diff existed — and unchanged after it.
UNTOUCHED_PROSE_FINGERPRINT = "f49a2dd37b3afdec"

# THE NINETEEN RULES T-0045 EDITED, applying MagicStrategy_Round3_Rulings (registry 1.2.1 ->
# 1.2.2). They are excluded from the fingerprint below for the same reason round 2's fifteen
# are: this guard asks "did a rule move that NO reviewed patch names?", and a rule named by a
# later patch is not an unexplained move.
#
# **This list was DERIVED from the diff against the pre-patch registry, not typed from the
# pack** — a hand-transcribed exclusion list excludes by construction exactly the wrong-row
# edit the guard exists to catch. GATE-027 and GRADE-019 appear in BOTH rounds.
ROUND3_TOUCHED = {
    "GATE-001", "GATE-008", "GATE-012", "GATE-014", "GATE-015", "GATE-016", "GATE-027",
    "GATE-028", "GATE-031", "GATE-033", "GATE-034", "GRADE-006", "GRADE-011", "GRADE-018",
    "GRADE-019", "GRADE-033", "PRIM-002", "PRIM-006", "PRIM-007",
}


def _rule(rid: str) -> dict:
    return contract.rule(rid)


def _prose(rid: str) -> str:
    r = _rule(rid)
    return " ".join(
        str(r.get(f, "")) for f in ("statement", "notes", "inputs", "triage_note", "open_half_note")
    )


# ---------------------------------------------------------------------------
# The denominator
# ---------------------------------------------------------------------------
def test_every_rule_the_patch_names_carries_a_concrete_check():
    """The denominator is load-bearing: you cannot list a rule without checking it.

    THE PREVIOUS VERSION OF THIS TEST WAS A PAIR OF TAUTOLOGIES — Review's finding, and it
    was the test written to encode Review's own nine-versus-fourteen point. It asserted
    `PATCH_ENTRIES == 9` against a module constant set to 9, and that a hand-written
    14-element set has 14 elements. **Both restate literals and neither can fail.** The
    finding survived into a constant; the check did not survive with it.

    The cause is structural rather than careless: `REGISTRY_PATCH.json` is NOT in this
    repository, so `THE_FOURTEEN`, `STALE_GONE` and `ANCHORS_PRESENT` are hand-transcribed
    from a source no in-repo test can read. **Counting them proves nothing.**

    What CAN be asserted here is coverage of the transcription by concrete checks: every
    rule named in `THE_FOURTEEN` must carry at least one stale-fragment or citation-anchor
    assertion. Adding a rule to the list without giving it a check now fails.

    WHAT REMAINS OUT-OF-BAND, and is not claimed by any assertion in this file: that the
    fourteen are the rules the patch actually names. Review verified that from outside at
    `1d0f74a` — fourteen named, fourteen changed, none missed, none extra (plus `EXIT-003`
    from Priority 5). **It cannot stay verified without repeating that read, which is the
    argument for vendoring `REGISTRY_PATCH.json` — filed as B109, not done here.**

    The load-bearing checks in this file are the untouched-rule fingerprint and the
    stale-fragment / anchor pair, NOT any count.
    """
    checked = set(STALE_GONE) | set(ANCHORS_PRESENT)
    assert checked == THE_FOURTEEN, (
        f"named but unchecked: {sorted(THE_FOURTEEN - checked)}; "
        f"checked but not named: {sorted(checked - THE_FOURTEEN)}"
    )
    for rid in TOUCHED:
        assert rid in contract.known_rule_ids(), f"{rid} is not in the registry at all"


# ---------------------------------------------------------------------------
# Prose applied — and applied where it was meant to go
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rid,fragment", sorted(STALE_GONE.items()))
def test_the_stale_sentence_is_gone(rid: str, fragment: str):
    assert fragment not in _prose(rid), (
        f"{rid} still carries the round-1 text the patch replaces: {fragment!r}"
    )


@pytest.mark.parametrize("rid,anchors", sorted(ANCHORS_PRESENT.items()))
def test_the_rulings_citation_anchors_are_present(rid: str, anchors: list[str]):
    prose = _prose(rid)
    missing = [a for a in anchors if a not in prose]
    assert not missing, f"{rid} is missing its citation anchors: {missing}"


def test_gate_002_inputs_no_longer_name_an_unqualified_timing_input():
    """The patch names `inputs`, not just `notes` — OFF_4 is a level state, never a clock."""
    inputs = _rule("GATE-002")["inputs"]
    assert "relative timing of reaction," not in inputs
    assert "LEVEL-STATE" in inputs


def test_no_rule_outside_the_patch_had_its_prose_touched():
    """The complement check: matching the intended fifteen cannot catch a wrong-rule edit.

    This is what sees "right text, wrong row" — the failure mode that verifying only the
    fifteen is structurally blind to.

    The first version of this test looked for round-2 MARKER words in the prose and it was
    the wrong instrument: it measured whether the applier happened to write the phrase
    "round 2", not whether a rule was touched. It produced one false positive (GRADE-035,
    whose notes already said "round 2" at f3bd716 and which nobody edited) and two false
    negatives (GATE-004 and GATE-022, genuinely rewritten without the phrase). A fingerprint
    over the untouched rules measures the property the test is named for.

    Pinned at f3bd716, the commit before T-0027's diff existed, and RE-BASED at T-0045 when
    round 3 legitimately touched nineteen rules outside round 2's fifteen. If this fails, a
    rule outside BOTH patches moved — read the diff before updating the constant.

    **Re-basing rather than deleting is the point.** The guard's question is "did a rule move
    that no reviewed patch names?", and that question survives every round; only the set of
    named rules grows. Deleting it at the first legitimate change would have retired the only
    check that sees a right-text-wrong-row edit.
    """
    fp = hashlib.sha256()
    for rid in sorted(contract.rules()):
        if rid in TOUCHED or rid in ROUND3_TOUCHED:
            continue
        r = contract.rule(rid)
        fp.update(rid.encode())
        for field in ("statement", "notes", "inputs", "values", "triage_note", "resolution", "status"):
            fp.update(repr(r.get(field)).encode())
    assert fp.hexdigest()[:16] == UNTOUCHED_PROSE_FINGERPRINT
    assert len(contract.rules()) - len(TOUCHED | ROUND3_TOUCHED) == 86, (
        "the untouched population changed size — a rule was added or removed outside both "
        "patches, which no ruling authorises"
    )


# ---------------------------------------------------------------------------
# No status moved — the patch declares status_changes: []
# ---------------------------------------------------------------------------
def test_no_status_changed_and_entry_004_is_still_open():
    """REGISTRY_PATCH.json carries `status_changes: []`.

    Its ONE proposed change, ENTRY-004 OPEN -> READY, lives under a different key and is
    CONDITIONAL — "apply only if you accept the GATE-038 ruling". The operative condition is
    that the interval test exists in code; nothing implements it. A status is a claim about
    the code, so it stayed OPEN. If this test ever fails, check the implementation landed
    with the closure rather than just relaxing the assertion.
    """
    assert _rule("ENTRY-004")["status"] == "OPEN"
    assert _rule("ENTRY-005")["status"] == "OPEN"
    assert _rule("EXIT-003")["status"] == "OPEN"
    assert len(contract.ids_with_status("OPEN")) == 14
    for rid in THE_FOURTEEN - {"ENTRY-004", "ENTRY-005"}:
        assert _rule(rid)["status"] == "READY", f"{rid} moved off READY"


def test_open_items_carries_fourteen_not_the_patchs_thirteen():
    """A deliberate divergence, recorded in the registry rather than only in a report.

    P4 reduces open_items to 14 and then says "remove ENTRY-004 -> 13". We carry 14. A seat
    diffing the applied registry against the patch would otherwise read this as a
    misapplication, which is why the reason is in meta.open_items.note and the changelog.
    """
    meta = contract.registry()["meta"]
    ids = meta["open_items"]["ids"]
    assert len(ids) == 14
    assert sorted(ids) == sorted(contract.ids_with_status("OPEN"))
    assert "ENTRY-004" in ids
    assert "B102" in meta["open_items"]["note"]


# ---------------------------------------------------------------------------
# 5-i — the inference must not be promoted to doctrine by the act of applying it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rid", ["GATE-004", "GRADE-016"])
def test_main_asset_counted_ships_as_a_declared_parameter_not_a_bare_value(rid: str):
    """The patch adds a structured `values: {main_asset_counted: false}` while putting
    "ships as inference" and "the gate is required" in `notes`. A `values` block is read by
    tools; nothing parses `notes`. Applied literally, the machinery reads an inference as
    doctrine — violating the package's own hard rule 1, never present ours as his.
    """
    values = _rule(rid)["values"]
    assert values["main_asset_counted"] is False
    assert values["main_asset_counted_authority"] == "ENGINEERING"
    assert values["main_asset_counted_ratified"] is False
    assert values["main_asset_counted_provenance"] == "DECLARED_PARAMETER"
    assert values["required_compensating_gate"] == "main_asset_state = SETUP_INVALID"
    assert values["required_compensating_gate_implemented"] is False


def test_gate_004_is_not_marked_settled_while_the_gate_does_not_exist():
    """The exclusion has run UNGATED since 2026-08-08. A ratified-looking row over an
    ungated behaviour is worse than the gap, so the row records how long it ran that way."""
    notes = _rule("GATE-004")["notes"]
    assert "fd52295" in notes and "2026-08-08" in notes
    assert "NOT SETTLED" in notes.upper()


# ---------------------------------------------------------------------------
# meta — the blocks that contradicted the same file
# ---------------------------------------------------------------------------
def test_the_meta_block_no_longer_contradicts_itself():
    meta = contract.registry()["meta"]
    assert meta["version"] == "1.2.2"  # T-0045 applied round 3 on top of round 2
    assert meta["blockers"]["ids"] == []
    assert meta["counts"]["OPEN"] == len(meta["open_items"]["ids"]) == 14
    # A validator reading field_semantics.status would previously have rejected its own file.
    for value in ("READY", "OPEN", "DEFECT", "CALIBRATED", "WITHDRAWN"):
        assert value in meta["field_semantics"]["status"]
    corpus = json.dumps(meta["source_of_truth"]["corpus"])
    # The corrected text legitimately CONTAINS "1,258" in the phrase "not 1,258", so the
    # stale CLAIM is what must be absent, not the digits.
    assert "1,186 chart screenshots" in corpus
    assert "1,258 chart screenshots" not in corpus
    assert "213" in corpus and "1,186" in corpus


def test_the_three_register_rule_and_the_source_table_are_in_the_registry():
    """Both exist so a future reader answers these from the registry rather than re-deriving
    them: how to read the answers document, and whether an unfollowable citation is WRONG or
    merely NEVER REDISTRIBUTED TO US."""
    meta = contract.registry()["meta"]
    registers = meta["answers_document_registers"]["registers"]
    assert set(registers) == {"TRADER_FIRST_PERSON", "PRIOR_AI_ASSISTANT", "IMPERSONAL_SPEC_PROSE"}
    assert registers["PRIOR_AI_ASSISTANT"]["authority"].startswith("NONE")

    avail = meta["source_availability"]
    assert avail["verification_label"]["label"] == "UNVERIFIABLE_HERE"
    assert "His 1,186 chart images" in avail["not_redistributed_at_all"]
    assert "ENGINE_CONTRACT/CONFORMANCE_SUITE.md" in avail["named_by_the_package_but_NOT_in_this_repository"]


def test_the_changelog_records_the_divergences_and_what_was_not_applied():
    """A deliberate divergence recorded only in a work report is B82's shape: the report
    stops being read and the registry is what gets diffed."""
    # The round-2 entry is no longer LAST — T-0045 appended 1.2.2 (and reconstructed the
    # missing 1.2.0 line round-3 P7 asked for). This test is about ROUND 2's entry, so it
    # selects that entry BY VERSION rather than by position; `[-1]` silently retargeted the
    # assertions at whichever patch landed most recently.
    changelog = contract.registry()["meta"]["changelog"]
    entry = next(e for e in changelog
                 if isinstance(e, dict) and e.get("version") == "1.2.1")
    assert entry["version"] == "1.2.1"
    assert "NONE" in entry["status_changes"]
    assert any("ENTRY-004" in d for d in entry["deliberate_divergences_from_the_patch"])
    assert any("main_asset_counted" in d for d in entry["deliberate_divergences_from_the_patch"])
    assert any("CONFORMANCE_SUITE.md" in n for n in entry["not_applied_here"])


# ---------------------------------------------------------------------------
# The schema half
# ---------------------------------------------------------------------------
def test_the_qml_skip_licence_is_gone_from_every_place_it_was_written():
    """P1 names ONE site — the enum value. Our schema carried the same licence in THREE
    places, and an excuse deleted from the enum while its prose survives is still an excuse.
    """
    sc = contract.schema()["$defs"]["stop_candidate"]["properties"]
    assert "QML_SHAPE_UNDEFINED_IN_SOURCE" not in sc["unlocatable_reason"]["enum"]
    assert sc["unlocatable_reason"]["enum"] == [
        "NO_SUCH_PRIMITIVE_IN_SEARCH_WINDOW",
        "PRIMITIVE_BEYOND_DECISION_BAR",
        "PRIMITIVE_ON_WRONG_SIDE_OF_ENTRY",
    ]
    for field in ("unlocatable_reason", "locatable"):
        text = sc[field]["description"]
        assert "QML_SHAPE_UNDEFINED_IN_SOURCE" not in text or "removed" in text
        assert "drawn nowhere" not in text, f"{field} still carries the skip licence in prose"


def test_the_anchor_token_itself_is_deliberately_unchanged():
    """The pack's id/enum policy is stability. Only the EXCUSE goes — renaming the anchor
    would break every artefact keying off it."""
    anchor = contract.schema()["$defs"]["stop_candidate"]["properties"]["anchor"]["enum"]
    assert anchor == [
        "DEEPEST_SWING", "MOMENTUM_IMBALANCE", "LIQUIDITY_SWEEP_QML", "ORDER_BLOCK", "INNER_MSB",
    ]


def test_the_fourth_record_type_exists_and_forbids_a_rule_id():
    """`evaluation_unavailable`: a bar the engine COULD NOT evaluate, versus one it CHOSE not
    to. rule_id is forbidden by construction — no rule has an infrastructure input, so no rule
    can authorise the state."""
    schema = contract.schema()
    assert len(schema["oneOf"]) == 4
    eu = schema["$defs"]["evaluation_unavailable"]
    assert eu["additionalProperties"] is False
    assert "rule_id" not in eu["properties"]
    assert set(eu["required"]) == {
        "record_type", "bar_close_time_ny", "instrument", "cause", "scope", "trading_action_taken",
    }
    assert eu["properties"]["trading_action_taken"]["enum"] == [
        "BLOCKED_BAR", "BLOCKED_INSTRUMENT_SESSION",
    ]


def test_data_gaps_is_required_so_silence_becomes_a_statement():
    assert "data_gaps" in contract.schema()["$defs"]["scan_census"]["required"]


def test_zone_amplifiers_are_representable():
    amp = contract.schema()["$defs"]["setup_evaluation"]["properties"]["primitives"][
        "properties"
    ]["amplifiers"]["items"]["properties"]
    assert amp["geometry"]["enum"] == ["LEVEL", "ZONE"]
    assert "zone_low" in amp and "zone_high" in amp
    assert amp["collision_test"]["enum"] == [
        "INTERVAL_CONTAINS", "INTERVAL_OVERLAP", "EDGE_TOLERANCE",
    ]


def test_main_asset_state_exists_but_is_deliberately_not_required_yet():
    """THE DEFERRAL, asserted so it is visible rather than silent.

    The patch specifies `main_asset_state` as required. No producer computes the verdict —
    the gate does not exist — so requiring it would force every emitted record to assert a
    verdict the engine did not compute, and the only way to keep the suite green would be to
    teach the fixture to fake it. That is a vacuous green.

    When the gate lands, this test SHOULD fail. Promote the field then, and delete this test.
    """
    se = contract.schema()["$defs"]["setup_evaluation"]
    assert "main_asset_state" in se["properties"]
    assert se["properties"]["main_asset_state"]["enum"] == [
        "SETUP_VALID", "SETUP_INVALID", "UNREADABLE",
    ]
    assert "main_asset_state" not in se["required"], (
        "the gate now exists? promote the field, emit it from the producer, and delete this test"
    )


def test_correlate_availability_exists_but_is_deliberately_not_required_yet():
    """Same shape as main_asset_state: the correlate panels are not wired (B11), so no
    producer can state availability honestly."""
    cs = contract.schema()["$defs"]["correlate_state"]
    assert "data_available" in cs["properties"]
    assert cs["properties"]["unavailable_reason"]["enum"] == [
        "FEED_MISSING", "FEED_STALE", "INSUFFICIENT_HISTORY", "NOT_APPLICABLE",
    ]
    assert "data_available" not in cs["required"]
