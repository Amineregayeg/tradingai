# Known issues — open problems register

Problems found while building, **not yet fixed**. Solved issues are not listed
(they are in git history). Each entry says what it is, where it came from, and
what it could break.

Ordered by what would hurt most, not by how hard it is to fix.

Last updated: 2026-08-14 (T-0007: ENTRY_TF 1H -> 5m, the first live behaviour change. B37 CLOSED — the lookahead is out of production. B33 gained the instance it predicted: every legal execution timeframe would have broken the shadow; GATE-017 closed on the live path; B38 — GATE-018 stays OPEN; B39 — a conditional edit that matches nothing succeeds; B40 — the correlate margin is now 1.5x and nothing reports it shrinking)

---

## The rule for keeping this file honest

**At the end of every task, any problem found but not fixed gets written here
before moving on.** Not mentioned in passing, not left in a commit message —
written here, where it will actually be reviewed.

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

### B42. `shadow.py` carries two comment blocks that contradict each other about whether the perpetuals feed exists
**Found in:** 4.5 (manager, while tracing where the engine takes its data from)
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
four panels, keeping `:78-83` intact. **Not a product-code edit I should make** — noted
for whichever rules task next touches `shadow.py`, since GATE-017/019 will.

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

**There is no consolidation detector and no range detector**, in the registry or in the code.
Review checked: the only `overlap` match under `app/services/rules/` is PRIM-002's **BPR
overlap** — two opposite-direction imbalances overlapping *in price* — which is a different
concept from a post-sweep consolidation. **The word `overlap` is a false match.**

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
**What it is:** `shadow.py:486` is `deciding = decision.deciding_rule_id or "GATE-036"`.
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
**What it is:** `crypto_loop.py:802-813`. The entry-gate check returns **before** the
shadow is called:

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
panels are watched. Fold into whichever task next touches `data_health`.

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
