# Known issues — open problems register

Problems found while building, **not yet fixed**. Solved issues are not listed
(they are in git history). Each entry says what it is, where it came from, and
what it could break.

Ordered by what would hurt most, not by how hard it is to fix.

Last updated: 2026-08-16 (T-0026: B93 CLOSED — the AST guard measures the invariant the failure message always claimed, catching 26/26 against the clean-interpreter guard's 11/26, and all three guards are kept because they ask three different questions. Earlier, T-0023, target selection — EXIT-004 / TARGET-001 / TARGET-003, SHADOW ONLY like every rules task. B93 — a test can make a guard vacuous just by importing what the guard checks for: `test_every_rule_module_on_disk_is_imported` was vacuous for 23 of the 26 modules in its own domain; FIXED by a clean-interpreter guard, whose own limit is measured at 15 of 26 still reachable through a sibling and is NOT fixed. B95 — TARGET-001 and TARGET-003 are three levels, not two, and 'ignore size entirely' is the wrong implementation that looks safe. B96 — the active institutional destination has NO producer, so TARGET-001 registers unable to fire. B97 — `target_object_type` is lossier than PRIM-003's pool classes and INSTITUTIONAL_CANDLESTICK must never map to INSTITUTIONAL_LEVEL. Earlier, B90 CLOSED: EXIT-001 now reports `ticks_seen`, so an unobserved path and a long quiet one are no longer one record. Earlier, T-0022, the v1 exit model EXIT-001/EXIT-002 — the first rules in this programme that govern what happens AFTER a trade is taken, and SHADOW ONLY: nothing under `live/` or `broker/` imports them and `paper.py` still closes positions whole. B86 — `PaperPosition` has one `units`/`sl`/`tp` and `__slots__`, so it cannot represent a tranched position and the wiring task is a broker-layer change, not a call site. B87 — the 19:00 New York close is ours and UNRATIFIED, defaulted ON so shadow generates the evidence the ruling needs, and the wiring task must re-surface the question rather than inherit it. B88 — `ExitEvent` refuses `LIQUIDATION`, which is what makes criterion 1 enforceable at all, and becomes a hazard the moment a real liquidation can reach the exit path. B89 — a target at or inside 2R is refused outright because GATE-031 cannot run without GATE-025. Earlier, T-0021: B54 CLOSED — both tools collapse aliases and agree; every coverage figure now carries its space, and the script refuses to print an impossible set. B58 — the other tool is outside the repo, so half the agreement cannot be CI-enforced. Earlier, T-0016: the partially-evaluable requirements are enforced by script over the whole registry — B56, eleven emitted fields that cannot say where they came from, baselined not fixed and needing a task id; B57, the two of six standing requirements that script can actually enforce, so a green run is not read as six. Earlier the same day, T-0007: ENTRY_TF 1H -> 5m, the first live behaviour change. B37 CLOSED — the lookahead is out of production. B33 gained the instance it predicted: every legal execution timeframe would have broken the shadow; GATE-017 closed on the live path; B38 — GATE-018 stays OPEN; B39 — a conditional edit that matches nothing succeeds; B40 — the correlate margin is now 1.5x and nothing reports it shrinking)

---

## The rule for keeping this file honest

**At the end of every task, any problem found but not fixed gets written here
before moving on.** Not mentioned in passing, not left in a commit message —
written here, where it will actually be reviewed.

---

## THIS PROJECT'S DEFAULT FAILURE — read this before filing or reading an entry

**An output that does not discriminate between working and broken.** Stated once here because it
has been re-derived inside individual entries and task plans too many times to keep treating as a
coincidence.

**Its commonest specific form: conflating *"this was never measured"* with *"this was measured and
came back empty."*** Three subsystems acquired it on 2026-08-14 alone:

| where | the collapse |
|---|---|
| `ConditionReading` | `producer=None` (no implementation exists) vs. a producer that ran and found nothing |
| the census | *"the rules were not consulted"* vs. *"the rules were consulted and permitted"* |
| panel thickness | `bar_sample_count = None` (not applicable to an exchange bar) vs. a genuinely thin bar |

**Same shape, other surfaces, all in this register:** `deciding_rule_id or "GATE-036"` laundering an
absence into a citation (**B31**) · a test that can only construct honesty (**T-0011's plan**, on
`test_telemetry_contract.py:223` — no entry of its own yet) · a mutation invisible to its own trap,
printing eight `ok` lines byte-identical to a real pass (**B30**'s instance list) · `disturbed_count`
hardcoded to `0` · a quotation that does not say which part it addresses (**B45**) · a count that
does not say which set it counted (**B43**) · a claim that does not say which criterion it answers
(**B49**).

**Three of those citations were wrong in this section's first version — corrected 2026-08-14 by
Review, and the corrections are left visible rather than silently applied.** It said **B41** for the
honesty-only test, when B41's own second sentence disclaims that family — *"A new species. Every
prior entry in this section is an output that fails to discriminate. **This is a detector that was
never wired**"*; **B39** for the eight-`ok`-lines mutation, when B39 is a conditional edit that
matches nothing; and **B44** for the undenominated count, when B44 is about inputs declared as data
names. **This section's own thesis, in the section stating it, within an hour of it being written**
— and each wrong citation pointed at a real entry describing a real defect, which is why reading it
did not feel wrong.

### The two fixes that keep working

**1. MAKE THE VALUE CARRY ITS OWN ANSWER.** A bare number cannot tell you where it came from, so
provenance travels with it: `DeclaredQuorum` carries its rule id and version, `correlate_denominator`
ships beside the grade it explains, `expected_poll_seconds` states what it assumed. **Three-for-three
whenever the question is *"was this value legitimate?"***

**2. REPORT THE DENOMINATOR, AND NAME THE SET.** A flag count with no denominator cannot distinguish
*clean* from *not looked at*. `examined 11 of 64` and `32 of 79 distinct` are honest;
`6 flagged` and `40 implemented` are not.

### HOW IT PROPAGATES THROUGH CODE THAT IS INDIVIDUALLY CORRECT

**The mechanism, found by Execute while fixing an instance of it:**

> **A helper that correctly merges two things for its own purpose will merge them for yours too,
> unless you separate them again at the boundary.**

`quorum_blocked` treats *"no producer exists"* and *"a producer exists and was never called"* as
one thing — **and it is right to**, because for its purpose both mean *no quorum*. The defect
appeared when its return value was reused as the **record**: the fix that added a fourth state to
distinguish the two absences **re-merged them in the emitted payload**, through a helper that was
not wrong. Caught by a test, not by rereading.

**So a correct abstraction is a route by which this failure spreads.** The question to ask of any
shared helper is not *"is it right?"* but ***"right for whose purpose, and does the caller need a
distinction it deliberately discards?"*** Every collapse in the table above is defensible
somewhere — that is why the code reads well at every individual site.

### A SECOND PROPAGATION MECHANISM — a fact re-derived from a rendering of itself

**Found by Review, in a regression it introduced and caught in the same pass.** Its sweep grouped
skipped entries with `"date" in detail` — **string-matching its own human-readable message to
recover a fact the code already had.** The moment the message wording changed, every prose-only
entry in the register appeared under a heading saying they cite code.

> **A derived fact must come from the thing that knew it, never from a rendering of it.**

**Three instances, all this evening:** `quorum_blocked`'s merged dict reused as a record · a `git
log -S` for a symbol answering *"where does this string's count change"* when the question was
*"where did this line move"* · a report filtered by matching its own prose. **Fixed by carrying
reason CODES structurally beside the message** — and the comment says so, because the next person to
improve the wording will otherwise re-break it identically.

**Related to the boundary-merge mechanism above and distinct from it:** that one is a correct
abstraction discarding a distinction its caller needed; **this one is a round trip through a
presentation layer.** Both let the failure travel through code that is individually right.

### NEGATIVE FINDINGS INHERIT THE SCOPE OF THE SEARCH THAT PRODUCED THEM

**A distinct form, found by Review correcting its own entry.** B45 said *"There is no consolidation
detector and no range detector, in the registry or in the code."* The search was `app/services/rules/`
and the claim was written repo-wide. **`ict/detector.py:476` has one** — a volume-percentile detector
for Supply/Demand zones. B45's substance survives (different question, different path, not in the
registry, so GATE-040 genuinely had no producer) but its scope was overstated.

> ***"I did not find it"* written as *"it does not exist."***

**Why this is worse than the positive form and not merely another instance of it:** a positive claim
carries a referent you can go and check. **A negative claim has no referent — you cannot follow a
citation to an absence.** So the only thing bounding it is the scope of the search, and if the search
is not stated the claim cannot be checked at all, only re-run by someone who guesses the same way.

**So: state the search.** *"No `session_open` anywhere under `app/`"* is checkable. *"There is no
session marker"* is not.

**AND THE BETTER FIX, WHERE IT IS AVAILABLE: ask a question that carries its own denominator.**
Review's formulation, which upgrades "state the search" from a discipline to a design choice:

> **A grep answers *"where does this text appear"*. `implementations()` answers *"which rules are
> there"*. The second question has a knowable denominator and the first does not.**

**Measured:** re-deriving *"only one rule declares a condition table"* by inspecting every class in
`rules_pkg.implementations()` through its live module gives **40 rule ids across 17 modules, 1 of 17
with the signal** — and the `OFF_CONDITIONS` substring that made the grep version unsafe **is not
reachable by this method at all**, because it is not a module-level sequence.

**So an inspection-derived negative carries its scope inherently and a text-derived one cannot.**
The same correction closed the `decided_by` claim days earlier: a grep said no write site set it,
and both sites did — through `**Attribution.ict().as_columns()`, invisible to text search.

**Same day, same seat, a second instance:** *"GATE-041 is the only rule declaring a `CONDITIONS`
table"* — load-bearing for T-0016's denominator of 1 — rested on a grep anchored to line-start or
four-space indent under `rules/*.py`, reported as a repo fact. **The conclusion held** (a wider search
surfaces only `OFF_CONDITIONS`, a substring, in a rule using neither shared type) **and the evidence
had a scope nobody could see.**

### A MUTATION MUST FAIL ONLY FOR THE PROPERTY UNDER TEST — and it can miss from either side

**Two mutations written hours apart missed this from opposite directions, which is what makes it a
form rather than two mistakes:**

    T-0017's   would have PASSED for an unrelated reason — the corpora on which the wrong
               threshold value is accepted are the oldest in a live fetch, so within six hours
               there is nothing left to demonstrate and the mutation goes vacuous. A vacuous
               mutation passes.

    T-0016 3b's would have FAILED for an unrelated reason — "unblock the middle rule and confirm
               the outer clears" had no middle rule to unblock, because both declarations name
               an unimplemented leaf rather than a blocked rule. It would have failed whether or
               not the mechanism existed.

**Neither would have discriminated, and neither failure is visible in the mutation's own text** —
both read as precise, both name real objects, both would have run. **T-0017's needed measuring how
the corpus moves; 3b's needed reading what the declarations actually contain.**

**So the check on a mutation is not "does it fail today" but "would it fail for THIS reason and no
other, and would it still be able to fail next week".** The passing side is the more dangerous of
the two — a mutation that fails spuriously gets investigated, and one that passes spuriously gets
recorded as evidence.

### WHEN THE DEFECT IS TIMING, THE OBSERVABLE IS THE CALL — not the output

**A third discrimination class, distinct from the two reachability failures above.** Those were about
whether a mutation *runs*. This is about what a test can observe **in principle**: a correct test, a
reachable defect, and **no overlap between them**.

**The instance.** T-0011 reorders a gate call so the block reason can be recorded. If the
implementation *reuses* the early value rather than re-evaluating, a position closed during an
intervening `await` leaves the engine skipping on *"already in a position"* while holding none — a
changed trading decision. **And the verification criterion — same skips, same reasons, same entries
taken — could pass on every run**, because it observes VALUES and the defect is a difference in
*when* a value was read.

**The answer is mechanical:** spy the two methods, assert the order, assert the call count is 2 rather
than 1. **Reuse produces one call; re-evaluation produces two.** A call-sequence assertion
discriminates it; no number of value assertions can.

> **When a defect is WHEN something happened rather than WHAT it produced, the observable is the
> CALL, not the output.**

**With the caveat that must travel with such an assertion:** it pins the **implementation**, not the
property. It will fail when someone legitimately restructures, and that failure looks like a defect —
**so it carries a comment saying what it protects**, or it becomes another guard nobody can interpret.

**AND THE SAME DISTINCTION SOLVED A PROCESS FAILURE THE SAME HOUR.** Three attempts to stop the
Manager committing Review's uncommitted register work: *chain the commands*, then *check the tree
first*. Both are about **when** to check, and both were beaten by timing. The one that worked on its
first outing is about **what to read** — **the diff of what you are about to stage.** Status can be
stale; a diff cannot, because it is the thing itself. **Observe the artefact, not a report about it.**

### TWO NUMBERS QUOTED TOGETHER MUST BE CHECKED AGAINST EACH OTHER

**Cheap, and it caught nothing for hours because nobody applied it.** The Manager reported
*"33 of 79 distinct implemented"* alongside *"effective coverage 37 / 91"* in the same updates.
**Effective coverage cannot exceed implemented. 37 > 33 on its face.**

**The contradiction is visible without knowing which figure is right** — which is what makes it
worth stating as a rule. Both numbers came from tools, both looked authoritative, and they came from
**different** tools: `rule_waves.py` collapsed aliases and `check_rule_coverage.py` did not (**B54**).

**Past tense as of T-0021 (2026-08-14): both collapse now, both print both spaces, and the coverage
script asserts these relations on itself and refuses to print an impossible set.** This sentence is
amended rather than left standing because it was a live claim about current behaviour — and the
entry it cites is the one about two tools disagreeing, so a reader arriving here after the fix would
have been told to distrust a tool that had been repaired.

**So: when a report carries two figures about one quantity, check them against each other before
checking either against reality.** An impossible pair localises the error to one of two places without
any further work; a plausible pair proves nothing but costs nothing to verify.

**THE PRECONDITION, WITHOUT WHICH THE CHECK CANNOT BE PERFORMED: every figure carries its space.**
`37/91 ids` and `31/79 distinct` are checkable against one another. **`effective coverage` and
`distinct implemented` are not** — the reader cannot tell whether a contradiction is real or a units
mismatch. **A number quoted without its space cannot participate in the check that would catch it.**
That is the referent argument (**B49**) arriving in arithmetic.

**A milder instance in a CORRECT verdict, found by Review in its own:** T-0014's review says
*"effective coverage is unchanged at 37 / 91"* at `:29` and *"33 of 79 distinct… 31 of 79"* at `:98`.
Internally consistent — 31 ≤ 33, and 37/91 is id-space — **but `:29` never says it is id-space**, and
the two sit 69 lines apart. **A reader can reconstruct the impossible pair out of an accurate
document.**

### AND THE CHECKS WORTH HAVING ARE THE ONES THAT RUN THEMSELVES

**Every failure in this preamble was a check that was available and unused rather than absent.** The
red CI nobody read. The pinned worktree nobody ran the suite in. The occurrence count nobody asserted.
The diff nobody looked at before staging. The two figures nobody compared.

**The common property: each costs one command, and NOTHING PROMPTS IT.** The tool does not ask, the
file does not ask, and the reviewer runs it only if the thought occurs. **B47's lesson generalised: a
check that depends on someone remembering is a check that will be skipped exactly when the session is
busiest** — which is when the defects arrive.

**So prefer the mechanical form every time it exists:** invariants a tool asserts about its own output
(`effective <= implemented <= total`, which holds in any space without knowing which number is right)
over a rule to compare figures; `agents/ci_range.py` over a habit of checking CI; the two sweeps over
a discipline of re-reading the register. **The good version of every entry in this preamble is a
command, not a resolution.**

**AND THE DETECTORS WERE NOT THE PROBLEM. Every mechanism that actually caught a defect on 2026-08-14
was designed in advance and worked:**

    CI                                       caught the red push at 16:11:37, within a minute
    test_every_rule_module_on_disk_is_imported  failed at 62df7d6 — "Extra items: 'consolidation'"
    base.py's __init_subclass__              refused the GRADE-035 alias claim with a TypeError,
                                             which rescoped T-0014 before a cycle was spent
    verify_guards.sh                         passed honestly throughout, on every mutation

**What was missing was a reader.** So the tools built that day are not detectors — checked, and four of
five merely **route or correct signals that already existed**: the two sweeps read `KNOWN_ISSUES.md`
and `git log`, `ci_range.py` reads the Actions API (**B53**'s whole point), the `rule_waves.py` fix
collapses aliases in an existing counter, and the invariants above are a self-check inside a tool that
already printed the numbers. **Not one adds detection.**

**The consequence for the next proposal, and it is narrower and cheaper than "build a tool":**

> **Before building a detector, check whether the thing is already detected and merely unread.**

**B53 is the pure case** — the signal existed, was correct, was timestamped, and nobody had ever looked
at it. **Had that question been asked first, `ci_range.py` was the obvious build and T-0018's
guard-list framing would never have been written.**

**One qualification, from Review against its own claim:** `verify_guards.sh` was designed in advance
and has needed three recorded fixes — **B18**'s over-wide restore, the `MUTATED` flag its own trap
could not see, and the 127 exit code. **Designed in advance is not the same as correct.** The point is
where to look first, not which kind of tool is better.

### A PROBE THAT A DEAD RULE PASSES — and the control run that separates them

**Found by Execute building T-0016's criterion 2, and neither the plan nor the standing section on
partially-evaluable rules named it.**

The check flips one condition to `NOT_EVALUABLE` and asserts the rule declines to decide. **A rule
that returns its default unconditionally — a completely dead rule — passes every one of those probes
perfectly.** *"Blocked"* and *"always default"* are indistinguishable from the probe alone.

> **The project's signature failure, inside the check written to enforce the project's signature
> discipline.**

**The fix is an ALL-TRUE CONTROL, run first: if the rule cannot reach a verdict with every condition
readable, the probes below prove nothing and the script fails rather than passing.** Measured on
landing: GATE-040's control is FAIL and GATE-041's is PASS, **so both are live rather than dead**, and
the probes mean what they claim.

**This is the criterion-2 analogue of the mutation-discrimination form above** — a probe that passes
whether or not the property holds, where 3b-i was a mutation that *failed* whether or not it held.
**Same defect, third position: the passing side, in a probe rather than a mutation.**

### A MEASUREMENT TAKEN ON ONE BRANCH IS NOT A PROPERTY OF THE RULE

**The Manager reported five keys on GATE-041 lacking provenance. There are six.** The list was
measured on the **blocked** branch only; `mandatory_satisfied` (`:204`) exists solely on the **decided**
branch and has no provenance either.

**So the count was complete for the path examined and read as complete for the rule.** That is the
denominator problem in a place the *name-the-set* fix does not reach: the set was named — *"every
top-level key of `values`"* — and **the code path was not.** A rule with two exit branches has two
`values` dicts, and one record per rule leaves the other branch unchecked while the figure reads as
covered.

**Execute's check examines both branches per rule for exactly this reason.** The general form: **when a
function has multiple exits, "I measured its output" names one of them.**

### A LIMIT CAN FAIL IN BOTH DIRECTIONS — and only one had been checked

**Every limit written into a tool tonight existed to stop a number being trusted too much.** Review's
observation, made after catching the inverse: **a limit that OVERSTATES uncertainty does damage too,
because a reader discounts a figure that deserved to be trusted.**

**The instance.** `deploy_preflight.py` claimed `open_positions` was *"the broker's `open_trade_count`,
not what the strategy considers live — so if those can differ this reports the broker's view."*
**They cannot differ.** `paper.py:139` is `open_trade_count=len(self._positions)`;
`crypto_loop.py:363` is `len(await self.paper.get_positions())`; `:366` is
`any(p.pair == pair for p in await self.paper.get_positions())`. **The same list, three readers.**

**So the tool reported the variable under test and told the reader it was a proxy.** For the task that
number was written to protect, that is the difference between *"this is the thing"* and *"this is
adjacent to the thing"* — and a reader acting on the limit would have deployed with less confidence
than the measurement warranted.

**Corrected as its own section in the file rather than silently**, because a silent fix makes the tool
look like it was always right, and the failure mode is the interesting part.

**AND THE COROLLARY, which is the reusable half:** an inferred or caveated answer must announce **when
its assumptions lapse**, not merely that it has them. *"It degrades silently if either changes"* is the
defect — not the inference. So the pair inference in that tool now checks its own two assumptions on
every run: **whether the activity buffer spans the window asked about**, and **whether every configured
symbol is accounted for** — reporting an unaccounted symbol as *"cannot infer"* rather than *"not
held"*. **Absent-versus-empty, in the tool, on the field that matters.**

**With those, an inference is honest at every degradation and a better data source becomes an
optimisation rather than a correctness fix.** Without them it is a correct answer with no expiry date
printed on it — **which is exactly what B34 was.**

### A CHECK WRONG IN THE STRICT DIRECTION READS AS CONSERVATIVE AND GETS LESS SCRUTINY

**Execute's clause, in GATE-037's `COVERAGE_NOTE`, and it names a failure mode nothing else here
does:** a check that fails on the mere *presence* of a banned token *"would enforce the opposite of the
doctrine **while looking stricter**."*

**Every limit and every criterion written on 2026-08-14 assumed the danger was permissiveness** — a
guard that fires too rarely, a threshold that accepts too much, a mutation that passes vacuously.
**The strict direction was never checked**, and it is the direction that attracts less review, because
over-strictness reads as caution.

**Two instances, one in a rule and one in a tool:**

* **GATE-037** — the statement explicitly permits premium/discount geometry to be **recorded** as
  reading vocabulary while forbidding it from influencing a decision. **A check failing on presence
  would forbid the reading vocabulary the rule protects**, and would have passed review as the safer
  reading.
* **`deploy_preflight.py`'s limit 3** — claimed a number was a proxy when it was the variable under
  test. **A limit that overstates uncertainty makes a reader discount a figure that deserved trust.**

> **Ask of every guard: what does it forbid that the doctrine permits?** The permissive failure is
> caught by the mutation discipline; **the strict failure is caught by nothing already in place.**

### AND A NAMED PATH THAT DOES NOT EXIST IS A SILENT NO-OP

**Found the same hour, in the same rule.** `gate_037_no_premium_discount.py:121` scans
`("decision", "entry", "gates", "rule_evaluations")`. **Measured: `gates` has ZERO occurrences in
`TELEMETRY_SCHEMA.json` and zero in the model**, and the only gate-ish schema keys are
`mitigated_imbalance_count` and `unmitigated_imbalance_count`.

**So the check names four paths, can only ever scan three, and nothing says so** — a path that does not
exist is indistinguishable from a path that is clean. **Same class as the deferral sweep's `.py`-only
file matcher and `ci_range`'s ancestry inference: the tool reported on what it looked at and did not
say the lookup found nothing.**

**The fix is the denominator discipline applied to path names:** assert the named paths exist in the
record shape and report any that do not, so a rename or a typo reduces coverage **loudly**.

### A FABRICATED MEASUREMENT IS NOT AN UNVERIFIED ONE — and it wears the same clothes

**Self-caught and retracted by Execute within the hour, which is the only reason this entry can be
written at all.** `B59`'s first version reported
`abs(100.20-100) = 0.19999999999999574`, included, against
`abs(99.80-100) = 0.20000000000000284`, excluded — a float asymmetry biasing amplifier counts above
the entry.

**The figure came from no arithmetic.** Execute's own words: *"I derived it from an expectation of
asymmetry and wrote it down as a measurement."* Verified independently — every plausible form gives
**identical deltas of `0.20000000000000284` for both edges**, and `0.19999999999999574` appears
nowhere:

    half = abs(100.0) * 0.2 / 100.0   ->  0.2 exactly
    99.80  delta 0.20000000000000284  <= half  False
    100.20 delta 0.20000000000000284  <= half  False

**Why this is a distinct class rather than another unverified claim.** Everything else in this
preamble is a *true statement about the wrong thing*: an accurate quotation with unmarked scope, a
correct sha on the wrong task, a real count over the wrong set. **This was never measured.** It has
the form of a measurement — a repr-precision float, two comparisons, a directional conclusion — and
**that form is what made it credible**, because this register has taught every seat to trust a figure
that looks measured.

**And the sharpest part is Execute's, about its own report:** the defect was caught *in the code*
because a criterion demanded testing the statement's own worked example rather than a convenient one.
**The entry's numbers were then the convenient ones.** The discipline was applied to the artefact
under test and not to the claim about it.

**What survives, and it is more serious than the retracted version:** the real defect is
**form-dependence, not asymmetry.** Two of three natural implementations **exclude the doctrine's own
only concrete boundary:**

    abs(p - e) <= e * pct / 100        EXCLUDES both documented edges
    abs(p - e) / e <= pct / 100        EXCLUDES both documented edges
    precompute the band 99.80..100.20  INCLUDES both

**So the choice of arithmetic decides whether the rule admits its own worked example, and none of the
three would be flagged in a diff.**

**The retraction is visible in all three places that carried the claim** — entry, function docstring,
test docstring — rather than silently applied, because a silent fix makes the entry look like it was
always right and the failure mode is the finding.

### EVERY DEFECT THAT MATTERED WAS FOUND BY RUNNING SOMETHING, NOT BY READING

**Review's closing generalisation, 2026-08-14, and the one thing from this evening that transfers
past this project:**

> *"Every defect I found by reading, I could have found by reading. **Every defect that mattered, I
> found by running something.**"*

**Its own list, and none of these was visible in a diff:**

    the hardcoded FALSE in GATE-041          a rule that could never fire
    a guard that could not fire              mutation passed against unchanged code
    arithmetic that went negative            a limit wrong in both directions
    a check that scanned DEAD CODE           965 tests green, the path unreachable
    a tool that withheld verdicts it had     cancelled blocked the transfer

**All five were one command away.** And the asymmetry is the point: **reading finds what someone
wrote down wrongly; running finds what nobody wrote down at all.** A docstring that requires
opposite-direction overlap sits beside a scan that does not check it, and both halves read correctly
in isolation — **the contradiction exists only in the execution.**

**The operational form, for whoever inherits a seat here: if a claim can be checked by running
something, the review is not finished until it has been run.** Not "read the code that supports the
claim" — **run the thing and read what it prints.**

### A SOURCE-TEXT GUARD THAT BREAKS ON EVERY SIGNATURE CHANGE GETS RELAXED BY WHOEVER IS BUSIEST

**Execute's observation, 2026-08-15, written in the comment where it relaxed one — and it is a
principle about guard DESIGN rather than an incident.**

`test_shadow_stage_a.py` asserted call ordering by substring index:

    src.index("_shadow_evaluate(pair, entry)")  <  src.index("sig, trace = evaluate_latest_bar_traced")

**T-0011 added an argument to that call, so the pattern stopped matching.** Verified: the old substring
now occurs **0 times**, which means the assertion **raised `ValueError: substring not found` rather than
failing on the property it names.** Execute matched the call OPENING instead —
`"await self._shadow_evaluate(pair, entry"`, which occurs exactly **once**, so `index()` is
unambiguous — and it is *tighter* than the original in adding `await self.`.

> **The principle, in its words: a source-text guard that breaks on every signature change gets relaxed
> by whoever is holding the unrelated diff.**

**And that is the part worth keeping: the person who relaxes such a guard is BY CONSTRUCTION the person
least placed to judge it.** They are mid-task, the guard is failing for a reason unrelated to their
work, and the cheapest way past is to widen the pattern. **A guard that cries wolf on every legitimate
change trains the project to loosen it, and the loosening happens under time pressure by someone whose
attention is elsewhere.**

**So the design rule is to assert the NARROWEST THING THAT IS ACTUALLY THE PROPERTY.** The property here
is *ordering of two calls*, not *the argument list of one of them* — **the original pattern encoded both
and only one was intended.** Every incidental detail a guard pins is a future false failure, and every
false failure spends the credibility that makes the guard obeyed.

**Related and distinct from B39:** B39 says assert the occurrence count before a scripted edit. **This
says choose the pattern so the count stays 1 across changes you expect** — B39 catches a match that
silently became zero; this stops it becoming zero for reasons that do not matter.

### EVERY COLLAPSE FILED TONIGHT PRODUCED A FALSE CLEAN — EXCEPT ONE, AND IT COST A FINDING

**Review's observation, 2026-08-15, and it is a direction rather than a new instance.**

    ci_range     cancelled read as no-verdict         -> false CLEAN (a hole that was not there)
    ListAgents   own absence read as a dead seat      -> false ALARM about a live registry
    the suite    contaminated run read as clean       -> false CLEAN (and the number was right)
    grep         FILE absent read as PATTERN absent   -> false ALARM at a correct finding

**The Manager's `requirements-prod.txt` miss is the one worth separating.** Checking Execute's `B65`, it
grepped `requirements-prod.txt` **at the repo root, where no such file exists** — it lives at
`backend/requirements-prod.txt` — and a `|| echo "not in requirements-prod.txt"` fallback **printed a
confident negative for a missing file.** `grep` returns the same non-zero exit for *pattern absent* and
*file absent*, **and the fallback text asserted the first.** Same instrument as `echo $?` after a pipe,
which all three seats have been bitten by.

> **The direction is the point: nearly every collapse this register files produces a FALSE CLEAN — a
> guard that passes, a verdict that transfers, a suite that looks green. This one produced a FALSE
> ALARM, aimed at a reviewer's CORRECT result.**

**And the two cost different things.** A false clean costs a cycle, or a defect reaching production. **A
false alarm aimed at a correct finding costs THE FINDING** — the Manager was one step from overturning
`B65` on the strength of a `grep` that had not read a file, and `B65` is the one that stopped a census
being built to a spec that could not be stored.

**So the collapse check has a second question beside "what does this output fail to distinguish":
WHICH WAY DOES THE COLLAPSE FALL?** A tool that collapses toward *clean* will lose you a defect. **A
tool that collapses toward *alarm* will lose you a colleague's correct work**, and it will do it while
feeling like diligence, because contradicting a peer's result reads as checking it.

**Concretely, and it costs nothing: a fallback message must not assert more than the command
established.** `|| echo "grep found nothing OR the file is missing"` is honest; `|| echo "not in
requirements-prod.txt"` is a claim the command never made. **Test for the file before reporting on its
contents.**

### AND ITS LIMIT, WHICH THE RULE ABOVE WOULD OTHERWISE HIDE — added within hours by its own author

**Review qualified this the same night it wrote it, after watching a fresh seat make the same error
on its first message.** The rule above, read alone, tells a new reader that running is *sufficient*.
**It is not, and the counterexample is the author's own worst instance of the evening:**

> **The failure is not trusting the tool. It is reasoning from a tool's output without accounting for
> what the tool structurally CANNOT show.**

    ci_range     could not show a cancelled run's transferable twin, because it never looked
    ListAgents   cannot show you YOURSELF — a session is excluded from its own listing

**In both cases the output was COMPLETE AND CORRECT FOR WHAT IT MEASURED, and the reader supplied a
conclusion about what it did not.** Review *ran* `ci_range` and still concluded that `8d3fc8f` was an
uncoverable hole. **Execute #3 ran `ListAgents` and concluded a live registry entry was dead — its
own.** Two seats, two instruments, same shape: **the absent case and the true case produce an
identical observation, and the reader picks the one implying action.**

**So the pairing is: run it, AND ask what the output cannot distinguish.** The second half has no
command behind it — it is the question *"what would this look like if the opposite were true?"* **In
both instances tonight the answer was "exactly the same", and that was knowable before the wrong
conclusion, not after.**

**AND REVIEW NARROWED THAT INTO SOMETHING EXECUTABLE, which the version above is not.** *"What if the
opposite were true"* is the right question and **hard to ask cold.** The answerable form:

> **READ THE OUTPUT'S LABELS, NOT ITS ROWS, AND ASK WHETHER ANY TWO MEAN THE SAME THING, OR ANY ONE
> MEANS TWO.**

    ci_range     printed `cancelled` and `no run` — TWO WORDS FOR ONE epistemic state
    ListAgents   prints a list whose absence has TWO CAUSES — not running, and being you

**In both cases the collapse was visible in the output's own vocabulary before any conclusion was
drawn.** Two labels for one state, or one label for two. **That is checkable in seconds and it would
have caught both.**

**And it composes with the failure it corrects: Review RAN `ci_range` and still concluded a hole
existed. Running produced a correct row and the reader supplied the collapse.** So the pairing is not
*"run, then think"* — it is **"run, then read what the row does not say."**

**The constructive corollary, and it is why the four `agents/` tools now print their own limits:
a tool that ENUMERATES THE STATES IT CANNOT SEPARATE has done the second half for its reader.**
`landed_sweep`'s *"0 true positives in 15 flagged"*, `ci_range`'s workflow-boundary block and its
transfer ages, the prober's `strategy_step` note, `deferral_sweep`'s five documented blind spots.
**Every one of those exists so the next reader does not have to reconstruct what the output collapses
— and every one was written after that collapse cost something.**

**This entry exists because the rule above was promoted to this preamble hours before its limit was
found**, which is the boundary problem this register recorded the same evening: a rule *correct in
the case that produced it*, read later by someone with no access to that case. **The limit belongs
beside the rule, not after it in a message.**

### THE SHARPENED LENS: NOT "IS THIS RIGHT" BUT "IS THIS RIGHT AT THE MOMENT IT IS FIRST READ"

**Review's formulation, 2026-08-14, after finding two defects in a plan it had already reviewed
twice.** This register's standing lens is *does this output distinguish working from broken* — ~25
instances. **That lens passes both of the defects below**, which is why it needed sharpening rather
than restating.

    T-0011 criterion 3   asserted rule ids on omissions that criterion 4-i had established
                         can never have them.   CORRECT WHEN WRITTEN -- 4 was rewritten later
                         and 3 was not.         Fails at a REWRITE boundary.

    T-0011 criterion 5   a CI check over census records, where the plan's own opening says
                         there are ZERO censuses.  CORRECT IN STEADY STATE.
                         Green the day it ships. Fails at t=0.

**Neither criterion is wrong. Each is right everywhere except at the boundary where it will actually
first be read** — and that is the only moment that matters, because **the first reading is the one
that establishes whether anyone believes the mechanism works.** A check that is green on day one
because its input set is empty gets believed on day one.

> **So ask when, not whether.** *Is this right at a rewrite? At t=0? On an empty set? On the first
> run, by a reader who has no other evidence?*

**And Review's account of why it missed both across two prior passes is the transferable half:
"I was reading the criteria I had findings in."** A reviewer's attention concentrates where it has
already invested, so **the criteria most likely to carry an unamended contradiction are the ones
nobody objected to** — which is the unaudited-copy rule below, arriving inside a single document
rather than across two.

### WHEN A CLAIM LIVES IN TWO ARTEFACTS, FIX THE ONE NOBODY CHECKS FIRST

**Execute's formulation, in its last message before running out of context, and it is a new axis on
the stale-claim family rather than another instance of it:**

> *"I corrected exactly this claim in the work report an hour earlier and left it standing in the
> handoff. **The report has a reviewer. The handoff has a reader who inherits it as fact and has no
> way to check.** I fixed the audited copy and left the unaudited one."*

**Everything else here is about WHEN a claim goes false** — B34's overnight invalidation, B11's
within-hours, the rule that recent entries are the least safe. **This is about WHERE it sits when it
does, and the two are independent:**

    same claim, two homes
      work report   an AUDITED copy   — a reviewer re-derives it, so an error surfaces
      handoff       an UNAUDITED copy — a fresh reader inherits it as fact, and nothing points at it

**Correcting the audited copy feels like correcting the claim**, because that is where the correction
gets read back and acknowledged. **The unaudited copy is the one that survives into the next
session's assumptions** — and it is precisely the copy nobody re-derives: no register entry, no CI
row, no test.

**Three instances the same night, and in all three the copy that stayed wrong was the copy with no
reviewer:** **B45**'s complete quotation versus its unmarked scope · **B50**'s `COVERAGE_NOTE`
pointing at a register entry that did not say what it claimed · the work report versus the handoff.

> **So: fix the unaudited copy first.** The audited one has a mechanism behind it and will be caught.
> The unaudited one has only whoever remembers it is there.

### And it keeps appearing in this register itself

**Not as irony — as evidence that accuracy is not the property that prevents it.** B45's quotation
was verbatim and complete. B49 was filed twice under one number, both correct. B43 read its own
example through an alias face whose status no canonical rule holds. **Both staleness sweeps had it
in their first version.** Every one of those was individually accurate, which is exactly why nothing
caught them.

This exists because of a specific failure: a problem was described as "noted"
when it had only been said out loud and never recorded. A conversation scrolls
away. Claiming something is written down when it is not is worse than saying
nothing, because it stops anyone else from writing it down either.

Two things that make entries worth having:

* **Verify before you write.** Checking one such claim showed the claim itself
  was wrong *and* uncovered a more serious defect underneath (B4 — a startup
  race that silently disconnects the broker). A register full of guesses is a
  register nobody trusts.
* **Say what it could break, not just what it is.** "X is unset" is a note;
  "X is unset, so a reboot silently drops the broker and the dashboard shows
  nothing" is a decision someone can act on.

Fixed something? Delete its entry in the same commit as the fix. A register that
only grows becomes wallpaper.

**ONE EXCEPTION, LEARNED 2026-08-13: delete-on-fix is right for DEFECTS and wrong for
RECURRING STATES.** B24 was *"the dominance fix is merged and not deployed"*. It was
correctly deleted when that fix shipped — and **the same category recurred within
hours** as B37, with nothing holding the space in between. A state that will be true
again should be a **standing entry that is narrowed**, not one that is deleted and
rediscovered. "Merged, not deployed" is the worked example: narrowed to whatever is
currently merged-and-undeployed, it catches the next one without anyone noticing the
gap.

---

## A. Wrong numbers — these can mislead a decision

### A10. The engine does not trade the Magic Strategy — it trades the pre-contract ICT strategy, and one of its gates is explicitly forbidden
**Found in:** conformance audit of the live path against `RULE_REGISTRY.json` v1.2.0,
2026-08-08, asked as "is the platform trading the delivered strategies?"

**RE-VERIFIED END TO END 2026-08-13 (T-0002). A10 was understated, not overstated
— see `docs/CONFORMANCE_AUDIT_2026-08.md`, which is re-runnable.** This entry was
written by reading the source; the audit measured it from production records and
reached the same verdict by a second route, plus three things this entry did not
say:

* **`scripts/audit_live_conformance.py` prints the number.** 392 decisions, 12
  ever acted on, and **0 registry rule ids cited on any of them** — mutation-proven
  with `--self-test` before the zero was trusted. The claim is now a command
  rather than a paragraph.
* **The live path could not cite a rule even if it evaluated one.**
  `decision_records` has no rule-id column; `telemetry_records` has
  `deciding_rule_id` as a first-class column. The gap is in the schema, not only
  in the wiring.
* **Every live trade since the shadow began was one Salim's engine refused.**
  3 of 3, matched sub-second on the same instrument, the contract engine ruling
  `STAND_ASIDE` citing GATE-036 each time. And **all 22 entries taken before
  2026-08-13 23:05:30Z were triggered from 1H**, an analysis-only timeframe under
  GATE-017/019 — measured from records, not from `ENTRY_TF`. **That number is final:
  the set is closed by the switch to 5m, so no 23rd can join it.** (Reported as 12 at
  audit time and 20 an hour before the switch; both were true when written, which is
  why this one is pinned to a boundary rather than a date.)

**Do not cite the 96.9% agreement between the two engines as conformance.** They
agree only because both declined, for unrelated reasons: the contract engine is
blocked by GATE-036 on 100% of bars because the correlate panels are unwired
(B11). It is not judging the setups; it cannot see them.

**GATE-001 / GATE-002 are the entry's own argument in one line:** implemented,
tested, counted in the 35/117 — and violated on every bar, because nothing calls
them.
**What it is:** the live loop's only entry decision is
`crypto_loop._tick_symbol` → `strategy_step.evaluate_latest_bar_traced`. That function
cites **zero** rule ids. It is the v1 ICT edge (daily-BOS bias → LTF BOS → FVG retrace),
written before the package arrived and unchanged since.

The contract work that exists is real but **not connected to anything that trades**:

| Built | Wired into the live path |
|---|---|
| `app/services/rules/` — 33 of 117 rules (GATE-023, PRIM-001…006, and M4's graders) | no — only tests and `check_rule_coverage.py` import it |
| `app/services/telemetry/` — contract records, validation, append-only store | no — the loop writes `decision_records`, not the contract's three record types |

So **33/117 rules implemented, 0/117 evaluated on any trade**, and 32/91 HARD_GATEs
implemented but 0 evaluated.

M3 and M4 both landed on 2026-08-08 — the primitive layer (PRIM-002/003/004/006) and then
the graders (GRADE-001…009, GATE-001/002/003/004/005/006/007/008/009/048). Coverage moved
3 → 7 → 33. **Neither narrows this entry**, and the gap between the two numbers above is now
the whole problem: a grader nothing calls changes no decision, and building more of them
does not close a gap that is architectural rather than volumetric. See
`MAGIC_STRATEGY_EXECUTION_PLAN.md` — no milestone in the original M0–M8 map ever switches
the live loop over.

**Where the running engine actively contradicts a HARD_GATE:**

* **GATE-037** — ~~the premium/discount entry filter~~ **CLOSED 2026-08-09.** The
  filter is deleted from `strategy_step.py` and `backtest/engine.py`, the equilibrium
  midpoint is no longer computed on the decision path, and `use_premium_discount` is gone
  from the feedback loop's tunable knobs. HG-16 now exists as
  `tests/integration/test_conformance_gate_037.py` — the first of the 78 conformance
  assertions to be a test. It checks the emitted records AND the source of the decision
  path, because a filter that simply never fired on the sampled data would pass the first
  check alone while waiting for the market that trips it.
* **GATE-032 / GRADE-017** — risk is the 9-cell `box_grade × disturbance` lookup
  (1.50/0.75/0 · 1.25/0.50/0 · 1.00/0.25/0). We size every trade at a flat 1% —
  `live/fixed_config.py` pre-registers `RISK_PCT` and deliberately makes it not a knob.
  Neither grader exists, so the lookup has no inputs even if it were wired.
* **GATE-001 / GATE-002** — heavy-disturbance hard skip and the disturbance classifier.
  Not implemented; nothing blocks a trade on correlate disagreement.
* **GATE-008** — roster is `BTCUSDT.P · ETHUSDT.P · TOTAL · USDT.D`. We trade `BTC/USD`
  and `ETH/USD` off Binance **spot**, and read no correlate panel at decision time (this is
  the A3 axis, restated as a rule violation).
* ~~**GATE-017 / GATE-019** — 1H is analysis only~~ — **CLOSED 2026-08-14 (T-0007).**
  `ENTRY_TF` is now `"5m"`, and the guard that never existed exists:
  `test_fixed_config_timeframes.py` fails if it is ever set to an HTF, and fails
  separately if `BIAS_TF` stops being higher. GATE-017 is a HARD_GATE and **nothing had
  ever enforced it** — the only prior `tests/` hit was a docstring mention, rationale
  rather than coverage. The violation is historical, and **every one of the 22 entries
  in the corpus still carries it.**
* **EXIT-001 / GATE-022** — 70% at 2R, 30% runner, everything flat at 19:00 New York.
  The live signal carries a single TP at `rr_partial`-R and there is no session close;
  the 70/30 machinery exists only inside the backtester.
* **GATE-025 / 026 / 027** — five-anchor stop ladder, 2R floor, no-trade if nothing
  clears 2R. We use one anchor (swing or FVG edge, ATR-buffered) and never test an RR floor.

**Why it matters:** the platform is producing paper trades, a win rate and an equity
curve from a strategy that is not the one it was given, while the repo now contains a rule
registry, a telemetry store and a coverage script — the furniture of conformance. Anyone
reading the engine page, or `check_rule_coverage.py`'s "PASSED", can reasonably conclude
the delivered strategy is what is being measured. It is not, and no runtime signal says so:
the loop stamps `engine_version: "ict-v2-lookahead-fixed"` and nothing anywhere refuses to
trade for want of a rule.

**Also note:** `backtest/engine.py:378` applies a filter it names **"Magic Alignment
(first-order)"** — agreement with BTC's own daily bias. That is invented machinery under a
contract name; the real GATE-008/GATE-002 alignment is a four-panel roster with a
disturbance count. It is backtest-only and never reaches the live path, but the name will
be believed.

**Fix:** this is M3–M8 of `MAGIC_STRATEGY_INTEGRATION.md`, not a patch — 88 further hard
gates, and the graders in §2.4 that nothing can test automatically. Two things are worth
doing before any of it: ~~(1) drop the GATE-037 premium/discount filter~~ — done,
2026-08-09; (2) make the live path emit
contract telemetry with `deciding_rule_id`, so "which rule stopped this trade" has an
answer other than "none of them". Until the roster, the disturbance grader and the risk
matrix exist, the engine cannot cite a rule for its position size, which is readiness
gate 5's floor.

### A3. Backtests still measure a different venue than they trade
**Found in:** Phase 4 planning; **narrowed by 4.4**
**What it is:** the LIVE path can now read CFT's own candles
(`PRICE_SOURCE=cft`), so live analysis and execution finally agree. Historical
backtests cannot: CFT serves only ~125 days of 1H history against the ~470 the
corrected backtest window needs, so backtests stay on Binance.
**The divergence is now measured rather than unknown** (300 matched 1H bars):

| | BTC | ETH |
|---|---|---|
| close vs Binance | −0.0485% (stdev 0.0093) | −0.0485% (stdev 0.0090) |
| bar-range difference | mean 0.013%, max 0.060% | mean 0.014%, max 0.117% |

The close offset is a near-constant BID-side spread and moves no structure —
BOS/FVG/direction are scale-invariant. The **bar ranges** are the real risk: a
high or low differing by up to 0.117% can create or erase the FVG an entry
depends on.
**Why it still matters:** a backtest result on Binance bars is not strictly a
prediction of CFT behaviour, and the gap is largest exactly where the strategy
is most sensitive.
**Fix options:** accept and disclose it (the divergence is now quantified); or
start archiving CFT candles now so that in ~1 year a same-venue backtest becomes
possible. Archiving is cheap and the history is unrecoverable if not collected —
the same argument as the dominance collector.
**SECOND AXIS, added by the Magic Strategy M0 work:** the strategy's roster names
`BTCUSDT.P`, the Binance PERPETUAL, and everything we have ever measured — the
corrected baseline, the CFT comparison above, every backtest — was computed on
Binance SPOT. Measured over 500 matched 1H bars, the perp extends beyond the spot
bar on **497 of 500 (99%)**, with a median bar-range difference of **2.89%** of
the bar's own range — two orders of magnitude larger than the CFT divergence in
the table above.
**Why it matters:** adopting the perpetual (see `MAGIC_STRATEGY_M0_CONTRACT.md`
§1.1) is correct for fidelity to the documented strategy, but it means the
existing baseline and `scripts/baseline/reference_trades.csv` describe a
different series from the one the engine will run on. They do not carry over.
**Fix:** re-run the corrected baseline on perpetual bars before comparing any new
result to it, and mark the spot-era baseline as belonging to a different venue
rather than deleting it.

### A6. The CFT order body has never been accepted by CFT
**Found in:** 4.5
**What it is:** the order path is built and tested, but only against a MOCK. Its
endpoint map was reverse-engineered from CFT's web terminal by network capture,
so the field names are inferred, not documented — `stopLoss` vs `sl`,
`volume` vs `lots`, whether `instrument` is required alongside `symbol`.
**Why it matters:** a mock accepts whatever it is given. The first real order is
therefore also the first test of the body shape, and the plausible failure modes
are not symmetric: a rejected order is harmless, but a *partially* accepted one —
filled with the stop-loss field silently ignored — is an unprotected live
position.
**Fix:** the first live order must be placed manually, at minimum size, with a
human watching, and the result compared against what the adapter expected. That
is precisely the Tier-3 decision `ALLOW_LIVE_TRADING` exists to force; do not let
the first real order be one the engine placed on its own.

### A7. Two flags must be set to trade, and nothing warns if only one is
**Found in:** 4.5
**What it is:** enabling live orders needs `ALLOW_LIVE_TRADING=true` on the api
AND `BRIDGE_ALLOW_TRADING=true` on the bridge. That is deliberate — one mistake
cannot arm a funded account. But the halfway state is silent.
**Why it matters:** with only the api flag set, the engine believes it can trade
and every order fails at the bridge with a 403. The reason is now clear in the
message (fixed in 4.5), but nothing surfaces the mismatch *before* an order is
attempted.
**Fix:** show both flags on the dashboard's broker panel — `trading_enabled` is
already reported by `/status` on the bridge and flows through
`/api/brokers/accounts`. Small piece of UI.

### A5. The engine still runs on Binance prices, not CFT's
**Found in:** 4.4; **made switchable by 2.2**
**What it is:** the live loop still reads Binance. CFT prices are now selectable
from the New-run form on the engine page — no env change or redeploy — but
nobody has selected them.
**Why it matters:** until it is switched, live analysis reads a different venue
than it would trade on. Measured: closes differ by a near-constant −0.0485%
(harmless — structure is scale-invariant) but individual bar RANGES differ by up
to 0.117%, which can create or erase the FVG an entry depends on.
**The trade-off to weigh first:** CFT bars arrive through the browser bridge, so
the engine gains a dependency on it, and CFT serves only ~125 days of 1H history
against Binance's years — a restart rebuilds less context.
**The engine page can no longer switch it.** With the settings frozen, the
price source is `fixed_config.PRICE_SOURCE` and changing it is a code change
plus a deploy. That is the deliberate cost of one configuration for every run.
**Sharpened now that the prop-firm simulator is the default:** the challenge
simulation runs its rules — $250 daily loss, $500 drawdown on a $5,000 account —
against decisions taken on BINANCE bars. A simulated breach is therefore a
statement about what would have happened on Binance prices, not certainly about
what CFT would have done. The gap is small and measured (table in A3) but it is
largest exactly where an entry is marginal.
**Fix:** set `PRICE_SOURCE = "cft"` in `backend/app/services/live/fixed_config.py`
and redeploy, once the browser-bridge dependency and the ~125-day history limit
are acceptable.

### A4. LTF-BOS gate is mildly non-causal
**Found in:** inherited (residual #1)
**What it is:** `bos_dir_upto` uses full-series `smc` `broken_index`, which is
derived from swing detection that can see later bars. Measured impact: ~3% of
entry-eligible bars.
**Why it matters:** it is a filter, not a direction source, so the effect is
bounded — but it means fine-grained edge numbers are not fully trustworthy.
**Fix:** decide whether to make it causal *before* trusting detailed results;
doing so shifts the baseline you compare against.

---

## B. Silent failure — things that break without telling anyone

### B41. The detector built to catch B34 was written, documented, schema'd, tested — and never called
**Found in:** T-0010 verification, 2026-08-14, by the Manager while checking my change.
**A new species. Every prior entry in this section is an output that fails to
discriminate. This is a detector that was never wired** — and it is invisible for the
same structural reason as all of them: **a record type that is never emitted looks
exactly like one with nothing to report.** Zero census records reads as "no coverage
problems" to anyone querying the store.

**What it is.** `records.py:303` defines `scan_census`, whose own docstring names this
exact failure as its reason for existing:

> *"Build a `scan_census` — THE POPULATION RECORD. This is the one that stops a
> filtered sample being reported as full coverage. Every unemitted bar must name the
> registry rule id that authorises the omission; any pre-filter citing no rule is
> undocumented logic by definition, and is the cheapest way to score 100% fidelity
> while running on something nobody has seen. Under our emission policy
> (`every-closed-bar-roster-v1`) `unemitted_bars` should always be empty. **If it is
> ever not, that is the finding.**"*

**B34 is that finding** — a filtered sample reported as full coverage, for the
platform's entire history. The designated auditor never showed up:

```
registered  models/telemetry_record.py:41   RECORD_SCAN_CENSUS constant
            services/telemetry/store.py:31  id-field key map
            services/telemetry/validate.py:25  accepted record type
            contract/TELEMETRY_SCHEMA.json:2690  full schema definition
            services/telemetry/records.py:303   the builder
callers in app/   NONE
production        156 records, ALL setup_evaluation. ZERO scan_census, ever.
```

**Three layers of intended guard, none load-bearing.** The docstring cites
`every-closed-bar-roster-v1` — **the emission policy id that was false**, retired to
`...-with-sufficient-history-v2` in T-0010. The schema (line 128) says *"C-13
reconciles emissions against the scan_census under this policy."* **`C-13` does not
exist** — zero references in `app/`, `tests/`, `scripts/` or `docs/` outside the schema
sentence describing it. So: a false policy, verified by a census never emitted, checked
by a conformance rule never written.

**The part that makes it worse than "nobody got to it": the tests pass.**
`test_telemetry_contract.py:209` and `:226` both call the builder, both green. **Green
tests on a never-invoked builder are worse than no tests** — they make the mechanism
look wired. And the second test is the sharpest artifact here:

```python
def test_the_census_defaults_to_claiming_no_omissions(declared):
    census = rec.scan_census(..., bars_observed=19, evaluations_emitted=19)
    assert census["unemitted_bars"] == []
```

**It hand-passes the two numbers in equal and asserts the record says so.** It
constructs the coverage claim the census exists to *check*. It cannot fail on B34,
because B34 is `bars_observed != evaluations_emitted` in production and **no production
code has ever computed either number.** The test's own docstring asserts the truth of
`every-closed-bar-roster-v1` — a claim that was already untrue when it was written.

**And the schema says exactly what that fixture is.** `TELEMETRY_SCHEMA.json:2764`,
on `unemitted_bars`:

> *"The **honest zero-suppression case** is an engine whose `emission_policy_id` is
> `EVERY_CLOSED_BAR...`, for which this array is empty and **`bars_observed ==
> evaluations_emitted`**."*

**The schema offers that as a description of what an honest engine looks like. The test
used it as a fixture.** It instantiated the canonical honest case, by hand, and checked
the record reported it faithfully — while production was the dishonest case and nothing
measured the difference. The invariant named there is the one property worth verifying,
and the test asserts it **by construction** instead of deriving it.

**FOURTH LINK, AND IT IS THE WORST ONE, BECAUSE IT SHIPPED.** `store.py:131`
`count_by_type` is live code — called, working — and its docstring reasons about a
reconciliation that has never happened:

> *"a census that does not reconcile against the evaluations it counts means the
> population is not what it claims."*

**The other three links were unbuilt: a false claim, an unemitted record, an unwritten
rule. Absence is at least honest.** This one is a shipped, running function telling any
developer who reads it that the reconciliation is a thing this system does. **An unbuilt
guard is absent; a shipped function documenting an absent guard is actively
misleading.** Its own filter is `run_id` only — no window, no instrument, no timeframe —
so it cannot perform the reconciliation it describes even in principle.

**And the time column needed to build it is a trap, measured on production records:**

```
timestamp_ny  2026-08-13T20:35:00-04:00   <- BAR OPEN time. A str, NY-local.
created_at    2026-08-14 00:40:18Z        <- WRITE time. Real datetime, UTC.
```

The bar stamped `20:35` closes at `00:40Z` and the row is written ~20 s later, so
**`created_at` ≈ bar time + one full bar period.** At 5m the write lag *is* the bar
interval. Filtering the census window on `created_at` therefore shifts it by **exactly
one bar at every boundary, deterministically** — not drift, a systematic off-by-one.

**That produces a phantom MAJOR rather than a silence, which is worse than it sounds.**
`bars_observed` derived from the bar series would exceed `evaluations_emitted` derived
from a shifted window by one, every window, forever. Criterion 4 of T-0011 calls an
omission with no `rule_id` *"undocumented logic (C-13, MAJOR)"* — so the census would
raise a MAJOR at every boundary, caused entirely by its own filter. **An alarm that
fires every cycle gets muted, and a muted alarm is the silence we started with.**

`timestamp_ny` is the correct field — it is bar time — but it is a **string in NY-local
time** while the builder takes UTC datetimes, so the window must be converted, not
compared. Note also that its lexicographic order **inverts across the autumn DST
fall-back**, when local time repeats: `01:59-04:00` sorts after `01:00-05:00` while
being an hour earlier. One night a year, on a 24/7 market.

**Fix (not folded into T-0010 — this is a mechanism to wire, not a line to move).**
Call the builder once per scan window with `bars_observed` and `evaluations_emitted`
derived from the loop's actual counters, never passed in agreeing; write C-13 to
reconcile them; make a zero-census store a FAIL rather than a silence. **The test must
be rewritten to compute the numbers from a fixture where they disagree** — as written it
would pass against an engine that emits nothing at all.

**What it means for T-0010.** *"The shadow now sees every bar"* is currently
**asserted**, proven once by `test_shadow_sees_blocked_bars.py`. The census is what
would measure it continuously and name the first bar it misses. **T-0010 proves the fix
once; the census proves it every hour.** Related: **B34** (the filtered sample),
**B32** (nothing reports whether the shadow records at all), **B13**.

**NARROWED, NOT CLOSED — T-0011, 2026-08-15.** All three layers now exist. The reason this
entry stays open is stated before the fix, because the fix is the part that reads as closure:

* **No census has been emitted in production yet.** The offline work is complete and pushed;
  the deploy is Malek's. Until a real session date rolls over on the live engine, the caller
  is code that has never run against production, which is a weaker claim than B41 needs to
  be closed by. **The first census is the finding, and it does not exist yet.**
* **C-13 is implemented as its reconciliation clause only.** `census.reconcile()` answers
  "does this census add up, and is every shortfall accounted for". The schema's other
  mentions of C-13 (cross-record joins from a census to the evaluations carrying its
  `scan_id`) are not built. Naming it "C-13, done" would be this entry's own species.
* **CI exercises the check with a SELF-TEST, not a corpus.** There are no censuses in CI and
  none in production, so a corpus run would examine zero and report green — the exact
  silence this entry is about. What CI asserts is that the checker CAN bite; whether it
  DOES is `--api --require-records`, which is a question about production.

**What was built:** `backend/app/services/telemetry/census.py` — both counts derived from
outside the emitting loop (bars from the series, evaluations from stored rows filtered on
PARSED bar time), the missing set computed by difference, and `reconcile()` as C-13.
`crypto_loop._maybe_emit_census` is the caller, firing on NY session rollover.
`scripts/check_census_reconciliation.py --self-test` is the CI step.

**And the ruling that changed the design, because it is the durable part.** The first design
put each omission in `unemitted_bars` with a sentinel `rule_id`. `unemitted_bars.items`
REQUIRES a `rule_id` matching the registry pattern, so an omission caused by a FAILURE cannot
be represented there without inventing a rule — see **B65**. The Manager ruled: the array
stays empty, the counts go in `notes`, and **the resulting imbalance is left standing rather
than absorbed**, because *an empty array with a silent mismatch is exactly the honest-looking
census this task exists to prevent*. Related: **B34**, **B64**, **B65**, **B66**, **B68**.

### B42. `shadow.py` carries two comment blocks that contradict each other about whether the perpetuals feed exists
**Found in:** 4.5, **2026-08-14** (manager, while tracing where the engine takes its data
from). *Date added so `agents/stale_sweep.py` can bound this entry — with a version alone it
reported NOT EXAMINED, which is not a clean bill and read like one.*
**Severity:** low as behaviour, moderate as documentation — it misdirects the next reader
of the exact file it lives in

`shadow.py:66-77` still describes the **pre-T-0008** world, in the present tense:

> *"We do NOT have the other two: `BinanceSource` reaches only spot … and **no code in
> this repo calls `fapi.binance.com`**."*
> *"So the layout is read with two of four panels and **GATE-008 fails, naming the two
> that are absent**. That is the honest steady state…"*

**All three claims are now false.** T-0008 added `binance_perp.py`, whose `_BASES` is
exactly `("https://fapi.binance.com",)` (`:50`). GATE-008 does not fail — verified on the
live engine at `tf=['5m'] G8=PASS G2=PASS den=3`, a complete four-panel read.

**The contradiction is thirteen lines apart in one file.** `:90` opens *"The other two,
from a different host and a different instrument family (T-0008)"* — the correct,
current statement — directly beneath the block saying they cannot be had.

**Why it is worth an entry rather than a quiet edit.** The stale block is not decoration:
it is the *reasoning* a maintainer would consult before touching the roster, and it argues
for accepting a two-panel failure as "the honest steady state". A reader who trusts it
concludes the disturbance grade is unavailable and may re-derive a workaround for a
problem already solved — or read a real future GATE-008 failure as the documented normal.

**What must NOT be deleted with it:** the paragraph at `:78-83` — *"SPOT WAS NOT
SUBSTITUTED FOR PERPETUAL, DELIBERATELY"* — is **still true and still load-bearing**, and
is the reasoning that kept a plausible-but-wrong disturbance grade out of the risk matrix.
Only the "what is actually missing now" block is stale.

**Fix:** rewrite `:66-77` to say the feed was acquired in T-0008 and the roster now reads
four panels, keeping `:78-83` intact. **Not a product-code edit the Manager should make.**

> **ASSIGNED TO T-0011 BY ID, 2026-08-14 — and the reason is this entry's own first attempt
> failing.** It originally read *"noted for whichever rules task next touches `shadow.py`,
> since GATE-017/019 will."* **GATE-017 and GATE-019 landed in T-0012 at `ab7dc77` and did
> not touch `shadow.py`** — verified: that commit changes `base.py`, `__init__.py`, three
> rule modules, one test and the coverage script. **So the deferral had no owner from the
> moment the prediction failed, nothing reported that it had failed, and the entry was still
> open when a staleness sweep surfaced it as one of two entries no dated check could
> examine.**
>
> **DEFER BY TASK ID, NEVER BY PREDICATE.** *"Whichever task next touches X"* has no owner
> the instant the prediction is wrong. **Third instance in one day:** the same shape produced
> **T-0015** (perpetual-panel staleness, deferred to *"whichever task next touches
> `data_health`"* — which turned out to be the task that correctly refused it) and the
> census's C-13 residue.
>
> **T-0011 is the owner** — it will be in `shadow.py` for criterion 4's omission paths — **and
> the edit is required whether or not that turns out to be true.**

**The pattern, which is the reason to record it at all:** this is the *third* time a
comment in this repo has outlived its fact — `BLOCKED_ON_CORRELATES`' own header (`:61-64`)
records the previous instance, where code sat waiting for CryptoCap after CryptoCap was
replaced. **A resolved blocker leaves its explanation behind, and the explanation keeps
being read as current.** Related: **B21** (stale artefact read as live), **A3** (the
spot-vs-perp venue divergence this block is reasoning about).

### B43. `status: READY` does not mean the rule is quantified — the OPEN flag is not a reliable signal
**Found in:** 4.5 (manager, scoping T-0012)
**Severity:** moderate, and it scales with the rules programme — it governs how 57 tasks are
written

**The project's fifth standing rule is that the 14 `status: OPEN` rules each need a DECLARED
PARAMETER stamped as ours, never an invented threshold. `status` has been the only signal for
which rules those are. It is not reliable.**

**GATE-041 is `status: READY`, `enforceability: HARD_GATE`, and its own statement says:**

> *"The switch to Reverse requires 'multiple structural confirmations' drawn from seven … **HOW
> MANY of the seven, and whether any is mandatory (e.g. the micro MSB), is never stated.**"*

**So its central threshold is unstated and nothing in the registry flags it.** An implementer
following `status` would write `>= 3 of 7`, ship a fully green HARD_GATE, and the invented
quorum would be indistinguishable from a ruled one. **`READY` is the more dangerous case than
`OPEN` precisely because it carries no warning.**

**GRADE-035 is a second instance, and worse in a different way.** It is `CALIBRATED`, and its
notes say *"No minimum duration or consolidation criterion is ruled … do not harden them into
a rule without a ruling"* — while its **statement quotes two durations**, *"around 2 days"*
and *"around 24H"*. **The forbidden numbers are in the text and the prohibition is in a
different field.** An implementer reading top-to-bottom writes `timedelta(hours=24)`.

**Why this is a register entry and not just a plan note.** It changes the shape of every
remaining rules task: **the declared-parameter check must read the statement and notes for an
admission of an unstated threshold, and must not trust `status`.** If the affected set is
large, **the "14 OPEN rules" figure understates the declared-parameter work substantially** —
and that figure is quoted in `PROGRAMME_TO_CUTOVER.md` as a scoping input.

**MEASURED, and reported as a floor rather than a count.** Review's sweep:

    READY/CALIBRATED rules whose own text admits an unstated quantity :  12
      ...of which HARD_GATE                                          :  10
    registry `status: OPEN` count                                    :  14
    -> declared-parameter work is ~26, not 14

The ten HARD_GATEs marked READY with an admitted hole: **GATE-004, GATE-022, GATE-027,
GATE-038, GATE-041, GRADE-013, GRADE-019, GRADE-029, GRADE-031, TARGET-005.**

**CORRECTED 2026-08-14 (Review, during the T-0012 review). THE TEN ARE NINE.** `GRADE-029` is
`alias_of GATE-041` and **both faces are in that list**, so one rule was counted twice. The
distinct figure is **9 HARD_GATEs**, and the derived total is **~25, not ~26**. The thesis is
untouched — it was always reported as a floor — but the number was quoted as an absolute, and
absolute counts are what aliases break.

**The rule for auditing the rest of this register's counts, because it is not "collapse
aliases everywhere":** an alias collapse **only reduces a count when BOTH faces appear in the
list.** `GATE-041` + `GRADE-029` both appear, so the count drops by one. `GRADE-035` appears
alone, so collapsing it to `GATE-040` **renames the entry without changing the total.** A
sweep that collapses indiscriminately will under-count exactly as badly as one that does not
collapse at all.

**AND THIS ENTRY'S OWN THESIS HAS A STRONGER INSTANCE THAN THE ONE IT ARGUES FROM.** Measured
across all 13 alias pairs, exactly one disagrees:

    GRADE-035   CALIBRATED   ->   GATE-040   READY

**One rule, two ids, two different statuses.** This entry says *"`status` has been the only
signal for which rules need a declared parameter, and it is not reliable"* — and cites
GRADE-035 as *"a second instance… It is `CALIBRATED`"*, **which is the alias face; the
canonical says `READY`.** So the example was read through the less reliable of two
disagreeing answers, which is the entry's own point arriving one level down. `rule_waves.py`
now reads status at the canonical after collapsing and exits non-zero on any alias/canonical
disagreement — currently that one pair.

**EVERY OTHER ABSOLUTE REGISTRY COUNT AUDITED, and the load-bearing one survives.** Applying
the both-faces rule across the whole registry:

    status OPEN        14 ids   14 distinct   no alias faces at all   SAFE
    status READY      100 ids   89 distinct
    status WITHDRAWN    2 ids    1 distinct   (B45, already corrected)
    status CALIBRATED   1 id     0 distinct   <-- see below
    HARD_GATE          91 ids   79 distinct
    ADVISORY           11 ids   10 distinct
    SOFT_PREFERENCE    15 ids   15 distinct

**The "14 `status: OPEN` rules" figure is unaffected** — none of the 14 is an alias face. That
matters more than the corrections, because it is the scoping input quoted in
`PROGRAMME_TO_CUTOVER.md` and the one this entry warned understates the work. **It understates
it for the reason this entry gives, not for an alias reason.**

**`CALIBRATED` describes ZERO distinct rules.** The status appears on exactly one id —
`GRADE-035` — which is an alias face whose canonical `GATE-040` is `READY`. So a sentence of
the form *"the CALIBRATED rules"* refers to no canonical rule at all, and **this entry's
second example is built on a status that, collapsed, no rule has.** Related: **B48**,
**B49**, **B45**.

**It is a floor, and the reason matters more than the number.** The sweep matched a fixed
phrase list, and **GRADE-035 is a 13th instance that the patterns missed** — its text reads
*"Documented durations, which the rulings OMIT rather than retire"*, which no phrase in the
list covers. **So the true figure needs reading, not matching** — the same tool class as
`edges()` reading prose. Reported as "at least 13, by a method demonstrably incomplete"
specifically so it is not trusted as a total, which is how the 14 came to be trusted.

**Consequence for the programme:** `status: READY` does not mean implementable. **Ten HARD
GATEs are READY with a hole where a threshold should be**, and each needs a declared
parameter stamped as ours — the fifth standing rule arriving ten times in a programme scoped
as 57 implementations.

**Fix, when the sweep lands:** either correct `status` on the affected rules, or add a field
that records "carries an unquantified threshold" independently of readiness — and until then,
every rules task treats the statement text as authoritative over `status`. Related: **B38**
(a parameter forced by a constraint must say so), **A10**.

### B44. 82 of 117 rules declare their inputs as DATA NAMES, so their dependencies are invisible to any rule-id graph
**Found in:** 4.5 (Review, adjudicating the prose citations `rule_waves.py` prints)
**Severity:** moderate — it does not break running code, it mis-plans the work that writes it

**Only 35 of 117 rules' `inputs` cite a rule id. The other 82 name data.** So a dependency
written as a field name is invisible to any planner that follows rule ids, and the gap is not
theoretical:

    GATE-025  output : "Full candidate table [{anchor, stop_price, rr, accepted}]"
    GATE-031  inputs : "selected_stop.rr; partial_level (2R); target price."

**`selected_stop.rr` is a field of GATE-025's output.** GATE-031 consumes GATE-025, GATE-025
consumes *"the five stop anchors from GATE-027"*, and **neither GATE-025 nor GATE-027 is
implemented.** The real chain is **GATE-027 → GATE-025 → GATE-031**, and `rule_waves.py`
reports **GATE-031 as wave 1** — the earliest slot, two producers short.

**The sharpest part, because it argues against trusting the fix that caused it:** the script's
earlier prose-following version placed GATE-031 in **wave 3, correctly**. Correcting the
definition of an edge — which was right, and which removed four false cycles — **moved this
rule from a right answer to a wrong one.** Being right about the rule did not make every
answer better.

**No second heuristic was added, deliberately.** Matching input data names against `output`
text would not catch this case: GATE-025's output names `rr`, not `selected_stop.rr`. **A
matcher that misses the instance that motivated it is worse than an honest gap, because it
reads as coverage** — this register's recurring finding.

**Mitigation, and it is a process step rather than a tool:** before dispatching any rules
task, **resolve every one of its rules' `inputs` to the rule that produces that data and
confirm the producer is implemented.** `agents/rule_waves.py --inputs <wave>` dumps the raw
`inputs` and `output` of a wave for exactly this. The script now prints the 82/117 figure and
this GATE-031 example on every run, so its waves cannot be read as complete.

**A related bug this found in the tool itself, recorded because the shape recurs:** the same
run asserted that three rules declaring `inputs: n/a` had resolved edges. **That was not a
registry contradiction — it was the planner harvesting rule ids from the explanation after
the em dash**, e.g. GRADE-018's *"n/a — a prohibition on the implementation of GRADE-017"*
and GRADE-031's *"n/a — specification-level blocker on GRADE-027, …"*. **A prohibition on a
rule and a blocker on a rule are the opposite of depending on it** — the prose-is-not-an-edge
mistake, one field over, caught by an assertion written ten minutes earlier. Fixed:
`inputs: n/a` now declares zero inputs and its explanation is treated as prose. **Waves moved
from 37/12/7/1 to 40/11/5/1.**

**Also decidable and worth keeping:** `inputs: n/a` is a *proof* of zero dependencies —
15 rules carry it. GATE-037's is *"n/a — a negative constraint on the decision record"*, so
it cannot depend on anything whatever its statement mentions.

### B45. Two HARD_GATEs depend on components the contract never specified — and two WITHDRAWN rules were being counted as work
**Found in:** 4.5 (Review on the detector, manager on the withdrawals)
**Severity:** moderate — it mis-scopes the rules programme in both directions at once

**GRADE-035 (`HARD_GATE`, `CALIBRATED`) names an input that does not exist and never did.**
Its `inputs` are *"Time and price action since the sweep; **the consolidation/overlap
detector**; the absence of fresh old-direction gaps; the NY 9:30 open marker."*

> **AMENDED after B48 — and the amendment is about this entry, not about GRADE-035.**
>
> **The quotation above is complete and accurate. This entry then addressed one of the four
> inputs, and the plan it produced dropped two of the others entirely** — see **B48**.
>
> **Nothing in the entry distinguished *quoted* from *addressed*, so the full quotation read as
> coverage.** That is why B48 took a further pass to surface: **the information was on the
> record the whole time, in an entry that had already been read.** Review's finding, about the
> register rather than the code.
>
> **Status of each input, which is what this entry should have carried from the start:**
>
> | input | status |
> |---|---|
> | time and price action since the sweep | available |
> | **the consolidation/overlap detector** | **no producer — the subject of this entry, T-0014 Part 1** |
> | the absence of fresh old-direction gaps | **available today from `PRIM-002` — dropped, restored by B48** |
> | the NY 9:30 open marker | **no producer — dropped, restored by B48** |
>
> **Standing discipline this establishes: when an entry quotes a specification, mark which parts
> it addresses.** An accurate, complete quotation is the most convincing possible form of
> "handled", and it is not evidence of handling. **This register's recurring subject is an output
> that does not discriminate between working and broken; here it is a quotation that does not
> discriminate between cited and covered.**

**There is no consolidation detector and no range detector**, in the registry or in the code.
Review checked: the only `overlap` match under `app/services/rules/` is PRIM-002's **BPR
overlap** — two opposite-direction imbalances overlapping *in price* — which is a different
concept from a post-sweep consolidation. **The word `overlap` is a false match.**

**SCOPING CORRECTED 2026-08-14 by Review, who wrote the claim.** *"In the registry or in the
code"* was checked **only under `app/services/rules/`** and stated repo-wide. There is a
consolidation notion elsewhere: `ict/detector.py:474` `detect_sd_zones` uses *"volume below
the 30th percentile (consolidation), then a strong impulse candle"* to find Supply/Demand
zones. **The substance of this entry is unaffected** — that is a volume-cluster detector
serving S/D zones on the legacy ICT path, not price-geometry range compression after a
sweep, and it is not in the registry, so GRADE-035/GATE-040 still had no producer and
T-0014 still had to build one. **But the claim was broader than the search**, which is
`B49`'s class applied to a negative: *"I did not find it"* was written as *"it does not
exist."* A negative finding inherits the scope of the search that produced it and must
carry it.

**Consequence now that T-0014 part 1 has landed: two definitions of "consolidation" coexist**
— `rules/consolidation.py` (span ≤ k × mean bar range, k declared at 3.0) and
`ict/detector.py` (volume percentile). Different purposes and different paths, so this is not
a conflict to resolve. It is `B33`'s two-vocabularies shape, and it wants one sentence in each
place saying which question it answers, so *"does this engine detect consolidation?"* stops
having two true answers depending on which file is open.

**And no `PRIM-` rule specifies ranges at all**, while `GATE-037`'s output already references
`primitives.ranges` as *"reading vocabulary"*. **So the contract references a primitive it
never defines, and a HARD_GATE depends on it.** That is a gap in the contract rather than in
our implementation, which makes it different from every other missing-rule entry here. Split
into **T-0014**, which builds the primitive before the rule.

**The same shape, second instance:** GATE-041's *"momentum begins deteriorating"* resolves to
`GRADE-028`'s `momentum_slowdown{sign1..sign4}` — **`SOFT_PREFERENCE` and unimplemented**, so
it will never arrive from the HARD_GATE programme. **A HARD_GATE blocked by a soft rule is
invisible to any plan that tracks only hard gates**, and the planner was filtering exactly
that way.

**In the other direction: GATE-034 and GRADE-033 are `status: WITHDRAWN` and were counted as
work.** Both sat in the dispatchable set, so the programme's headline *"57 HARD_GATEs
missing"* was **55 to implement plus two withdrawals** — and someone following the plan would
have built a rule the contract has retired. Fixed in `agents/rule_waves.py`: withdrawn rules
are excluded from the waves and named on every run.

**Correction to B43 that belongs here:** B43 said the ten READY-with-a-gap rules need numbers
from Salim. **For the quorum family he was already asked and declined** — GRADE-031 records
*"The trader declined to fix these"* and mandates declared, versioned parameters instead. **So
a declared parameter is the ruled outcome there, not a workaround**, and GRADE-031 is itself a
HARD_GATE: the contract's answer to its own missing numbers is a mechanism we are obliged to
build. Related: **B43**, **B44**, **A10**.

### B46. A fixture pair proves a check discriminates and cannot bound its threshold — and ~26 rules need a threshold we choose
**Found in:** 4.5 (Review, on T-0014; measurement reproduced independently by the manager)
**Severity:** methodological, and it applies to most of the remaining rules programme

**Every mutation criterion this project writes is a fixture pair: one case that must pass, one
that must fail. That proves a check DISCRIMINATES. It says nothing about WHERE THE BOUNDARY
SITS — and for a rule whose content is a threshold, the boundary is the whole rule.**

**Measured, not argued.** A naive consolidation detector — `window span ≤ k × average bar
range`, 12-bar window — over **719 real BTCUSDT perpetual 1H bars.** Review measured it; the
manager reproduced it against `fapi` independently, within 0.2 points:

    k = 2.0  ->    4/708 =  0.6%  of windows called CONSOLIDATION
    k = 3.0  ->  180/708 = 25.4%
    k = 4.0  ->  485/708 = 68.5%
    k = 5.0  ->  638/708 = 90.1%

**One parameter, no structural change, "almost never" to "almost always" — and every setting
passes the fixture pair**, because a genuine-consolidation fixture is tighter than a
strong-trend fixture *by construction*. **Nobody would question 3.0 versus 4.0 in review, and
it is 25% versus 69% of all market conditions.** At the top of the range the rule that fixture
pair was protecting is vacuous: the prerequisite passes on nine bars in ten.

**Why this is a register entry and not a note on one task.** B43 established that **~26 rules
need a parameter we declare** rather than 14. **A large share of those are continuous
thresholds**, and for every one of them the mutation discipline that has served this project
well — *"a guard is not proven until it has been made to fail"* — **is satisfied by a guard
that fires on 0.6% or on 90% of reality.**

**The mitigation, and it generalises:** for any declared threshold, **measure and report the
rate at which the guard fires over the real corpus**, and declare a bound on that rate as part
of the parameter. The rate is cheap — a single command produced the table above — and it is
what makes the declaration checkable instead of decorative.

**And one failure direction is worse than the other, which the rate also exposes.** For
GRADE-035 specifically, a false positive means calling a **slow drift** a cool-off. A slow
drift after a sweep is the **continuation** GATE-040 says the engine must assume by default, so
an over-permissive detector does not merely err — **it manufactures reversal authority out of
price action that means the opposite.** Where a threshold has an asymmetric failure direction,
say which one it is. Related: **B43** (the ~26 figure), **B38** (a forced parameter must say
so), **A10**.

### B47. A deployed change had a review verdict that existed nowhere anyone would look — and both signals for "is there a verdict" were misleading at once
**Found in:** 4.5 (Review found its own routing error; the manager found its own)
**Severity:** process, and it is the loop's own version of the defect the loop keeps finding

**T-0013 was reviewed, PASSED, and deployed — and for roughly twenty minutes there was no
verdict anywhere the Manager would look.**

**Two independent failures, and neither contradicted the other, which is why nothing alerted:**

* **The verdict was addressed to the wrong seat.** `PROMPT_REVIEW.md:164` specifies PASS goes
  `--to manager` and FAIL goes `--to execute`. Review sent the PASS to Execute. It had been
  inconsistent across the whole run — T-0004 to the Manager, T-0006/7/8/13 to Execute — **so
  the convention was documented and unfollowed, and nothing checked.**
* **The task state said `REVIEWING`, and the Manager had written that value itself.** History:
  `REVIEWING by manager 10:36:18` → `DONE by review 10:45:00`. The Manager asserted `REVIEWING`
  after 10:45 **without re-reading it** — trusting a value because it had produced it, which is
  the exact failure this register documents in code, committed by the agent maintaining the
  register.

**The shape, and it is why this is recorded rather than just fixed:** the check for *"is there a
verdict?"* consulted **two independent sources — an inbox and a state file — and both returned a
misleading answer.** Two wrong signals that happen to agree produce more confidence than one,
not less. **A single source would have been safer than two that cannot disagree.**

**Consequence:** a change that alters the live write path for every trade was deployed while its
review sat in another agent's drawer. **The review was not missing, and that is the point** —
the work was done correctly and the record of it was unfindable, which is
`B29`'s shape moved from telemetry to the message layer.

**Fixes:** Review has committed to routing PASS to the Manager per the prompt. **The Manager's
half needs no new mechanism — re-read state before asserting it, particularly state you wrote.**
No prompt change is required: `PROMPT_REVIEW.md` was already correct, which is itself the
finding — *a documented convention that nothing enforces is a convention only when someone
remembers it.* Related: **B15** (a stale registry with no verifier), **B29**, **B39**.

### B48. Two of GRADE-035's four named inputs were quoted into this register and then dropped from the work — and one of them is the sanctioned replacement for a threshold we forbid
**Found in:** T-0014 pre-review, 2026-08-14, by Review
**Severity:** moderate — it under-builds a HARD_GATE and leaves an implementer with no
sanctioned way to express a condition the rule requires

**RE-POINTED 2026-08-14 after T-0012 review, and the re-pointing is half the entry's value
now. `GRADE-035` IS AN ALIAS — the registry marks it `alias_of GATE-040`**, so this entry was
filed against a rule id that cannot be implemented: `base.py`'s `__init_subclass__` raises on
any class claiming an alias, *"the alias is registered automatically, so claiming it directly
hides the rule it restates."* T-0014 was rescoped to `GATE-040` on this finding.

**And the two ids DECLARE DIFFERENT INPUTS, which is the durable problem this entry now
carries:**

    GATE-040   Time and structure since the sweep; the seven confirmation
               conditions (GATE-041); the HTF directional bias.
    GRADE-035  Time and price action since the sweep; the consolidation/overlap
               detector; the absence of fresh old-direction gaps; the NY 9:30 open marker.

**Same rule by declaration, different declared dependencies.** So implementing `GATE-040`
registers `GRADE-035` as covered **while three of GRADE-035's four inputs still do not
exist** — the exact three below. **An alias inherits coverage but not its own input list**,
and nothing checks the union. Now T-0014 criterion 4c: satisfy the union of both lists, or
record per input which is unmet and why; a green coverage line for `GRADE-035` must not be
reachable while the detector, the fresh-gap check and the 9:30 marker are all absent.

**Applying B49 to this entry: the finding below is sound and its referent was wrong.** Read
every "GRADE-035" that follows as "the GATE-040/GRADE-035 pair, whose GRADE-035 face declares
these inputs."

**`B45` quotes GRADE-035's `inputs` in full and then scopes the task to one of the four.**
The registry says: *"Time and price action since the sweep; the consolidation/overlap
detector; **the absence of fresh old-direction gaps**; **the NY 9:30 open marker**."* B45's
attention went entirely to the missing consolidation detector — correctly, it is the largest
gap — and **T-0014's plan inherited that scoping**, treating cool-off as two components
(consolidation, momentum slowdown) rather than four. The other two are in neither the plan's
criteria nor its Out of scope.

**"Absence of fresh old-direction gaps" is buildable today, and it does a job we are
currently asking an unratified knob to do.** `PRIM-002` is registered and its `Imbalance`
carries `direction` and `formed_index`/`bar_time` — fresh and directional, already there.
**A drift still printing fresh old-direction gaps is not a cool-off**, and that test needs no
threshold at all. T-0014's own Risks section names the continuous knob as *"the largest
single risk in the task"* — `k` from 3.0 to 4.0 moves the consolidation rate from **25% to
69%** with no fixture failure — and asks a price-geometry detector to reject slow drift.
**The rule's own named input rejects it structurally.**

**The NY 9:30 open marker has no producer anywhere.** Checked: no `9:30`, `session_open` or
`market_open` under `app/`; `app/services/telemetry/ny_time.py` provides `to_ny`, `iso_ny`,
`now_ny` and `NY = ZoneInfo("America/New_York")` only, and GATE-023 uses it for offsets.
**So a session-open marker is a missing producer in the same class as `GRADE-028`** — but it
was never recorded as one, because B45 stopped at the detector.

**Why the second one is worse than a missing input usually is.** T-0014 forbids hardening the
documented durations — *"`if elapsed >= timedelta(hours=24)` is a forbidden implementation…
`elapsed_duration` is recorded, not compared"* — and that prohibition is right. But **the
statement's own operationalisation of that duration is the session marker, not the clock**:
*"it takes around 24H to cool off… then the price shifts at 9:30AM in the morning the next
day."* A session boundary is not a duration comparison, so it does not collide with the
prohibition. **Forbidding the clock while its sanctioned replacement has no producer leaves an
implementer who needs a time component with nothing legitimate to reach for** — which is the
condition under which the forbidden comparison gets written anyway.

**The generalisable shape, which is why this is an entry and not a plan comment:** a register
entry that quotes a full input list and then scopes work to the worst item **reads afterwards
as if the list were covered.** B45 is accurate in every word and still produced a plan missing
half the rule's inputs, because nothing distinguishes *"quoted"* from *"addressed"*.

**Fix:** enumerate a rule's inputs as individual components with a producer id or `None` each
— the shape T-0012's `ConditionReading`/`CONDITIONS` already uses for GATE-041 — so an input
with no producer is a recorded `None` rather than an omission nobody can see. Then a session
marker gets built or gets tracked. Related: **B44**, **B45**, **B46**, **B43**.

### B49. A true claim about the wrong subject passes verification by construction — the two-seat loop cannot catch it
**Found in:** T-0012 carrier exchange, 2026-08-14, by Review and the Manager (one error each)
**Severity:** moderate — it is the only defect class so far that the review loop is
*structurally* unable to catch, rather than one it happened to miss

**What happened.** Review reported *"criterion 9's typed carrier exists — `ConditionReading`
at `gate_041_reverse_switch.py:81`"*. The carrier for criterion 9 is **`DeclaredQuorum`**;
`ConditionReading` serves criterion 10a. The Manager verified the report — `ConditionReading`
exists, is shared, enforces its invariant both ways — **and every one of those facts is
true.** An amendment then went to Execute pointed at the wrong carrier, and would have moved
`DeclaredQuorum` out of the rule that owns it.

**Why this one is different from the rest of this register.** The two failures compose into
something neither contains:

* **Review asked the wrong question and answered it truly** — *"does a typed carrier exist"*
  rather than *"does criterion 9's carrier exist"*. The claim is left **true**.
* **The Manager verified the claim and not the referent.** A verification step naturally has
  the fact in front of it and **not the question the fact was offered as an answer to.**

**So the check cannot fail.** Review's error survives verification *because* verification
tests truth, and the error is in the mapping from fact to question — the one place the check
does not look. **This is not two people being careless in sequence.** The second seat, which
is the mechanism that catches everything else here, is blind to this class by construction.

**Second instance on the Manager's side, recorded because it establishes the pattern rather
than the incident:** T-0010 was reported built at `fb8bc228` — a correct sha attached to the
wrong task. Both times a true fact was attached to the wrong subject and verified cleanly,
**because a true fact verifies as true regardless of what it is about.**

**The fix is already on this project as a code pattern, one criterion away from where the
error happened.** `DeclaredQuorum` exists because **a bare `4` cannot tell you where it came
from**, so the value was made to carry its own rule id and version — *"make the value carry
its own answer"*, GRADE-031's whole content. **A claim citing a criterion by number is a bare
`4`**: it asserts a referent and carries nothing to check it against. Quote the requirement
being answered and the mismatch is visible **in the sentence**, with no verification step at
all.

**Same defect as two other entries filed the same night, which is why it is a class and not an
incident:**

    B45          a quotation that does not say which part it ADDRESSES
    B48 / T-0016 a count that does not say which SET it counted
    B49          a claim that does not say which CRITERION it answers

**A reference that does not carry its referent.** In all three the reference was individually
accurate, which is exactly why nothing caught it.

**Fix:** partial. Review has committed to quoting the requirement rather than citing its
number, and the Manager to naming the referent it checked. **Both are disciplines, and this
register's own recurring lesson is that a documented convention nothing enforces is a
convention only when someone remembers it (B47).** No mechanical check is proposed here
because none is obvious — which is the reason to write the entry rather than the reason not to.

**REJECTED, and the reason is the crux: "ask which referent was checked" as a READER-side
discipline.** It puts the burden on the reader, **and the reader is precisely who does not have
the referent.** Any fix that depends on the recipient noticing an omission has the same shape as
the defect. The two disciplines above are both PRODUCER-side for that reason: quote the
requirement you are answering, name the referent you checked.

**Concrete consequence, unaddressed:** **every task file in `agents/tasks/` cites its criteria by
number**, and dispatch messages inherit it — *"criterion 9"* is a bare `4`. So this defect is
currently present in the primary artefact the loop runs on, not only in one exchange.

Related: **B47**, **B45**, **B48**, **B39**, **B50**.

### B50. GATE-017 is implemented for one of its two clauses, and the residue is recorded nowhere except in a note that says it is recorded
**Found in:** T-0012 review, 2026-08-14, by Review, in the pinned worktree at `ab7dc77`
**Severity:** low as a gap, moderate as a signal — the gap is small and declared; the
pointer to it is false, and a false pointer is how a declared gap becomes an undeclared one

**The gap.** `GATE-017`'s statement has two clauses. Clause 1 — *an order triggered from an
analysis-only timeframe is a violation* — is implemented and proved by a synthetic HTF
fixture driven in both directions. **Clause 2 is not implemented:** *LTF events must not
redefine the higher-timeframe destination unless the HTF analysis itself changes.* That is a
**stability requirement across consecutive LTF triggers**, and nothing records the HTF
destination per event, so there is nothing to compare across triggers. **Clause-1-only was
explicitly permitted by T-0012's plan provided the residue was recorded**, so the scoping is
correct and this entry is the record it required.

**The defect is the pointer.** The rule's own `COVERAGE_NOTE` ends:

> *"Recorded in KNOWN_ISSUES rather than counted as covered."*

**It was not.** Searched at `ab7dc77`: no entry for clause 2, and no match for `HTF
destination`, `redefine the higher` or `stability requirement` anywhere in this file. **The
only GATE-017 line a reader would find says the opposite** — *"**GATE-017 / GATE-019** — 1H is
analysis only — **CLOSED 2026-08-14 (T-0007)**"*. So someone checking the register for GATE-017
residue finds a closure notice.

**Why it is worth an entry rather than a correction.** The `COVERAGE_NOTE` mechanism is good
and is the right home for a residue — it is a class attribute, it travels with the rule, and
`check_rule_coverage.py` prints it on every run, so it cannot go stale unnoticed the way a
document can. **The note did its job.** What failed is the one clause in it that names another
artefact: **a note that is durable and self-printing ended with a claim about a file it cannot
see.**

**This is B49's class, third instance, and the first one in code rather than in prose** —
a true-sounding reference whose referent was never checked. It is also the second time
GATE-017 specifically has carried a claim about its own closure that outran the record:
**A10's GATE-017 row was asserted CLOSED in a commit message by an edit that matched nothing
(B39)**. Same rule, same shape, different mechanism, one week apart.

**Fix:** this entry is the missing record, so the `COVERAGE_NOTE` is now true as written. **No
change to the note is needed and none should be made** — amending it to say "recorded nowhere"
would be correct today and wrong the moment anyone wrote the entry. **The durable lesson is
narrower than the entry: a self-printing note may state a fact about itself; when it states a
fact about another file, nothing prints that.** Related: **B49**, **B39**, **B47**.

### B51. B18 does not exist, and four places cite it — two of them in shipped code
**Found in:** 2026-08-14 by Review, verifying the new preamble's citations
**Severity:** low as behaviour, moderate as a signal — it is the register's own
reference-integrity failure, and the two code citations cannot be seen from this file

**There is no `### B18.` heading in this register.** Zero. Yet `B18` is cited four times:

    KNOWN_ISSUES.md:1681      "of the B18 fix (`a4367ad`) that nobody predicted"
    KNOWN_ISSUES.md:1718      "check plus the B18 fix make a spurious refusal far more likely"
    verify_guards.sh:80       "The promise used to be wider, and the width was the bug (KNOWN_ISSUES B18)"
    verify_guards.sh:145      "strictly worse than the data loss B18 describes"

**The referenced content is real** — `a4367ad` exists and the `restore()` narrowing it made is
in the script — so this is not a fabricated citation. **The entry was renumbered, folded or
dropped and its inbound references were not updated.**

**Why the code citations are the serious half.** `verify_guards.sh:145` sends a reader to
*"the data loss B18 describes"* to justify a specific safety decision. **That reader opens this
file and finds nothing**, and the decision then looks unjustified rather than merely
undocumented. **A dangling reference in code is worse than one in prose**, because prose is read
by people auditing the prose, and `verify_guards.sh` is read by whoever is about to change the
mutation prober — the highest-consequence file in the repo to misunderstand.

**And this file cannot see it.** Both sweeps at `agents/` read `KNOWN_ISSUES.md` and check
whether entries' citations still resolve **outward**. Nothing checks whether **inbound**
citations resolve — that a `B18` referenced from a shell script still names an entry.
**Same asymmetry as `B50`'s:** a note can state a fact about itself; nothing prints a fact about
another file.

**Fix:** decide whether B18 was folded into another entry (its subject — `restore()` restoring
more than the run changed — is described in `B30`'s instance list and in the script's own header)
and either restore the number as a pointer or update the four citations. **A one-line
`### B18. — folded into Bnn` stub is enough**, and is what makes the two code citations resolve
again. Related: **B49**, **B50**, **B30**, **B47**.

### B52. NOT A DEFECT — the lookahead suite protects a property across two modules and an unguarded file. Kept as the record of two wrong versions.
**Found in:** 2026-08-14 by Review. **Severity: NONE. Filed twice at moderate and HIGH, and
both claims were wrong.** Kept rather than deleted because the way it was wrong is the entry.

**WHAT IS ACTUALLY TRUE, measured last and stated first.** A subtle causality defect injected
into `ict/detector.py` — a file no probe covers and `GUARDED_FILES` does not contain — **IS
caught**:

    detector.py:280   "candle_index": max(int(i) - 1, 0)     # FVG born one bar early
    engine.py:295     fvg_by_idx.setdefault(int(f["candle_index"]), ...)
    engine.py:362     "born": i

    FAILED tests/integration/test_no_entry_fills_at_its_own_bar_extreme
    1 failed, 2 passed

**A one-bar index shift, two modules from the assertion, and the lookahead suite fails.** That
is a stronger test than either seat credited it with, and it is the answer to the question
T-0018 was built on.

**VERSION 1 was wrong about the mechanism.** It claimed the FVG probe's property *"also
depends on `detect_fvg`"*. `born` is assigned at `engine.py:362` and compared at `:403` —
**`born+2` is engine-local**, as are both other probed engine properties. I asserted a
dependency from an import list without checking whether the PROPERTY depended on the import.

**VERSION 2 was wrong about reachability, and louder.** It reported *"965 passed with a
genuine lookahead in the codebase"* — but the mutation went into `_detect_fvg_manual`, which
**is dead code**: `_SMC_AVAILABLE` is true, `smartmoneyconcepts==0.0.27` is pinned in
`requirements-prod.txt`, and the manual branch runs only if the library is absent or raises.
**A mutation in unreached code passes trivially.** The Manager established it with a tripwire
— `raise` in the manual path leaves the suite green, `raise` before `smc.fvg` turns it red.

**THE LESSON IS ONE COMMAND, NOT MORE CARE.** Both versions asserted a defect from a mutation
whose reachability was never established. **Establish that the mutated line executes BEFORE
concluding from its result** — a tripwire, or a check of which branch the tests take. Version
2 was filed HIGH on that basis; running the check first would have produced no entry at all.

**WHAT SURVIVED AND MOVED ELSEWHERE.** The guard-list reasoning stands on its own and is in
T-0018: widening `GUARDED_FILES` is `B18` (one global `MUTATED`, `restore()` over the whole
list), the transitive closure is **63 of 153 modules**, and a probe cannot manufacture a test
that does not exist. **And the real exposure is the Manager's, not this entry's:**
`requirements-prod.txt` states that *"the three lookahead fixes are written against
[`smartmoneyconcepts`] exact output semantics"* and *"treat any bump here as a strategy
change"* — **and nothing pins the library's output.** The engine-side property is well
tested; the assumption underneath it is not tested at all. Related: **B18**, **E1**, **B39**.

### B53. CI's verdict has no consumer — main went red for nine minutes and no one in the loop knew
**Found in:** 2026-08-14 by Review, after the Manager found T-0014 part 1 had been pushed red
**Severity:** moderate — the detection already works; only the routing is missing, which is
why this is worth an entry rather than a project

**`62df7d6` (T-0014 part 1) was pushed with a failing suite.** Reproduced in a pinned
worktree:

    tests/unit/test_rules_base.py:158   AssertionError
    Extra items in the left set: 'consolidation'
    1 failed, 15 passed

**CI caught it, correctly, within a minute.** From the Actions API:

    e1baefd   success   16:33:16Z   main
    ff084ac   success   16:20:36Z   main
    62df7d6   FAILURE   16:11:37Z   main    <- part 1
    3c8d31c   success   15:55:46Z   main

The workflow triggers on push to every branch, it fired, and its verdict was right. **Execute
self-caught the break and fixed it nine minutes later in `ff084ac`, whose title says so.**

**So the failure is not detection.** A correct red verdict existed on `main`, was recorded
with a timestamp, was resolved by its author — and **never entered the review record.**
Neither the Manager's dispatch nor Review's part-1 report mentioned it, because **nothing in
the three-agent loop reads CI.** The signal was not missing; it had no consumer.

**Why the review protocol did not catch it either, stated because the division of labour is
otherwise correct.** Review takes a baseline before a task and verifies when the task lands,
which is right for attribution and deliberately leaves intermediate commits to CI. **That
division works only if someone reads CI.** A task pushed in several commits therefore has a
middle state that Review does not check by design and that CI checks and reports to nobody.
**Review also had a worktree pinned at `62df7d6` throughout the part-1 review and never ran
the suite in it** — the answer was one command away in a tree already built.

**FIXED — the routing exists: `agents/ci_range.py <base>..<head>`** prints the CI conclusion
for every commit in a range from `GET /actions/runs`, so a verdict can state it for **commits
nobody pinned** without running the suite again. Adopted into Review's protocol 2026-08-14:
**endpoint runs are mine; intermediate commits are CI's, and I read them now.**

**Cited only after verifying it, because CI runs PER PUSH and not per commit**, so most
commits in a batch push have no run of their own and the tool must infer. Three defects were
found and fixed before this entry pointed at it, and the third is the one a reader should
know about:

* **v1 fired on every batch push** — every runless commit reported as a gap. The muted-alarm
  failure, in the tool built to route a signal nobody read.
* **v2 inferred from ANCESTRY** — a runless commit was *"covered by"* the next green
  descendant. **False, and systematically false in the only window that matters: a fix commit
  makes every red ancestor between the break and itself look covered.** Proved on `ab6a427`,
  which v2 called covered and which is red.
* **v3 searched for evidence only INSIDE the queried range**, so `bd674d5` read `=success` or
  `UNKNOWN` depending on where the range started — **a verdict that was a property of the
  query rather than the commit**, failing by manufacturing UNKNOWNs.

**v4 infers by TREE IDENTITY across history** — a runless commit inherits the conclusion of
the nearest commit whose code tree is byte-identical, in either direction — and reports
`UNKNOWN` where no such neighbour exists. **Verified rather than read:** `ab6a427` inherits
its red; `bd674d5` gives the same answer from two different ranges; an unpushed
code-changing commit reports `UNKNOWN`; and a **frontend-only** commit reports `UNKNOWN`
rather than inheriting, which v3 would have got wrong — its comparison covered
`backend/` and `scripts/` while CI runs four jobs including `frontend/`. **`TREE_IGNORE` is
now an exclusion list (`docs/`, `*.md`), so a new top-level directory defaults to counted
rather than silently ignored** — `B52`'s lesson applied before it could bite.

**Related and distinct: `B30`** is *"a `cancelled` check reads as green — the only CI state
that asserts nothing"*. **It was filed yesterday — T-0006, 2026-08-13 — and it is Review's
own finding and largely its wording.** So the loop established one day ago that **CI states
are review-relevant**, and still routed nothing. B30 is a state that misleads a reader; this
is a state no reader reaches. **The same seat filed both**, which is the part worth keeping:
knowing a signal matters is not the same as arranging to receive it. Related: **B30**,
**B47**, **B39**.

### B54. Two live tools count the registry differently — `rule_waves.py` collapses aliases and `check_rule_coverage.py` does not
**Found in:** T-0014 verdict, 2026-08-14, by Review. **Filed here 2026-08-14, late, and the
lateness is half the entry.**
**Status: FIXED, 2026-08-14 (T-0021, `check_rule_coverage.py`).** Both tools now collapse and
agree — measured live, not asserted: `rule_waves.py` prints `DISTINCT HARD_GATEs 79 implemented 33`
and the coverage script prints `HARD_GATE covered 41 / 91 ids   33 / 79 distinct`.

**THE ENTRY STAYS RATHER THAN BEING DELETED, and B51 is the reason.** Two live places cite it —
`agents/deferral_sweep.py:41` uses it as the worked example of a predicate deferral, and this file's
own *TWO NUMBERS QUOTED TOGETHER* section cites it for the divergence. Deleting a fixed entry that
things point at produces *a live fact with a dead pointer*, which is B49's second class and exactly
what B51 recorded when four artefacts cited a `B18` that did not exist.

**WHAT THE FIX DOES AND DOES NOT COVER.** The coverage script's own counting is enforced in CI
(`backend/tests/unit/test_rule_coverage_counting.py`, 8 tests, alias-collapse mutation included).
**`rule_waves.py` lives OUTSIDE the repository, so CI can never see it** — see **B58**. What is
enforceable from inside is the *interface*: the `implemented ids:` line that `rule_waves.py` parses
is pinned by test, so the two tools cannot diverge through this side silently changing shape.

**Severity:** moderate — the programme is scoped on an absolute count and two tools disagree
about it

**`check_rule_coverage.py` reports:**

    implemented but CANNOT FIRE    4
        GATE-040 · GATE-041 · GRADE-029 · GRADE-035

**That is TWO rules.** `GRADE-029` is `alias_of GATE-041` and `GRADE-035` is `alias_of
GATE-040` — one class each, registered under two ids by `base.py`'s alias mechanism. The same
inflation runs through `implemented 42 / 117` and `effective coverage 37 / 91`.

**`rule_waves.py` was fixed to collapse aliases on 2026-08-14. `check_rule_coverage.py` was
not.** So the two tools now disagree, and the disagreement was introduced by fixing one of
them. Distinct figures: **2 blocked**, **33 of 79 distinct HARD_GATEs implemented**, **31 of
79 able to reach a verdict**.

**Not introduced by T-0014 — made visible by it**, because T-0014 was the first task to add
an alias pair after the collapse rule was adopted. **The ratio survives collapsing because
aliases inflate numerator and denominator together; the ABSOLUTE counts do not, and the
programme's remaining-work figure is an absolute count.**

**AND THE REASON THIS ENTRY IS LATE IS THE FINDING I WOULD KEEP.** I reported it in
`agents/tasks/T-0014/review-01.md` as *"belongs to whoever owns the coverage script"* —
**a deferral by predicate, with no task id, written by me, hours after the loop adopted DEFER
BY TASK ID, NEVER BY PREDICATE and filed four instances of it.** It then sat unowned because
a predicate deferral has no owner the moment nobody recognises themselves in it.

**Two mechanisms let it hide, and both are mine:**

* **A verdict is not the register.** This file's own preamble opens with the rule that a
  problem found and not fixed is *written here* — *"not mentioned in passing"*. **A review
  verdict is passing.** `B47` is the precedent: a verdict that existed where nobody would
  look.
* **`agents/deferral_sweep.py` reads only `KNOWN_ISSUES.md`.** Verdicts under
  `agents/tasks/*/review-*.md` carry deferrals and **nothing sweeps them** — so the tool
  built to catch predicate deferrals is blind to the file type in which I wrote one. Limit
  now recorded in the script.

**Fix, applied:** the coverage script now prints **both** figures labelled — `42 / 117 ids` beside
`34 / 104 distinct` — rather than picking one, because both are legitimate answers to different
questions and a bare number cannot say which set it counted. Related: **B43**, **B45**, **B47**,
**B49**, **B58**.

### B73 — PRIM-002's SUPER_BPR promotion read the FUTURE, and no prober covers this primitive

**Found in:** T-0020, 2026-08-15, while implementing the lookback bound. **Not in the plan** —
the plan names three consequences of the unbounded scan and this is a fourth.

**What it was.** `_bprs` promoted a band to SUPER_BPR by counting every imbalance in the
series whose band covers the intersection. There was no index constraint, so **imbalances
formed AFTER the band counted toward it.** A band created at bar 1 could be promoted by a gap
that first printed at bar 900. Its own docstring already said a BPR *"exists from the moment
its LAST component printed"*; the code did not enforce it.

**Why it survived.** `verify_guards.sh` probes eight guards and **none of them is in
PRIM-002.** Tier 0.2 covers the FVG entry rule, the daily bias window, three dominance
properties and three execution properties. The contract primitives have no lookahead prober
at all, so a primitive reading forward is invisible to the machinery built to catch exactly
that. The suite's own `test_lookahead_regression.py` is likewise about the ICT path.

**Why it matters beyond the classification.** Lookahead in a primitive is the failure mode
this project spent Tier 0.2 on: a backtest that reads forward reports edge that cannot be
traded. PRIM-002 feeds ENTRY-001, which is every admissible entry object in the contract.

**Fixed** — components must satisfy `formed_index <= formed`, and
`test_a_component_formed_after_the_band_cannot_promote_it` goes red without it.

**NOT fixed, and it is its own entry:** see **B75**. Related: **B74**.

### B101 — `ci_range.py` measured the distinguishing fact and dropped it on one branch of three

**Filed by Review 2026-08-16, against my own tool, found by Execute during the T-0026 verdict. The
bug is FIXED. What is OPEN is that the fix is unexercised, and that is the reason this has an id.**

### The defect

`own_cancelled` is computed once and was used on **two branches of three**:

    inherited branch   why = "own run CANCELLED; "     printed it
    UNKNOWN branch     had = "run CANCELLED"           printed it
    PENDING branch     DROPPED IT ENTIRELY

**So a commit whose own CI run was CANCELLED printed as plain `PENDING`.** I read that and wrote
*"PENDING … I will flag it if it turns red."* **It was never going to turn.** `ce12b88`'s Backend
suite was killed by the workflow's concurrency group when `07eb4c0` landed.

> **`PENDING` says wait for THIS sha. The truth was that this sha's run was dead and the coverage
> depended on a DIFFERENT sha finishing. Those imply different next actions, and only one of them
> was printed.**

**This is the sharpest instance of the standing family we hit all night, because of where it
happened: the instrument built to stop outputs that do not discriminate, failing to discriminate —
on the one branch of three that lost the fact, which is the branch that produced the line a reviewer
then repeated in a verdict.**

**The cause is not ignorance of the distinction.** `cancelled` is handled deliberately elsewhere in
the same file, with a comment explaining why it must not be a separate outcome (**B30**). **The fact
was known, computed, and dropped on output.**

### Fixed

That branch now reports **`SUPERSEDED`** with *"own run CANCELLED and will NEVER complete; tree
identical to X, WHOSE RUN IS STILL IN PROGRESS — check THAT sha, not this one."* **The label changed,
not only the arrow**, because the label is what a reader acts on.

### What is OPEN, and why it is here rather than in a verdict

**The new branch has never executed.** Its condition — a cancelled run coinciding with a
tree-twin still in progress — stopped holding the moment `07eb4c0` completed. **I verified only that
two real ranges still report correctly with no regression. That is a regression check, not a test of
the fix.**

> **It is correct by construction and verified against nothing — the same state as `B93`'s
> `REASON_OUTSIDE_V1` and `TARGET-001`'s `CANNOT_FIRE`.**

**What would exercise it:** any range containing a commit whose own run was cancelled while a
tree-identical commit's run is still in progress. **Execute measured that three seats pushing in
quick succession is now the normal condition** — `03b18d6` cancelled the run before it, `ce12b88`
cancelled `03b18d6`'s, `07eb4c0` cancelled `ce12b88`'s — **so this will recur, and the next reviewer
to hit it should confirm the branch fires rather than assume it.**

**Related:** **B92** (the guard family and its standing limit — it prevents recurrence, it cannot
produce discovery), **B30** (why `cancelled` asserts nothing), **B93**, **B81**.

### CLOSED, same day — the branch is now EXERCISED rather than correct-by-construction

**Review filed this OPEN on exactly the right grounds: the new branch had never executed, its condition
stopped holding the moment `07eb4c0` completed, and *"verifying two real ranges still report correctly
is a regression check, not a test of the fix."* It refused to grade its own tool more softly than it
graded `REASON_OUTSIDE_V1` and `TARGET-001`'s `CANNOT_FIRE` an hour earlier.**

**Exercised by the Manager with the stubbing pattern from `landed_sweep`'s mutation: ONLY the CI fetch
was replaced** — a real commit pair with genuinely identical code trees, its own run `cancelled`, its
twin `in_progress`. **The tree comparison, the commit list and every other branch stayed real.**

    2d48c7ae  SUPERSEDED  <-- own run CANCELLED and will NEVER complete; tree identical to
                              07eb4c00, WHOSE RUN IS STILL IN PROGRESS — check THAT sha, not this one
    07eb4c00  IN_PROGRESS <-- RUN IN PROGRESS — no verdict YET, and not 'unverified'

**Both branches fire, distinctly, in one output.** The label is `SUPERSEDED` rather than `PENDING`, and
the arrow names the sha to check — **which is the part a reader acts on, and the part the defect
destroyed.**

**What this does NOT establish:** that the condition arises in production the way the stub arranged it.
**Review's prediction stands** — `03b18d6`, `ce12b88` and `07eb4c0` each cancelled the run before it, so
three seats pushing in succession is the normal condition. **The next reviewer to meet it should confirm
the branch fired rather than assume it**, and now has a known-good output to compare against.

### B86 — `PaperPosition` CANNOT REPRESENT A TRANCHED POSITION, and the v1 exit model needs one

**Filed 2026-08-15 by Execute, T-0022. This is the plan's own named risk, measured rather than
worked around: the Manager asked for the finding in preference to a workaround, and this is it.**

**The 70/30 split is the first rule in the programme that requires a position to have PARTS.**
Everything before it decides whether a trade is taken; `EXIT-001` decides what happens to it after.

    backend/app/services/broker/paper.py:22
      class PaperPosition:
          __slots__ = ("id","pair","direction","entry","units","sl","tp","open_time","mark")

**ONE `units`, ONE `sl`, ONE `tp`, and `__slots__` so an attribute cannot even be attached at
runtime.** `_settle()` does `self._positions.pop(pos.id, None)` — **a position leaves the book whole
or not at all. There is no partial-close path in the class.** `on_tick` closes 100% at `sl` or `tp`.

**So the model was built where it could be correct — `rules/exit_001_v1_model.py`, shadow only —
and NOT forced into the broker.** `V1ExitModel.simulate` walks a price path and emits `exit_events`;
it holds `remaining_fraction` itself and never touches a `PaperPosition`.

**What this costs the wiring task, stated so it is not rediscovered:** wiring the v1 exit model is
**not** a matter of calling the model from `on_tick`. It requires either a second position record
for the runner (two `PaperPosition`s, which splits one trade's identity across two rows and breaks
the `position_id` join in `_settle`'s event and everything downstream of it), or a genuine tranche
model on `PaperPosition` (`units` becoming a list of open tranches, with `_settle` closing one
tranche rather than popping the position). **The second is correct and is a broker-layer change with
its own migration for the closed-trade record shape.** Neither is a small change, and a wiring task
scoped as "call the model from the exit path" will discover this after it has started.

**What it could break:** nothing today — nothing under `live/` or `broker/` imports the model, and
`test_no_live_or_broker_module_imports_the_exit_model` goes red the moment that stops being true.
The risk is entirely to the wiring task's estimate. Related: **B87**, **B88**, **B84**.

### B87 — the 19:00 New York close is OURS AND UNRATIFIED, and it will not look it in six weeks

**Filed 2026-08-15 by Execute, T-0022. Implemented as the rule states, defaulting ON, stamped
`ratified=False`. The open question is not the number; it is whether the number was ever meant for
our instrument.**

    the rule says      EXIT-001: "the end of the trading session (19:00 New York time), at which
                       point any remaining position is closed"
    its provenance     GATE-022 records that 19:00 enters the codex ONLY through the EURUSD /
                       algo HT v2.0 strand — "70% of position 2RR, 30% (EOD; 19:00)" — and that
                       the two-strand question is "answered by adoption, never by argument"
    our instrument     BTC and ETH. 24/7. The Magic Strategy has NO session-end concept.
    asked              question 4 of the pack sent to Salim 2026-08-15 — UNANSWERED

**Why it was NOT defaulted off despite 24/7 making it look wrong: a session close that never fires
generates no evidence.** One that fires in shadow produces the measurable record the ruling should
rest on — how often a runner would have been cut and the R it was carrying. `EXIT-001`'s telemetry
emits `runner_cut_by_session_close` and `runner_r_at_session_close` **only on records where it
fired**, so the count is obtained by counting keys rather than by reading values (a field present on
every record cannot be counted, and a default of `False` is indistinguishable from a record written
before the field existed).

**THE ACTUAL RISK IS THE HANDOFF, NOT THE BEHAVIOUR.** Nothing in a declared parameter's declaration
says *"still unanswered"* to someone reading it much later, and by then it will have sat in the code
looking settled. **Two requirements on the wiring task, which are requirements and not notes:**

1. **Re-surface the ratification question BEFORE enabling the session close.** Do not inherit it.
2. **Bring the shadow evidence to that decision** — the count of runners that would have been cut
   and the R they were carrying.

**What it could break:** once wired, a runner is cut every evening on an instrument that trades
through the night, on our authority rather than Salim's. **Today it cuts nothing** — T-0022 is
shadow-only and nothing under `live/` references `EXIT-001`. Related: **B86**, **GATE-022**.

### B88 — `ExitEvent` REFUSES `LIQUIDATION`, which is right today and a hazard the moment it is wired

**Filed 2026-08-15 by Execute, T-0022, after Review raised it as a forward note. Kept strict
deliberately; recorded because the reason it is safe expires at wiring.**

**The telemetry schema's `exit_event.reason` enum has SIX values; `EXIT-001`'s output names FOUR.**

    schema     PARTIAL_2R, FINAL_TARGET, STOP_HIT, SESSION_CLOSE, LIQUIDATION, MANUAL_OVERRIDE
    EXIT-001   PARTIAL_2R, FINAL_TARGET, STOP_HIT, SESSION_CLOSE

**Both extras belong in the schema** — SIZE-003 keeps `LIQUIDATION` separate from `STOP_HIT` so an
isolated-margin liquidation is never counted as the strategy's stop working, and `MANUAL_OVERRIDE`
is a human act outside any model. **Neither belongs in EXIT-001's output.** The consequence is that
**a record carrying `LIQUIDATION` VALIDATES against the schema and violates the rule**, so T-0022's
criterion 1 ("a fifth reason is a defect") is enforceable only in the rule, never by the contract.
`ExitEvent.__post_init__` therefore raises on anything outside the four.

**THE HAZARD: once the model is wired, a real margin liquidation would RAISE inside the exit path
instead of recording one.** Review's reading, which I agree with: SIZE-003 keeping liquidation
separate reads as *a different event path*, not *an invalid value of this one*. **The wiring task
must settle this BEFORE it ships** — most likely a separate constructor or a distinct event type for
non-model exits, so that `EXIT-001`'s four-reason guarantee survives without the exit path throwing
on a real market event.

**And a limit on what the EXIT-002 check currently proves.** `ladder_violations` reports
`REASON_OUTSIDE_V1` over raw stored dicts, but **every route to an exit event in this codebase goes
through `ExitEvent`, which has already refused the bad value — so that finding cannot fire over
anything produced today and its test is verified against its own fixture.** It guards a future
writer. The tranche-count findings (`MULTIPLE_PARTIALS`, `MULTIPLE_TERMINALS`, `TOO_MANY_TRANCHES`,
`OVERSIZED_EXIT`, `SCALE_OUT_LADDER`) **are** reachable from validly constructed `ExitEvent`s,
because the constructor validates each event alone and says nothing about the sequence. Related:
**B84** (nothing writes a stored exit record at all), **B52**, **B86**.

### B89 — a target sitting at or inside 2R is REFUSED, and the rule that should adjudicate it cannot run

**Filed 2026-08-15 by Execute, T-0022. A deliberate choice with a live consequence, recorded because
the choice is only defensible while the model is unwired.**

**`GATE-031` governs the gap between the 2R partial level and the final target and says the engine
"must not silently invent" a minimum one. `GATE-031` is NOT DISPATCHABLE:** its inputs name
`selected_stop.rr`, produced by `GATE-025`, which is unimplemented (wave 2). So the rule that would
decide what to do about a degenerate runner **cannot be consulted.**

**What T-0022 did:** `TradePlan.__post_init__` raises `DegenerateRunner` when the final target is not
STRICTLY beyond the 2R level. It neither invents a gap (which GATE-031 forbids) nor hides the
condition (which the plan forbids). **It refuses to represent the setup at all.**

**Why that is a problem and not merely conservative:** the market produces such setups. A target at
exactly 2R makes the partial and the final target fire on the same tick at the same price and gives
the runner zero distance to run — but it is a real configuration, and **refusing to model it means
that once wired, the engine cannot express a trade the strategy might well take.** Today it costs
nothing: nothing calls the model. **At wiring it becomes "the engine raised instead of trading",
which is a worse failure than a degenerate runner.**

**Resolution requires GATE-025, then GATE-031** — in that order — and the wiring task must not
paper over it with a minimum-gap constant, which is the specific thing GATE-031 prohibits.

**The near-miss worth keeping.** The guard was written with the module's own `_beyond` helper, which
is INCLUSIVE, so a target sitting exactly ON the 2R level was accepted as a normal trade. Inclusive
is correct for `_beyond`'s other caller — a price touching a level HAS reached it — and wrong here.
**One predicate served "has the market reached this?" and "is this plan admissible?", whose boundary
cases fall on opposite sides.** Caught by the parametrised test at `target == 110`, which failed on
first run. **Anywhere a comparison helper is shared between a market question and an admissibility
question, the shared helper is where that distinction gets lost** — not generalised into its own
entry because this is one instance and one is not a pattern, but worth the grep if a second appears.

### CORRECTION to `35b3712`, and the commit that carried B91 committed two defects of its own

**Both are the Manager's, both were preventable by reading output it had just generated, and they are
recorded here because the entry above was landed by a commit that demonstrates two of this register's
standing failures.**

**1. IT SWEPT REVIEW'S `B90` IN.** `B90` was uncommitted in the shared tree; `git add KNOWN_ISSUES.md`
took it. **So `B90` is committed under the Manager's authorship and message, when Review wrote it** —
the exact authorship property both seats defended two hours earlier, when Review refused to commit its
own `B83` while a peer was blocked precisely so finder and committer would differ. **`B90` is Review's
finding: `EXIT-001`'s `NOT_APPLICABLE` has no denominator.** Attributed here because the commit
message cannot be.

**And the check ran.** `git status --porcelain` printed ` M KNOWN_ISSUES.md` **immediately before the
edit, in the same command block** — the file was already dirty and the output said so. **It was not
read.** Fifth instance of the shared-file hazard, and the first where the warning was on screen.

**2. THE COMMIT MESSAGE SAYS `B86`. THE ENTRY IS `B91`.** And `B86` exists — it is Execute's
`PaperPosition` tranching entry. **So the message points at a real and unrelated entry**, which is
worse than pointing at nothing.

> **This is the SECOND time, and the first is recorded in `B80`'s own footnote.** Same mechanism
> exactly: **the script wrote the heading from the id the ledger returned, and the Manager typed the
> number into the commit message by hand.** The generated copy was right both times; the hand-copied
> one was wrong both times.

**`B80` recorded that as an instance of the unaudited-copy rule and changed nothing about how commit
messages get written.** A note is not a mechanism, and **the recurrence is the evidence.** The fix is
to derive the id in the message from the same variable as the heading, never to retype it — **and if
that is not done, this will appear a third time.**

**Neither defect affects the CONTENT of `B90` or `B91`.** Both entries are correct and in the file
once. **What is damaged is the audit trail**, which is the thing the register exists to be.

### B93 — a test can make a guard VACUOUS just by importing what the guard checks for: 23 of 26

**Filed 2026-08-15 by Execute, T-0023. Found by accident, and the accident is not the finding —
these are repo-wide numbers, measured.**

**`test_rules_base.py::test_every_rule_module_on_disk_is_imported` exists to catch a rule module
that `rules/__init__.py` does not import**, because such a module is invisible to
`check_rule_coverage.py` — it counts as unimplemented while sitting in the tree. **It cannot do
that job for almost any module in its domain.**

    guard domain                              26   (29 .py in rules/ minus the three
                                                    NOT_RULES at test_rules_base.py:157)
    imported DIRECTLY by some test module      23
    guard therefore VACUOUS for                23 / 26
    still protected                             3   gate_017_analysis_only_tfs,
                                                    gate_037_no_premium_discount,
                                                    grade_031_declared_quorums

**The mechanism: `implementations()` is a PROCESS-GLOBAL registry populated by any import, and
pytest imports every collected test module before running any test.** So a test file that imports
a rule module directly has already registered it by the time the guard runs. No mutation, no bad
assertion — **the collection order does it.**

**Observed live, not theorised.** During T-0023 an `__init__.py` edit was reverted in the shared
tree (see **B94**). All 50 tests in the new file stayed green, **the guard stayed green**, and
`check_rule_coverage.py` correctly held at 39/104 with EXIT-004, TARGET-001 and TARGET-003 reported
unimplemented. **Two instruments disagreeing silently — and the suite was the wrong one**, which is
the inversion worth keeping, because the suite is the instrument everyone trusts. That is `B54`'s
shape reached by a new route: **a test masking a guard through its own imports.**

**And the guard's failure message asserted something the guard cannot know.** It read *"not imported
by rules/__init__.py"* — a specific claim about a specific file — while the assertion can only
establish *"not registered in THIS interpreter"*. **The standing family one layer nastier: the
output does not discriminate AND it names the specific thing it did not check**, in the sentence a
reader trusts while debugging. Found by Review.

**FIXED in this task, both halves.** `test_the_package_alone_registers_every_rule_module` spawns a
clean interpreter importing ONLY the package, so no test's imports can reach it; the old guard's
message now says only what it can support and points at the new one.

**THE NEW GUARD'S OWN LIMIT, MEASURED THE SAME WAY RATHER THAN CAVEATED — this is the part that is
still open.** Rule modules import each other, so removing one module's import block from
`rules/__init__.py` often leaves it registered anyway through a sibling. Removing each of the 26 in
turn and re-importing the package in a clean interpreter:

    STILL REGISTERED via a sibling — new guard BLIND   15 / 26
    registration genuinely lost   — new guard CATCHES  11 / 26

**So it reliably catches a GROUP going missing, which is the case that occurred, and NOT every
single dropped import line. NOT FIXED: the 15.**

**State all three numbers together, or "fixed" reads as "covered":**

    OLD guard, in the full suite    catches   3 / 26
    NEW guard, clean interpreter    catches  11 / 26
    STILL BLIND                              15 / 26

**3 → 11 is a real improvement and it is not 26. The two blindnesses are one property each of two
different instruments, not two properties of one:** 23/26 is the OLD guard in a full-suite context
(a test already imported it, so it never had a chance); 15/26 is the NEW guard in a clean one (a
sibling re-imports it). The first is fixed; the second is not.

---

## CLOSED by T-0026 — the AST guard is built, and the numbers below are MEASURED, not projected

**`test_every_rule_module_is_imported_BY_NAME_in_rules_init` parses `rules/__init__.py` and asserts
every on-disk module appears in an `Import`/`ImportFrom` node.** Removing each of the 26 modules'
import blocks in turn and running both guards on each:

    AST guard catches                          26 / 26
    clean-interpreter guard catches            11 / 26
    AST catches where the subprocess does NOT  15        <- exactly the residue above, closed

**11 + 15 = 26 reconciles against the T-0023 measurement**, which is the check that the two runs are
measuring the same thing. **Not "it now catches everything" as a claim — every one of the 26 was
mutated and observed**, because that sentence has been wrong twice in this entry's history.

**And the failure message is TRUE for the first time.** It reads *"not imported by
`rules/__init__.py`"* and the assertion has now actually opened that file. Demonstrated on a module
a SIBLING imports (`exit_004_target_object`, imported by `target_001_concerning_objective`):
**exactly one test fails, naming that module, while both runtime guards pass** — which is the
difference between the syntactic question and the runtime one in a single observation.

**ALL THREE GUARDS ARE KEPT, because they ask three different questions:**

    is the import WRITTEN?          AST            syntactic, exact, no proxy
    does importing WORK?            subprocess     catches a renamed class or broken decorator
    registered in THIS process?     original       the weakest, and the one that was vacuous

A module can be imported in the file and still fail to register, so the runtime check is not
redundant with the AST one. **The original is kept and its message no longer claims what it cannot
support.** `NOT_RULES` is now a single module-level constant read by all three rather than a local
copy in each.

**The first risk was measured rather than assumed: every import in `rules/__init__.py` is at module
level.** The guard reads top-level nodes, so an import nested in a `try`, an `if` or a function body
would be invisible to it while still being real. The test walks the whole tree and asserts the
nested-only set is empty, so **the day someone adds a conditional import, the guard says its domain
has narrowed instead of quietly under-reporting.**

**WHAT REMAINS OPEN, AND IT IS THE PROXY POINT ONE LEVEL UP:** the AST check sees that a name appears
in an import statement. It does not execute anything, so it cannot see a module that is imported and
then fails to register for its own reasons — that is the subprocess guard's job, and that guard is
still blind to the 15 by construction. **Neither guard alone is sufficient and neither is redundant;
the pair is the coverage.** No further work is filed.

---

**Everything below is the record as it stood BEFORE T-0026, kept because the reasoning is the
finding.**

**THE CHEAP INSTRUMENT THAT WOULD CLOSE ALL 15, named here so whoever takes it does not re-derive
it (Review's, and it is better than what was built).** Parse `rules/__init__.py` with `ast` and
assert every module on disk appears in an import statement. No subprocess, no interpreter state.

* **It measures the invariant the failure message actually claims** — *"not imported by
  `rules/__init__.py`"* — instead of *"was registered in this interpreter by anybody"*. **That
  substitution is what created BOTH blindnesses: registration is a proxy, and it is the proxy that
  has failed twice.**
* **Sibling re-import cannot defeat it, because nothing is executed.** A module reachable only
  through a sibling has no import statement in `__init__.py`, so it fails.
* Its one limit: it assumes `__init__.py` imports explicitly rather than looping with `importlib`.
  **True today**, and a conversion to a dynamic loop would break it loudly — the right direction.

**A SMALL FOLLOW-UP TASK — became T-0026 and is now DONE; see the closure block above.** It was left out of T-0023 deliberately: that task
was three target-selection rules and this would have been its third expansion.

**AND THE LESSON FROM HOW THE MEASUREMENT NEARLY WENT WRONG, which is not "check your numbers".**
The first harness reported **7/26** and it was an artefact: the remover assumed a multi-line import
block's first line ends with `(`, and these end with `# noqa: F401`, so it deleted the header and
left a dangling body. **It was caught only because the bad edits BROKE LOUDLY** — 17 of 26 failed to
import, a signal impossible to read as a result. **Had the remover produced syntactically valid but
semantically wrong edits, 7/26 would have looked exactly like a clean measurement.** Nothing in the
process would have caught it. **A harness whose failures are silent is a harness whose findings are
unfalsifiable**, and that property is worth checking before trusting any measurement, including the
ones in this entry.

### B95 — TARGET-001 and TARGET-003 look contradictory and are not: THREE levels, not two

**Filed 2026-08-15 by Execute, T-0023. Not a defect — a reading that the next person will get wrong
without this, because the two statements contradict each other on their face.**

    TARGET-001   "The concerning liquidity is NOT simply the closest liquidity";
                 "Distance alone never determines the destination"
    TARGET-003   "the engine should target the CLOSEST one first"

**The reconciliation is not an interpretation. TARGET-001 states the carve-out itself and hands it
to TARGET-003, which then adds a level the carve-out does not mention:**

    LEVEL 1   WHICH OBJECTIVE          TARGET-001   distance is BARRED as an input
    LEVEL 2   ACROSS timeframes        TARGET-003   SIZE RANKS
    LEVEL 3   within one dir + one TF  TARGET-003   proximity wins, size is NOT the tie-break

*"Proximity survives ONLY as an ordering input among same-direction, same-timeframe candidates"*
(TARGET-001, delegating) and *"SIZE IS NOT A SAME-TF SELECTOR. Size still ranks ACROSS timeframes;
it never beats proximity WITHIN one"* (TARGET-003, occupying it and naming a middle level).

**So distance is BARRED at level 1 and MANDATED at level 3. An implementation using distance in the
first, or size in the third, is wrong in opposite directions — and both pass a test that only checks
a target came out.**

**THE TRAP IS LEVEL 2, AND IT IS THE CONSERVATIVE-LOOKING CHOICE.** *"Ignore size entirely"*
satisfies every same-timeframe test — size never breaks a tie because size is never read — and
**violates the rule**, because size is the cross-timeframe ranker. `§9.B IM13`'s pixels state both
halves at once: *"1D+1D LIQ > 1D LIQ. However 1D+1D area is NOT our concern at the moment."*

**Implemented as two functions with different orderings, and the tests pair them: the SAME large
pool must WIN across timeframes and LOSE within one.** A single sort cannot produce both results,
which is what makes the separation checkable rather than asserted. Related: **B96**.

### B96 — "the active institutional destination" has NO PRODUCER, so TARGET-001 cannot fire

**Filed 2026-08-15 by Execute, T-0023. Measured before building, as the plan required.**

**TARGET-001's selector is *"the next unresolved objective that supports the active institutional
destination"*. Nothing in this repository produces an institutional destination** — zero mentions of
`institutional_destination`, `active_destination` or any spelling, anywhere under `app/`. No rule
computes one and none is planned in any wave.

**So TARGET-001 consumes an input the engine cannot supply.** It is taken as a PARAMETER, and
`CANNOT_FIRE_WITHOUT = ("active_institutional_destination",)` is declared so
`check_rule_coverage.py` files it under *"implemented but CANNOT FIRE"* rather than letting it
inflate effective coverage. **Registering it moves implemented 39 → 42 and effective 36 → 38, not
39** — the distinction `B54` exists for.

**Why no heuristic was substituted, which is the whole point:** the obvious fallback is to infer the
destination from price or from the nearest structure. **That is the banned reasoning wearing a
different name** — TARGET-001's `banned_inputs` are `fixed_pct_distance` and
`atr_multiple_distance`, and its statement forbids asking *"is liquidity within X% or Y × ATR?"*.
Inferring a destination by proximity would violate the rule at the exact point the rule exists to
govern, while passing every test that only checks a destination was present.

**What it could break:** nothing today — the rule returns `NOT_APPLICABLE` naming the missing
producer, and nothing calls it. **At wiring, TARGET-001 is inert and the target layer has no
selector**, so EXIT-004 would be handed candidates nobody chose between. Deriving the destination is
its own task and needs Salim's structure, not our inference. Related: **B95**, **B97**.

### B97 — `target_object_type` is lossier than the pool classes feeding it, and one mapping is a TRAP

**Filed 2026-08-15 by Execute, T-0023. The first LIVE instance of `B77` — a contract enum lossier
than the vocabulary feeding it — and it is live because this task populates the field.**

    PRIM-003 BUILDS            faithful target_object_type?
    SWING_LEVEL                NO   -> widened to the generic LIQUIDITY_POOL
    INSTITUTIONAL_CANDLESTICK  NO   -> widened to LIQUIDITY_POOL. SEE BELOW.
    EQUAL_HIGHS_LOWS           yes
    SESSION_LEVEL              yes

**Two of the four classes PRIM-003 actually produces have no faithful target type.** (The other
three of its seven — `PARABOLIC_COMPRESSED`, `INSTITUTIONAL_LEVEL`, `DIAGONAL_POOL` — are its
declared `UNBUILT_CLASSES`, each needing a number Salim declined to fix, so counting them here would
inflate a live problem with a latent one.)

**THE TRAP: `INSTITUTIONAL_CANDLESTICK` MUST NOT MAP TO `INSTITUTIONAL_LEVEL`.** The names differ by
one word and the objects are different. `INSTITUTIONAL_LEVEL` is a monthly/weekly/daily **deep-V
swing extreme** — what `TARGET-007` is OPEN about, because *"a 'Deep-V' is not defined by a fixed
retracement percentage or ATR value"*. `INSTITUTIONAL_CANDLESTICK` is **PDH/PDL, PWH/PWL, PMH/PML and
the Monday range**. Mapping one onto the other files every previous-day-high target as a deep-V
extreme: **a CONFIDENT WRONG CLASS, strictly worse than a visibly generic one**, because the generic
bucket announces its imprecision and the wrong class does not. **Nothing in the schema warns anyone,
and a future edit "tidying up" the mapping lands on it** — so the test is written against the
mistake (`test_institutional_candlestick_does_NOT_map_to_institutional_level`) rather than for the
behaviour.

**Half-filled imbalances also widen**, to `UNFILLED_IMBALANCE`. `PRIM-002` distinguishes
`HALF_FILLED` and even carries `fill_fraction`; the statement names *"unfilled or half filled"* as
targets both; the enum has one value for the pair.

**Not fixed by widening the schema — that is not ours.** The field is SET rather than omitted
(`target_object_type` is not in the schema's `required` list, so omitting would validate and would
make *"no faithful value exists"* read as *"nobody populated this"*), `type_is_widened` is emitted
beside it, and the true class is recoverable by joining `target_object_id` to the linked
`setup_evaluation`'s `primitives.liquidity_pools[]`.

**The honest cost, which a duplicate would have hidden: a `trade_execution` read ALONE cannot tell
you the pool class.** That is real. The remedy is the join, not a second copy — a pool's class is
immutable, so a stored copy can only ever drift. **`fill_state_at_selection` IS carried, and is not
the same kind of thing:** an imbalance's fill state ADVANCES as price approaches, so the join returns
the state NOW and never the state WHEN THE TARGET WAS CHOSEN. One is a duplicate; the other is the
only copy of a different fact. See **B91** for the general form. Related: **B77**.

### B98 — `DISTANCE_WORDS` rejects standard SMC vocabulary, and the rejection will read as a rule violation

**Filed by Review 2026-08-15 from the T-0023 verdict at `119d773`. MEASURED, not reasoned. The task
PASSED; this is a false positive waiting in a heuristic, not a defect in the rule.**

`why_names_a_destination()` rejects a `why_selected` containing any of `DISTANCE_WORDS`, which
includes the bare substrings **`"far"`** and **`"near"`**. **Run against realistic strings:**

    False   the far edge of the daily order block
    False   the far side of the H4 flip zone
    False   the nearest unresolved high              <- correct, this IS a distance answer
    True    the weekly equal highs at 112.5
    True    sell-side liquidity under the Monday low
    True    the unresolved daily high that the destination sits above

**`far side` and `far edge` are standard SMC vocabulary for a STRUCTURAL location** — the far side
of a flip zone is the same object `GATE-027`'s notes discuss under `§9.J IM79/IM86`, where a stop
must cover the WHOLE zone. **A `why_selected` naming one is a structural answer, and the check
reports it as a distance answer.**

### Why it is worth an id despite being small

**The failure is not "a string got rejected". It is that the rejection is indistinguishable from a
real TARGET-001 violation** — the same value, the same FAIL, the same message. **A reader six weeks
from now sees a rule breach and goes looking for a distance-based selector that does not exist.**
Standing family: an output that does not discriminate between working and broken.

**And the reasoning cannot be repaired by lengthening the list**, because the list is lexical and the
property is semantic. `"far"` is a distance word in *"the far one"* and a structural word in *"the far
side of the zone"*, and no blocklist separates them.

### What holds it up today, and what would not

**The blocklist is NOT the load-bearing check and the module says so** — a constant string passes it,
and the real assertion is that two destinations produce two DIFFERENT strings, with `why_selected`
derived from the destination object rather than templated. **So today nothing generates a `far side`
string, because the generator names the destination's id and label.**

**The exposure arrives when a human or a later rule supplies the `why`** — which `TARGET-007` (`OPEN`,
deep-V undefined) and the `GATE-027` ladder work both plausibly do. **The check is fine as a tripwire
on machine-generated text and wrong as a validator of human text, and nothing currently records which
of those it is.**

**Cheapest honest fix:** require the whole-word form and drop the two bare substrings, or state in
the docstring that the check applies only to derived strings and must not be run over supplied ones.
**Either is a line. The point is that it stops being silent.** Related: **B97**, **B96**.

### B100 — an entry filed against STALE PROSE is correctly filed and still wrong

**Filed 2026-08-16 after Salim's round-2 rulings superseded `B82`. Review asked for it as its own line
rather than a note on `B82`, and it is right: the register now contains entries whose subject is
DOCUMENTATION LAG rather than defect, and nothing distinguishes them.**

**`RULE_REGISTRY.json` v1.2.0 is half-migrated.** Every `status` field is correct — the corpus triage
landed in full. **The prose around those statuses was never updated: nine rules carry a RESOLVED status
with `notes` that still pose the question as open.**

> **Six of the nine questions this loop sent Salim were re-asks of stale prose.**

### `B82` is the worked example, and it was filed correctly

**`B82` recorded that `GATE-027`'s five-anchor stop ladder is known-incomplete, citing its `notes`:
*"the wide-cover variant … folded into 'Momentum Imbalance' or dropped, unstated."*** Review insisted
it be filed rather than left in a task's Out-of-scope section, **on the correct grounds that an
Out-of-scope paragraph stops being read when the task closes.** That reasoning still holds.

**And the gap was already closed in the source.** The wide-cover stop is a **post-selection
zone-coverage modifier**, cited twice in his own words. **The registry's prose had not caught up.**

    the entry's reasoning     sound
    the entry's citation      accurate — the notes really did say that
    the entry's subject       a documentation gap, not a strategy gap
    the entry's conclusion    wrong

### Why this needs distinguishing rather than just fixing

**A defect entry and a lag entry decay differently.** A defect entry stays true until someone fixes the
code. **A lag entry is falsified by a document being updated somewhere else entirely** — and nothing in
this repo watches the upstream contract's prose.

**So `stale_sweep.py` cannot see it** (the cited code did not change), **`deferral_sweep.py` cannot see
it** (an owner was named), and **`landed_sweep.py` cannot see it** (no task closed). **Three tools built
to catch stale entries, and this class is invisible to all three** — because they all watch OUR
artefacts and the falsifier is in someone else's.

**The cheap discipline, and it costs a phrase: when an entry's evidence is a `notes` or `statement`
field rather than code, SAY SO IN THE ENTRY.** *"Filed against `GATE-027`'s notes"* is checkable against
a later contract version; *"the ladder is incomplete"* is not.

**And the standing consequence for this loop: before filing a gap sourced from registry prose, check
whether a patch supersedes it.** `CLAUDE.md` in the round-2 package says it directly — *"if you read a
rule's notes or statement and it sounds like an open question, check `REGISTRY_PATCH.md` before treating
it as one."*

### B99 — when the DATA validates the wrong hypothesis, and it does so on the row you check first

**Found 2026-08-15 by Execute, verifying two facts the Manager had given it for `T-0024` rather than
relaying them. It accepted one, confirmed the other, and found a third the Manager had not seen.**

**`GATE-032`'s risk matrix is additively decomposable — `LIGHT = NONE - 0.0075`, exact for all three
grades, and the registry says so in `values.exact_relation`. It is NOT multiplicatively
decomposable.** That much was already ruled.

**What was missed: the multiplicative reading is CORRECT ON THE FIRST ROW.**

    grade          NONE     LIGHT    additive -0.0075   multiplicative x0.5
    MANIPULATED    0.0150   0.0075   correct            ALSO CORRECT      <-- the trap
    SUPER          0.0125   0.0050   correct            WRONG (0.00625)
    STANDARD       0.0100   0.0025   correct            WRONG (0.0050)

**`0.015 x 0.5 = 0.0075` and `0.015 - 0.0075 = 0.0075`. The two hypotheses agree on exactly one row,
and it is the row `GATE-032`'s statement leads with** — so it is the row an implementer spot-checks
first.

### Why this is a new shape rather than another instance

**Everything in this register's standing family is about an OUTPUT that fails to discriminate** — a
test that cannot fail, a count with no unit, a green run that means nothing. **All of them are
defects in something someone wrote.**

> **This one is in the DATA.** Nobody wrote a bad check. **The table itself contains a coincidence
> that validates the wrong rule on the most likely first observation** — and no amount of care in
> writing the test helps, because the value being checked genuinely agrees.

**It is the criterion-cannot-see-its-own-defect shape with the defect relocated from the instrument
to the subject.** The instrument is fine. The subject is misleading.

### What actually protects against it

**Not "check carefully" — check the row that DISCRIMINATES, and know which one that is.** Here,
`MANIPULATED` cannot distinguish the two hypotheses and either other row can. **The test must carry
all three and its docstring must say why three**, because a later edit trimming it to *"one
representative row"* restores the trap **and would look like a tidy-up.**

**The general form, and it is cheap: when a rule can be read two ways, find a case where the two
readings DISAGREE before writing any test.** If every case you have agrees, you have not tested the
rule — **you have tested a value on which both readings happen to coincide.**

**Third instance tonight of a family where the check is sound and the thing checked is the problem**,
after `T-0011`'s criterion 5 over an empty census and `EXIT-002`'s constraint over exit sequences
nothing writes. **In all three the assertion was correct and the world it ran against could not tell
it apart from a broken one.**

### B94 — why the announce-your-writes obligation is ABSOLUTE: the reader has no detection channel

**Filed 2026-08-15. This entry is a PAIRING and contains no new finding — both halves already exist
and neither entry contains the join.** `B63` established the writer's duty; Execute supplied the
reason it cannot be best-effort. **Filed now rather than "when the dust settles", which Review
correctly identified as a deferral with an unobservable trigger living in a message — the `B82`
shape, from the seat that had just filed `B82`.**

### The two halves

**`B63`, the writer's duty.** Two measurements can share a worktree only if neither writes. A tool
that mutates a shared tree owes an announcement, because **the writer is the party that knows** —
Review could prove it had disturbed its own suite because it had caused the disturbance, while
Execute's predecessor *"could not prove non-disturbance from inside my own session."*

**Execute's sentence, the reader's side, written after a contaminated mutation run:**

> **"A seat running a measurement cannot distinguish 'my mutation did this' from 'someone reverted a
> file underneath me' — both are just a red line."**

### The join, which is the whole of this entry

**A duty on the writer is normally a convenience: it saves the reader work the reader could do
itself.** Here it is not. **The reader has NO detection channel at all** — a red test is a red test,
and nothing distinguishes a mutation's effect from an unannounced write landing mid-run.

> **So "announce your writes, best effort" is not a weaker version of the rule. It is NO RULE** — a
> writer who announces when convenient produces a world in which the reader's results are sometimes
> meaningless and never identifiably so.

**Measured, not argued.** Execute's eleven-mutation table came back with one test red on all eleven.
**It nearly recorded eleven honest reds.** The cause was `rules/__init__.py` being reverted mid-run by
the Manager. **Nothing in the output said so**, and nothing could have.

### And it retroactively settles a decision that looked like caution

**Review discarded a T-0017 baseline it could not establish was right. The figure turned out to have
been right, and the discard was still correct** — not because the number was suspect, but because
**had it been wrong, nothing available to Review would have said so.** `B63` already records that a
contaminated run and a clean one print identically. **This entry names the consequence: the only
available response to an undetectable class is to discard and re-take.** Not caution. The sole
option.

### The operational form

* **If you write to a shared tree, announce it — before, not after, and every time.**
* **If you are measuring, you cannot verify that nobody wrote. Do not try.** Re-take instead, in a
  `git worktree`, where the question does not arise.
* **A red line is not evidence of what made it red.** Establish the tree was quiet **by construction**
  rather than by inspection, because inspection cannot.

**Four instances tonight, all from the Manager, all `git reset --hard` in a shared tree** — including
one inside the recovery from the first, and two inside a guard added to prevent the first. **None was
detectable by the seat whose work it destroyed until the work was already gone.**

### B92 — the register-commit check is now a HOOK, and a note stopped being the mechanism

**Designed by Review, tested by it against real history before proposing it, installed and verified
by the Manager 2026-08-15.** `.git/hooks/commit-msg` → `agents/register_commit_check.py`.

**THE RULE, entire: every `### B<id>` heading a commit ADDS must be named somewhere in that
commit's message.**

    35b3712   added=[B90 B91]         unnamed=[B90 B91]   CAUGHT — both of the night's defects
    e9ad0df   added=[B86 B87 B88 B89] unnamed=[]          pass  — Execute's, names all four
    d9b987c   added=[B85 B84]         unnamed=[]          pass  — legitimately two, both named
    c52f1d5   added=[B83]             unnamed=[]          pass
    9b2bbef   added=[B82]             unnamed=[]          pass

**One rule catches two unrelated defects and does not false-positive on the legitimate two-entry
commit:**

* **A MISTYPED ID** — the message said `B86`, the diff added `B91`, and `B86` was a real unrelated
  entry.
* **ANOTHER SEAT'S ENTRY SWEPT IN** — Review's `B90` was dirty in the shared tree and
  `git add KNOWN_ISSUES.md` took it. **Caught by the same rule without needing to know whose it
  was:** an added heading the author never named.

### Why it succeeds where four previous guards failed

**Every earlier defence read the tree BEFORE staging** — `git status` first, chaining `add` and
`commit` with `&&` — **and all of them were beaten by timing, four times.** This reads the **staged
diff**, after `git add`, **when the race is already over.** A file swept in by `git add` cannot hide
from a check on what is actually about to be committed.

**And it is a HOOK because all three seats share ONE working tree.** A habit adopted by one seat
protects nothing against a cross-seat defect — **the entry it saves is the one the other seat wrote.**

> **This is "a note is not a mechanism" applied to its own instance.** `B80` recorded the mistyped id,
> changed nothing about how messages get written, **and it recurred within the hour.** The recurrence
> is the argument.

### THE UNGUARDED DIRECTION: an id NAMED in a message that does not exist in the register

**Review found the inverse of the rule and deliberately did not propose fixing it tonight. Recorded
here with its trigger, because *"if it happens again"* in a message is `B82`'s shape and the Manager
has now been caught by that twice.**

**The rule is: every heading a commit ADDS or REMOVES must be named in its message. The inverse is
unguarded** — **a commit that adds no heading and cites an id that does not exist passes cleanly.**
`16a5243` cited `B98` five times against a register that had no such entry, and the check correctly
returned without an opinion because the commit added nothing.

### The trigger, and the Manager's first version of it was measuring the wrong thing

**Proposed: *"if a second dangling citation appears, that is the trigger."* Review dismantled it:**

> **An incident caught for the WRONG REASON is not evidence about the mechanism that failed to catch
> it.**

**The refused commit an hour earlier said `B97` — a real, unrelated entry belonging to Execute — AND
swept in an unbid `B98`. The hook caught it via the SWEEP rule.** So **the citation route has already
fired once and produced no observation of itself**, because the two rules could not be distinguished
by that event.

**Waiting for a "second" therefore measures the rate of citation defects that arrive WITHOUT an
accompanying sweep** — a different quantity, with a base rate nobody has seen. **`B81` in a new
place: the guard went red, coverage looked real, and the red came from a different mechanism than the
one under test.** The count says one; **the count cannot say one OF WHAT.**

**Corrected trigger: THE NEXT CITATION DEFECT OF ANY KIND.** Not a second dangling one — **the
narrower phrasing excludes the two already on record**, `B80`'s footnote (a citation pointing at a
real unrelated entry) and this one. **Two instances of the class, zero observations of a guard, which
is a better basis than a trigger that cannot be evaluated.**

### Why not build it now, which is Review's call and I agree

**The convention it would enforce was decided minutes ago and has not been lived with.** The ruling —
**an entry lands BEFORE or WITH the code that cites it, and the obligation is on the COMMITTER, not
the citing seat** — is the symmetric form of Execute's removal argument. **A strict check today would
flag Execute's behaviour in `16a5243`, which was correct:** it could not commit another seat's entry
without taking its authorship, so it scoped its own commit and left the entry. **The latency was the
Manager's.**

**A check that flags the right behaviour teaches people to bypass it**, which is the credibility cost
recorded above for over-tight guards.

### THIRD BRANCH — a MODIFIED block, ratified after it was the one sweep of three the guard missed

**Requested by Execute, recommended by Review, ratified and implemented by the Manager 2026-08-16
because it changes every seat's commits.**

**The argument is the asymmetry one extended:** an ADDED heading says *"here is a problem"*; a REMOVED
heading says *"this problem is fixed"*; **a MODIFIED block flipping a verdict open → closed makes the
same claim as a removal, in prose instead of on the index, with the same optimistic failure
direction.**

**The instance, and it is the Manager's — sixth sweep of the night:**

    03b18d6  14:22  carried Execute's preamble edit reading "T-0026: B93 CLOSED — the AST guard
                    ... catching 26/26", swept from the shared tree
    ce12b88  14:25  landed the guard

**For three minutes `main` claimed a closed defect with nothing behind it.** The hook saw only
`+### B100` — the committing seat's own heading, correctly named. **Three sweeps tonight, two caught,
one missed; the guard's hit rate was a fact about how the sweeps happened to be shaped.**

### The narrowing matters as much as the branch

**v1 of this branch took every `B<nnn>` in an added line. Against `03b18d6` that yielded TWENTY ids**,
because the register's *"Last updated"* preamble names every entry ever written. **Requiring twenty ids
in a message to fix a typo is the over-tight guard recorded above** — *"a guard that cries wolf on
every legitimate change trains the project to loosen it, and the loosening happens under time pressure
by someone whose attention is elsewhere."*

> **The defect is not a MENTION. It is a VERDICT FLIP.** So the rule is: **closure claims present in
> added text and ABSENT from removed text.**

**Replayed:** `03b18d6` → `['B93']`, caught. `ce12b88`, `672b3db`, `b8ca332` → no new claims, all pass.
**One true positive, zero false positives across four real commits.**

**The honest cost, which Review stated rather than argued away:** an edit that genuinely closes an entry
now needs its id in the message. **That is one token and a true statement about what the commit did.**

**And Review's caveat belongs beside this branch rather than in prose: this is the THIRD branch added
by a person after an incident, and none of the three came from the guard firing in normal operation.**
It prevents recurrence; **it cannot produce discovery.**

### WHAT A GREEN HOOK IS EVIDENCE OF — read this before trusting it

**Review's formulation, put here rather than left in a message because it is the thing a future seat
will most easily get wrong about this guard.**

**It HAS been proven capable of firing.** Replayed against `35b3712` and `33a3951`, live-tested in
both the refusing and passing directions, both before and after the removal extension. **So this is
not `B79`'s shape** — a claim documented and never asserted. **Capability is demonstrated.**

**What has never happened is a catch IN ANGER, and those are different facts.** Every defect it now
covers was found by a person:

    the mistyped id            found by reading a commit message against its diff
    the swept-in foreign entry found by Review noticing its entry under someone else's name
    the silent fallback        found by Review reading the code against the author's own sentence
    the missing removal check  found by Execute having its deletion swept

**Two extensions in two hours, both from reading rather than from firing.**

> **So its coverage is exactly the set of mistakes ALREADY MADE, and its blind spots are, by
> construction, the mistakes nobody has made yet.**
>
> **It prevents recurrence. It cannot produce discovery. A green hook is evidence about the PAST,
> not about this commit.**

**The practical consequence: do not let a passing hook substitute for reading your own staged diff.**
`git diff --cached KNOWN_ISSUES.md | grep '^[+-]### B'` costs one line and answers the question the
hook only answers for the failure modes someone already hit.

### EXTENDED TO REMOVALS — and a REMOVED heading is the STRONGER claim

**Found by Execute after the guard let a swept DELETION through. Verified: `33a3951` named `B94`,
added `B94`, satisfied the check — and carried away Execute's uncommitted removal of `B90`.**

    a69f368  B90 present: 1
    17ebdd6  B90 present: 1
    ec711b4  B90 present: 1
    33a3951  B90 present: 0    <- removed here, while the FIX was still uncommitted

**For about twenty minutes `main` said `B90` was fixed with no code implementing it.** Fifth sweep by
the Manager, and the first the new guard was supposed to prevent.

**The rule was asymmetric and the asymmetry was backwards. Execute's argument, adopted:**

> **An ADDED heading says *"here is a problem."* A REMOVED heading says *"this problem is FIXED."***
> It retires a known defect, and the register's rule is that an entry disappears only when the fix
> lands in the same commit. **A swept deletion breaks that invariant silently, and it breaks it in
> the OPTIMISTIC direction** — the register and the code disagree, with the register claiming the
> better state.

**So the check is now symmetric: every `### B<id>` a commit ADDS *or REMOVES* must be named in its
message.** Same staged diff, same place in the hook.

**Replayed against history:**

    33a3951   adds=[B94]  removes=[B90]  unnamed_del=[B90]   CAUGHT
    c6ebd2f   adds=[]     removes=[]                          pass
    e9ad0df   adds=[B86 B87 B88 B89]     removes=[]           pass

**And the removal branch says why it fired**, because the two cases need different responses: an
unnamed ADD is usually a typo or another seat's entry; **an unnamed REMOVAL means you are retiring
someone else's fix, or your own too early.**

**Implemented by the Manager rather than referred to Review, whose design it is** — the gap was live,
the fix was ten lines, and **the Manager caused the incident it closes.** Review invited to change any
of it.

### THE GUARD ITSELF SHIPPED WITH TWO INSTANCES OF THE FAILURE IT ENDS — found by Review reading it

**Review read `register_commit_check.py` in full rather than the description, on the grounds that an
executable a peer installs into a shared tree is exactly the thing to read.** Both findings are the
guard committing its own founding defect.

**1. THE DOCSTRING NAMED THE WRONG STAGE.** The shim said *"MUST be commit-msg, not pre-commit"*; the
module it invokes said **"Installed as `.git/hooks/pre-commit`"**, in bold, as fact. **A file that
records its own installation is what a future reinstaller follows — and it instructed them to
recreate exactly the misconfiguration that had just cost a failure.** The wrong instruction in the
more authoritative-looking place.

**2. THE SILENT FALLBACK WAS THE FAILURE, STILL IN THE CODE.** With no `argv[1]` it fell back to
`git log -1 --format=%B` — **the previous commit's message.**

> **The author's own sentence about that failure, written an hour earlier: *"a hook at the wrong
> stage is worse than no hook, because it reports confidently from the wrong input."* That behaviour
> was still in the code, unmarked, as a fallback.**

**And the two compose into a working trap:** follow line 31, install as `pre-commit`, get no
`argv[1]`, and the hook **silently validates against the previous commit's message** — refusing
correct commits and **passing wrong ones whose predecessor happened to name the right id.**

**Fixed by failing closed.** A guard that cannot see its input refuses rather than substituting a
different one. **This is the AST tripwire's principle inside this guard: *"could not look"* must never
share a result with *"looked and found nothing"* — and the fallback made it share a result with
*"looked at something else entirely,"* which is worse, because the wrong input still yields a
confident verdict.**

**Verified after the fix: no message file → exit 1. Both hook directions still correct.** And the
first attempt to verify it **read the exit code through `| head`, which returned head's status** —
the same pipe defect, in the check written to catch confident reporting from the wrong input,
measured wrongly by its author sixty seconds after fixing it.

### Installed at the wrong stage first, which is worth recording

**It went in as `pre-commit`, which receives NO ARGUMENTS.** The message file is passed to
`commit-msg`. So the script's fallback read `git log -1` — **the PREVIOUS commit's message** — and the
check compared new ids against an old message. **It refused a correct commit and would have passed a
wrong one whose predecessor happened to name the right id.**

**A hook at the wrong stage is worse than no hook**, because it reports confidently from the wrong
input — this register's standing shape, in the guard written to end it.

### And the cleanup destroyed a real commit

**Testing it, the Manager ran `git reset --hard HEAD~1` to drop a test commit the hook had just
REFUSED TO CREATE.** No test commit existed, so it dropped **`a69f368`** — the correction commit —
instead. **Recovered from `origin/main` in full; nothing was lost.**

**The defect: a cleanup that assumes the thing it is cleaning up exists.** The second attempt guarded
it — *"only reset if the top commit is the test commit"* — which is the shape to use.

**AND REVIEW'S FRAMING IS BETTER THAN "CARELESS", so it is the one to carry: A GUARD THAT WORKS MAKES
ITS OWN TEARDOWN'S PRECONDITION FALSE.** The teardown assumed a commit existed; **the refusal the test
was verifying is precisely what stopped it existing.** The more correct the guard, the more certainly
the cleanup is wrong — **so the interaction is structural rather than sloppy**, and any test of a
refusal has it.
**`git reset --hard` with an unverified target is the only command tonight that destroyed work, and it
was in the teardown of a test, not in the change under test.**

### B91 — a snapshot of a MUTABLE value is EVIDENCE, not a duplicate — the limit of "never store a second copy"

**Found 2026-08-15 by Execute while applying a Manager ruling, and it is a refinement of that ruling
rather than an exception to it. Filed because the rule as I stated it would, applied literally, delete
evidence.**

**The ruling was:** do not copy a liquidity pool's `class` into the target record — set
`target_object_id` to the pool's own id and recover the class by joining to the linked
`setup_evaluation`. **Rationale: a second copy can go stale, and the copy nothing checks is the one
that goes wrong.**

**Execute applied it, dropped `source_class` and `tf` as duplicates, and KEPT `fill_state` — then
flagged the asymmetry rather than letting it pass unexplained.** It is right, and the test it found is
the one my rule was missing:

    pool `class`          IMMUTABLE.  A stored copy can only ever DRIFT FROM the truth.   -> DUPLICATE
    imbalance fill_state  MUTATES as price approaches. A join recovers the state NOW,
                          never the state WHEN THE TARGET WAS CHOSEN.                     -> EVIDENCE

> **"It was HALF_FILLED when we selected it as a target" is unrecoverable by any later read.** By
> settle time the imbalance may be `FULLY_FILLED`, and the join returns that — **correct, and
> useless.** So the stored value is not a second copy of a fact; **it is the only copy of a different
> fact.**

### The general form

**"Do not store a second copy" assumes the source can be re-read to get the same answer. That
assumption is what makes a copy redundant, and it fails for anything that changes.**

**So the test before deduplicating is not *"is this value available elsewhere"* — it is *"will
re-reading it later return the value I mean?"*** For an immutable attribute, yes, and the copy is
waste. **For a state that advances, no** — and a decision record that omits it can never be
reconstructed, because **the world moved on and the source now describes the world, not the
decision.**

**This is the same distinction as B34's stale-claim family seen from the other side.** There, the
danger is a copy that goes false. **Here, the copy is the only thing that stays true** — the SOURCE is
what goes false relative to the moment being recorded.

### And name the field so it cannot be misread

**`fill_state` alone invites the reading that it is current state, which the join would then
contradict.** A point-in-time field must say so in its name — `fill_state_at_selection` — **the same
device as `risk_altcoin_heavy_as_written`, where the suffix is the registry warning a reader that the
value is a quotation rather than an input.**

**A snapshot that does not announce itself as a snapshot is a stale value waiting to be believed.**

### B85 — the id ledger issued a DUPLICATE, and it took two independent failures that each looked harmless

**Filed 2026-08-15. `B83` was assigned twice: to Review's cushion-monotonic entry, committed at
`5a58e2a`, and again to the Manager's empty-world entry minutes later. The second is now `B84`.**

**The ledger exists for exactly this** — `bus.py bid` was built after two seats both wrote a `B55`,
and its promise is *"it takes the max of the highest committed heading and the highest previous
claim, so it sees the uncommitted claim the file cannot."* **It issued a collision anyway.**

### Two failures, neither sufficient alone

    1. THE FILE SCAN WAS BLIND.  regex `^### B(\d+)\.`  — it requires a PERIOD after the number.
       Every heading since the format changed reads `### B83 — …` with an EM-DASH.
       So the scan silently matched nothing newer than the last period-formatted entry.

    2. REVIEW DOES NOT BID.  By arrangement it writes entries and the Manager commits them —
       the separation that makes "finder and committer are different seats" true, and which
       this register defended two hours before this happened.

**Each is survivable alone.** With a working scan, an unbid entry is still seen once committed. With
every entry bid, a blind scan does not matter. **Together the id was invisible to both halves and the
next bid reissued it.**

> **And the blind scan had been broken for a long time without symptom, because the claim file alone
> was sufficient while every entry was claimed.** The tool reported *"highest in file 60"* on every
> bid for hours — **a number that had stopped moving, printed next to one that kept moving, and
> nobody read the pair.** That is this register's two-numbers-together check, available on every
> single invocation and never performed.

### What made it visible, and it was not a check

**Nothing detected it. The Manager noticed the returned id was one it had committed itself twenty
minutes earlier** — recognition from memory, in the one window where that memory existed. **A seat
that had not committed `B83` personally would have taken `B83` and written a second entry under it.**

### Fixed, and the residue

**The regex now matches `^### B(\d+)\b`** and the scan reports `highest in file 84`, which is
correct. **The arrangement that Review does not bid is NOT changed** — it is load-bearing for
authorship, and the correct fix was the scan, not the convention. **A process rule and a tool must not
both be relied on to cover the same gap unless one of them is checked.**

**Standing consequence: `bid` prints `highest in file N` and `highest previously claimed M` on every
call. READ BOTH.** If `N` stops moving while `M` climbs, the scan is broken again — **the failure is
visible in the tool's own output and always was.**

### B84 — a check over an empty world: TWO confirmed, and here is what the third must look like

**Filed 2026-08-15 as a DEFERRAL WITH A TRIGGER, not as a shape. Renumbered from B83 to B84 —
see B85 for why the ledger issued a duplicate.**

** There are two instances and two is
not a pattern** — but *"wait for the third"* is a decision with a condition, and `B82` established
that such decisions die in whatever message they were written in. **This is that decision, put where
`deferral_sweep.py` can see it.**

### The two

    T-0011 / criterion 5-i    a CI check over `scan_census` records, with ZERO censuses stored.
                              Green the day it ships, and stays green until the first census exists.

    T-0022 / EXIT-002         a negative constraint over exit sequences. `records.trade_execution()`
                              is the ONLY builder of a record carrying an `exits` array and has
                              ZERO CALLERS in app/, tests/ or scripts/ — verified by Review and
                              independently by the Manager. `records.setup_evaluation()` IS called,
                              at `shadow.py:711`, so this is not "telemetry is unwired" generally.

**Both are the same failure: an assertion whose input set is empty passes, and the pass is
indistinguishable from the assertion doing its job.** The remedy in both cases is `T-0011`'s `5-i` —
**report the number of records examined and make ZERO a distinct outcome rather than a pass.**

### What is NOT a third, and naming it is the point

**The Manager listed the prober's `strategy_step` gap as a third instance in the same breath as
saying it would wait for a third. Review caught the contradiction and the diagnosis is Review's:
`strategy_step` is a different animal.** A probe with no step to probe is **a checker with nothing to
check**; these two are **a telemetry type that shipped with a schema, a builder and no producer.**
**Dropped from the count. The honest number is two.**

### The trigger, stated so a later reader can recognise it

**File the shape as its own entry when a THIRD case appears with all of:**

1. **a stored record type or field defined in the contract**, with
2. **a builder or writer that exists in the source**, and
3. **no caller anywhere**, so that
4. **a conformance assertion written over it passes on an empty set.**

**If the third arrives, the question the entry must answer is which of two worlds we are in:** *"new
telemetry types routinely ship without producers"* — a process defect in how contract work is
sequenced — or *"this happened twice for unrelated local reasons"*. **Two instances cannot separate
those and three probably can.**

**And check the trigger BEFORE writing a conformance check over any stored record type.** The cost of
the check is one grep for callers of its builder; **the cost of skipping it is a green CI row that
means nothing, discovered by whoever eventually wires the producer.**

### B83 — the ladder is asserted cushion-monotonic, and if that is true `GATE-030`'s flag can never fire

**Filed by Review 2026-08-15, from reading `GATE-027`'s notes in full while verifying B82. Not
measured on data — this is an inconsistency between three rule texts and `T-0025`'s plan, and which
side of it is true is exactly what nobody has established.**

**The three statements.** `GATE-027` asserts the ladder *"is cushion-monotonic"* — *"The first
options provide more room for natural pullbacks, while the later options progressively reduce that
cushion."* `GATE-025` says reject a candidate below 2R and *"evaluate the next tighter option"*,
where **"next tighter" means next in ladder order** — which is only "tighter" if the ladder is
monotonic. And `GATE-030` (SOFT_PREFERENCE) emits `TIGHTER_THAN_NECESSARY` **"when a tighter
candidate is chosen over a wider one that also cleared 2R."**

> **Walk the ladder in order and stop at the first rung clearing 2R. If the ladder really is
> cushion-monotonic, that procedure CANNOT select a tighter candidate over a wider one that also
> cleared 2R — every wider candidate sits earlier and was already rejected for failing 2R. So
> `GATE-030`'s flag is unreachable by construction.**

**Either the monotonicity claim is true and `TIGHTER_THAN_NECESSARY` is dead code, or the flag is
reachable and the monotonicity claim is false. Both cannot hold, and nothing measures which.**

**Why the false side is plausible rather than theoretical.** The ladder is monotonic at its ends by
definition — `DEEPEST_SWING` is the deepest, `INNER_MSB` the innermost. **Rungs 2–4 are not ordered
by construction at all:** `MOMENTUM_IMBALANCE`, `LIQUIDITY_SWEEP_QML`, `ORDER_BLOCK` are named chart
objects, and there is no reason a swept wick cannot sit closer to entry than an order block on a
given setup. **Monotonicity is an empirical property of rungs 2–4, asserted in prose as if it were a
definition.**

**This is live for `T-0025`, which does not mention `GATE-030` anywhere.** Its plan says the ladder
runs *"from most cushion to least, stopping at the first candidate that clears 2R"* — **the
assertion adopted as fact.** If it is false, the implementation is wrong precisely on the setups
where the ordering matters, and no criterion in the task can see it.

**It is measurable, and the shape is B78's, not a single fixture's:** compute the five anchor prices
per setup over a corpus SET and check whether ladder position is monotonic in `|entry − stop|`. **One
inversion anywhere proves the flag reachable and the claim false.** Two pinned setups prove nothing,
for the same reason `ε` needed a corpus rate.

**What must not happen:** implementing the ladder, observing `TIGHTER_THAN_NECESSARY` never fires,
and reading that as the rule being satisfied. **It is the same reading either way** — which is the
standing family: an output that does not discriminate between working and broken. Related: **B82**
(the same rule's other unresolved sub-item), **B79**, **B52**.

### B82 — `GATE-027`'s five-anchor ladder is KNOWN-INCOMPLETE, and nobody has decided the sixth

**Filed 2026-08-15 at Review's insistence, and the reason it is here rather than in a task is the
entry's own point.** It was written in `T-0025`'s **Out of scope** section, which was correct
guidance for the implementer and **stops being read the moment T-0025 goes DONE.**

**`deferral_sweep.py` cannot see it.** Its docstring states the blind spot in as many words: *"IT
READS ONLY KNOWN_ISSUES.md … a clean run here says nothing about task files."* **This is the first
thing to fall into a blind spot that was documented before it had an instance.**

### The gap

`GATE-027`'s ladder has five anchors — `DEEPEST_SWING`, `MOMENTUM_IMBALANCE`, `LIQUIDITY_SWEEP_QML`,
`ORDER_BLOCK`, `INNER_MSB`. **Two documented stop behaviours are not among them:**

* **The wide-cover variant** — *"my SL is way above… because i am covering the imbalance above with
  the BB level"* (`049/116`).
* **`§9.J IM79/IM86`'s rule that a stop at a flip zone must cover the WHOLE zone.**

**`GATE-027`'s own notes say the disposition is unstated:** whether these were *"folded into
'Momentum Imbalance' or dropped"* is **not recorded anywhere** (`§10.F.2` item 19).

> **So the ladder is not five-of-five. It is five documented anchors with at least one documented
> behaviour that fits none of them, and no ruling on whether that behaviour is a sixth anchor, a
> special case of the second, or withdrawn.**

**This is question 5(b) in the pack sent to Salim on 2026-08-15. Unanswered.**

**What must NOT happen, and it is the reason this is worth an id:** an implementer meeting a
wide-cover stop in a fixture and **folding it into `MOMENTUM_IMBALANCE` because that is the nearest
slot.** That is a ruling, made by whoever was holding the diff, wearing the ladder's authority — the
same shape as widening `emission_policy_id` to make a failure compliant. **The ladder is authoritative
for what it lists; it is silent, not exhaustive, about what it does not.**

**Distinct from the QML hole** (`T-0025` criterion 2), which is a listed anchor the engine cannot
locate. **This is an unlisted behaviour the doctrine demonstrates.** One is a slot with no shape; the
other is a shape with no slot.

### B81 — "already covered" can mean "covered by a test that sends you the wrong way"

**From T-0018, found by Execute past the criterion that asked the question. Review added `1c` during
plan review to test the task's own premise — *nothing pins the library's output* — because that
premise had never been contested. Measured per axis:**

    smc.fvg stamping                   shifted 1 bar   1 FAILED   -> "already caught"
    smc.swing_highs_lows confirmation  shifted 1 bar   1 FAILED   -> "already caught"
    smc.bos_choch BrokenIndex          BrokenIndex-1   7 passed   -> NOT CAUGHT

**Two of three protected, so the motivating claim was two-thirds false and the task shrank to one
axis.** That alone is `1c` working.

**THEN EXECUTE LOOKED AT *WHICH* TEST CAUGHT THEM, WHICH NOBODY ASKED FOR.** Both "caught" results
fired the same single test — `test_fixture_opens_trades_both_directions`, **a canary asserting the
fixture still trades.**

> **It goes red because a shifted library STOPS TRADES, not because anything noticed the semantics
> moved.** So a reader who saw it fail would go looking **in the engine**, at trade generation —
> **away from the library that actually changed.**

**That downgrades the verdict: not *"already caught"* but *"incidentally caught by a test that
misdirects."*** One axis unprotected and two behind a canary, which is a different picture from two
of three protected.

### The shape, and it is distinct from everything above it

    a test that CANNOT fail        the standing family — ~25 instances
    a test that fails for the
      WRONG REASON                 THIS — it fails, so coverage looks real, and the failure
                                   points at the wrong subsystem

**A canary is cheap and worth having. The defect is COUNTING IT AS COVERAGE OF THE THING IT DID NOT
TEST.** *"Does a test fail when I break this?"* is the question everyone asks; **the second question
is *"does the failure tell the reader WHAT broke?"*** — and a coverage audit that only asks the first
will report a misdirecting canary as protection.

**So when a premise check reports *"already covered"*, name the covering test and read it.** The
distinction costs one grep and it changed T-0018's conclusion after the criterion had already been
satisfied.

**AND THE OPERATIONAL FORM IS NARROWER THAN "READ THE FAILURE MESSAGE" — Review's addition, and it is
the part that can actually be enforced:**

> **A coverage measurement must record WHICH TEST caught it, never only the count.**

`1c` returned `1 FAILED -> already caught`. **That string was true and useless.** It became a real
result the moment the test's **name** appeared, because the name was
`test_fixture_opens_trades_both_directions` and **any reader can see instantly that a fixture-trades
canary is not library-semantics coverage.**

**A count cannot be wrong in that way. It also cannot be right** — it carries no information that
distinguishes protection from coincidence. **Same family as everything else in this register: an
output that does not discriminate between working and broken**, arriving in the output of a check
written to establish coverage.

### B80 — VERIFICATION CAPACITY RUNS OUT LAST, and a seat that refuses the next task is doing it right

**Execute #3 finished five tasks, declined to start `T-0022`, and gave the reason. Recorded because
the refusal is the correct behaviour and the next seat needs to know it is allowed.**

> *"Starting T-0022 now would mean opening the largest and most consequential task in the programme —
> the first one that changes what happens to money — with enough room to write code and not enough to
> verify it. **Five of my seven passing mutations were vacuous TESTS, and I only caught them because I
> had room to ask why nothing went red.** A half-verified exit model is worse than none."*

**FIVE OF SEVEN. The mutation discipline's main yield this session was catching its own tests being
broken**, not catching the code being wrong — and that catch is the part that needs slack.

### Why context exhaustion is specifically dangerous, and it is not "less gets done"

**Work is written early and verified late.** So a seat that runs low does not degrade evenly:

    early context    code written, tests written, mutations run
    late context     "why did nothing go red?"  <- the half that finds vacuous tests
    exhausted        code still lands. verification silently does not.

> **Context exhaustion converts a verifying seat into a non-verifying one WITHOUT CHANGING ITS
> OUTPUT.** The commits look the same. The suite is green either way — **that is what a vacuous test
> means.** So this is the register's standing failure applied to a seat rather than a tool: **an output
> that does not discriminate between verified and unverified.**

**Hence the rule: do not start a task you cannot finish verifying, and say so rather than starting
it.** Execute #3 is the first seat here to stop on that ground rather than on running out mid-task, and
**its predecessors both exhausted themselves mid-work and left a handoff written under pressure.** This
one wrote the handoff deliberately, with room.

### Footnote, and it is the same-claim-two-homes rule catching its own author

**This entry is `B80`. The commit that introduced it says `B78` in its subject line** — and `B78`
exists, belongs to Execute, and is about the reproducibility of a declared rate. **So a reader
searching `git log` for `B80` finds nothing, and a reader following the `B78` message finds an entry
about something else.** Corrected by a follow-up commit rather than a force-push.

**The mechanism worked and the hand-typed copy did not.** `bus.py bid` returned `B80` correctly —
Execute had taken 78 and 79 while I was working, which is exactly the collision the ledger exists to
prevent. **The script wrote the heading from the returned variable and I typed the number into the
commit message by hand.**

> **The generated copy was right; the hand-copied one was wrong. That is the unaudited-copy rule from
> this preamble, and the unaudited copy was the commit message** — no test, no CI row, and nothing
> pointing at it, exactly as that entry predicts.

### And the same session produced a third-order instance of the truncation failure

**I built `agents/rule_show.py` specifically because a 420-character slice cost `T-0023` a rule level.
I then ran it on `GATE-032`, piped the output through `sed` to read only the `SIZE-004` half, and
scoped `T-0024` from the part I did not read.**

**What was in the unread half:** `exact_relation` — *"LIGHT = NONE - 0.0075, exact for all three
grades"* — which makes criterion 1's *"no decomposition reproduces it"* **false**, and
`depends_on: ["GATE-002","GRADE-002","GRADE-003","GRADE-004"]`, which answers a question the plan's
out-of-scope section told the implementer to go and check.

    the tool truncated        -> B44, filed against rule_waves.py
    the reader truncated      -> T-0023, 420 chars, lost a rule level
    the reader truncated the FULL-TEXT TOOL'S OUTPUT  -> this, one hour after building it

**Three levels of the same failure, the third by the author of the fix, inside the hour.** The lesson is
not "read more carefully" — it is that **a tool cannot fix a truncation the caller performs downstream
of it.** `rule_show.py` printed everything and said it printed everything; **`sed -n '/^SIZE-004/,$p'`
discarded it after the guarantee had been honoured.**

**Both instances were caught by Review, and both were caught in the same direction: my confident claim
contradicting the registry.** That is the false-alarm direction from the collapse entry above — it
costs a colleague's correct work rather than a cycle, and it is now four for four.

### B77 — `poi_type` cannot express two of the five imbalance types, and M6 is where that bites

**Found 2026-08-15 by the Manager while auditing the schema ahead of T-0017, for the failure class
`B65` established: an artefact that cannot represent what the engine produces.** **NOT a live defect —
filed so it is not discovered by whoever is mid-build on M6.**

    /$defs/imbalance/properties/type            FVG · VOLUME_IMBALANCE · GAP · BPR · SUPER_BPR
    /$defs/.../imbalance_primary_poi/poi_type    IMBALANCE ·                GAP · BPR · SUPER_BPR

**Two enums, overlapping objects, different vocabularies.** The mapping M6 must write:

    FVG               -> IMBALANCE      lossy: the name changes
    VOLUME_IMBALANCE  -> IMBALANCE      LOSSY: collapses with FVG, no distinct slot
    GAP / BPR / SUPER_BPR               identity

> **So a record can say the primary POI was "an imbalance" and cannot say WHICH KIND.** `FVG` and
> `VOLUME_IMBALANCE` are distinct primitives the detector separates and the contract then merges —
> **and the merge is invisible in the stored record**, which is the property that makes it worth an
> entry rather than a note.

**Why it is not live, stated so nobody spends time confirming it:** `entry_criteria` is **absent from
`setup_evaluation.required`**, nothing in production populates it, and `shadow.py:694` says so
explicitly — *"`entry_criteria`, none of which exists before M6"*. **But if `entry_criteria` IS present
it requires `imbalance_primary_poi`**, so the first M6 record that carries entry criteria at all must
resolve this mapping. **There is no partial adoption.**

**And `poi_type` itself is optional inside `imbalance_primary_poi`** (no `required` list), so **the
lazy path is to omit it** — a POI recorded with `met: true` and no type, which validates. **That is the
outcome to forbid in M6's plan rather than discover in its review.**

**Same family as `B65` and one degree milder:** there, the truthful record could not be stored; here it
can be stored and says less than the engine knew. **Unrepresentable versus lossy — and lossy is the
one that passes validation.**

### B76 — a BATCHED push leaves intermediate commits with no run, and tree identity cannot rescue them

**Found 2026-08-15 by Review inside a T-0015 verdict — it declined to call the range clean — and
verified by the Manager. `1b1c61a` is genuinely UNVERIFIED.**

    1b1c61a   committed 01:06:50   T-0015 panel recency and thickness    NO RUN, no twin
    d2d85ea   committed 01:13:36   T-0015 a bar closing in the future    run at 01:17:54, success

**Both were pushed together, so the workflow fired only for the pushed tip.** And `d2d85ea` modified
the same two files (`data_health.py`, `test_panel_health.py`, +78 lines), **so the two trees differ and
no verdict can transfer.**

### The asymmetry, which is the part worth carrying

**This project has already recorded that cancellation rate tracks push cadence (`B62`). This is the
opposite failure and it is strictly worse:**

    PUSH OFTEN     runs get CANCELLED           tree identity USUALLY RESCUES them, because
                                                consecutive register commits share a code tree
    PUSH BATCHED   intermediates get NO RUN     tree identity CANNOT rescue them, because each
                                                commit in the batch changed code — that is why
                                                they are separate commits

> **Cancellation is loud and recoverable. A never-run intermediate is silent and unrecoverable** —
> and it is the one nobody looks for, because the tip is green and the range summary says `0 red`.

**`ci_range` reports it correctly and always did** — *"no run, and no identical-tree commit anywhere —
UNVERIFIED"*, `1 UNKNOWN` in the totals. **The gap was never in the tool; it was that nobody ran it
over a range containing a batch.** Review ran it and reported the one UNKNOWN rather than the
range-level `0 red`, which is the whole reason this is filed.

### Severity, stated precisely because "unverified" overstates it

**The SHIPPED code is verified.** T-0015's final state is in the green tip; what never ran is an
intermediate state **that no longer exists on `main`** and that nobody will check out. **So the cost is
not a live untested path — it is that `git bisect` across this range lands on a commit whose test
status is unknown, and that a claim of "every commit on main is green" is false.**

**Remedy is a choice rather than a fix, and both options are legitimate:** push one commit at a time and
every state is tested, or batch and accept that intermediates are untested. **What is not legitimate is
batching and then saying every commit is verified.** Run `ci_range` over the range after any multi-commit
push, and read the `UNKNOWN` count rather than the `red` count.

### B79 — the library-semantics exposure, and the ONE axis that was actually unprotected

**Filed by T-0018, 2026-08-15.** Points at `requirements-prod.txt`, NOT at `ict/detector.py`.

**The exposure.** `requirements-prod.txt` says *"the three lookahead fixes are written against
its exact output semantics… treat any bump here as a strategy change"*, and
`test_lookahead_regression.py` restates the same dependency in prose. **Both DOCUMENTED it;
neither ASSERTED it.** The file is not in `GUARDED_FILES`, a bump is a one-line diff, our
engine code is unchanged, and no probe fires. **The prober cannot help** — it verifies that
existing tests are load-bearing, and there was no test to be load-bearing.

**MEASURED PER AXIS rather than assumed, by monkeypatching each library function at its
boundary and running the existing lookahead and bias-causality tests:**

    smc.fvg stamping                  shifted one bar      1 FAILED  -> already caught
    smc.swing_highs_lows confirmation shifted one bar      1 FAILED  -> already caught
    smc.bos_choch BrokenIndex         BrokenIndex - 1      7 passed  -> NOT CAUGHT

**So two of three were already protected and the task shrank, which is the good outcome.** The
honest form of *"treat any bump as a strategy change"* is *"here is precisely which part is
unprotected"*, and it is `BrokenIndex`.

**AND THE TWO "CAUGHT" RESULTS ARE WEAKER THAN THE WORD SUGGESTS.** Both were caught by
`test_fixture_opens_trades_both_directions` — a canary asserting the fixture still trades. It
fires because a shifted library changes behaviour enough to stop trades, not because anything
noticed the semantics moved, so the red would send a reader to the engine. *Something goes red*
is not *the right thing goes red*.

**Fixed:** `tests/integration/test_smc_output_semantics.py` pins all three against the pinned
version's real output, asserts the pin itself (`==0.0.27`), and mutates each at the LIBRARY
boundary — which is the only thing distinguishing "pins the library" from "re-tests the engine".

**A transcription error I made and measured out.** My first swing assertion used a SYMMETRIC
window either side of the swing — the intuitive reading, and wrong: it holds on 11 of 12. The
library's rule is the FORWARD window, 13/13, which *is* the confirmation lag `_daily_bias_events`
corrects for. A guessed semantic would have shipped as a test failing on real data for reasons
unrelated to any bump.

**Not done, deliberately:** `requirements-prod.txt` is NOT added to `GUARDED_FILES`. The list is
for files the prober WRITES TO — `restore()` runs `git checkout` over the whole list, so adding
a file the script never mutates means the next probe destroys uncommitted work in it (**B18**).
The dependency closure (63 of 153 modules, saturating at depth 4) is why a guard list is the
wrong instrument here at all. **B52's collapse is recorded in B52 and is not restated here.**

### B78 — how reproducible is a declared rate? Measured, and the answer bounds every future threshold

**Filed by T-0017, 2026-08-15.** The next declared threshold will face the question "is that
rate real or is it the window you measured on", and this is the only measurement of it.

**The drift, over sliding 863-bar corpora of live 5m `BTCUSDT.P`:**

    sliding 863-bar corpora    min 12.9%   max 20.4%   spread 7.5 points
    |change| over 1h           median 0.23   max 1.17
    |change| over 3h           median 0.70   max 2.70
    |change| over 6h           median 0.82   max 3.05

**So a rate quoted without its window is reproducible to about ±3 points over a few hours.**
That is the size of the error bar on any single-corpus declaration, and it is large enough to
move a value across a band edge — which is the whole of T-0017.

**AND `k = 3.5`'s 6-of-54 ACCEPTANCE DID NOT SURVIVE THE FIXTURE CAPTURE. It is 0 of 54.**
The plan turned on that value: Review measured it marginal on a live fetch, and the mutation
was specified against it. In `tests/fixtures/btcusdtp_5m_1500.csv`, captured five days later,
`3.5` runs 37.8%–43.7% and is **rejected on every corpus**.

**This is the plan's own predicted risk arriving, and it is the reason the criterion forbade
pre-committing to a `k`.** The marginal value in the pinned fixture is **`k = 2.5` at 26 of
54**, and that is what the mutation runs on. **The fixture was NOT recaptured to look for a
friendlier number** — the property under test is that the set form is stricter than the
single-corpus form, not that any particular `k` is marginal.

**What it says about the method rather than the value:** a threshold's marginality is not a
property of the threshold. It moved from 6/54 to 0/54 in five days without anyone changing
anything, which is a stronger statement of the same finding the drift table makes.

**The declared `k = 3.0` is unmoved** — 54/54 in the live measurement and 54/54 in the pinned
fixture, 16.5%–21.7%. The declaration is robust; only the marginal neighbours move.

**The fixture is now a maintained artefact** and it will age. Its value is REPRODUCIBILITY,
not currency: a red run against it is unambiguously a defect because the market cannot move
under it, and that is exactly what a live check cannot offer. A fixture nobody re-captures
describes a market that no longer exists, and that is acceptable and stated. Related:
**B46**, and T-0014 Part 1's declaration, which is honest and unchanged.

### B75 — no Tier 0.2 probe covers ANY contract primitive

**Found in:** T-0020, 2026-08-15, as the structural half of **B73**. Review confirms it is the
honest successor to **B52**, which asked whether the prober's guard list was too narrow, found
that it was not, and became a note. **This is the gap B52 was reaching for.**

**What it is.** `verify_guards.sh` probes eight guards and every one of them is the LEGACY
path: the ICT FVG entry rule, the daily bias window, three dominance properties, three
execution properties. **Not one covers a contract primitive** — PRIM-001 through PRIM-006, the
inventory that produces every admissible entry object after cutover.

**Why it matters, and B73 is the proof rather than the hypothesis.** PRIM-002's SUPER_BPR
promotion read forward — a band formed at bar `i` promoted by a component formed at `i+900` —
and it went unnoticed through two independent measurement passes by two other seats. **Tier
0.2 exists precisely to catch a rule that reads the future, and it is pointed entirely at the
code being replaced.** A primitive reading forward is invisible to the machinery built for
that class of defect.

**The five others have never been checked.** Swings, liquidity pools, sweeps, breaks and SR
flips all scan sequences and all could take the same shape.

**Fix:** extend `GUARDED_FILES` and the probe list to the primitives — one probe per
primitive that mutates its causality constraint and requires a test to go red. Note the
prober refuses to run on a dirty tree, so this also puts the primitives under that guard.
Related: **B73**, **B52**.

### B74 — what T-0020 did NOT achieve: the declared tolerance is not met, and the lookback is ours

**Filed by the implementer of the fix, 2026-08-15**, because the improvement is large enough
to read as completion.

**The declared tolerance is NOT met.** 5.0 percentage points was stated BEFORE the fix and
measured against the unfixed code (46.6-point spread), so it genuinely rejects the old
behaviour. The fixed code gives **8.8 points**. That is recorded as a `strict=True` xfail
rather than widened, because moving a tolerance after measuring is the `k = 3.0` shape this
task exists because of.

**What the fix DID achieve, so the two are not confused:**

    monotonic unbounded growth      gone  (15.8->62.4 rising; now 6.6/12.1/14.0/16.0/15.1)
    bands differing 250 vs 999      0 of 54
    bands differing 320 vs 999      2 of 86  (was 11 of 86) — both window-EDGE cases
    lookahead in the promotion      fixed (B73)
    same-direction bulk promoting   fixed — fires on 2 of 698 bands, so rare, not decoration

**Why the aggregate metric is a poorer measure than it looked, and I chose it before knowing
that.** The share's denominator is EVERY imbalance, and the BPR population grows
super-linearly with window length because BPRs come from PAIRS — 26 BPRs from 50 simple
imbalances at 150 bars, 698 from 356 at 999. So the share moves with window length even when
the promotion RULE does not. The per-band comparison has no such confound, and it is the
metric that matches the operational question.

**`SUPER_BPR_LOOKBACK_BARS = 60` IS OURS AND UNRATIFIED.** The statement says "≥3 overlapping
gaps" and never says within what window. Causality and the direction requirement are ruled;
this is not. The sensitivity across 20/40/60/80/120/240 is in T-0020's work report so a
reader sees the curve rather than the point that suited us — and note that a SMALLER bound
gives a FLATTER curve (20 bars gives a 1.2-point spread), which is precisely why it was not
chosen that way.

**And the already-collected shadow corpus is classified the OLD way.** Every SUPER_BPR in it
counted future and unbounded-history components. Any conformance number over the pre-2026-08-15
window is measuring a different classifier and must be excluded rather than compared.
Related: **B73**, **B60**.

### B70 — a mutation going red is not evidence it went red FOR THE REASON CLAIMED

**Found in:** T-0011, 2026-08-15, by Execute against its own mutation. Review reports the mirror
of it against T-0017's criterion 4 the same evening, which makes two in one day.

**What it is.** Standing rule 2 is *"a guard is not proven until you have made it fail"*. It says
nothing about **which** guard fails, and that gap is where a proof evaporates.

T-0011's criterion 2 needed proof that the census filters on BAR time rather than WRITE time. The
mutation I ran first removed the window filter entirely. Output:

    FAILED test_the_dst_fall_back_inverts_a_string_sort
    1 failed, 18 passed

**Red, restored, and worthless.** `test_the_filter_is_on_bar_time_not_write_time` — the test that
exists for exactly this — **passed**, because every row in its fixture is inside the window, so
removing the window changes no count. I had proven the DST guard a second time and the bar-time
guard not at all. Re-run as an actual `created_at` filter, the right test fails.

**Why it is easy to miss and hard to catch afterwards.** The exit code is 1 either way. The
summary line says `1 failed`. Nothing in the transcript distinguishes "the guard I was proving
went red" from "a neighbour went red", and a work report that says *"mutation A goes red"* is
literally true and carries no information. **The check is free and it is the only one: read the
NAME of the test that failed and confirm it is the one the mutation was aimed at.**

**Generalises past mutations.** Any assertion that a change is detected has this shape — a CI
step that fails for a syntax error, a smoke test that fails on a missing fixture. The observation
that something broke is not the observation that the thing you were testing broke.

**Fix:** when a work report claims a mutation, it names the mutation AND the test that went red,
and the reviewer checks they correspond. Applied in T-0011's report. Related: **B39** (assert the
occurrence count before a scripted edit — the same failure one step earlier: an edit matching
nothing, so the mutation never happened at all).

### B71 — "it validated" and "it is correct" are different claims, and the validator only answers one

**Found in:** T-0011, 2026-08-15. Execute built the design; Review had made the mirror error from
the other side an hour earlier, and named the pair.

**What it is.** The first implementation of `unemitted_bars` put a vocabulary term in
`omission_class` and a sentinel `GATE-000` in `rule_id`. **It validated against the pinned schema
and its tests were green** — `unemitted_bars.items` has no `additionalProperties: false`, so an
extra property is admitted, and `GATE-000` matches the `rule_id` pattern because the pattern
checks SHAPE and the registry check happens somewhere else entirely.

**Both facts are true and neither makes the design right.** A pattern-valid id that is not in the
registry is a fabricated authority; an extra property is a schema widened by the implementer to
unblock their own task. The Manager's ruling withdrew both. **The green suite was not evidence —
it was the absence of one particular kind of evidence being mistaken for the presence of another.**

**And the mirror, which is the half that makes it a pair.** Review specified the `DECLINED`/
`ERRORED` vocabulary from the schema's PROSE without opening the field's validator, and the
Manager passed it on as an instruction. **Two reviewers reasoned about a field with a validator
attached and neither read the validator; the implementer found it because the code had to run.**
Review's own phrasing: *"Execute found it in the artefact with the validator; I found it in the
prose."*

**Why it matters here specifically.** This project's telemetry is validated at the store, which is
a genuinely good design (B41's chain depends on it) and which makes "it stored" feel like a
verdict on correctness. It is a verdict on shape. Every semantic property — is this the right
rule, does this omission exist, is this authority real — is outside what any JSON Schema can say.

**Fix:** no fix, it is a discipline. When a schema accepts something surprising, that is a
question rather than a permission. Related: **B65** (the schema clause that made this reachable),
**B70**.

### B69 — four sites still name `every-closed-bar-roster-v1`, including `scan_census`'s own docstring

**Found in:** T-0011, 2026-08-15. Flagged to me by the Manager mid-build as out of scope, and
recorded here rather than fixed for that reason.

**What it is.** The engine has declared `every-closed-bar-with-sufficient-history-v2` since
T-0010. Four places still say `v1`:

    records.py:310                        scan_census's docstring, describing what the
                                          policy permits — the most misleading of the four
    tests/unit/test_telemetry_contract.py:34, :224      fixture + docstring
    tests/integration/test_telemetry_store.py:33        fixture

`crypto_loop.py:983` also names v1 and is CORRECT — it is a historical comment about what
T-0010 fixed, and rewriting it would erase the record.

**Why it matters.** `records.py:310` is the docstring of the record this task exists to emit,
and it states a policy the engine no longer declares plus a rule the schema cannot enforce
(*"every unemitted bar must name the registry rule id"* — see **B65**). A reader reaching for
the authoritative description of `unemitted_bars` lands on it. The two test fixtures declare a
policy no engine emits, so they validate a shape nothing produces.

**Why it is not fixed here.** The Manager scoped it out and I did not overrule that. My own
argument for including it — that it is the docstring of the function whose semantics I changed
— is real, and it is recorded here so the next reader can weigh it rather than rediscover it.

**Fix:** one pass over the four sites. `v1` should survive only where it is describing history.

### B64 — `scan_context.bar_close_time_ny` carries the bar's OPEN time, and its NAME is the evidence it does not

**Found in:** T-0011, 2026-08-15, while deciding which column the census may filter on.

**What it is.** `shadow.py` sets `scan_context.bar_close_time_ny = iso_ny(now)` where `now`
is `bars[-1].time` — the last CLOSED bar's OPEN time. The same value goes into the record's
top-level `timestamp_ny`. Measured on production rows rather than reasoned from the source:

    timestamp_ny  2026-08-13T20:35:00-04:00     = 00:35Z
    created_at    2026-08-14 00:40:18Z

**A 5m bar stamped 20:35 is written at 00:40:18Z.** If 20:35 were the CLOSE, the row would
land at 00:35 plus a few seconds. It lands five minutes later, which is one full bar period —
so the stamp is the OPEN and the bar closed at 00:40Z.

**Why it matters.** Anything joining on that field believes it has close times. At 5m every
join is one bar out; at 1H, an hour. It is the shape that does not raise: both values are
valid `iso_ny` strings, both sort, and the wrong one is the one the field is named after.

**Not fixed, deliberately.** Correcting the value would give one field two meanings either
side of a deploy, and every stored record would need a date to interpret it. `census.py`
derives close from `timestamp_ny` plus the timeframe period on BOTH sides of its comparison
instead, so the convention cancels and the census is right whichever way this is settled.

**Fix:** decide it once for the whole store — either rename the field or correct the value
and record the changeover — and do not do it in a task that also computes with it.

### B65 — the schema REQUIRES `rule_id` on an unemitted bar while its prose describes an entry with none

**Found in:** T-0011, 2026-08-15, by Execute while implementing the criterion that instructed
it. Confirmed by Review against the schema it had itself specified, and verified independently
by the Manager, who ruled on it the same hour.

**What it is.** Two clauses of `TELEMETRY_SCHEMA.json` cannot both be honoured:

    unemitted_bars.items  required  ["bar_close_time_ny", "rule_id", "reason"]
    rule_id               pattern   ^(GATE|GRADE|TARGET|ENTRY|EXIT|SIZE|PRIM)-[0-9]{3}$

    the same array's description:
      "An entry with NO rule_id, or with a rule_id absent from the registry,
       is undocumented logic (C-13, MAJOR)."

**An entry with no `rule_id` cannot validate, so `store.py` raises before it is written, so
the case the prose asks C-13 to catch can never reach C-13.** The outer defence makes the
inner one unreachable — this register's recurring shape, arriving inside the contract.

**Why it matters, and it is not academic.** The contract authorises a skipped bar two ways:
by POLICY (`emission_policy_id`, declared once, no per-bar record) or by RULE (a per-bar
entry naming a `GATE-nnn`). **An omission caused by FAILURE — a dead database, a missing
panel, a thin layout — is authorised by neither and has no representation anywhere.** That is
the whole gap, and it is narrower than "the contract assumes every omission is rule-authorised".

**What T-0011 did about it.** Nothing to the schema — an implementer widening a contract to
unblock their own task is how a contract stops being one. `unemitted_bars` stays empty for the
failure class, the counts go in `notes`, and the arithmetic is allowed to come out unbalanced
with the shortfall declared to the bar. C-13 reports a DECLARED shortfall as the contract gap
and a SILENT one as a census that does not add up, which are different failures.

**Fix:** Salim's ruling. Filed as the fourth contract-gap item. Until then every infrastructure
failure shows up as a MAJOR that cannot be cleared by fixing the engine, only by the contract
gaining a way to say "we could not evaluate this".

### B66 — the census's evaluation count scans an instrument's whole history, with no time bound in SQL

**Found in:** T-0011, 2026-08-15, written by the author of the query.

**What it is.** `census.emitted_closes` filters in SQL on `record_type`, `instrument` and
`signal_tf` only, then parses `timestamp_ny` and applies the time window in Python. The window
is deliberately NOT in the SQL: the only bar-time column is a New-York-local STRING, and every
way of comparing it in SQL is either lexicographic (wrong across the autumn fall-back, and
silent) or a cast that assumes an offset (wrong for half the year). Correctness first.

**Why it matters.** The row count grows without bound: ~288/day/instrument at 5m, so ~576/day
for the two configured pairs, ~210k rows after a year. Every census emission reads all of an
instrument's rows and discards the ones outside one day. At today's 156 telemetry records this
is free. It will not stay free, and the failure mode is a census emission that gets slower
every day without ever getting wrong — so nothing will flag it.

**Fix:** the durable answer is a real bar-time column (`timestamptz`, UTC) written beside
`timestamp_ny`, which makes the window an indexed SQL predicate and retires this entry and half
of **B64** at once. A generous `created_at` band as a pre-filter would work sooner but has to be
proved wider than the largest possible write lag, and a backfill breaks that proof.

### B68 — the declared emission policy says "sufficient history" and its own comment claims the exception path too

**Found in:** T-0011, 2026-08-15, while classifying the omission population the census reports.

**What it is.** `shadow.py` declares `emission_policy_id="every-closed-bar-with-sufficient-history-v2"`,
and the comment above it lists TWO conditions the name is meant to cover:

> *"the price fetch returned fewer than 60 bars, or fewer than 10 reach the primitives — no
> series to evaluate; **the evaluation raised and was swallowed**, which is by design and which
> nothing reports (B32). Both are DATA-availability."*

**The second is not a history condition.** A raised exception arrives from a missing panel, a
schema violation or an unreachable database. Calling that "insufficient history" is v1's false
coverage claim — the one B34 was filed for and T-0010 fixed — narrowed rather than fixed.

**Why it matters.** It is the difference between an omission the contract authorises and one
nothing authorises, and it is the exact loophole the Manager forbade in T-0011's plan:
`emission_policy_id` is `{"type": "string"}` with no enum and no registry, so a policy can be
renamed to cover anything. *A policy declares what the engine CHOOSES not to evaluate; a
failure is what it COULD NOT evaluate, and the second is not the engine's to declare.*

**Not fixed.** The policy string is untouched — renaming it either way is the loophole. The
census classifies the two paths correctly regardless (`OMISSION_POLICY` for insufficient
history, `OMISSION_FAILURE` for the swallowed exception), so the counts are right while the
declaration is still over-broad.

**Fix:** narrow the comment to the condition the name actually states, and treat the swallowed
exception as what **B65** says it is — a class the contract cannot yet express.

### B67 — no endpoint exposes a live position's SL/TP, so "every open position has a stop" is unobservable

**Filed 2026-08-15 while checking Review's observation that production has held two positions for
twenty-five hours with ZERO closes.** The exit path turns out to be sound. **The finding is that I
could not establish that from production, only from the source.**

## What the engine actually does, traced end to end

    _tick_symbol()          every tick, per pair, live ticker price
      -> paper.on_tick()    sets the mark, then per position:
                              LONG   price <= sl -> SL      price >= tp -> TP
                              SHORT  price >= sl -> SL      price <= tp -> TP
      -> _settle()          realises pnl, fires _on_settle_cb for ALL close paths

**And SL is always present on the live entry path.** `crypto_loop.py:441` is `sl = float(sig.sl)` —
unconditional, so a signal without one raises rather than opening a stopless position. **`tp` is
conditional (`if sig.tp is not None`) and `on_tick` guards both**, so a TP-less position is possible
by design and an SL-less one is not. `ExecutionService` passes them through at `service.py:147`
(`sl=sig.sl, tp=sig.tp`).

**So zero closes in twenty-five hours is consistent with a working engine.** `RISK_PCT = 0.01` on a
$5,000 account is ~$50 at risk per trade; `unrealized_pl` is **-11.44** across two positions, roughly
a tenth of the combined risk. **Price is well inside both stops. There is no defect here.**

## The defect is that I proved it from the CODE and cannot prove it from the SYSTEM

**Two states produce an identical `/api/engine/status` payload:**

    holding two positions correctly, price inside both stops
    holding two positions that CAN NEVER CLOSE

**Nothing in the response separates them.** `open_positions` is a count. `unrealized_pl` is a sum.
**No endpoint exposes a position's `sl` or `tp`** — `/api/positions` returns `[]` from a different
source, `/api/engine/sim` is account-level, and `get_positions()` carries the fields internally but
publishes none of them.

**I resolved the ambiguity by LEAVING the output and reading the source.** That works for a reader who
has the repo, at a moment when the code is trustworthy — and **it is not available to an operator, to
a monitor, or to anyone asking "is the engine currently safe" rather than "was it written correctly".**
The property that matters — *every open position has a stop* — is a **runtime** property, and it is
checked nowhere at runtime.

> **This is the same shape as `B53` and the deploy-preflight gap, one level in: a correct signal that
> exists inside the process and is not published.** `deploy_preflight.py` already has to INFER held
> pairs from an activity deque because the pair list is not exposed. **This is the same omission on the
> same object, and the inference trick does not work for `sl` — no activity line carries it.**

## Why it is worth an entry rather than a shrug

**Every safety argument this project has made about the live engine is a source-reading argument.**
`ALLOW_LIVE_TRADING` defaults false, the CFT connection is double-gated, SL is unconditional at
`:441`. **All true, all verified by reading, and none of them observable from outside the process.**
**A deploy that broke any one of them would present an identical status payload to one that did not.**

**The cheap remedy is not a monitor, it is a field:** publish `sl` and `tp` per position in
`/api/engine/status`, and the check becomes *"is any open position missing a stop"* — one comparison
over data already in memory. **Deferred by id rather than predicate:** not ticketed yet, because it is
a product change to a live endpoint and the queue is mid-T-0011. **Do not fold it into a rules task.**

### B63 — the B25 handshake is a CROSS-SEAT protocol, and the same hazard exists INSIDE one seat

**Filed 2026-08-15 from Review's own contaminated baseline, self-caught and self-discarded before it
was reported as a number.**

Review started a suite run and a prober run against the same pinned worktree to save wall-clock:

    prober   exit 0   9 ok   TIER 0.2 PASSED   porcelain 0 before / 0 after
    suite    DISCARDED — ran concurrently with the prober IN THE SAME WORKTREE

**The prober `sed`-mutates guarded files eight times and restores between probes**, so the suite was
collecting and executing while the tree beneath it was mutated and reverted. **The figure is
untrustworthy in BOTH directions — a failure could be a mutation window, a pass could be luck about
which files were being read when.**

**The prober's own numbers survive, and the pair that establishes that is worth naming:**
`git status --porcelain` **0 before and 0 after**, which is what separates a real pass from a
`restore()` that silently no-opped. **Contamination ran one way.** The prober writes; the suite only
reads.

### THE CONTAMINATED RUN RETURNED THE SAME NUMBER, AND THAT IS THE ARGUMENT FOR DISCARDING IT

    contaminated   1024 passed   133.32s
    clean          1024 passed   127.41s

**The contaminated measurement was CORRECT.** Recorded because the instinct on reading B63 is *"so the
number was wrong"*, and it was not — **and if contamination reliably produced wrong numbers it would
be self-announcing and no rule would be needed.**

**What it means is that a contaminated run and a clean one are INDISTINGUISHABLE FROM THEIR OUTPUT.**
Same count, same exit code, nothing in the figure recording that the tree moved beneath it. **Only the
elapsed time differed — 133.32s against 127.41s — and no threshold on a suite's duration is a
contamination detector.**

> **So this is tonight's lens landing on a measurement instrument rather than a reporting one: the
> output collapses two states.** *"1024 against a stable tree"* and *"1024 against a tree mutated
> eight times"* print identically. **The discipline therefore cannot be "check whether it looks
> contaminated" — THERE IS NOTHING TO LOOK AT.** It has to be structural: do not run a reader
> concurrently with a writer, **because you will not be able to tell afterwards.**

### Which makes the DISPOSITION load-bearing rather than the diagnosis

**Review's own statement of it, and it is the part to carry:**

> *"I did not discard that figure because it was wrong. **I discarded it because I could not establish
> it was right** — and it was right."*

**A rule that only bites when you were ALSO UNLUCKY is a rule people stop following.** This instance
cost nothing: the number was correct, the re-run wasted about two minutes, and every incentive pointed
at keeping the first figure and annotating it. **The rule held anyway, and recording that it cost
nothing is what stops the next reader treating the discard as an overreaction.**

**The generalisation past the prober: any tool that mutates a shared tree owes an announcement, and no
reader can be asked to detect one.** That is why the fix is announcing writes rather than detecting
them — not because detection is expensive, but **because detection is impossible from the output.**

### The structural gap, which is the reason this is filed rather than noted

**`B25` exists precisely because the prober mutates a shared tree. It is a protocol between SEATS** —
post `STARTING`, ring the doorbell, other seats hold off, post `DONE`. **Nothing in it addresses two
measurements inside ONE seat**, and the hazard is identical: the prober does not care whether the
reader it disturbs belongs to another session or to the same one.

> **So the discipline was built for cross-seat coordination and applied to other seats and not to the
> author's own concurrent work.** Review's words: *"I knew that about the prober — it is why the B25
> handshake exists — and applied it to other seats and not to myself."*

**The generalisation is narrower and more useful than "do not parallelise":**

> **Two measurements can share a worktree only if NEITHER WRITES.**

**Read/read is safe and worth keeping — the wall-clock saving is real.** Read/write is not, in either
order, and **the writer does not have to be a test to count: the prober, `verify_guards.sh`, and any
`git checkout` are all writers.**

### And it is the second instance of this shape in one evening, from opposite directions

    Execute #2   "the prober ran green twice, the second because the Manager committed tracked
                 files while my first was in flight; I CANNOT PROVE NON-DISTURBANCE from inside
                 my own session."
    Review       CAN prove disturbance, because it caused it.

**Together they bound the problem: from inside a session you cannot establish that you were not
disturbed, but you can establish that you disturbed something.** So the asymmetry to act on is that
**the writer is the party that knows** — which is what B25 already assumes for other seats, and is
the reason the fix is to announce writes rather than to detect them.

**Correct handling, recorded because discarding a number you have already computed is the part people
skip:** Review reported the contamination, discarded the suite figure, kept the prober figure with the
evidence for why it survives, re-ran the suite against a quiet tree, and **said the baseline was not
usable in the interval** — rather than reporting a figure it did not trust and annotating it.

### B62 — `ci_range.py` withheld verdicts it already had, because `cancelled` blocked the transfer

**Status: FIXED, 2026-08-14. And the route to it is the point: Review reasoned about the WORLD from
this tool's OUTPUT, and the output was wrong about the world.**

Review observed that 3 of the last 16 commits have `cancelled` runs — correct, and it identified the
cause correctly too: **`cancel-in-progress: true` means a push within ~2 minutes of the last kills
its predecessor's run, so THE CANCELLATION RATE IS A FUNCTION OF PUSH CADENCE**, and this loop's
cadence is high precisely because it documents as it goes. Then it drew the consequence:

> *"`.md` is in `TREE_IGNORE`, so a cancelled run on a register commit costs nothing — the code tree
> is identical to a neighbour and the verdict transfers. **A cancelled run on a code-carrying commit
> is a hole tree identity cannot fill.**"*

**BOTH HALVES WERE FALSE, AND THE TOOL IS WHY.**

    v5 logic:  if concl in ("none", "None"):   <- tree-identity search ran ONLY here
               elif concl == "cancelled":      <- printed "asserts nothing" and STOPPED

**So a register-only commit with a cancelled run did NOT transfer** — `efc61dc` and `5635e5a` are
`.md`-only, code-identical to green commits two positions away, and were reported as though nothing
was known about them. **And the code-carrying one was not a hole either:** `8d3fc8f` carried seven
rule files and 1292 insertions, and its code tree is **byte-identical to `dbd7b5f`** (verified: empty
diff excluding `*.md`), which is green. **All three cancellations were coverable; the tool declined
to look.**

**Review had the refuting fact in its own next sentence** — *"that code landed again via
`881df28`/`dbd7b5f`, which is green"* — and still concluded "hole". **A generalisation stated one
clause after the counterexample that kills it.**

### Why the tool got it wrong, and it is this register's own defect worn inside out

**The usual failure here is an output that does not discriminate between working and broken. This is
the mirror: an output that DISCRIMINATES WHERE THERE IS NO DIFFERENCE.**

**By the tool's own printed doctrine — `CANCELLED: asserts nothing (B30)` — a cancelled run and an
absent run are in the SAME epistemic position.** v5 nonetheless routed them down different branches
and gave only one of them the search. **The tool stated the equivalence and then failed to act on
it**, which is the same shape as `SUPER_BPR`'s docstring requiring opposite direction while the code
did not check it: **the correct rule written down beside code that does not implement it.**

**Fixed:** `cancelled` now falls through to the identical-tree search, and the provenance is labelled
so the reader is never told a verdict is the commit's own — `own run CANCELLED; tree identical to
d58265c5`. Where no twin exists, a cancelled code-carrying commit is still reported as
**UNVERIFIED**, and now says explicitly that this is the case tree identity cannot fill — **which is
the residual truth in Review's claim, and it is much rarer than the claim implied.**

    before   3 cancelled, 0 covered, 2 of them silently unverified
    after    3 cancelled, 3 covered, 0 UNKNOWN, exit 0

### Follow-up, same evening: a transfer now states its AGE, and Review's caveat is why

**Not a defect — a missing units label on a claim that already varied in strength.** The
identical-tree search spans the whole pool (~192–200 commits), so **a transfer has no time bound.
Tree identity says the CODE is the same. It does not say the CI ENVIRONMENT was:** CI resolves
`pip install` from `requirements-prod.txt` at run time and the repo cannot pin what a registry
served. **So a green inherited from one minute earlier and one inherited from two days earlier are
different strengths of claim, and they printed identically.**

    5635e5a   tree identical to d58265c5 (run 79s later)
    efc61dc   tree identical to a144aa98 (run 11m earlier)
    8d3fc8f   tree identical to dbd7b5f5 (run 4m later)
    2cdf55f   tree identical to a386de8f (run 33m earlier)

**Nothing in the audited range is affected — every transfer is minutes apart, and both seats checked
independently.** But the mechanism permits a 200-commit-old transfer, so the age is now printed.

**It is the same argument as B62's provenance label, one axis over:** that one made inheritance
visible so no transferred verdict reads as the commit's own; **this makes staleness visible so no old
transfer reads as a fresh one.** In both cases the fix is not to withhold the verdict — it is to stop
the row from overstating it.

### And the age label itself shipped without its reference point — caught by checking the arithmetic

**Review could not reconcile 2 of 3 rows and reported "I cannot tell" rather than "this is wrong",
which is the correct verdict and the rarer one:**

    tool said  79s      run-to-run from created_at gives  75s
    tool said   4m      run-to-run from created_at gives  3m19s
    tool said  11m      run-to-run agrees

**Its hypothesis was `updated_at` and that was wrong — it is `created_at` throughout.** The real gap
is that **the two ends are different KINDS of event**: one is when the *inheriting commit was
committed*, the other is when the *twin's run started*. The residual is the commit-to-queue lag,
which is why it shows up only where a full run sits in the pair — **exactly the pattern Review
observed, correctly, from a wrong cause.**

**AND THE MIXED REFERENCE IS RIGHT RATHER THAN SLOPPY, for a reason that only appears once you ask
what the alternative would be: most commits taking a transfer HAVE NO RUN AT ALL.** That is the
entire reason a transfer exists. **A run-to-run age would be undefined in the majority case and
defined only for the cancelled ones** — an age that exists for some rows and not others, which is
worse than a mixed reference that is always available.

**So the number stays and the label now names both endpoints:** `vouching run started 79s after this
commit`.

> **This is T-0015's criterion 2a in miniature, and it arrived three hours after that criterion was
> written.** Either reference is defensible; leaving it unstated is not. Review's phrasing is the one
> to keep: **"a number without its reference point cannot be checked, only disputed"** — and a reader
> who checks with the obvious timestamp gets 75, concludes the tool is broken, and is wrong about
> that too.

**Third instance tonight of a fix introducing the defect it was fixing:** the phantom-path guard that
substring-matched schema prose, `--no-write` making the write path the untested one, and now an
age label added for honesty that could not itself be checked.

### Independently audited, and the auditor signed the claim it had been wrong about

**Review re-derived all five tree-identity claims in `7dfc3de..b543dcc` with its own diffs rather
than reading the tool's output** — `git diff --quiet A B -- . ':(exclude)docs/' ':(exclude)*.md'` —
**and signed all five, including `8d3fc8f` vs `dbd7b5f`, the one it had called a hole.** It also
checked two structural properties the entry above asserts but did not prove:

* **`.github/workflows/` is NOT in `TREE_IGNORE`**, so a workflow change breaks tree identity and the
  tool refuses to inherit rather than transferring a green across a different job set. **Load-bearing:
  it is what stops the T-0016 case being silently inherited.**
* **The transfer is a TREE claim, not a HISTORY claim** — which is why `8d3fc8f` inheriting from its
  own descendant is sound. **Direction does not matter once the trees are identical**, and v2's
  ancestry-based version was the defect.

### The transferable part

**A verdict this project ALREADY OWNED was withheld for hours by a tool built to surface verdicts**,
and nobody noticed because *"cancelled"* reads like an answer. **B53's shape — a correct signal,
produced continuously, with no consumer — arriving one layer up: the signal had a consumer, and the
consumer dropped it on a branch.**

**And the cadence coupling is worth keeping even though its consequence was wrong:** cancellation
concentrates exactly when two seats push in the same minute, **which is also when the race that
produces code-carrying register commits happens. The same event causes both** — so the commits most
likely to lose their run are the ones most likely to be carrying somebody else's code.

### B61 — DEFER BY TASK ID fixed ATTRIBUTION and never fixed NOTIFICATION

**Status: TOOL BUILT, `agents/landed_sweep.py`. Nothing owed today; the whole exposure is
prospective and it is 8 references deep.**

`deferral_sweep.py` exists because of B35 and B42, and its central argument is this:

> **A PREDICATE DEFERRAL IS WEAK BECAUSE MATCHING PRODUCES NO NOTIFICATION.** B35's predicate was
> CORRECT — the right task arrived, in the right file, twice — and it still slid off, because
> nothing tells a task that it has satisfied someone else's condition.

**That argument never depended on the deferral being a predicate.** Nothing tells the eight
sentences that name `T-0020` that `T-0020` has landed either. **So the rule this loop adopted —
DEFER BY TASK ID, NEVER BY PREDICATE — made the owner NAMEABLE and left the silence exactly where
it was.** The rule was right. It solved half the problem and was recorded as solving the problem.

**Measured, and the whole exposure sits on one task:**

    T-0020    DISCHARGED 2026-08-15 — all 12 references updated, and the assertion
                                        they were waiting for is written (see B60 item 3)
    T-0015    1 reference
    T-0017    1 reference

**All eight of T-0020's say some form of *"until T-0020 lands, no rule may assert the precedence
ordering."* The hour it lands, all eight are false.** Now criteria 9, 9a and 9b of that task, with
the references enumerated in the plan so the implementer does not have to find them.

### And the tool inverted its own premise on first run, which is the more useful half

**Version 1 asked the retrospective question — "does anything defer to a task that already
shipped?" — and flagged 9. I read all nine. ZERO were owed work.** One was a genuine deferral that
had been honoured; the other eight were narration:

    "T-0014 FORBIDS hardening the durations"      standing constraint, still true
    "Status: FIXED, 2026-08-14 (T-0021)"          closure record
    "which T-0003 EXISTED TO FIX"                 historical narration
    "this is T-0007's defect EXACTLY"             teaching reference
    "T-0012. This task must not change its verdict"   scope constraint

**And the reason is structural rather than a bad word list: once a task lands, this project writes
about it in the past tense and as a standing constraint, and those are the DOMINANT way a landed id
appears.** *"X forbids Y"* and *"X owes Y"* are both present-tense claims about a finished task, and
no vocabulary separates them reliably. A widened list went 0-for-2 instead of 0-for-9 and was no
more correct.

> **So the retrospective question is the wrong question, and the prospective one is right.** The
> product is not cleanup after a landed task — it is *"tell whoever closes T-0020 that eight
> sentences go false the moment they do."* **That bucket is precise (8 of 10 genuine) and it arrives
> before the sentences go stale rather than after.**

**AND THE PRECISE RETROSPECTIVE ANSWER NEEDS NO WORD LIST AT ALL — IT NEEDS A SNAPSHOT.** A
reference recorded *while its task was open* is a known deferral. Persist it; when the task closes,
any recorded reference still present is owed, with no vocabulary in the decision.
**`deferral_sweep.py` could not make this move because it had no moment at which its predicate was
known-good. A task id gives us one** — which is the second thing defer-by-task-id bought, and
nobody had spent it.

**Mutation-proved rather than asserted:** stubbing `T-0020` to DONE turns exit 0 into exit 1 with
all eight listed, both through the word list and through the snapshot.

### Three defects found in this tool, in the seat that keeps filing them

* **Version 1 counted every `T-NNNN` in source — 64 references, 11 tasks — and labelled them all
  "DEFERS TO A LANDED TASK."** Almost all were attribution (*"added by T-0016"*), which goes stale
  never. **A count that cannot tell "this work is owed" from "this work was done" is an output that
  does not discriminate between working and broken**, produced in the tool built to catch a cousin
  of it.
* **`states[t]` KeyErrors on any task id present in text but absent from the bus.** Invisible in
  production because every id happens to exist; found only because the mutation stub supplied a
  short state dict. **The mutation test found a bug in the tool, not just in the tool's subject.**
* **The mutation test corrupted production state.** Proving the check fires needs a stubbed task
  state, and that run then rewrote the real snapshot from the stub's view, in which every task but
  one looked open. **A sweep that reads like a report and writes as a side effect turns a test run
  into a state change.** The write is now `--no-write`-able and the test opts out.

**AND THE NOISE BUCKET GROWS AS THE PROJECT DOCUMENTS ITSELF, WHICH SETTLES THE ARGUMENT ABOVE.**
Measured across three runs the same evening: **0-for-9, then 0-for-2 against a widened list, then
0-for-4** — and **two of the last four are the plan text written to DISCHARGE the deferrals**,
`T-0020/plan.md` quoting *"T-0019 was forbidden from…"* in the criterion that exists to pay that
[DISCHARGED 2026-08-15 — T-0020 landed; the prohibition is lifted and the assertion written]
debt. **Writing about a deferral produces deferral-language prose**, so the retrospective bucket
gets noisier every time the loop does the right thing. **A checker whose false-positive rate rises
with good behaviour cannot gate anything** — which is why the exit code follows the snapshot and the
word list only advises.

### CORRECTED BY REVIEW: MY REASON WAS WRONG EVEN THOUGH THE CONCLUSION HELD

**I wrote that no word list can separate *"X forbids Y"* from *"X owes Y"* because both are
present-tense claims about a landed task. Review falsified it: a marker list gets 3 of the 4 live
constraints** — `until … lands`, `must land`, `owns` all fire. **A word list is 75%, not hopeless.**

**What actually defeats it is the fourth case, and it is not a vocabulary problem.**
`entry_001:27` [DISCHARGED 2026-08-15] — *"That is T-0020's defect, not this rule's — and it is why the tests here hand this
rule an EXPLICIT candidate list"* — **carries its obligation in a DESIGN CHOICE described by the
sentence, not in a verb.** The tests use an explicit candidate list and could stop once T-0020 lands.
**No word list reaches that, because the sentence never says anything is owed.**

**And the two error directions compose into an argument neither of us had alone:**

    FALSE NEGATIVE   on the subtlest case — obligation as design choice, no modal
    FALSE POSITIVE   COUPLED TO PROGRESS — 2 of the last 4 are the plan text written to
                     DISCHARGE these deferrals, quoting "T-0019 was forbidden from…" inside
                     the criterion that exists to pay that debt

> **So the signal degrades fastest exactly when the process is going best**, and *"a threshold you
> can only meet by writing less about your own work is not a threshold. A measure that penalises
> diligence will be switched off."*

**That is the real case for the snapshot and it is stronger than mine: the snapshot does not parse
intent. It only needs the sentence to have EXISTED while the task was open — a fact immune to how
much anyone writes about it.** The tool now **prints its own record (0 true positives in 15
flagged)**, because what stops the next reader widening the list to catch `entry_001:27` is knowing
it has never had a true positive and that widening raises noise on the same curve.

**AND THE COUNT DRIFTED INSIDE THE PLAN THAT DEPENDS ON IT.** T-0020's criterion 9 first said *"the
eight deferrals"*. Amending the plan and writing this entry pushed it to **eleven** — the prose
describing the debt is itself deferral-language text naming the task. **Criterion 9 now refuses to
pin a number and sends the implementer to the tool**, because a hardcoded count is *correct when
written* and wrong when read.

### `--no-write` MADE THE WRITE PATH THE ONLY UNTESTED PATH

**Review's third finding, and it was self-inflicted an hour earlier.** `--no-write` was the correct
fix for a mutation test that rewrote production state. **But it means the run being exercised and the
run that ships are different runs, and the difference is the path that produces the artefact every
later run depends on.**

**The dangerous asymmetry was in the load, not the write:** the old code printed *"snapshot
unreadable — treating as absent"*. **That is the safe direction for CORRUPTION and the unsafe one for
TRUNCATION — a snapshot missing half its entries parses fine and silently narrows what can ever be
violated.** An unreadable snapshot degraded loudly; a readable-but-incomplete one degraded silently,
and nothing distinguished them.

**Now: atomic temp-plus-rename; shape-validated on read with `exit 2` rather than treat-as-absent;
and a scan-scope guard**, because truncation is not the only way a baseline shrinks — a partial
checkout writes a perfectly valid, narrower snapshot. **Verified in four directions:** real write
stamps `_meta`; a malformed snapshot exits 2 and is left untouched on disk; a planted
`files_scanned: 900` against a 313-file run refuses; a 330 → 313 shrink still writes.

### AND IT IS A CATEGORY, NOT FOUR INSTANCES

**Four `agents/` tools are now load-bearing for dispatch decisions, and all four have no test, no CI
row, and one reader:** `stale_sweep.py`, `deferral_sweep.py`, `ci_range.py`, `landed_sweep.py`.
**All sit outside the repo**, so CI cannot see them even in principle. **Every one of them is the
unaudited copy in the same-claim-two-homes rule** — the tools that decide what work is owed are
themselves the artefacts nothing checks. Named here rather than ticketed because the remedy is a
decision about where these files live, which is not a task-sized question.

**Standing limit, inherited and stated because a sweep that hides its blind spots is what this
register is about: the trigger is a word list and it MISSED one live deferral** —
`entry_001_imbalance_poi.py:27` [DISCHARGED 2026-08-15], *"That is T-0020's defect, not this rule's"* — until that phrasing
was added by hand. **5 references, 4 matched.** "Nothing owed" means "nothing matched as owed".

### B60. PRIM-002's type distribution, the GAP zero, and the 0.2% amplifier window — three measurements T-0019 owes the register
**Found in:** T-0019, 2026-08-14. **Measurements, not defects** — filed because the plan
required them and because two of the three are the evidence behind decisions taken elsewhere.

**1. THE TYPE DISTRIBUTION, over 999 live 5m `BTCUSDT.P` bars:**

    FVG 268 · VOLUME_IMBALANCE 92 · BPR 59 · SUPER_BPR 651 · GAP 0     (1070 total)

**PRIM-002's docstring claimed the engine "detects FVGs only" and that three of four types
were invisible to it. That was false from the moment the module landed** — B42's class, a
comment denying what the file beside it does, and it is the first thing ENTRY-001's
implementer reads. **Corrected in the same commit**, with the measurement in place of the
claim.

**2. `GAP` IS 0 IN THE CORPUS AND IS NOT UNREACHABLE.** A hand-built fixture with bodies apart
AND wicks apart produces one, with the band cut between the wicks
(`test_t0019_entry_decision.py`). **So zero is a market fact about a 24/7 perpetual, which has
no session gaps — not a dead branch.** Worth stating as method rather than as a result: **a
corpus count can only ever say "not seen yet"**, and no amount of additional data converts
that into "cannot happen". The construction settles it in one fixture.

**3. `SUPER_BPR` AT 61% WAS NOT A PROPERTY OF THE MARKET — DISCHARGED BY T-0020, 2026-08-15.**
651 of 1070 at 999 bars; 23% at 150, because the promotion scan had no time bound and the
callers differ (shadow 320 bars, backtest 250). The scan is now causal, requires both
directions among its components, and is bounded by a DECLARED lookback that is ours.

**The prohibition this item carried is lifted and the assertion it was blocking is written.**
Discharging the sentence without writing the test would have deleted the debt rather than
paid it, so `test_t0019_entry_decision.py::test_the_precedence_ordering_holds_over_detected_bars`
now ranks what PRIM-002 actually detects over a committed corpus, at both live window
lengths. **That test does NOT catch the original defect** — measured, not assumed: removing
the lookback leaves it green, because the strongest type present is the same either way.
`test_t0020_super_bpr_stability.py::test_the_two_live_callers_never_disagree` is what
catches it. Both matter and only one discriminates; see **B74** for what remains.

**4. THE 0.2% AMPLIFIER WINDOW IS OURS AND UNRATIFIED**, and the statement stamps itself:
*"The 0.2% value is an engineering guideline, not a strict market rule."* Carried as a
declared parameter on every GATE-038 record with its source and `ratified=False`. **Its firing
rate is reported with its denominator** (B46): a corridor that catches every level and one
that catches none emit the same shaped record, and only the rate separates them. **No live
firing rate is quoted here, because GATE-038 is not wired to a live amplifier feed** — PRIM-003
and PRIM-006 produce the levels and nothing routes them in yet. Quoting a rate from a fixture
as though it were a corpus measurement is the error this entry exists to avoid.

### B59. The choice of collision arithmetic decides whether GATE-038 admits the doctrine's OWN worked example
**Found in:** T-0019, 2026-08-14, writing the test for the quoted example.
**Status: FIXED in the same commit.**
**CORRECTED 2026-08-14 after the Manager could not reproduce the mechanism — this entry first
claimed an ASYMMETRY and quoted a figure that comes from no form this code uses. See the bottom.**

**The statement gives the boundary outright:** *"If the entry POI is at 100.00, any amplifier
between 99.80 and 100.20 is considered to be colliding."* Both edges, one case.

**Measured, on the form this rule actually uses (`half = abs(entry) * pct / 100`):**

    half                    0.2                    exactly representable
    abs(99.80  - 100.00)    0.20000000000000284    > half  -> EXCLUDED
    abs(100.20 - 100.00)    0.20000000000000284    > half  -> EXCLUDED

**Both edges are excluded, SYMMETRICALLY. A bare `<=` rejects BOTH prices the doctrine names as
colliding** — the rule refuses its own only concrete example.

**AND THE DEFECT IS FORM-DEPENDENCE, NOT FLOAT NOISE.** Three implementations that look equally
reasonable in a diff disagree about the documented example:

    abs(p - e) <= e * pct / 100         EXCLUDES both edges
    abs(p - e) / e <= pct / 100         EXCLUDES both edges
    precompute the band 99.80..100.20   INCLUDES both edges

**Two of the three natural forms fail the doctrine's own example, and nobody would flag either in
review.** That is worse than a bias: it makes the trader's single written boundary a pass or a fail
depending on an arithmetic choice made incidentally — the same shape as `k=3.0` versus `k=3.5`
looking reasonable either way, on a number the trader actually wrote down.

**Fixed** with `isclose` at the boundary only: both edges in, 99.79 and 100.21 out, interior
untouched. **The chosen form and the fact that the other two exclude the example are stated in the
function's docstring**, so the choice is visible rather than incidental, and
`test_the_statements_own_worked_example_is_the_boundary_check` asserts both directions.

**HOW IT WAS CAUGHT, and this part is unchanged:** the criterion said to test the statement's OWN
worked example rather than a convenient number. **A test written with 99.5 and 100.5 passes and
proves nothing about the boundary.** Quoting doctrine literally into a fixture is what surfaced it.

**THE CORRECTION, recorded rather than silently applied.** The first version said the comparison
*"admits the upper edge and rejects the lower one"* and quoted
`abs(100.20 - 100.00) = 0.19999999999999574`. **That figure was not measured — it was derived from
an expectation of asymmetry, and no arithmetic in this file produces it.** The Manager tried every
form it could construct, found all of them symmetric, and reported that rather than editing the
entry. **A register entry with a fabricated mechanism is what this register spent the night
removing**, and this one was filed by the seat that had just filed two entries about unverified
claims. **The catch was real; the explanation was invented.** Related: **B46**, **B49**.

### B58. One half of the cross-tool agreement cannot be enforced from inside the repository
**Found in:** T-0021, 2026-08-14, while satisfying its criterion 2.
**Severity:** low today, and structural — it is the reason B54 can recur in the other direction

**T-0021's criterion 2 asks that "something must fail if the two tools diverge again".
`agents/rule_waves.py` is not in this repository** — it sits beside it at
`/mnt/c/Users/malek/TradingAI/agents/`, so no test in `backend/tests/` and no CI job can execute it.

**What IS enforced in CI:** the coverage script's own counting, its alias collapse, its internal
invariants, and **the interface the other tool consumes** — `rule_waves.py` parses
`implemented ids:\s*(.+)` and a test pins that line's shape and space. So this side cannot change
silently.

**What is NOT:** `rule_waves.py` changing its own collapsing. The live comparison exists — it was
run by hand for T-0021 and both tools agree — but **a comparison run by hand is a habit, and B15,
B19, B21 and B47 all say habits do not hold.** The asymmetry is worth naming precisely: the tool
that was WRONG is now guarded, and the tool that was RIGHT is not.

**Fix:** move `rule_waves.py` into the repository, or have it assert against the coverage script's
published `distinct implemented:` line and exit non-zero on disagreement. The second is smaller and
puts the check where the two tools already meet. **Needs a task id.** Related: **B54**, **B47**.

### B56. Eleven emitted telemetry fields state a value and cannot say where it came from
**Found in:** T-0016, 2026-08-14, on the first run of `scripts/check_partial_rules.py` — which
is the point of the script rather than an aside.
**Severity:** moderate — an auditor cannot re-derive these values, and one of them is the field
most likely to be disputed

**The whole population, measured across every rule the check can invoke — not a sample:**

    GATE-041   conditions_total · not_evaluable_count · not_read · unread_count ·
               mandatory_satisfied
    GATE-040   cool_off · duration_enforced · not_evaluable · not_read
    GATE-019   session_gates_unconditional · swing_mode_available

**`RuleEvaluation.value_provenance` exists so an auditor can re-derive a verdict with no engine
access.** These eleven keys are emitted with no entry in it. Their siblings have one:
`satisfied_count` gets `derived("count of conditions with state TRUE")`, `not_evaluable` gets
`derived("no implementation produces this input")`.

**THE ONE THAT MATTERS MOST IS `not_read`.** It names a producer and asserts that nobody called
it — **the field most likely to be argued with by whoever is named in it, and the one field that
cannot say where it came from.** Review found that in T-0012's cycle and correctly declined to
spend a cycle on it there.

**`GATE-041.mandatory_satisfied` was not in T-0016's plan's list of five**, which was measured on
the BLOCKED branch only. It exists solely on the decided branch. The check examines both branches
per rule for this reason. **The general form is filed by the Manager above as *A MEASUREMENT TAKEN
ON ONE BRANCH IS NOT A PROPERTY OF THE RULE*** — kept there rather than restated here, because two
records of one fact drift.

**NOT FAILING THE BUILD, DELIBERATELY.** They are a named baseline in
`check_partial_rules.PROVENANCE_PRE_EXISTING`, printed on every run, and a **new** gap fails
immediately. A check that landed red would have been switched off within a day. **Clearing one
means deleting its baseline line in the same commit — the script fails on a baseline entry that
no longer describes anything**, so the list cannot outlive what it excuses.

**Two keys are NOT in this population and are named exemptions instead:** `GATE-041.outcome` and
`GATE-040.mode`. Both are the verdict itself, and the rest of the payload is its provenance;
requiring the outcome to explain its own origin is circular. `mode` is Execute's extension of the
plan's reasoning to the second instance, marked as such in the code.

**Fix:** add a `derived(...)` / `from_record(...)` entry for each, and delete the matching
baseline line. **Needs a task id.** Related: **B44**, **B49**.

### B57. `check_partial_rules.py` enforces two of the six standing requirements, and a green run must not be read as six
**Found in:** T-0016, 2026-08-14 — recorded because the plan required the limit to be written
down where it will be read, not only printed.
**Severity:** low as a defect, high as a misreading — this is the shape that produced **B41**

**The six standing requirements for a partially-evaluable rule live in
`agents/PROGRAMME_TO_CUTOVER.md`. The script mechanically enforces two:**

    1 / 2a   no quorum is claimed while any condition is unreadable   ENFORCED
    2        the invariant is SHARED, not duplicated inline           ENFORCED
    3        counted as registered-and-blocked, not implemented       NOT — per rule
    4        the verdict distribution is reported                     NOT — per rule
    5        the non-default verdict proven reachable on a fixture    NOT — per rule

**And within requirement 2 it checks that a direction was passed EXPLICITLY, never that it was
the correct one.** No script can: `CONTINUE` for GATE-041 and `FORWARD` for GATE-040 are both
conservative and point opposite ways, so there is no general direction to fail in. **That is read
out of each rule's own statement.**

**Three more limits, all printed by the script on every run so they cannot be separated from the
result the way a plan can:**

* **A clean grep means *"no instance of the KNOWN pattern"*, never *"no duplication"*.** A rule
  phrasing the invariant differently escapes it. The import-binding check is the signal that does
  not depend on phrasing — and it is an IDENTITY test against `base.quorum_blocked`, not
  `hasattr`, because an inline copy written as a module-level function wearing the sanctioned name
  satisfies `hasattr` while being exactly the duplication being hunted. Verified both ways.
* **Only 2 of 34 implementations declare condition readings today** (GATE-040, GATE-041). *"All
  rules pass"* currently means *"the two rules I could call pass"*, **and a check covering two
  rules produces output identical to one covering all of them.** The ratio is printed for that
  reason.
* **The probes drive `evaluate` directly.** Nothing here proves the live engine calls these rules
  at all — no rule has ever decided a live trade (**A10**).

**No rule violated criterion 2 or criterion 3 at the time the check landed.** That is a real
result and also the least informative one available: the two rules it examines were written under
maximum attention, and 55 remain. Related: **B41**, **B49**, **A10**.

### B18. The prober's restore promise was wider than its mutations, and the width was the bug
**Found in:** earlier session. **Status: FIXED** (`a4367ad`). **This heading exists because four
artefacts cite `B18` and the entry did not — B51 recorded that and recommended a stub with no owner,
so it stayed absent.**

**What it was:** `verify_guards.sh`'s `restore()` ran `git checkout` over every path in
`GUARDED_FILES` on any exit once *any* probe had mutated *anything*, because `MUTATED` is a single
global flag. **So a guarded file the script never wrote to was still checked out — destroying
uncommitted work in it.** Fixed by making the restore conditional on a mutation having occurred, and
the pre-flight refuses on a dirty guarded file rather than silently reverting it.

**Why the heading matters even though the defect is fixed.** The citations are load-bearing arguments,
not references:

    verify_guards.sh:80    "The promise used to be wider, and the width was the bug (KNOWN_ISSUES B18)"
    verify_guards.sh:145   "strictly worse than the data loss B18 describes"
    KNOWN_ISSUES.md:1681   "of the B18 fix (a4367ad) that nobody predicted"
    KNOWN_ISSUES.md:1718   "the check plus the B18 fix make a spurious refusal far more likely"

**Two of the four are in shipped code**, and a reader following them found nothing — **a live fact
with a dead pointer, B49's second class**, and the reason T-0018 could reason about widening
`GUARDED_FILES` at all: the argument against it lives here. Related: **B51**, **B49**, **T-0018**
criterion 4.

### B55. `DAY_TRADE` is declared twice and reconciled nowhere — and the notes saying it is recorded were the third false pointer from one file
**Found in:** T-0012 verdict, 2026-08-14, by Review, checking a citation
**Severity:** low as behaviour, and the citation half is the reason it is here

**The mode is declared in two places and neither reads the other:**

    gate_017_analysis_only_tfs.py:116   TRADING_MODE = "DAY_TRADE"     the rule's constant
    shadow.py:628                       mode={"trading_mode": "DAY_TRADE"}   hardcoded literal,
                                                                            and it is the LIVE emitter

**GATE-019's implementation is right and its reasoning is right.** It deliberately spelled the
constant as the schema spells it, *"because using `day_trading` here would have made two
spellings of one quantity — B33's shape, which cost this project forty minutes of silent
shadow downtime."* It also says the literal *"should read this constant"* and did not change
it, correctly, under the task's shadow-only clause. **The remaining defect is only that the
two are unreconciled: change one and nothing tells you about the other.**

**THE CITATION HALF.** Both the constant's comment (`:114`) and `GATE-019`'s `COVERAGE_NOTE`
(`:138`) say the duplication is **"recorded as B45"**. **It is not in B45, and it was not
anywhere in this file** until this entry. Checked both by entry and by whole-file search for
`trading_mode` and `DAY_TRADE`.

**That is the third claim of the form "recorded elsewhere" from `gate_017_analysis_only_tfs.py`
and the third that was untrue when written** — `B50` records the first, where GATE-017's
clause-2 note said *"Recorded in KNOWN_ISSUES"* and no entry existed. **Same file, same author,
same mechanism**: a `COVERAGE_NOTE` is durable and self-printing, so a fact it states **about
itself** cannot go stale unnoticed — and a fact it states **about another file** is printed by
nothing. **Three instances make it the file's normal case rather than a slip.**

**Fix:** this entry is the missing record, so all three notes are now true as written and none
should be edited — the same conclusion as B50, for the same reason: amending them to say
"recorded nowhere" would be correct today and wrong the moment anyone wrote the entry. **The
durable repair is that a note claiming an external record should be written by whoever writes
the record, not by whoever wants it to exist.** Related: **B50**, **B49**, **B33**, **B45**.

### B11. The disturbance grader now runs on real data — and its grade still decides nothing
**Found in:** M4 (implementing GATE-002/007/008/048), 2026-08-08
**THE DATA HALF IS FIXED, 2026-08-13 (T-0008); THE ENTRY STAYS FOR THE HALF THAT IS NOT.**
This entry said the grader "cannot run", that the two
perpetual panels "are instruments this platform cannot fetch", and that GATE-008 "FAILs
naming the two that are absent". **Every one of those clauses is now false**, and they
went false within hours of being written — which is why this is rewritten rather than
annotated: it was the largest open blocker in the register, so a stale B11 misleads in
the most expensive direction available.

Production, on a real four-panel read:

```
GATE-008 PASS  panels_missing []
GATE-007 PASS  alignment_tf ['1H']   thin_panels []
GATE-002 PASS  grade NONE
notes: "BTCUSDT.P: 720 bars from https://fapi.binance.com (PERPETUAL, symbol BTCUSDT)"
```

`BinancePerpetualSource` supplies the two perpetuals from `fapi.binance.com`, the
collector supplies TOTAL and USDT.D, and **GATE-002 appears in `rules_evaluated` for
the first time in this project's history.** Spot was never substituted for perpetual —
the panel identity is carried on the read, so a source aimed at spot reports SPOT and
its panel is refused rather than accepted.

**What is NOT closed, and it is the whole of the remaining gap:** the grade is
**shadow-only**. `_tick_symbol` still calls the ICT path and reads none of this. A
disturbance grade that decides nothing is the same furniture A10 describes — see
**A10**, which this does not narrow.

**The sampling half stays closed:** 1H holds 360 samples against a minimum of 20, and
1m holds 6 and stays refused (**B16**).


**What it is:** GATE-007 requires the layout to be confirmed at the **execution** timeframe,
and GATE-017 makes 1H analysis-only — so the four panels must be read on 30M, 15M or 5M. Two
of those four panels are CryptoCap indices we synthesise ourselves, and
`collect_dominance.py` samples at **60 s**:

| Execution TF | samples per bar | credible? |
|---|---|---|
| 30M | 30 | yes |
| 15M | 15 | marginal |
| 5M | 5 | no — see F1, the same defect one timeframe down |

So `DisturbanceClassifier` is implemented and tested, and on live data today it can only be
fed at 30M without inventing structure. Its inputs for TOTAL and USDT.D are `CorrelateRead`s
whose `observed_order_flow` and `expected_break_confirmed` come from structure detection on
those bars — and structure on a 5-observation bar is noise with an OHLC shape.
**Why it matters:** this is not a missing feature, it is the difference between a grader that
runs and one that produces a disturbance grade from fabricated geometry. The grade keys the
risk matrix, so a bad TOTAL read does not produce a slightly wrong alignment — it moves the
matrix cell and therefore the position size, or trips GATE-001's hard skip on a tradable
setup. History is *not* the constraint here: ~12 days at 15M is ~1,150 bars, plenty for LTF
structure. Sampling rate is.
**Verified, because the collector's own docstring reads the other way:** it warns that
CoinGecko `/global` refreshes only every ~602 s and that polling it per minute yields "nine
identical samples and then a jump — FABRICATED STRUCTURE". That is a warning about a
*different* construction. This collector does not take dominance from `/global`: it computes
market cap = price × supply, where **supplies** come from CoinGecko once a day (slow by
nature, fine) and **prices** come from Binance `/ticker/price`, real-time. So the intraday
resolution is bounded by our poll rate and nothing upstream — raising the rate buys genuine
structure, not duplicates. Anyone reading only the docstring would conclude the opposite.
**Both halves of the fix have landed IN PRODUCTION as of 2026-08-10; the entry stays open
because the DATA has not caught up.**
1. **Refuse rather than fabricate — done** (`ccdd4a4`). A bar assembled from too few samples
   is not a low-quality bar, it is not a bar. `CorrelateRead.bar_sample_count` carries the
   observation count, `LayoutReadability` fails GATE-007 when a panel is thinner than the
   declared minimum, and GATE-036 turns that into a STAND_ASIDE that cites a real rule. This
   half is what makes *any* execution-timeframe choice safe, and it is independent of which
   one is chosen.
2. **Raise the sampling rate — reached production 2026-08-10 at `--loop 10`, not 15** (T-0001).

   **This entry said "done" while it was not, and that is the more useful half of the
   story.** `--loop 15` was committed on 2026-08-09 (`56518f8`) and this text recorded the
   sampling-rate fix as complete the same day. The server was never updated: its own
   compose said `--loop 60`, and `tradingai-dominance-collector-1` ran six days on the old
   cadence — the container was created 2026-08-04, so it predates the commit by five days
   and outlived it by one. Those are two different clocks and conflating them is easy:
   the container's six days is not six days of a false register entry.
   `check_deploy_drift.py` reported it the whole time and exited 1, and nobody read the
   exit code. The cause was structural, not careless — the collector is compose project
   `tradingai-dominance` under `/home/deploy/`, outside every documented deploy path, and
   a grep for "dominance" or "collector" across the runbook and the agent prompts returned
   nothing. There was no step to skip. `scripts/deploy_dominance.sh` now exists so there is
   one, and it re-runs the drift check itself rather than announcing success.

   **The cadence is 10 s, not the 15 s this entry used to name.** 15 s was chosen when the
   question was which timeframes clear the minimum at all; it does not survive contact with
   jitter. `MIN_SAMPLES_PER_SYNTHETIC_BAR = 20` and 15 s gives a 5M bar **exactly 20** —
   one missed or late poll lands it on 19 and GATE-007 refuses the panel. There is a
   guaranteed overrun twice a day: `refresh_supplies()` runs inside a normal tick and holds
   a hard `time.sleep(6)` between its two CoinGecko calls, while the cadence controller
   sleeps `max(1.0, interval - elapsed)` and never makes up a deficit.

   | Execution TF | samples @60s | samples @15s | samples @10s |
   |---|---|---|---|
   | 5M | 5 | 20 — zero margin | **30** |
   | 15M | 15 | 60 | **90** |
   | 30M | 30 | 120 | **180** |
   | 1M | 1 | 1 | 6 — still fails, see B16 |

   Cost is 6 Binance requests/minute instead of 1, against limits the collector's own header
   calls generous; supplies are untouched. 10 s is also the floor `collect_dominance.py`
   enforces (`interval = max(10, int(args.loop))`).

**What is still true, and why this is not deleted:** every sample collected before
2026-08-10 18:23 UTC is 60 s apart, so **the existing ~14 days of history remain 30M-only
and always will** — it cannot be backfilled. Measured on the full pre-change series: 4,013
completed 5M bars, median 5 samples each, **0.0% clearing the 20-sample minimum** for TOTAL
and USDT.D alike. The engine refuses to grade those layouts rather than fabricating them,
which is correct and also means a 5M shadow window run over that history stands aside on
every bar. **Close this entry when the collector has run at 10 s for long enough to cover
the intended shadow window** — 20 trading days or 300 evaluations per symbol, whichever is
later (`MAGIC_STRATEGY_EXECUTION_PLAN.md` M9 Stage A) — not when the code merged, and not
now that the deploy has happened. The clock starts 2026-08-10, not 2026-08-09.
**Also note this task did not wire the correlate panels.** `/api/engine/shadow` still shows
every record blocked on GATE-008 with "roster panels TOTAL and USDT.D are unavailable". The
series is now capable of being read; nothing reads it yet.
**Also worth knowing:** the healthcheck's 600 s staleness threshold was left alone. It still
catches a dead collector at either rate, and tightening it to match a 10 s cadence would
trade a real signal for flapping. `COLLECTOR_STALE_MIN`/`COLLECTOR_DOWN_MIN` in
`data_health.py` were left alone for the same reason.

### B9. Four primitive sub-parts need numbers nobody has ruled on — BLOCKED ON THE TRADER
**Found in:** M3 (implementing PRIM-002/003/004/006), 2026-08-08
**What it is:** four documented objects rest on a threshold the corpus never states, so they
are **not detected at all** rather than detected with a guessed number:

| Object | The missing number | Rule |
|---|---|---|
| Parabolic / compressed liquidity | how tight is "very tight" | PRIM-003 class 3 |
| Institutional levels (deep-V extremes) | what makes a V a deep V | PRIM-003 class 4, **TARGET-007 is OPEN** |
| Diagonal / trendline pools | the staircase geometry, drawn by hand throughout | PRIM-003 |
| Liquidity sweep FAIL | how close is "extremely close" without crossing | PRIM-004 (a) |
| Engineered-liquidity build | cluster size, spacing, and candle shrinkage | PRIM-004 |
| Momentum imbalance | how large is "large" | PRIM-002 `is_momentum_imbalance` |

**Why it matters:** these are not cosmetic gaps, they are *destinations*. TARGET-001 picks
the trade's objective out of the pool inventory and GATE-025's 2R floor is measured to it, so
an invented threshold would not produce a slightly different target — it would produce
targets the trader never marked, and every reward-to-risk computed against one would be
fiction that validates perfectly. TARGET-007 says the quiet part outright: V-quality "should
be used as a weight, not as a filter", and the printed 5-tier list must not be transcribed as
an ordering because it contradicts itself at ranks 1–2.
**What we did instead:** PRIM-002's momentum flag and PRIM-004's failed sweep are emitted
only when the caller passes a declared parameter, and are left unset otherwise — the
`fake_msb` precedent from PRIM-005. The other three classes are simply not emitted, and each
implementation declares a `COVERAGE_NOTE` that `check_rule_coverage.py` now prints, so
"PRIM-003 implemented" cannot be read as "PRIM-003 finished".
**How it ends:** these belong on the same list as `OPEN_ITEMS/TRADER_QUESTIONS.md`. None of
them blocks M4 — the graders do not read these classes — so this is a question to batch, not
a gate to wait on.

### B12. Nothing says HOW the execution timeframe is chosen, and the trader varies it
**Found in:** answering "should the timeframe be set or can it vary?", 2026-08-08.
**What it is:** the contract fixes the legal *set* ({30M, 15M, 5M}, GATE-018) and
requires that within one decision every panel uses the SAME timeframe
(GATE-007, GRADE-010, HG-13: `alignment_tf` must equal `signal_tf`). It says
nothing about whether that timeframe may differ from one trade to the next — and
the telemetry schema stamps `signal_tf` on **every** `setup_evaluation`,
`trade_execution` and `scan_census` record, which is only worth doing if it moves.
The trader does move it: 6 bracketed trades on 1M, 2 on 3M.

A search of all 117 rules found no rule governing the choice. It is also **not
among the questions being put to him** — `TRADER_QUESTIONS.md` asks whether 1M/3M
are legal, and answers that from behaviour, but never asks how he picks.
**Why it matters:** if the engine varies the timeframe, the selection rule is ours
and invented, and it sits **upstream of every gate** — box grades, alignment,
stop ladder and therefore risk all read from whichever series we chose. That is
the worst possible place for an undeclared input: nothing downstream can be
audited past it, and a conformance score would be computed over a choice no rule
justifies.
**Fix, in order:** (1) keep it FIXED and declared for the first shadow window, so
the fidelity measurement has one fewer moving part; (2) add "how do you decide
which chart to drop to?" to the trader's question list — it is cheap and currently
missing; (3) only make it variable once there is a ruled or declared selection
rule, stamped on every record like any other declared parameter.

### B13. The telemetry schema cannot say "the layout was never read"
**Found in:** M9 Stage A, 2026-08-09.
**What it is:** `correlates.disturbance_grade` is an enum of `NONE | LIGHT |
HEAVY`. There is no value for *not evaluated*. The shadow engine has no correlate
panels at all (B11), so it must write one of the three, and `NONE` is the only
one that is not an outright claim — but read alone it says "checked, and nothing
was disturbed", which is the opposite of what happened.
**Why it matters:** C-04 is the contract's own principle that silence is not a
pass, and the schema enforces it everywhere else — `rule_evaluation.verdict` has
`NOT_APPLICABLE` and `UNIMPLEMENTABLE` precisely so an unaskable rule cannot be
recorded as a passing one. `disturbance_grade` is the one place that distinction
is unavailable, and it is a grade the risk matrix reads.
**How we handle it meanwhile:** every other field on the record contradicts the
optimistic reading — `layout_size` is 0, `states` is empty, GATE-008 and GATE-002
are `NOT_APPLICABLE` with their reasons, the decision is `STAND_ASIDE` and
`block_reason` is `NO_ALIGNMENT`. A reader who looks at only the one field can
still be misled.
**Fix:** ask Salim to add `NOT_EVALUATED` (or a sibling `layout_readable`
boolean) when he regenerates the schema against registry v1.2.0 — B8 is already
open for that regeneration, so this rides along with it.

### B14. Nothing enforces stopping the engine before a deploy — it is a documented habit, not a guard
**Found in:** setting up the three-agent working loop, 2026-08-10.
**What it is:** recreating the `api` container kills the live engine mid-run.
Positions opened by that run keep existing as rows, but no process will ever
check their stop-loss again — they are not "still open", they are abandoned.
`POST /api/engine/stop` closes them at the current price and ends the run
cleanly, so the correct sequence is stop → deploy → verify → start. That sequence
is written in `agents/PROMPT_EXECUTE.md` and in the deploy runbook. **Nothing in
the code refuses a deploy that skips it.**
**Why it matters now specifically:** Malek granted the Execute agent authority to
deploy unattended (2026-08-10). Until now every deploy had a human at the
keyboard who could notice an open position; from now on some will not. This is
exactly how the ETH LONG of 2026-08-08 06:00 was destroyed twelve hours in — the
only trade the platform had taken at the time.
**What it could break:** a silent loss of a real position, and a run whose
recorded result is wrong in a direction nobody can reconstruct afterwards,
because the trade shows as open forever rather than as closed at a price.
**THE SAFE SEQUENCE IS NOW OBSERVED TO WORK — which narrows this entry to what it
always actually was: the absence of enforcement, not doubt about the procedure.**
On 2026-08-12 (T-0004) the stop-then-deploy path was deliberately driven with
**two open positions** live, and measured either side. This had never been done
on purpose before; the docstring at `crypto_loop.py:894-905` promising that
`stop()` *closes* rather than abandons had been asserted since 2026-08-08 and
never once verified.

```
pre-stop     OPEN 2   realized_r populated 0   gap_r populated 0
post-stop    OPEN 0 · LOSS 2 (both fields populated) · WIN 1 (both populated)
post-START   ABANDONED in that run  0        (the reconciler runs at run start)
             ABANDONED repo-wide    5        unchanged from pre-deploy
```

The last line is what makes this evidence rather than an absence:
`reconcile_abandoned_decisions` was present, it ran when the new run started, and
it converted nothing — while five `ABANDONED` rows from earlier runs sat
untouched beside it. **Both positions settled through the normal path with real
P&L.** Timing note for anyone repeating this: an unsettled position reads `OPEN`
immediately after a stop and only becomes `ABANDONED` once the next run starts,
so a single reading at stop time cannot detect the failure. Take both.

**This does not close the entry.** What was verified is that the procedure works
*when followed*. Nothing still refuses a deploy that skips it, which is the whole
of this entry — and the risk grew rather than shrank, because the sequence now
has a successful precedent that makes it feel routine.

**A RESTART DOES NOT ONLY ORPHAN A POSITION — IT RE-ENTERS IT. Added 2026-08-13.**
The engine scans on startup, so seconds after a restart it re-detects the setup sitting
on the last closed bar and enters it again at the same signal price. Measured across
the whole corpus: **20 acted-on entries, 14 distinct setups, 6 re-entries — 5 of them
restart artifacts** with entry prices identical to the cent, minutes apart.

**The worst single row is `ETH/USD LONG @ 1922.61` on 2026-08-09: first entry
`ABANDONED`, second `LOSS`.** One setup, two recorded outcomes, one of them an absence
— abandoned by a restart and re-entered by the same restart.

**`inputs_hash` is DISTINCT on all 20**, so these are not one decision replayed: the
engine re-derived the same level from a larger bar window. Which means **the natural key
hides it** — group by `inputs_hash` and you get 20 distinct entries and no duplicates at
all. The duplication is only visible on `(symbol, direction, signal_entry)`.

**What it could break:** every denominator computed from entries rather than setups.
`docs/CONFORMANCE_AUDIT_2026-08.md` counts 12-of-12 entry integrity across a corpus
inflated this way. And the cycle is self-perpetuating — each deploy closes two positions
as operator and immediately re-opens them, so the operator-close ratio moves on **every**
deploy rather than occasionally. It also explains why "deploy when flat" almost never
pays: the engine goes flat-to-two within seconds, so the only flat window is between
stop and start.

**Fix:** make it structural rather than procedural. Either the api refuses to
shut down cleanly with an open run without closing it (a shutdown hook already
calls `stop()` — verify it survives `--force-recreate`, which is a SIGKILL path,
because a hook that only runs on SIGTERM is not a guard here), or a preflight
script that a deploy must pass. Until then this is a habit, and habits are what
the register exists to distrust.

### B15. The agent message bus goes silently deaf when a session restarts
**Found in:** setting up the three-agent working loop, 2026-08-10.
**What it is:** the three agents wake each other with `SendMessage`, addressed by
the session name recorded in `agents/registry.json` during the HELLO handshake.
Those names (`tradingai-02`, …) are assigned per session and change when a
session is restarted or compacted into a new one. The message file is still
written to the right inbox — that half is durable — but the doorbell goes to a
name that no longer exists.
**What it could break:** the loop stalls with no error anywhere. Execute finishes,
sends WORK, and Review never wakes; Malek sees a task that has been "REVIEWING"
for hours and no indication that anything is wrong. Worse: if the stale name has
since been reassigned, the wake-up goes to an unrelated session working on
something else.
**How we handle it meanwhile:** `bus.py send` warns when the recipient role is
unregistered, and `bus.py tasks` shows each task's state and cycle, so a stalled
task is visible if you look. Re-running the handshake corrects the registry.
**Fix:** have each agent re-run `ListAgents` before sending and refuse to ring a
doorbell whose name is absent from the live peer list — that turns a silent stall
into a loud one, which is the whole difference.

**Note added 2026-08-12: the fix above is written down and we keep doing it by
hand instead.** Three sessions opened T-0003 by re-deriving the peer table
through set arithmetic across each other's `ListAgents` output — because no
session can see its own row, two peer lists are needed to identify either one.
That handshake is a manual substitute for the fix in the paragraph above, which
needs no coordination and cannot go stale. Same shape as B19 and B21: **a habit
that must be performed, standing in for a check that would fail on its own.**

Two corrections to how this entry has been *described* in passing, both wrong and
both tested rather than argued: **bare names DO resolve** — a message addressed to
`tradingai-4c` with no `[ref]` arrived — so "a bare name does not resolve" is not
the mechanism here and never was. The entry above is accurate: names change on
restart, and the doorbell goes to a name that no longer exists. The `[ref]` is
only needed to disambiguate.

### B16. The 1M second shadow run can never have readable correlate panels — a decision collides with a guard
**Found in:** T-0001, raising the collector to `--loop 10`, 2026-08-10.
**What it is:** `MAGIC_STRATEGY_EXECUTION_PLAN.md` §5.4 records Malek's decision of
**5M execution timeframe, with 1M as a second shadow run to compare against it**. At the
new 10 s cadence a 1M bar holds **6 samples** against `MIN_SAMPLES_PER_SYNTHETIC_BAR = 20`.
Clearing 20 on a 1M bar needs a poll every 3 s — and `collect_dominance.py` reads
`interval = max(10, int(args.loop))`, so **the script enforces a 10 s floor**. 3 s is not
merely undesirable, it is unreachable without changing that line, and changing it means 20
Binance requests a minute against a free endpoint.
**Why it matters:** the 1M run will `STAND_ASIDE` on GATE-007 for every single bar, citing
GATE-036, exactly as the 5M run does on the 60 s history today. So the 5M-vs-1M comparison
the decision exists to produce **cannot be produced as specified** — the 1M arm yields no
gradeable layouts at all, not merely worse ones. Reading its output as "1M performs poorly"
would be reading the guard, not the market.
**What it could break, concretely:** M9 Stage A's shadow window is the evidence base for
Stage B, the cutover. If half that window is an arm that structurally cannot grade anything,
the window is smaller than it appears and the comparison it was designed around is absent.
Worse, the 1M records will look like ordinary abstentions — the same `STAND_ASIDE` /
GATE-036 shape a genuine market refusal produces — so nothing in the telemetry distinguishes
"the layout was unreadable by construction" from "the layout was read and refused".
**Not fixed here:** T-0001 changed the collector's cadence, not the decision. This is for
Malek: either drop the 1M arm, or accept it as a null arm and say so in the record, or
re-open the 3 s question with its cost attached. **Settle it before Stage A's window is
treated as meaningful**, because afterwards it is 20 days of data with a hole in it.

### B17. The collector's `--status` readout still uses a per-minute denominator — NARROWED, the api half is fixed
**Found in:** T-0001, 2026-08-10. **Api half closed 2026-08-12 (T-0004).**
**What it is:** two readouts kept a once-per-minute denominator in production. **One is now
fixed; one remains.**

* ~~**`/api/system/data-health` → `recent_density_pct`**~~ — **CLOSED 2026-08-12.** The api
  was redeployed in T-0004 at merge sha `71feb556b3e`, after stopping the engine cleanly so
  no position was abandoned (B14). Verified in the running container:
  `data_health.py:77 EXPECTED_POLL_SECONDS = 10.0`, and the payload now carries
  `expected_poll_seconds` so a reader can check the denominator instead of trusting it.

  **A SUB-100 READING IS THE FIX WORKING, NOT DEGRADATION. Do not raise an alarm on it.**
  The old denominator was `min(100.0, 100.0 * recent / 60.0)`; at a 10 s cadence the
  collector puts ~360 samples in the hour, so it computed `100*360/60 = 600` and clamped to
  exactly **100.0**. It was arithmetically *incapable* of printing below 100 unless polling
  fell slower than 60 s. The new denominator is `3600/10 = 360`, so **any value under 100 is
  reachable only under the fixed code.** Review observed **99.7** (≈359 samples) shortly
  after the deploy — that reading is the discriminator, and it is proof in a way the field
  itself never was before.

  **But most of the time it still reads 100.0, and that is not a failure.** Three readings
  taken by me minutes later, eight seconds apart, all returned `100.0` with
  `expected_poll_seconds: 10.0`. Both observations are correct: the field only falls below
  100 when the hour happens to miss a sample or two. **A future reader who checks, sees
  100.0, and concludes the fix did not land would be wrong** — the discriminator is
  `expected_poll_seconds` being present in the payload at all, since that field did not
  exist before.

  Attribution, because it matters for what is evidence and what is inference: the 99.7 was
  Review's reading, not mine. I verified the arithmetic that makes it impossible under the
  old formula, and I observed only 100.0.

  This is today's recurring shape for the third time: **an output that does not discriminate
  between working and broken.** Eight `ok` lines with or without `restore()`; the one-step
  and two-step `curl` returning identical shas; a density that reads 100.0 either way. In
  every case the fix was to find the reading that *can* differ, not to trust the one that
  usually does not.
* **`collect_dominance.py --status`.** The fix is **on `main` as of 2026-08-10**, but the
  collector container `git clone`s `backend/scripts/` from GitHub main **at startup** and
  is guarded by an `/app/.ready` flag, so the running container still holds the code it
  cloned when it was recreated at 18:23 UTC. The fix is armed, not applied: it lands at the
  collector's **next recreate** (`./scripts/deploy_dominance.sh --force`), and until then
  `--status` in production reports density against a per-minute expectation and prints
  ~600%. Nobody needs to recreate the collector for this alone — a needless recreate puts a
  real gap in a series that cannot be backfilled, and this is a CLI readout, not the health
  signal. It will correct itself the next time the collector is deployed for any reason.

**Why it mattered, and why the remaining half is the same disease.** At 10 s a healthy hour
is ~360 samples; against a 60-sample expectation that is 600%, clamped to exactly **100.0**.
A collector degrading all the way back to 60 samples/hour — a sixfold loss on data that
cannot be backfilled — still read **100.0% healthy**. *(This paragraph now describes
`--status` only; `data-health` was fixed 2026-08-12.)* Measured either side of the cadence
change, nine minutes apart, on the api's readout before the fix:

| | 18:26:13Z (60 s) | 18:35:21Z (10 s) |
|---|---|---|
| `recent_density_pct` | 100.0 | 100.0 |
| `samples_in_tail` | 971 | 971 |

Two identical readouts across a 6× change in the underlying rate.
**And there is no second field that would reveal it.** `samples_in_tail` looks like a raw
count and is not a signal: `_read_tail` seeks `size - TAIL_BYTES` and parses a fixed 96 KiB
window, so it returns ~970 rows at any cadence and any level of degradation. Do not record
this as a weak signal; the panel has **none**.
**What still works, so the blind band is bounded:** `status` is driven by `age_min` against
`COLLECTOR_STALE_MIN = 5.0` and `COLLECTOR_DOWN_MIN = 30.0`, not by density. A **dead**
collector is still caught within five minutes at either cadence. What is invisible is
**partial** degradation between 1× and 6× — which is precisely the range a struggling
Binance endpoint or a slow container would produce.
**The replacement check until it is fixed** — no ssh, no token, over the public CSV:

```
curl -s http://31.97.183.142:8097/dominance_intraday_raw.csv | tail -400 | \
  python3 -c "import sys,csv,datetime as dt,statistics; \
r=[dt.datetime.fromisoformat(l.split(',')[0]) for l in sys.stdin if l[:2]=='20']; \
print('median gap', statistics.median((b-a).total_seconds() for a,b in zip(r,r[1:])))"
```

**Fix:** an api deploy carries `data_health.py`; the merge to main is **done**, so the next
collector recreate carries `--status`. The api deploy is the one with a cost — it requires
stopping the live run first (B14), so it should ride along with the next api change rather
than being done for this alone. **Close this before M9 Stage A's shadow window is treated as
meaningful**, not merely "at the next api deploy": the window is exactly when a silently
degrading collector would do the most damage and be least visible.

### B19. Nothing checks a `file:line` citation, and this register is made of them
**Found in:** 2026-08-12. Two agents independently audited their own citations
after one off-by-one surfaced: **12 wrong out of ~40 checked** — 7 in the first
two commits of a register entry, 5 in T-0003's pre-review.
**What it is:** every entry here, and every work report and plan, points at code
by `file:line`. Nothing verifies those, and they rot or arrive wrong silently.
Four distinct mechanisms were observed in a single session:

| mechanism | example |
|---|---|
| wrong cwd | `scripts/verify_guards.sh` is `backend/scripts/…` from the root; the bare form is correct only inside `backend/`, and CI uses it because the job sets `working-directory: backend` |
| wrong referent | `:71` (array opens) vs `:75` (the line meant) — both defensible, neither stated |
| off-by-one from a range read | `sed -n '78,100p'` where **line 78 is blank**: the first *visible* line reads as 78, and every citation from that read shifts by one |
| inheritance through a message | a number republished by an agent that verified the surrounding code but not the number — it gains apparent confirmation from each repetition |

**The split is mechanical, not a matter of care** — but it runs in one direction
only, and an earlier draft of this entry overstated it. What both audits show is
that **every wrong citation came from a range read or from another agent's
message, and `grep -n` never produced a wrong one.** The converse does not hold:
a third audit, of two further entries' citations, found seven correct — four from
`grep -n`, and **three from range reads that happened to start on a non-blank
line**. So a range read is not reliably wrong; it is *unverifiable without
recounting*, which is worse, because it produces right answers often enough to
feel safe. "I checked them and they were fine" is not evidence the method works.
This is not fixable by looking harder. It is fixed by reading from output that
emits the line number instead of output that requires you to infer it.

**Why it matters:** a wrong citation does not fail, it misleads — and it misleads
the reader who is *acting* on the entry, six weeks later, with no cheap way to
tell. It also degrades the register's whole purpose: entries here exist to be
trusted without re-derivation. Worst is the confidence marker — both audits found
wrong numbers sitting under phrases like "checked, not reasoned" and "things I
verified, so nobody re-verifies them". **The signal of confidence and the act of
checking had become the same gesture**, so the sentence that should have carried
a check instead discouraged one.

**How we handle it meanwhile:** cite from `grep -n`, never from a counted range;
never republish a line number from another agent's message without re-deriving
it; say which referent a number means when a block has several.

**Fix:** a linter that resolves every `file:line` in `KNOWN_ISSUES.md`,
`agents/tasks/**` and the runbooks against the repo and fails when the target
does not exist or no longer contains what the entry claims. It would have caught
all 12 in about a second. Note the property that matters: it **fails**, rather
than being a review step someone performs — the same distinction as B15's
unrun fix. A sweep performed once by a diligent reader rots exactly like the
citations it audits. Pairs naturally with **B21**, which is the same disease in
the register's numbers rather than its line references.

### B20. CI on `main` is advisory — nothing blocks on a red check and nothing reports one
**Found in:** 2026-08-12, chasing why a job configured to block had not blocked.
**What it is:** `main` has **no branch protection and no rulesets**. Verified
against the GitHub API:

```
GET /repos/Amineregayeg/tradingai/branches/main/protection  -> 404 Not Found
GET /repos/Amineregayeg/tradingai/branches/main             -> "protected": false
GET /repos/Amineregayeg/tradingai/rulesets                  -> 0 rulesets
```

**AND IT CANNOT BE FIXED FROM THIS SEAT — a capability limit, not a permission one.**
Verified 2026-08-14: the `Docz2868` token holds `push: True, pull: True` but
**`admin: False, maintain: False`** on `Amineregayeg/tradingai`, and the protection
endpoint 404s for reading as well as writing. **No authorisation the owner gives an
agent changes this** — it needs him to set protection in GitHub's settings himself, or
to grant the token admin. Recorded so a future seat does not spend the attempt: this is
not "not done yet", it is not doable from here.

So every CI job on this repo is advisory. `Tier 0.2 - lookahead guards must bite`
carries no `continue-on-error` and fails the job on exit 2 — it is written to
block, and there is nothing for it to block. Nothing rejects a push to a red
`main`, and nothing requires a PR, a review or a green check to get there.

**Why it matters — and this is the part that already cost three days.** Nothing
*routes* a red `main` to a human, and nothing *stops* one either. CI is a machine
that observes correctly, reports honestly to a page nobody opens, and is wired to
no consequence.

That is not hypothetical. It has already happened, and the incident is recorded
here because the entry that used to hold it (A11) was deleted when its tests were
fixed on 2026-08-12:

```
2026-08-10T19:56Z  failure  946ca1c   <- was main, and what production ran
2026-08-10T17:23Z  failure  3402adb
2026-08-09T21:19Z  failure  b3264d6
2026-08-09T18:43Z  failure  7f51836
2026-08-08T21:55Z  success  8d30278   <- last green
```

Two checks were red across those four commits. One of them,
`Tier 0.2 - lookahead guards must bite`, meant **the project's mutation-testing
harness ran zero probes from 2026-08-09 to 2026-08-12** — all eight, including
five with no connection to the test that was failing. Nobody noticed for three
days, across a full task and a production deploy, and `946ca1c` reached
production by ordinary `git push`. **Nothing was overridden, because there was
nothing to override.**

The reason it went unnoticed is the reason to keep this entry: a script exiting
non-zero with a loud, accurate error reads as a broken environment rather than as
a disabled guard, and a red check that has been red for a while stops looking
like news. Compare the 2026-08-04 incident (`bd0e2a0`), where the same script
printed `TIER 0.2 PASSED` having run no tests: that failure was **invisible**, as
it never reached CI. This one was **visible and ignored**, which is worse.

**What it could break, concretely:** the guarantee everyone in this project has
been reasoning from — that `main` is releasable — is not enforced anywhere. A
lookahead regression reintroduced tomorrow would turn `Tier 0.2` red, and that
red would neither stop the merge nor reach anyone. Note also that runtime
containers `git clone` `main` at startup, so an unreleasable `main` is not a
staging concern: it is what the next container recreate ships.

**How we handle it meanwhile:** check CI by hand after every push to `main` —
`gh`-less, so via the API. This is a habit, and habits are what B15, B19 and this
entry all say do not hold.

**NO AGENT IN THIS PROJECT CAN CLOSE THIS. Established 2026-08-12 (T-0004).**
Branch protection is an admin-only endpoint, and the token every agent pushes
with is not an admin:

```
login       : Docz2868
repo        : Amineregayeg/tradingai        (owner: Amineregayeg)
permissions : admin False · maintain False · push True · triage True · pull True
GET /branches/main/protection -> 404        (GitHub reports admin-required as "Not Found")
```

So this is not a token to rotate or a call to retry. **Only the repo owner can
enable it** — by running `ENFORCE_ADMINS=false ./scripts/enable_branch_protection.sh`
with an admin token, by using the web UI, or by granting `Docz2868` admin. An
agent attempting it gets a 404 that reads like a missing endpoint rather than a
permission denial, which is why this needs writing down: the failure does not
announce its own cause.

**`enforce_admins=false` is the recorded decision, and it is not the script's
default.** `scripts/enable_branch_protection.sh:55` defaults to `true` and its
header argues for it — *"false leaves a silent hole … the badge says protected
while the property does not hold."* That reasoning assumes the bypasser and the
gated party are the same actor. Here they are not: the agents are non-admin, so
they are bound either way, and B20's whole purpose — stopping an agent loop
merging past a red check — survives `false` intact. What `false` buys is that the
one human on the project can still push a fix at 2am without dismantling the
gate. **This was checked rather than assumed:** had the agents' token carried
admin, `false` would have voided the entry and `true` would have been correct.

**The name-exactness risk is already retired**, whoever runs it. The script derives
reported job names from a real workflow run and `grep -Fxq`s each required check
against them, so it cannot produce the failure that looks like success — a
required context CI never emits, which blocks every future PR forever. All four
names verified string-identical to what CI reported on `71feb55`.

**Fix:** require the four CI checks on `main` via a ruleset, and route a red
`main` somewhere a human reads. The first is **a decision, not a task** — it
changes how everyone lands code, and it is Malek's call, not an agent's.
**Recording this is not a recommendation to switch it on today.**

**One live precondition, stated as a check rather than a claim.** Turning
protection on while `main` is red would block every merge until it is green, so
the order matters. Do not take this paragraph's word for the current state —
**resolve it, in two steps**:

```bash
# 1. Resolve the sha DIRECTLY. Never the commits/main endpoint: it has served a
#    stale cached ref on this repo before, and it fails convincingly — four green
#    checks belonging to a commit that is not the tip.
SHA=$(git ls-remote https://github.com/Amineregayeg/tradingai.git main | cut -f1)

# 2. Ask about THAT sha, not about a name.
curl -sH "Authorization: token $TOKEN" \
     "https://api.github.com/repos/Amineregayeg/tradingai/commits/$SHA/check-runs"
```

All four checks must read `success`. The two-step form is not pedantry: a cached
`main` is how T-0001 nearly reported a successful push as failed, and a reader
deciding whether to enable branch protection is the last person who can afford a
green answer about the wrong commit. An earlier draft of this very paragraph used
the one-step form.

Last measured 2026-08-12 at `a4f3b08`:
`Backend suite` **failure**, `Tier 0.2` **failure** — red, with the fix for both
sitting on an unmerged branch. An earlier draft of this entry asserted `main` was
already green; it was not, and that would have told Malek the blocker was gone
while it was still there. It would also have been the fifth stale figure of the
day, one paragraph above B21, which exists because of the other four.

**IT WOULD HAVE PREVENTED A RED `main` ON 2026-08-13.** A push with three failing
tests landed unimpeded (`157d701`). The required contexts this entry proposes include
`Backend suite (production pins)`, which was `failure` on that commit — **protection
would have blocked it.** Second time in one day this pending item has turned out to be
load-bearing rather than hypothetical.

**This entry outlives the incident that produced it, deliberately.** The red test
was incidental — the next one will be a different test, and the routing gap will
be identical. Do not close this because the four runs above went green.

### B21. The register quotes numbers the code owns, and nothing checks them
**Found in:** T-0003, 2026-08-12, after four stale figures surfaced from four
directions inside one hour.
**What it is:** entries here state figures that were true when written — suite
counts, poll cadences, thresholds, dates — and nothing re-reads them when a later
task makes them false. Four instances from one task:

* the A11 baseline `838 passed / 2 failed`, invalidated by T-0001 adding twelve
  tests (found by Review; the entry's own headline and its correction paragraph
  then disagreed with each other about the same number);
* **F1**'s "at 60 s polling a 1m bar holds one observation" and "drop `--loop` to
  ~15 s", both invalidated when the collector went to 10 s on 2026-08-10 — the
  advice became a *slowdown* while the entry's conclusion stayed correct;
* section **C**'s "Empty as of 2026-08-04", which reads as continuous drift-free
  state through a period when the drift check was in fact exiting 1;
* `DEVELOPING.md` was updated correctly for one of these and the register was
  not, so two documents disagreed about the same figure.

**Why it matters more here than in a doc:** `KNOWN_ISSUES.md` is where every
prompt's Step 4 sends an agent for its baseline. A stale figure here is
*load-bearing* — an agent that trusts `838` concludes that T-0001's twelve new
tests are twelve new failures, and spends its cycle chasing them. F1 shows the
worse shape: **right for the wrong reason**, so nobody rechecks it and every
detail a reader would act on is false.

**How we handle it meanwhile:** date-stamp a figure rather than overwriting it,
so a reader can order two numbers; and when a task invalidates an entry, correct
that entry in the same commit.

**Fix:** a check that reads both sides and fails when they disagree — the
register's quoted constants against the code that owns them
(`MIN_SAMPLES_PER_SYNTHETIC_BAR`, the collector cadence in
`deploy/compose.dominance.yaml`, suite counts, `TAIL_BYTES`). Same property as
B19's linter and B15's unrun fix: it **fails**, rather than being a sweep someone
performs. A sweep rots exactly like the figures it audits.

### B22. One red test disables all eight lookahead probes
**Found in:** T-0003, 2026-08-12 — the mechanism behind the three-day outage in
B20.
**What it is:** `backend/scripts/verify_guards.sh` checks `BASELINE_TESTS` as a
single block (`:148-156`) and refuses to mutate anything if any of them is red.
That refusal is correct and deliberate (`bd0e2a0`): a test that already fails
cannot demonstrate that removing a guard is what broke it. But the granularity is
wrong — the five baseline files back eight probes, so **one red file stops all
eight**, including the FVG probe, the daily-bias probe, both execution probes and
the resolve probe, none of which have anything to do with the file that is red.

That is exactly what happened: two failing dominance tests switched off lookahead
verification for the entire project for three days.

**What it could break:** the blast radius of any red test is the whole harness,
and the failure is silent in the way that matters — the script exits 2 with an
accurate, loud message, which reads as a broken environment rather than as
disabled guards.

**NEAR MISS, 2026-08-13.** A red suite was pushed to `main` (`157d701`, three failing
tests) and **`Tier 0.2` stayed green** — because those three tests happened to live
outside the five `BASELINE_TESTS` files. Had any of them landed in one, the prober
would have exited 2 and gone dark again: **the exact A11 condition, which cost three
days and which T-0003 existed to fix.** The design did not hold; it was not tested.
One file's difference.

**Fix:** baseline only the tests each probe actually uses, so a red dominance test
costs the three dominance probes and leaves the other five running. Deliberately
**not** done in T-0003: it changes the harness's design while that harness is the
instrument verifying the change, which is the wrong order.

### B23. A probe cannot tell that the line it mutates does nothing
**Found in:** T-0003, 2026-08-12. This is how A11 hid for as long as it did.
**What it is:** `probe()` guards two ways a probe can rot — a sed expression that
matches nothing (`:123-131`) and a test path missing from `BASELINE_TESTS`
(`:107-115`). Neither can see the third: **a sed that matches a line which has no
effect.** Probe 5 mutated `bars = bars.dropna(how="all")` for months while that
line dropped zero rows — the `samples` column had been assigned above it and is
`0`, never `NaN`, for an empty period, so `how="all"` could never match. The probe
guarding against fabricated bars across a collector outage was pointed at dead
code, and every guard it reported on was a guard it had not tested.

**Why it survives T-0003's fix:** the dominance line is live again, but nothing
was added that would detect the next occurrence. It applies to all eight probes.
A probe is only as good as the assumption that its target line does something,
and that assumption is currently unchecked.

**Fix:** no cheap one. The nearest thing is a coverage assertion — require each
mutated line to be executed by the probe's own test — which catches "dead line"
but not "live line with no effect". Worth a plan rather than a ride-along.

### B25. Three agents share one working tree, and `verify_guards.sh` rewrites tracked files in it
**Found in:** T-0003, 2026-08-12 — raised by the Manager, which declined to run
the script while Review was mid-verification for exactly this reason.
**What it is:** manager, execute and review all operate in the same checkout at
`/mnt/c/Users/malek/TradingAI/tradingai`. `backend/scripts/verify_guards.sh`
mutates four tracked source files with `sed -i` and restores them with
`git checkout`. Nothing coordinates that. Two sessions running it at once, or one
running it while another edits, interleave inside the same files.

**The destructive half is already gone, and it went as a second-order consequence
of the B18 fix (`a4367ad`) that nobody predicted.** Before that fix: session A is
mid-probe with a mutation in place, session B starts, B's pre-flight sees the
dirty file and `exit 1`s, the trap fires `restore()` unconditionally, and B's
`git checkout` wipes **A's** in-flight mutation from another session — leaving A
to finish probing against restored files and report a verdict it did not earn.
After the fix, B's `MUTATED` is 0, `restore()` returns early, and A is untouched.
Worth stating plainly because it is the only thing in this whole task that turned
out *better* than expected.

**Two windows remain, and the second is far more reachable than "two agents start
at the same instant" suggests.**

*Losing uncommitted work* is now a race rather than the norm. Pre-flight checks
**all four** guarded files against the shared tree, so a session already holding
edits in any of them refuses the other before it mutates anything — an earlier
draft of this entry said one session routinely destroys another's work, and that
was wrong. What is left is an edit that lands *after* a run cleared pre-flight:
that run then checks out all four by design, and must, because that is how it
undoes its own mutation. The window is the length of a run — minutes, since every
probe invokes pytest — not an instant.

*Two concurrent runs* is the reachable one. `probe()` restores at **both** ends
(`:117` and `:142`), so the tree is momentarily clean **between every pair of
probes** — seven such boundaries in one run. A second session starting at any of
them clears pre-flight honestly and begins mutating the same four files. Neither
is doing anything wrong and neither can see the other.

**What survives is observational, not destructive, and that is the worse kind.** A
result can be attributed to the wrong run: both sessions clear pre-flight before
either mutates, or one runs `pytest` while the other is mid-`sed`. The verdict is
then **unfalsifiable from either transcript** — each session's log is internally
consistent and neither carries the other's timestamps. On a task whose subject is
an instrument reporting outcomes it did not earn, an unattributable `ok` is the
worst failure available.

**The diagnostic, which is the useful part** (Review's): *an unexplained `exit 1`
on a tree you believe is clean means someone else is running.* The pre-flight
check plus the B18 fix make a spurious **refusal** far more likely than a spurious
**pass** — that asymmetry is what you can actually act on.

**How we handle it meanwhile:** one session runs `verify_guards.sh` at a time, and
says so on the bus before starting. That is a habit, and B15, B19 and B21 all say
habits do not hold — recorded as such rather than as a solution.

**Fix:** either a lock (refuse to start if another run holds it) or, better, have
the script operate in a `git worktree` of its own, so its mutations cannot reach
anyone else's checkout at all. The second removes the shared resource instead of
scheduling access to it.

### B26. Two services disagreed about the name of one variable, and the api read no dominance data at all
**Found in:** T-0006, 2026-08-13, by criterion 4c. **Live for as long as the api has
had the mount.** Fixed in the source; the durable half is owner-only.
**What it is:** `deploy/compose.vps.yaml:110` set **`DOMINANCE_DATA_DIR`** and mounted
`/opt/dominance` to `/data/dominance:ro`. `DominanceSource.__init__` read
**`DOMINANCE_DIR`**. So the api fell through to the `/opt/dominance` default — a path
that does not exist inside that container — and **every dominance read from the api
returned nothing**. The collector's own compose sets `DOMINANCE_DIR`, so the two
services disagreed about the name of the same thing and only one matched the code.

The mount was right. The value was right. The variable name was never read. The data
was present throughout: `/data/dominance/dominance_intraday_raw.csv`, 4.6 MB, written
minutes before it was found missing.

**Why nothing caught it:** no consumer failed loudly. `load_raw` returns an empty frame
for a missing file **by design** — the engine's contract is to abstain when an input is
absent, not to crash — so an unreadable path is indistinguishable from a collector that
has not written yet. Both are silence, and only one is a bug.

**How it was caught, because the mechanism is the point.** Criterion 4c required the
shadow record to show `GATE-008 panels_missing` == *exactly* the two panels we cannot
source, **and** `GATE-007 alignment_tf` non-empty. It came back with **all four missing
and an empty `alignment_tf`** — which is what "read nothing at all" looks like, as
opposed to "read the two we have". **Criterion 3 on its own passed**: the decision mix
had changed, GATE-008 was deciding instead of GATE-036, and the wiring was doing
nothing. A list of absences says nothing about the presences.

**Fixed where an agent can:** `DominanceSource` now accepts either name, preferring
`DOMINANCE_DIR`. **The durable fix is renaming it in the compose, and no agent can do
it** — `/docker/tradingai/docker-compose.yml` is root-owned, the deploy user has no
write access and no passwordless sudo, and root ssh is key-refused. Same owner-only
class as **B20**. Until then the repo's `compose.vps.yaml` deliberately still says
`DOMINANCE_DATA_DIR`, because that file is *the record of what runs* and editing it to
the correct name would make the record describe a deployment that does not exist.

### B27. `GATE-007` was judging a boundary artefact, not the bar being confirmed
**Found in:** T-0006, 2026-08-13, by criterion 4c again, immediately after B26 was
fixed. **Fixed in `850fc6b`.**
**What it is:** the panel read reported `frame["samples"].min()` over a 30-day window as
the bar's sample count. The thinnest bar in that window is the collector's **first
partial hour on 2026-08-04** — so a boundary artefact from the day collection started
decided whether today's layout was readable. GATE-007 failed with
`thin_panels: ['TOTAL','USDT.D']` at 1H, where a complete bar holds **360 samples
against a minimum of 20**: an 18× margin reported as too thin.

**The reasoning that produced it was internally coherent and wrong**, which is why it
survived review of its own comment: it argued from *"any panel under the minimum
fails"* to *"use the minimum across all time"*, and that does not follow. A mean would
have been wrong in the other direction. **GATE-007 asks whether the layout is readable
for THIS confirmation**, so the only bar whose thickness matters is the one being
confirmed on — the last complete bar, `drop_partial` having removed the still-forming
one.

**THE FIX CORRECTED THE GUARD'S SCOPE AND LEFT THE CONSUMER'S UNTOUCHED — read this
before assuming the read is now decision-bar-shaped.** (Review's finding, verified.)
`sample_counts` is now the decision bar. **`panel_bars` is still the full 30 days.**
So GATE-007 judges the right bar while the structural read it guards still consumes a
month of history. At 1H that is invisible, because every historical 1H bar clears the
minimum — it becomes visible at 5M.

**THE REMEDY THIS ENTRY USED TO GIVE IS WRONG AND WOULD BREAK THE GUARD. Corrected
2026-08-13.** It said to pass `min_samples` into `fetch_ohlcv_with_samples`. That
**filters the thin decision bar out of the frame**, so `.iloc[-1]` then returns an
older, thicker bar: GATE-007 reports `thin_panels: []` and **PASSes on a stale bar**.
It converts *"the decision bar is too thin, refuse"* into *"grade an hour-old bar and
call it readable"* — the exact failure this entry exists to describe, introduced by its
own prescription. Demonstrated: unfiltered 5 samples → FAIL; `min_samples=20` → 40
samples → PASS, on a bar nobody is confirming on.

**The correct shape is one fetch, two derivations.** Fetch unfiltered; keep
`sample_counts` as `frame["samples"].iloc[-1]`, the true count of the actual most-recent
complete bar; filter locally for `panel_bars` only. The guard then judges the bar being
confirmed on while the consumer sees only bars thick enough to read.

**This is the most dangerous staleness the register has carried**, because B27 is the
entry someone reads *specifically when they are about to touch that code*. Anyone reading "GATE-007 judges the decision bar" as a
description of the whole read will not look again, and T-0007 depends on someone
knowing the difference.

**One coupling the fix rests on, now pinned by a test rather than a comment**
(`test_panels_are_read_with_the_forming_bar_dropped`): `iloc[-1]` is the decision bar
only while `drop_partial=True` at the call site. A caller passing `False` makes it a
partial bar, thin by construction — **this bug, one caller away.**

**Kept as an entry although it is fixed**, because the class recurs: a windowed
aggregate answering a question about a single bar. Any future panel, timeframe or
quality metric that summarises a range is exposed to it.

### B28. Endpoint defaults truncate, and a truncated count reads as a measurement
**Found in:** T-0006, 2026-08-13.
**What it is:** `/api/engine/shadow` defaults to `limit=50`. A caller who omits the
parameter gets `n: 50` and a rule-count distribution that sums to exactly 50 —
indistinguishable from a population of 50. Measured the same instant:

```
limit=50   n=50   deciding {'GATE-008': 14, 'GATE-036': 36}
limit=500  n=124  deciding {'GATE-008': 14, 'GATE-036': 110}
```

The GATE-008 count is identical and the GATE-036 count is not, so **which conclusions
survive the truncation depends on where the cut falls** — the very thing a reader
cannot see. This is the same family as the register's other truncation findings and it
arrives through a default rather than through a pipe.

**How we handle it meanwhile:** pass `limit` explicitly whenever a count is being
reported, and state it beside the number.
**Fix:** have the endpoint return the true total alongside the returned slice, so `n`
cannot be read as the population.

### B29. Work can pass review unshipped, because the check is aimed one step short
**Found in:** T-0006, 2026-08-13. Fourth instance of one family in a single day.
**What it is:** a task's register changes and a test refinement sat **unpushed** while
the work was reviewed and marked DONE. The reviewer resolved the remote ref directly
— correctly, per T-0001's criterion 9 — got the tip, and confirmed it. **But
`git ls-remote` answers "what is the remote's tip", and the question was "does the
remote contain everything this task produced."** The first has a satisfying answer,
so nobody notices it is not the second.

**The disproof was already printed.** The same verdict's scope section listed the
diff — three files, no `KNOWN_ISSUES.md` — and a few paragraphs later asserted
"Register: B11 narrowed, B26/B27/B28 opened", taken from the work report. Evidence
in hand, not turned on the claim being made.

**On the author's side the same gap:** `git status --porcelain` answers "are there
uncommitted edits", not "is it shipped". Clean tree, three unpushed commits, twice in
one day after escalating a peer for exactly that reasoning.

**THE SAME SEAM RUNS THE OTHER WAY, 2026-08-13.** This entry is work passing review
**unshipped**. Hours later the mirror occurred: work shipped **unverified** — a suite
run and a `git push` chained in one command, with the push not gated on the result, so
three failing tests reached `main`. **Unshipped-but-reviewed and shipped-but-unverified
are the same missing gate seen from either side**, and neither is guarded by anything
structural. Both were caught by a human reading output after the fact.

**Fix, and it needs nothing built:** **cross the file list in the work report against
the file list in the diff.** A task claiming register changes whose diff contains no
`KNOWN_ISSUES.md` is unshipped, and both lists are already in front of the reviewer
when the verdict is written. For the author, the only version that holds is committing
and pushing in the same breath — the check that would catch it is one nobody runs at
the moment it matters.

**Why this is its own entry rather than a note on B19 or B21.** Those are about wrong
*content* — a citation that does not resolve, a constant that has gone stale. This is
about a *correct* answer to a question adjacent to the one being asked. No linter
catches it: every command ran, every output was accurate, and the inference from it
was not.

### B30. A `cancelled` check reads as green — the only CI state that asserts nothing
**Found in:** T-0006, 2026-08-13, closing a verdict against `main`'s tip. Review's
finding and largely its wording.
**What it is:** on `30e70d2` the check-runs read `success`, `success`, `success`,
**`cancelled`** — the cancelled one being `Backend suite (production pins)`, which had
run three minutes before stopping. **A scan for red finds none.** `cancelled` is
neither `success` nor `failure`: it occupies the slot where an assertion would be and
makes none.

**Why it is worse than the other non-discriminating outputs in this register.** Every
other instance — eight `ok` lines with or without `restore()`, the one-step curl,
`recent_density_pct` at 100.0, `panels_missing` as a list of absences — was a wrong or
truncated *value*. This is a **third state**, and the shapes we have learned to
distrust are all binary. A reader asking "is anything red" is asking the wrong question
of a tri-state field.

**And no other check substitutes for it.** `Tier 0.2` passing proves the **five** files
in `verify_guards.sh`'s `BASELINE_TESTS` are green and says nothing about the other 860.
The test added in that same commit was not one of the five — so it had been verified by
CI, by Tier 0.2, and by the reviewer's own suite run **none of them**.

**Cause not asserted.** A later push almost certainly superseded the in-flight run, and
that was not verified. The entry stands on the observed state and needs no theory of
why — a guessed mechanism in a register entry is the thing that gets checked once and
disbelieved.

**Fix:** assert every required check reads `success` explicitly. **Never infer from the
absence of `failure`.**

### B31. `deciding_rule_id` can name a rule that was never evaluated
**Found in:** T-0008, 2026-08-13, by Review's staleness audit. **Load-bearing, because
it has already inverted a committed document.**
**SCOPE RESTATED 2026-08-14 (T-0013): a second table now carries this field, and the
two DISAGREE.** `decision_records` gained `decided_by` + `deciding_rule_id`, and it
handles the same situation the opposite way:

```
shadow.py         deciding_rule_id or "GATE-036"   -> launders an absence into a citation
decision_records  deciding_rule_id = NO_RULE_DECIDED -> names the absence as an absence
```

**Two vocabularies for one quantity is B33's shape**, and here it is worse than cosmetic:
an audit joining the two tables on `deciding_rule_id` would count the shadow's absences
as GATE-036 firings and the live table's as a distinct sentinel. **Reconcile at the
cutover** — the live representation is the correct one, so the fix is to delete the
`or "GATE-036"` fallback rather than to teach the new table to imitate it.

**Deliberately NOT fixed in T-0013:** bundling it would have made that task's
discriminating mutation untestable in isolation.

**What it is:** `shadow.py:607` is `deciding = decision.deciding_rule_id or "GATE-036"`.
**(Line corrected 2026-08-14 by Review's staleness sweep — this entry said `:486`, which now
sits in an unrelated comment about correlate quorums. The FACT was still true and only the
POINTER had rotted, which is the harder case: an entry whose claim verifies and whose
citation does not lead anywhere is one an unlucky reader disproves.)**
So **GATE-036 is the fallback when no rule decided**, not a rule that fired.
`rule_id="GATE-036"` appears **zero** times as a rule evaluation anywhere in the source,
and **no shipped record carries one**. A record can therefore assert that GATE-036
decided while containing no evidence that it did, and a reader cannot distinguish
*"GATE-036 fired"* from *"nothing decided, this is the default."*

**The same label now means opposite things.** Before the panels were wired, GATE-036
appeared because GATE-008 and GATE-002 were hardcoded blocked — genuine blindness.
Now it appears because all four gates PASS and **no setup was in play**, which is the
rule's actual meaning (`gate_036_stand_aside.py`: *"STAND_ASIDE means no setup was in
play"*) and a market judgement rather than a data one. **Nothing in the record separates
those two cases**, and both have been read off the same field within a day —
`docs/CONFORMANCE_AUDIT_2026-08.md` built its central sentence on the first reading and
is corrected in place.

**What it could break — and this is why it ranks above the document error.** **Stage B's
gate 2 is "every abstention cites a rule id", and that gate is currently satisfiable by
the default.** An abstention citing a fallback is not an abstention citing a rule, so
the cutover's readiness criterion can be passed without ever being met. Same shape as
every criterion defect this week: a check whose success is indistinguishable from its
absence.

**Fix:** emit a real `GATE-036` rule evaluation when it is the decision — with its
reason, as every other rule does — or make the fallback explicit in the record
(`deciding_rule_id: null` plus a `no_rule_decided` marker). Either removes the
ambiguity; the second is honest about what happened and the first is more useful. Do
**not** rely on the label alone until one of them exists.

### B32. Nothing reports whether the shadow is recording, and it went dark for 40 minutes
**CLOSED 2026-08-14 (T-0009), deployed `9fe47ed42`.** `/api/system/data-health` now
carries a `shadow` section beside `dominance_collector` and `backups`. Read from
production immediately after the deploy:

```
status healthy   evaluation_state not_due   entry_tf 5m
expected_per_hour 24.0   age_bars 0.0   attests liveness_only
```

**The cadence is DERIVED** from `fixed_config.ENTRY_TF` through the existing
`_TF_SECONDS` map — `3600/300 × 2 symbols = 24`. **Mutation proved why that matters: a
hardcoded 1H figure reads the actual 40-minute outage as HEALTHY**, because 40 min is
under two 1H bars. The signal built to catch this outage would have missed it. That is
B21's class, caught by making it fail rather than by noticing it.

**Two honest limits, both stated in the payload rather than in a comment:**

* **It attests liveness, NOT correctness.** A shadow can be alive, writing every cycle,
  and grading a still-forming bar — a defect this project actually shipped on GATE-008's
  MAIN panel — with every field above green. `does_not_attest` names this so the first
  green reading cannot be cited as evidence the correlate layer is trustworthy.
* **When it fires it cannot say WHICH failure it is** — the loop turning with the
  evaluation raising, versus the loop not turning at all. `ambiguous_between` says so
  rather than implying it knows, and a `note` records that an active `engine_run` row
  means the run was never ENDED, not that the process is alive (**B14**).

**How long would the original outage have taken to notice?** Honestly: **at 5m, ten
minutes** — two bars — *and only if someone looked at the endpoint.* Nothing pages on
it; that was deliberately out of scope. So this converts an undetectable failure into a
detectable one, not into an announced one.

**The plan's own criteria 2 and 4 were invalidated before it was built**, by T-0010 four
hours later: the shadow now runs above the entry gates, so `already in a position` no
longer suppresses a record and the `blocked` state the plan centred on no longer exists.
**Recorded as a hazard of planning against a system under change, not as a defect in the
plan** — and the result is sharper than the plan could have specified, because a due bar
with no record now means broken outright rather than being drowned by position-holding.

**Found in:** T-0008, 2026-08-13, after a defect of mine stopped every shadow record
from validating.
**What it is:** `_shadow_evaluate` swallows every failure by design — `shadow.py:20`:
*"a shadow that can break the engine is worse than no shadow."* **That design is correct
and should not change.** Its consequence is that **a broken shadow is silent by
construction**: the engine trades normally, the api is healthy, the collector is
healthy, CI is green, and no record is written.

It happened. A schema-validation failure dropped every `setup_evaluation` for ~40
minutes while everything else read normal.

**Three agents explained the silence, three different ways, all wrong.** Execute said
"waiting on a 1H bar close"; Review said "no record since the pre-fix container's
output"; the Manager told Malek "waiting on the 22:00 bar". **None considered "the
shadow is crashing"**, despite the module documenting that failures are swallowed. A
silent failure was indistinguishable from a legitimate wait, and the wait was plausible
enough that each seat constructed its own version of it. That cost an hour and produced
a confident consensus.

**What it could break:** `data_health.py` has **no shadow section at all** — it watches
the dominance collector and nothing else. So the shadow can go dark indefinitely and
nothing reports it. **If that happened during the real Stage A window, the cutover's
evidence base would have a hole in it and no signal would exist** — a materially worse
version of tonight.

**Fix — CORRECTED 2026-08-13, because the first version of this remedy was wrong in
both halves.** It said: *cadence of one per closed bar per symbol, and stale means
dark.* **B34 disproves both.** The shadow records only on bars where the ICT path was
unblocked, so the expected cadence is **not** one per closed bar — and **stale usually
means blocked, not dark.** A signal built to that description would report the shadow
broken for most of every trading day, and **a liveness signal that is routinely wrong
launders the real outage into background noise.**

The correct shape is **three states, not two**: `due` / `not due` / `blocked`, with the
cadence derived from **flat bars** rather than bar closes, and `blocked` named as the
**common** case. Note that "not due" is its own state for a reason: at 1H the newest bar
is legitimately absent for 54 of every 60 minutes, and reading that as missing is an
error a person made here while proposing this very signal.

**Why this correction is filed rather than left to the plan:** T-0009's plan carries
the right version and will close; this entry outlives it. Whoever builds the signal in
six months reads **here**, and the stale remedy would reproduce the failure it
describes. That is B27's mechanism exactly — a superseded prescription in the entry
someone consults *while about to build the thing*. Same move as `expected_poll_seconds`
for the collector and `layout_size` for the grade — **convert an inference three agents
got wrong into a field with a number in it.**

### B33. The rule layer and the telemetry schema are two vocabularies with no translation point
**Found in:** T-0008, 2026-08-13, after the third divergence in one object in six
hours. **This entry is worth more than the three defects it generalises, because it
predicts the next one.**
**What it is:** `Disturbance.as_dict()` speaks the grader's vocabulary;
`correlate_state` in `TELEMETRY_SCHEMA.json` speaks the contract's. They disagree, and
**nothing sits between them.** Found one at a time, each only when it broke:

| the grader says | the schema requires |
|---|---|
| `asset` | `symbol` |
| *(no timeframe at all)* | `tf` |
| `observed_order_flow: NEUTRAL` | `BULLISH` / `BEARISH` / **`UNCLEAR`** |

**Every field is a separate opportunity to diverge, and every divergence is silent.**
`_shadow_evaluate` swallows validation failures by design — correctly, since a shadow
that can break the engine is worse than no shadow — so a mismatch drops the record and
nothing reports it. That is how the shadow went dark for ~40 minutes.

**The third one is the instructive one.** `asset`/`tf` were *missing keys*, which a
careful reader might spot. `NEUTRAL` is a **present key with an out-of-enum value**, so
**no key-presence check could ever find it** — and it fires on a routine market state,
whenever a panel shows no clear direction, and by construction for every missing panel
(`gate_002_disturbance.py:273`). With two of four panels absent for most of 2026-08-13,
the system was continuously in the condition that triggers it.

**And the trap for whoever fixes the next one:** `NEUTRAL` is **legal** in
`agreement_state` (`ALIGNED`/`NEUTRAL`/`DISTURBED`) and **illegal** in
`observed_order_flow`, in adjacent fields of the same object. A blanket rename fixes
one and corrupts the other.

**What it could break:** any field added to `correlate_state`, or any enum widened on
either side, diverges again — and the failure is another silent outage of the cutover's
evidence base. Ad-hoc translation at the point of breakage is not a fix; it is the
pattern.

**Fix:** **one translation point, with the schema as the authority.** A single mapping
layer between the rule layer's serialisation and the record's, so a new divergence is a
change in one place rather than a silent drop. Same shape as `correlate_denominator`
carrying its own provenance: make the contract visible at the boundary rather than
assumed across it.

**IT PREDICTED ITS OWN NEXT INSTANCE AND WAS RIGHT WITHIN HOURS — a fourth
divergence, at the same boundary, on the same day this entry was filed.** T-0007 set
`ENTRY_TF` to `5m` and the first bar evaluated failed the schema on
`correlates/states/*/tf`, `primitives/*/tf` and `timeframes/*`. The shadow went dark
again.

    data layer keys        ['1m','5m','15m','30m','1H','4H','D','W']   (lowercase minutes)
    schema timeframe enum  ['1M','3M','5M','15M','30M','1H','2H','4H','1D','1W','1MO']
    valid in BOTH          ['1H','4H']        <- only two; D and W are '1D'/'1W' in the schema
    ruled execution set    30M / 15M / 5M     <- NONE of them validate

**And the two that validate are both ANALYSIS-ONLY.** So: **every execution timeframe
the contract permits would have broken the shadow, and the only timeframes whose
telemetry validated were ones GATE-017 forbids trading on.** The platform's telemetry
was valid *because* the platform was non-compliant, and becoming compliant was
guaranteed to break it on the first bar — for any legal choice. Nobody could have
picked a value that worked.

Fixed with the single translation point this entry asked for (`shadow.schema_tf`),
applied wherever a timeframe enters a record. **A canonical rename would not do**:
fetching genuinely needs the lowercase form and recording genuinely needs the
uppercase one, in the same function, so a rename moves the failure rather than
removing it.

**The fix was itself incomplete on the first pass** — translating `correlates` and
`primitives` left `timeframes/*` failing — which is this entry's own "found one at a
time", applied to its own remedy.

**Meanwhile the guard is a test, and its scope matters.** `assert_valid` over *one*
record shape is a validator; over the reachable state space it is a guard. It now runs
across nine states — every grade, both directions, the USDT.D inversion, and every
degree of absence down to no panels at all — because `NEUTRAL` was caught only because
one fixture happened to produce it.

### B34. The shadow only records on bars where the ICT engine was NOT blocked
**Found in:** T-0008, 2026-08-13, by the Manager, chasing an absent record rather than
explaining it. **Bears on the cutover, not on T-0008.** Verified here from the source.

**THE ORDERING DEFECT IS FIXED — `51e0998`, 2026-08-14 01:18:58, *"Phase 1: the shadow now
sees every bar, including ones the engine could not trade."* ANNOTATED 2026-08-14 by Review,
during the T-0011 pre-review, because the entry still read as open and a plan had been
written on it.**

**THE TIMING IS THE LESSON, SO IT IS STATED BEFORE THE DETAIL. This entry was filed
2026-08-13 (T-0008) and was ACCURATE WHEN WRITTEN. It went stale about thirteen hours later,
by a commit from this same work stream.** Not an old entry nobody revisited — **an entry
invalidated overnight by our own next task.** So "check whether a cited entry is still
current" cannot be reserved for entries that look old: **the ones most likely to be stale are
the ones written most recently, because they describe the code we are actively changing.**
`B11` is the precedent — it *"went false within hours of being written"* — and this is the
second instance, which makes it the register's normal case rather than its exception.
Verified in pinned worktrees at both `d0b3f9b` and `ab7dc77`:

    :831   await self._shadow_evaluate(pair, entry)        <- now FIRST
    :837   block = await self._entry_block_reason(pair)
    :838   if block is not None: ... return

with a comment at the call site giving the reason for the placement. **The code block quoted
below is the OLD ordering and no longer exists at those line numbers.**

**What this does and does not close.** The shadow now evaluates blocked bars, so *"a blocked
bar produces neither a decision record nor a telemetry record"* is **false as of `51e0998`**,
and the four block reasons are **no longer the unemitted population**. What remains open is
narrower and still real: `_shadow_evaluate` returns without emitting when
`shadow.evaluate` yields `None` or when its single `except Exception` swallows one, and
**those bars are still invisible.** The population moved; it did not vanish.

**Consequence that made this worth annotating rather than rewriting:** T-0011's plan cites
*"already in a position"* as *"the common one, and **B34's exact population**"* and builds its
omission taxonomy on the four block reasons. **That taxonomy is aimed at bars the shadow now
evaluates.** A stale entry produced a plan pointed at the wrong population — the same failure
as `B11`, which is why that one was rewritten rather than annotated.

**What it WAS:** `crypto_loop.py:802-813`. The entry-gate check returned **before** the
shadow was called:

```
:802   block = await self._entry_block_reason(pair)
:803   if block is not None:
:806       await self._act(kind, f"... {block}, skipped")
:807       return                                  <- returns here
:813   await self._shadow_evaluate(pair, entry)    <- never reached
```

The block reasons are `KILL SWITCH ARMED`, `engine paused`, **`already in a
position`**, and **`max concurrent N reached`** (`:353-359`). So a blocked bar produces
**neither a decision record nor a telemetry record** — it exists only in the activity
log.

**THREE CONSEQUENCES, IN SEVERITY ORDER.**

**1. The declared emission policy is false, and it is stamped on every record.**
`shadow.py:214` declares `emission_policy_id="every-closed-bar-roster-v1"`. The
implementation emits on *every closed bar where the ICT engine was not blocked*.
Declared parameters exist so our choices can be audited as ours — **a declared
parameter that misdescribes the behaviour is worse than a missing one**, because it is
carried on every record and looks authoritative.

**2. The sample is biased, and the bias runs exactly the wrong way.** The engine
self-fills within seconds of a restart and holds until TP, SL or an operator, so
`already in a position` is its normal state. **The shadow therefore systematically
excludes the bars immediately following an ICT entry — precisely the bars on which the
two strategies would most differ.** Measured on 2026-08-13: entries at 19:00 UTC, then
no telemetry record for the 21:00 or 22:00 bars while the engine ran and skipped. Bars
`05:00`–`10:00` NY have no records at all.

**3. M9 Stage A's gate is denominated in this.** *"20 trading days or 300 evaluations
per symbol"* accrues only on flat bars, so the count is both slower than it appears and
**not a random sample of market conditions**. A conformance number computed over that
window measures agreement on the subset of bars where the ICT engine happened to have
nothing open.

**What is NOT true, checked rather than assumed:** T-0007's move to 5M does not worsen
the ratio. Flatness is time-based, so 12× the bars yields 12× the recorded evaluations
*and* 12× the skipped ones — **5M improves the rate and leaves the bias untouched.**
Recorded because it is the natural wrong inference.

**Interaction with B32, and it changes that design:** a shadow that legitimately
records nothing for three hours while a position is held is **indistinguishable from a
dead one** under a naive cadence check. The liveness signal must derive its expected
cadence from **flat bars**, not from bar closes.

**Fix:** move the shadow call above the entry-gate return, beside the bar-consumed
marking. The comment at `:808-812` already argues the shadow belongs before the ICT
evaluation for side-effect safety; the same reasoning puts it before the gates. **One
line — and it changes what is recorded on live bars, so it is a plan and not a
drive-by.**

### B35. GATE-007 asserts "same timeframe" by comparing LABELS, never times
**Found in:** T-0008, 2026-08-13, under the partial-bar defect. **This is the hole
that defect fell through, and it predicts the next one.**
**What it is:** `gate_008_roster.py:133-140` is `tfs = sorted({r.tf for r in reads})`
and fails only if more than one distinct **string** appears. `check()` at `:124-125`
is `alignment_tf == signal_tf`. Both are label comparisons, and **nothing anywhere
compares the panels' last-bar timestamps.**

So four panels labelled `1H` with last bars at **22:00, 22:00, 21:00, 21:00** pass
GATE-007 while being an hour out of step in content. That is not hypothetical — it is
what production ran until `drop_partial` was added to the perpetual source: the
dominance panels dropped their still-forming bar and the perpetuals did not.

**Why it is worse than the defect it hid.** The missing `drop_partial` was one
source's convention. **This is the rule that was supposed to catch any such
divergence and cannot.** Any future panel source with a different partial-bar
convention — a venue stamping bars at close rather than open, a feed with a reporting
lag — diverges again, silently, and GATE-007 reports the layout aligned.

**And it defeated the one check designed to be discriminating.** Criterion 4c —
three rounds of design between two agents, explicitly *"the reading that can differ"*
— asks **which** panels, **what** label, and **how thick**. It never asks **which
bar**:

```
panels_missing []      correct
alignment_tf   ['1H']  correct — the label matches
thin_panels    []      correct — exchange bars carry no sample count, so the check skips them
```

Green, over a lookahead in the **MAIN** panel. Lookahead is the single defect class
this project exists to prevent, with three regression tests for it on the entry path
and none on the correlate path.

**Fix:** a GATE-007 successor comparing last-bar **times** — the shape being all four
panels ending on the same closed bar. That is a rule change and needs a plan, not a
patch.

**Related asymmetry, recorded so it is not mistaken for an absence:** `data_health`
monitors recency for TOTAL and USDT.D via `COLLECTOR_STALE_MIN`/`age_minutes`. The two
perpetual panels added in T-0008 have **no recency monitoring at all**. Two of four
panels are watched. ~~Fold into whichever task next touches `data_health`.~~

> **OWNER: T-0015, assigned by id 2026-08-14.** The ticket already existed when this was
> annotated *"needs a task id"* — created hours earlier from **T-0009's criterion 10**, which
> deferred the same gap in the same words. **So the gap was described in two places, one with a
> ticket and one with a dead predicate, and nothing connected them.** That is this entry's own
> defect one level up: not a missing owner, but an owner nothing pointed to.
>
> **And Review's formulation of why the predicate form fails is better than the one recorded in
> B42, so it supersedes it:** `data_health.py` was touched **twice** today, both by T-0009 —
> `9fe47ed` and `20b8593` — and neither added the monitoring. T-0009 built the *adjacent*
> liveness signal in the *same file*. **So the predicate did not fail to find an owner; it found
> the right owner twice and slid off. A predicate deferral is weak not because matching is
> unlikely, but because MATCHING PRODUCES NO NOTIFICATION.**

**THE PREDICATE ALREADY FIRED — TWICE, AND BOTH TIMES WERE MISSED. Found 2026-08-14 by
Review, sweeping for the deferral class B42 established.** `data_health.py` has been
touched twice since this was written:

    9fe47ed  2026-08-14  T-0009: a liveness signal for the shadow (B32)
    20b8593  2026-08-14  T-0009 follow-up: density prorated to the window

**Neither added recency monitoring for the two perpetual panels**, and nothing reported
that the deferral had come due. **This is the fourth instance of `DEFER BY TASK ID, NEVER
BY PREDICATE`** (B42, T-0015, and B42's third), and the sharpest, because the task that
satisfied the predicate is the one that built the *adjacent* monitoring in the same file —
**the deferral was passed over by the only task that was ever going to be well placed to
honour it.**

**And it is not cosmetic, because `B40` changed what this costs.** The correlate margin
fell from 18× to 1.5× when `ENTRY_TF` went to 5m, so **a 5m panel carries 30 samples
against a minimum of 20** and collector reliability stopped being a comfort. B40 states
that *"nothing watches whether the panels are thick enough"* — and **two of the four have
no recency monitoring at all**, so for half the roster there is not even a staleness signal
underneath the missing thickness one. **Needs a task id.** Related: **B40**, **B42**,
**B32**, **B34**.

**RECENCY TAIL CLOSED — T-0015, 2026-08-15.** `data_health.panel_health()` now reports
per-panel recency for all four roster panels, `BTCUSDT.P` and `ETHUSDT.P` included, and
`data_health()` carries it as its own `correlate_panels` component. **B35's GATE-007
label-comparison finding above is UNCHANGED and still open** — this closes the tail about
unmonitored panels, not the head about how alignment is asserted.

**The threshold is DERIVED and the reference point is written down**, because both were
ways to ship this and measure nothing:

    threshold   PANEL_STALE_BARS = 2.0 bar-periods, from ENTRY_TF via _TF_SECONDS
    reference   the bar's CLOSE (label + one interval), not its label

`COLLECTOR_STALE_MIN = 5.0` is correct for a process polling every 10 s and would have
been catastrophic here: with `drop_partial=True` the newest complete bar's LABEL reaches
**9.9 minutes** old in healthy operation before the next one closes, so a 5-minute
label-referenced threshold alarms on essentially every cycle. An alarm that fires every
cycle gets muted, and a muted alarm is the silence this monitor exists to end.

**And the coupling is recorded as a coupling.** The panels are read at `signal_tf`, a
parameter that `crypto_loop` happens to feed from `ENTRY_TF`; they coincide by PLUMBING,
not by definition. `data_health` has no access to a per-panel timeframe, so the config
constant is the only option available — and if `signal_tf` ever diverges this monitor
measures against the wrong interval and goes silently wrong in the direction that never
alarms. Stated in the payload as `scope.timeframe_coupling`.

**THE HONEST RESIDUE: NOTHING CONSULTS THE FIELD.** It is reachable at
`GET /api/system/data-health` and no code reads it — nothing alerts, nothing refuses to
grade, nothing blocks a trade. That was deliberate (acting on the signal is out of
T-0015's scope, and making GATE-008 fail on stale panels would be a live behaviour
change), and it is **the same gap B32 recorded for the shadow**: a monitor that ships and
is never read is B41's shape one layer down. The payload says so about itself, in
`scope.does_not_attest`. Related: **B40**, **B32**, **B41**.

### B36. Broad exception handlers make a bug indistinguishable from an outage
**Found in:** T-0008, 2026-08-13. Partially fixed; the general case is not.
**What it is:** the shadow path swallows exceptions by design — *"a shadow that can
break the engine is worse than no shadow"* — and that design is correct. Its
consequence is that **the handler cannot tell a code defect from an unavailable
dependency, and reports both as the latter.**

Concretely: `_FakePerp`'s signature drifted from `BinancePerpetualSource`, so the call
raised `TypeError`. The broad handler caught it and recorded *"perpetual panels
unreadable"* — **exactly what a dead `fapi` host produces.**

**Why that is worse than the swallow it sits under.** A dead host is *expected*: it
yields `GATE-008 FAIL` naming the absent panels, which is a normal absent-panel day
that nobody investigates. **So a programming error is not merely hidden — it is
disguised as a routine, already-understood condition.** The shadow outage earlier the
same evening was at least anomalous; this would have looked ordinary.

**Partially fixed:** `TypeError` is now caught separately in `_read_panels` and named
as an interface error rather than an availability one. Still swallowed — it must be —
but no longer disguised.

**Not fixed, and this is the entry:** every other broad `except Exception` on the
shadow path has the same property. The handler should distinguish the exception
classes it is *willing* to treat as availability — transport errors, timeouts, empty
responses — from those that mean the code is wrong, which must surface loudly even
though they may never raise into the trading path.

**Related:** B32 proposes a liveness signal for the shadow going silent. This is the
other half — the shadow **speaking**, and saying the wrong thing about why.

### B38. GATE-018 is OPEN — 5M was forced by our collector, not settled by the corpus
**Found in:** T-0007, 2026-08-14. **Recorded so a running choice does not become a
ruling.**
**What it is:** the execution-timeframe conflict is **Salim's to settle and this task
did not settle it.** The registry marks GATE-018 OPEN, and the schema says so in its
own words — *"1M and 3M are present ONLY because the workspace documents execution on
them while the ruling excludes them."* The trader's bracketed charts are **6 trades on
1M and 2 on 3M against zero on 30M**; the declared set is `{30M, 15M, 5M}`.

**Why 5M, stated as the contingent engineering fact it is:** **1M is unavailable at any
polling rate the collector currently permits.** At 10 s a 1M bar holds 6 samples against
`MIN_SAMPLES_PER_SYNTHETIC_BAR = 20`, and `collect_dominance.py:453` enforces
`interval = max(10, …)` — a hard floor. **If the collector ever polls fast enough, the
question reopens exactly as it stands.** 3 s would do it.

**THE DECLARED PARAMETER, narrowly:** *we chose the highest-margin member of the
trader's declared execution set.* That is a choice and it is ours. **We did NOT resolve
which side of GATE-018 is right**, and nothing produced by running on 5M is evidence
about that.

**What it could break:** "we ran 5M for six months without trouble" becoming evidence
that the declared set won. It is not evidence — it is the consequence of a sampling
floor in a collector nobody chose for this purpose. **Do not let duration launder a
constraint into a ruling.**

### B39. A conditional edit that matches nothing succeeds, and the claim survives it
**Found in:** T-0007, 2026-08-14. **The one instance of this family fixable by tool
choice rather than by attention.**
**What it is:** an edit guarded by `if old in s:` — or any `sed`-style substitution —
**succeeds vacuously when its target is absent.** The file is unchanged, the exit code
is 0, and nothing distinguishes "replaced" from "found nothing to replace".

It happened: an edit meant to close A10's GATE-017 row targeted a string that lives in
`docs/CONFORMANCE_AUDIT_2026-08.md`, not in `KNOWN_ISSUES.md`. The guard skipped, the
commit landed, and **the commit message asserted "A10's GATE-017 row is CLOSED"** — of
a row still reading `violated`. It was then **reported as done to both peers.**

**That is worse than a silent failure staying silent: it is a silent failure being
actively converted into a positive claim, twice.** "It no-oped" undersells it.

**Why this one is cheap to close.** Every other instance this week required a
*different reading* to discriminate — `git status` versus `git log origin/main..main`,
bar time versus write time, `correlate_denominator` versus `disturbed_count`, the
schema versus a key list. **This one requires no new reading at all**, only an edit
primitive that raises when its target is absent. `assert old in s` before every
replacement; an editing tool that errors on a missing match is safe by construction.

**The read side is the same defect and is NOT closed by that fix.** A `grep` or
`sed -n` that matches nothing also exits successfully and prints nothing, and an empty
result has been read as a finding at least three times this week — a column that did
not exist, a schema set typed from memory rather than read, and a bar treated as
missing when it was not yet due. **On the write side an empty match changes nothing
and claims something; on the read side it returns nothing and is believed.**

**Fix:** assert-then-replace on every scripted edit, and for reads, distinguish "the
pattern is absent" from "the file/table/window is absent" before drawing a conclusion
from an empty result.

### B40. The correlate margin fell from 18x to 1.5x, and nothing fails when it shrinks
**Found in:** T-0007, 2026-08-14, by Review, carried into the verdict because no other
artifact would hold it. **A consequence of a correct change, not a defect in it.**
**What it is:** at 1H a correlate bar held **360 samples** against
`MIN_SAMPLES_PER_SYNTHETIC_BAR = 20` — **18x margin**. At 5m it holds **30**. That is
**1.5x**, and it is the operating margin from now on.

> **OWNER: T-0015, assigned by id 2026-08-14 — this entry had none.** It cited only T-0007, the
> task that found it, and *"nothing fails when it shrinks"* had no ticket for eleven hours.
>
> **Paired with B35's tail deliberately, and the two must stay SEPARATE FIELDS in one task.**
> Both ask *"does anything watch this panel property"*, both live in `data_health`, and half the
> roster is unmonitored on **both** axes: `BTCUSDT.P` and `ETHUSDT.P` carry
> `bar_sample_count = None` by construction, so they are structurally invisible to the `thin`
> check *and* have no recency monitoring. **Thickness and recency are orthogonal — density
> within a bar versus currency of the newest bar — and merging them yields one output meaning
> two things**, which T-0015's criterion 6 already forbids. One task, two fields, no shared
> verdict.

**Losing a third of a bar's samples makes the layout ungradeable.** At 10 s polling a
5m bar needs 20 of its 30 ticks; ten missed polls in five minutes takes GATE-007 to
FAIL. At 1H the equivalent required losing 340 of 360.

**Why it needs writing down: nothing fails when the margin shrinks.** There is no
alarm, no threshold, no degraded state. The layout simply stops grading — GATE-007
FAILs, GATE-002 goes NOT_APPLICABLE, the engine stands aside — and **that is
indistinguishable from a market with no setup.** It fails **later, intermittently, and
looking like a market condition**, which is the hardest shape to attribute.

**What changed beyond the number:** collector reliability was a comfort and is now a
**precondition**. Before T-0007 a collector hiccup cost nothing observable; now it
silently removes the correlate layer for that bar. **B32's liveness signal watches
whether the shadow is *recording*; nothing watches whether the panels are *thick
enough*** — and B35 records that GATE-007 asserts alignment by label, so it will not
tell you either.

**Fix:** report the margin as a number rather than discovering it as a verdict — the
per-panel sample counts already exist in the record (`thin_panels` is derived from
them). Surfacing "30 of 20 required" beside the grade turns a cliff into a gauge.
Related: **B34** means a thin bar on a blocked bar is invisible twice over.

**FIXED AS SPECIFIED — T-0015, 2026-08-15. The margin is a gauge, not a verdict.**
`panel_health()` reports per panel `samples`, `minimum`, and **`margin`** as a ratio, so
`30 of 20` reads as `1.5` and a figure trending toward `1.0` is visible before it becomes
a cliff. A boolean could not have said that.

**Reported on a SEPARATE axis from recency, and that separation is load-bearing rather
than tidy.** Thickness is observations WITHIN a bar (density); recency is how long ago the
newest bar closed (currency). A perfectly thick bar from six hours ago passes one and
fails the other. **And either can MANUFACTURE the other**: filtering thin bars out leaves
the newest-bar pointer on an older thick bar (**B27**), which turns a density problem into
a currency one. So the recency read takes the UNFILTERED frame, and
`test_thin_recent_bars_do_not_manufacture_staleness` pins it with a frame that is thin at
the tip and thick behind it — a uniformly thin fixture cannot catch this, because the
filter empties the frame and any implementation falls back.

**Criterion 6's question — does GATE-007's existing `thin` list already cover this? —
answered NO, and structurally.** `gate_008_roster.py` builds `thin` only `if
bar_sample_count is not None`, and the perpetual panels never set it: an exchange bar is a
candle, not a resampling of point observations. **The two panels this work exists for are
excluded from `thin` by the condition itself** — not partially covered, invisible. So
`panel_health` answers `not_applicable` with that reason rather than letting them fall out
of the check silently, which is how the gap survived.

**Same residue as B35: nothing reads the field.** Related: **B35**, **B27**, **B32**.

### B8. The delivered contract artefacts are mutually incompatible — BLOCKED ON SALIM
**Found in:** M1 (implementing the telemetry layer)
**What it is:** `TELEMETRY_SCHEMA.json` hard-pins `engine.rule_registry_version` with
`"const": "1.1.0"`, while the delivered `RULE_REGISTRY.json` ships as **1.2.0** — the
version the corpus triage produced when it cleared all 8 DEFECT rules and moved 20 rules
from OPEN to READY.
**Why it matters:** no record emitted against the real registry can ever validate against
the delivered schema. This is not the stale-prose problem in
`MAGIC_STRATEGY_INTEGRATION.md` §2.1 — that one misleads a reader; this one blocks emission.
**What we did instead of picking a side:** records keep stamping the TRUE versions. Writing
`1.1.0` while running 1.2.0 would make stored evidence claim a registry it was never
evaluated against, which defeats the only purpose of the field. The validator relaxes
exactly the two version `const`s and nothing else, and
`contract_loader.contract_version_skew()` reports the mismatch so it cannot pass silently.
**How it ends:** Salim ships a schema regenerated against registry 1.2.0.
`test_the_delivered_artefacts_are_mutually_incompatible_and_we_say_so` FAILS at that point
— deliberately — which is the prompt to delete the relaxation in `validate.py`.


### B1. Failures are visible but nothing tells you unprompted
**Found in:** I4 / 4.1; **narrowed by B1's monitoring work**
**What is now done:** `/api/system/data-health` and a dashboard panel report the
dominance collector, backups, and the CFT bridge session. A component the
backend cannot read reports `unavailable`, never `healthy`, so silence is never
mistaken for health. The collector also self-reports density over the last hour
rather than lifetime, so a recent death cannot hide behind a good long-run
average.
**What remains:** all of it is PULL. You have to open the dashboard. If nobody
looks for three days and the collector died on day one, three days of
dominance history are still gone — and that data cannot be backfilled.
**Why it was not finished:** pushing a notification needs a destination —
email (SMTP is a dependency but unconfigured), Telegram, a webhook. That is a
choice about where you want to be interrupted, not a code decision.
**Fix:** pick a channel, then alert on `data-health.ok == false` and on repeated
bridge failures. The detection already exists; only delivery is missing.

### E4. The economic calendar is the wrong source, not merely unconfigured
**Restated 2026-08-08** after checking GATE-015 in registry v1.2.0. The entry used
to read "no FINNHUB_API_KEY". That understated it: a Finnhub key would produce a
working integration that still fails the gate.
**What it is:** GATE-015 (READY, HARD_GATE) names the source — **Forex Factory
RED FOLDERS ONLY**, currencies USD (optionally EUR/GBP for crypto), and the
calendar's timezone **set to New York local** so its timestamps and the chart's
agree. We implemented Finnhub, which is a different provider with different
impact classification and no red-folder concept.
**Why it matters:** three HARD_GATEs depend on it — GATE-012 (no new entry within
15 minutes BEFORE a red-folder event), GATE-013 (none for 30 minutes after, AND
then wait for the first complete M15 candle to close — both conditions, not
either), GATE-015 itself. Until the ruled source is wired, those three can only
ever be NEVER_EVALUATED, which is readiness gate 5's blocking condition.
**Worth carrying into the implementation:** GATE-012's note records that the
15 / 30 / M15 constants appear in no workspace page and in none of the 1,258
images — they are trader-authorised engine constants, not recovered doctrine, and
should be emitted as declared parameters even though the rule is READY.
**Fix:** a Forex Factory red-folder source with New York timestamps. Then delete
the Finnhub client rather than leaving it as a selectable fallback — a second
calendar is a second answer to "was there news", and the gates cannot cite two.

### B3. Deploys are identifiable but not reproducible
**Found in:** I6. Narrowed after B3/I6 — the "nobody can tell" half is fixed and
deployed: both containers record the resolved SHA and `/api/system/version`
serves it. Verified in production on `9a383d907`, api and web matching.
**What remains:** `GIT_REF` defaults to `main`, so recreating a container
tomorrow gets a different commit. The deploy is now honest about this
(`pinned: false`) rather than silently floating, but honest is not the same as
reproducible.
**Why it matters:** a rollback still means finding the previous SHA by hand, and
recreating one container and not the other can still put the two halves on
different code — it is now *detectable* rather than prevented.
**EXTENDED 2026-08-14 — the floating ref couples unrelated decisions, and that is
sharper than the reproducibility problem above.** Read from the running container's
actual start command rather than inferred:

```sh
if [ ! -f /app/.ready ]; then
  git fetch --depth 1 origin "${GIT_REF:-main}"     # <- unpinned
  cp -a /tmp/src/backend/. /app/ ; rev-parse HEAD > /app/.build-sha
  pip install ; touch /app/.ready
fi
python deploy_migrate.py ; exec uvicorn ...
```

**The reassuring half, which was not written down anywhere and matters:** `/app` is
**not** a bind mount and `/app/.ready` lives in the container's writable layer, so a
host reboot, a daemon restart, an OOM kill or any `unless-stopped` auto-restart
**skips the clone block entirely** and keeps the running code. Passive events cannot
change the deployed version. **Only a deliberate `--force-recreate` (or `rm` + `up`)
re-clones.**

**The hazard half: a recreate ships `main` HEAD *in full*, whatever is on it at that
moment.** So any maintenance that requires recreating the api silently performs a code
deploy of everything merged since the last one. **This is live right now:** the pending
owner-only `DOMINANCE_DATA_DIR` → `DOMINANCE_DIR` compose fix requires a recreate, and
performing it would ship whatever is on `main` — currently including code the owner has
not ruled on. **Two independent decisions, one of which quietly executes the other.**

**Fix:** set `GIT_REF` to a full 40-char SHA in the VPS compose as part of
releasing, so a deploy is a deliberate act. Fetch-by-SHA and rollback to an
older SHA are both verified working against GitHub. **Until then, `GIT_REF` is also the
decoupling tool:** recreate with `GIT_REF=<current sha>` to perform compose maintenance
without shipping code, then deploy as its own act.

---

## C. Drift — the repo and the server disagree

*Empty as of 2026-08-04.* All four entries here (C1 the api's inline pip list,
C2 `--no-frozen-lockfile`, C3 the hand-copied collector, C4 no way to detect any
of it) are closed, and `scripts/check_deploy_drift.py` reports all seven
deployed services matching their committed description.

The category is kept rather than deleted because it will come back — every entry
above appeared the same way, by someone editing the server without the repo.
Run the check after a deploy; anything it reports belongs here.

---

## D. Production hygiene

### D5. Backups are on the same host as the database
**Found in:** D1 (recorded when backups were built)
**What it is:** verified daily backups now run, but they live in
`~/tradingai-backups/` on the same VPS as the database they protect.
**Why it matters:** they cover database corruption, a dropped table, a bad
migration, a deleted Docker volume — not loss of the machine. If the VPS goes
away, the backups go with it, including the unrecoverable dominance history.
**Why it was left:** off-site copies need a destination and credentials for it,
which is a decision (and a cost) rather than a code change.
**Fix:** sync `~/tradingai-backups/` to object storage or another host. The
directory is small — ~2 MB per run, so a year is under 1 GB.

### D2. The site is still plain HTTP — blocked on a DNS record
**Found in:** I10; **token half done 2026-08-04**
**Done:** both secrets rotated — the API token and the CFT bridge token, the
latter because it leaked into a chat transcript through an unredacted diff. The
old API token is confirmed revoked (401).
**Still open:** traffic is unencrypted, so the bearer token crosses the network
readable on every request.
**What blocks it:** a certificate needs a hostname. The app is reached at
`http://31.97.183.142:8095`, and Let's Encrypt will not issue for a bare IP.
Everything else is already in place — the host runs nginx with certbot and
serves ~8 domains this way (`aasp-mvp.aminereg.com`, `app.harbyx.com`,
`cal.evidenss.ai` …), so this is one vhost away once a name exists.
**What is needed from you:** point a hostname (e.g. `tradingai.aminereg.com`) at
`31.97.183.142` with an A record. Then it is one nginx site plus
`certbot --nginx -d <host>`, and the app moves to https with the token no longer
travelling in clear.
**Interim:** the token is fresh and single-use-by-you; the exposure is passive
network observation between you and the VPS.

### D7. One shared, non-expiring token is the entire auth model
**Found in:** D2 follow-up (asked whether the token ever changes — it does not)
**What it is:** `API_AUTH_TOKEN` is a static string in the VPS compose file,
read at container start. It has no expiry and no rotation schedule, and it
survives restarts, redeploys and recreates. It changes only when a human edits
that file.
**Why it matters:** three separate consequences, none urgent on a small trusted
team, all of which get worse the moment real money is involved.
  * A leak is permanent until someone notices and rotates by hand. There is no
    backstop — which is exactly why the D2 rotation had to be done manually.
  * It is one token for every person, not a login. There is no way to revoke one
    person's access; rotating locks everyone out and everyone must re-fetch.
  * Nothing is attributable. Every action through the dashboard is "whoever held
    the token", so the audit log cannot answer who placed an order.
**Why it is fine for now:** the platform places no real orders (the CFT bridge
still reports `trading_enabled: false`) and the team is three people.
**Fix when it stops being fine:** per-user credentials with an expiry, so the
audit log names a person and access can be withdrawn individually. Worth doing
before the bridge write-guard is ever unlocked, not after.


### D3. Nothing stops a broken merge — BLOCKED ON ADMIN ACCESS
**Found in:** I2 (CI)
**What it is:** CI runs on every push, but `main` has no branch protection.
**Why it matters:** a red build can be merged anyway; the robot reports and is
ignored.
**State:** the fix is written and tested as far as it can be —
`scripts/enable_branch_protection.sh`. It verifies the four required check names
against a real workflow run before applying, because a required check that no job
reports makes `main` permanently unmergeable with no visible cause.
**Blocked on:** the `Docz2868` token has `push`, not `admin`, and this endpoint
needs admin. GitHub reports that as `404 Not Found`, not `403`. Someone with the
Admin role on `Amineregayeg/tradingai` must run the script.
**Note before running it:** required checks apply to direct pushes too, so
`git push origin main` starts being rejected and all work moves to PRs. That is
intended, and it is the whole cost.

---

## E. Test coverage gaps

### E1. The live entry brain has no causality test
**Found in:** I2 (guard verification)
**What it is:** `strategy_step.py` carries the same born+2 lookahead guard as
the backtest, but no test exercises it, so `verify_guards.sh` cannot probe it.
**Why it matters:** **that is the code path that actually trades.** Its guard is
the only unverified one.
**Fix:** add `test_live_step_causality.py` asserting `evaluate_latest_bar` never
returns a Signal whose entry equals the deciding bar's own high/low, then add a
probe for it.

### E2. Seven pre-existing lint errors keep lint advisory
**Found in:** I2
**What it is:** 6 `no-explicit-any` plus one `react-hooks/exhaustive-deps`, so
the CI lint job runs with `continue-on-error: true`.
**Why it matters:** an advisory check is one people learn to ignore.
**Fix:** clear the seven, then flip `continue-on-error` to false.

---

## F. Known-minor (documented, low impact)

### F8. The local dev environment runs node 24, production runs node 20
**Found in:** B7
**What it is:** `scripts/dev_env.sh` uses whatever node is installed. This box
has v24.16.0; CI and the `web` container pin node 20.
**Why it matters:** vitest and `tsc` are unaffected in practice, but a local
`pnpm build` succeeding is NOT evidence the production build works — a
node-version-sensitive build failure would only appear in CI. DEVELOPING.md says
so explicitly, so the risk is someone trusting a local build anyway.
**Fix:** install node 20 (nvm/fnm) for parity, or leave it and keep treating CI
as the authority on `pnpm build`. Low impact either way.

### F1. 1-minute dominance bars are degenerate — **see B16, which supersedes this**
**Found in:** I4. **Corrected 2026-08-12:** both of this entry's stated reasons
were still describing 60 s polling, which production left on 2026-08-10.

It read: "At 60s polling a 1m bar holds one observation, so O=H=L=C … Drop
`--loop` to ~15s if 1m bars are ever wanted." At the deployed `--loop 10`
(`deploy/compose.dominance.yaml`) a 1m bar holds **6** observations, not one, so
it is no longer O=H=L=C — and "drop to ~15s" is now a **slowdown** that would
make it 4. The remedy was also never sufficient: the binding threshold is
`MIN_SAMPLES_PER_SYNTHETIC_BAR = 20` (`gate_008_roster.py:158`), which 15 s never
reached either. Clearing 20 on a 1m bar needs 3 s polling, and
`collect_dominance.py:453` is `interval = max(10, int(args.loop))` — a hard 10 s
floor, so it is unreachable without changing that line.

**The conclusion still holds; every reason given for it was false.** That is the
worst state for a register entry — correct, so nobody rechecks it, and wrong in
each detail a reader would act on. Kept rather than deleted because the
degeneracy is real, but the live arithmetic and the decision it collides with
now live in **B16**, and only there. Do not restate them here; two copies of a
number is how these diverged.

### F2. 245 pre-fix replay rows remain in the production database
**Found in:** I5. Now excluded from performance views and labelled in the
Journal, but they average +0.081R from the discredited lookahead engine. Leave,
regenerate, or delete — a data decision.
**Confirmed exactly 2026-08-13 (T-0002):** `setup_tag = 'Backtest replay'`, **245
rows, avg `0.0807R`** — the entry's figure holds to three decimals two weeks on,
which is worth recording in a register that produced five stale numbers this
week. They are cleanly separable by `setup_tag`, and the genuine live population
beside them is **7 trades**.

### F6. No close is labelled — every consumer must reconstruct it from price
**Found in:** T-0002, 2026-08-13.
**What it is:** nothing records *why* a position closed. `_persist_and_resolve`
writes only `realized_r`, `gap_r` and `outcome`, and `outcome` is derived purely
from the sign of pnl — `WIN if pnl > 1e-9 else LOSS if pnl < -1e-9 else
BREAKEVEN`. A take-profit, a stop-out and an operator close produce **three
identical records**.

**The information is not missing — the label is.** All seven live trades were
reconstructed unambiguously by matching `trades.exit_price` against the
`signal_sl` / `signal_tp` on the matching decision: three landed on the stop to
the cent, two on the target, two on neither (both at the T-0004 operator stop).
Corroborated by a second signature — `gap_r ≈ 0` occurs on exactly the two
take-profits and nowhere else, because `realized_r` can equal `expected_r` only
at target.

**What it could break:** every consumer must perform that reconstruction or be
wrong, and none of them documents doing it — including the feedback loop, which
reads `gap_r` and cannot distinguish "missed its target" from "a human stopped
the engine". Two of the seven trades are operator closes, so **28% of the live
corpus is not evidence about the strategy in either direction**, and nothing in
the schema says so.

**And the failure path is better instrumented than the success path:**
`reconcile_abandoned_decisions` writes a sentence for an abandoned position —
*"the engine stopped while this position was open… Not a loss — an absence."* The
only close this platform explains is the one that should never happen.

**Two things that make the reconstruction fragile, not just tedious:**

* **There is no foreign key between `decision_records` and `trades`.** The only
  FKs into `trades` are from `screenshots`, `checklists` and `orders`. So the
  linkage is a temporal join — five seconds, in this audit — which resolved 1:1
  on a 7-trade corpus and is the first thing to break at higher trade frequency.
  The schema declines to express the relationship as well as the reason.
* **The seven live trades carry no `sl` and no `tp` on their `trades` rows** (0 of
  7; the 245 replay rows have `sl`, and *no* row anywhere has ever had a `tp`).
  Anyone reconstructing from `trades` alone finds nothing and concludes the
  information does not exist. It does — on `decision_records`. Both an auditor and
  a reviewer reached the wrong conclusion here before checking the other table.

**Fix:** a `close_reason` on the close write, set where the close is decided
rather than inferred afterwards, and a real key between the decision and the
trade it produced. Cheap now, and it retires a reconstruction that currently has
to be re-derived by every reader — correctly, from two tables, with a join that
happens to be unique today.

### F3. Decision-record commit-window race
**Found in:** inherited (residual #5). A manual/kill close during the ~ms commit
of a just-opened decision can orphan it as `OUTCOME_OPEN`. Audit data only.

### F4. `/positions/demo` pair collision
**Found in:** inherited (residual #6). The dev seed endpoint can resolve the
wrong decision if the loop holds the same pair. Authed dev endpoint.

### F5. `status()` DB-down fallback switches balance source
**Found in:** inherited (residual #4). Cosmetic; only on the DB-unreachable path.

### F7. The CFT connection does not pin an account id
**Found in:** 4.2. `account_id` is empty on the stored connection, so the bridge
uses whichever account CFT currently has selected. Fine with one account;
ambiguous the moment there are several (the adapter's own docstring cites two —
`365105` for a 5k challenge, `373010` for a 2.5k instant). Balances would then
be read from whichever CFT last selected, with nothing in our UI showing which.
**Fix:** set `account_id` on the connection once the intended account is chosen.

---

## G. External / not ours to fix

### G1. The CFT integration is a workaround, not an integration
**Found in:** 4.1
**What it is:** CFT is behind Cloudflare bot protection that fingerprints the
TLS handshake, so no plain-HTTP client can reach it regardless of credentials.
We drive their web terminal with a real browser instead.
**Why it matters:** it breaks if CFT redesigns their login page or tightens
detection. It also means a permanent Chromium process beside the app.
**Fix:** ask CFT to allowlist the server IP (`31.97.183.142`) or expose a
documented API. Then the browser can be deleted entirely and the adapter becomes
ordinary HTTP. No longer urgent — but still the durable answer.

### G2. Docker-group access is root-equivalent
**Found in:** 4.1 deployment
**What it is:** the `deploy` user cannot write `/docker/tradingai` directly but
can mount it into a container running as root. This is inherent to Docker group
membership, not a misconfiguration.
**Why it matters:** it makes task I9 (root access) much less urgent, but that
login should be protected as if it were root — because it is.
