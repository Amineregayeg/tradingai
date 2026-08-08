# Running Salim's strategy — the execution plan

Written 2026-08-08, after the conformance audit that produced KNOWN_ISSUES A10.

`MAGIC_STRATEGY_INTEGRATION.md` remains the analysis and the milestone map. This
document is narrower and more uncomfortable: it is about the distance between
"117 rules are implemented" and "the engine trades Salim's strategy", which are
not the same achievement and are not even on the same axis.

---

## 0. Where we actually are

| | |
|---|---|
| Rules implemented | **7 / 117** (GATE-023, PRIM-001…006) |
| Rules **evaluated on a live decision** | **0 / 117** |
| HARD_GATEs evaluated | **0 / 91** |
| What the live loop actually runs | the pre-contract ICT edge, unchanged |
| Rules remaining | 110, of which **84 are HARD_GATE** |

Remaining by family: GATE 47, GRADE 39, TARGET 9, ENTRY 6, EXIT 5, SIZE 4.

The second row is the one that matters and it is the row nobody was tracking. We
have built a rule registry, a validated telemetry store, a coverage script and
seven primitives — the furniture of conformance — and connected none of it to the
thing that decides trades. `crypto_loop._tick_symbol` calls
`strategy_step.evaluate_latest_bar_traced`, which cites zero rule ids.

Two of its behaviours are not merely un-ruled but **counter-ruled**:

* it rejects candidates on a premium/discount test, which **GATE-037 forbids by
  name** — 5 of the 137 declines in run `7d788ad6` were made by a filter the
  doctrine says must never influence whether a trade is taken;
* it triggers entries from **1H**, which GATE-017/019 make **analysis-only** —
  every entry the platform has ever taken came off a series it is not allowed to
  trade from.

---

## 1. The hole in the existing plan

M0 through M8 build rules, telemetry, conformance and a scorecard. **No milestone
switches the engine over to them.** Read the list again: M3 builds primitives, M4
builds graders, M5 gates, M6 sizing, M7 tests the telemetry, M8 reports on it. At
the end of M8 the live loop still calls the ICT function, because nothing in the
plan ever says otherwise.

That is not a small omission. It is the difference between a project that ends
with a conformance score and one that ends with the strategy running. Building
rules faster does not close it; the gap is architectural, not volumetric.

So this plan adds one milestone the original lacks — **M9, the cutover** — and
places it before, not after, the conformance suite. A conformance suite over
telemetry that no trade produced is a test of a library.

---

## 2. Boundary with the parallel M4 agent

An agent is building M4 (graders and the correlate layout) right now. Its work in
progress is visible: `app/services/rules/grade_001_structure_box.py` declares
GRADE-001 and GRADE-009 and does not yet register them, which is why
`scripts/check_rule_coverage.py` currently exits non-zero. **That is expected and
must not be "fixed" from outside.** CI stays red on that step until they finish.

To keep two agents out of each other's way:

| Owned by the M4 agent | Owned by this track |
|---|---|
| `app/services/rules/grade_*.py` | `app/services/rules/gate_*.py`, `entry_*`, `exit_*`, `size_*`, `target_*` |
| the correlate/roster layout and dominance panels | session, timing and news gates |
| `rules/__init__.py` grader imports | `rules/__init__.py` — **append only**, never reorder |
| `contract/` — nobody edits vendored artefacts except to add a new pinned file |

Both tracks touch `KNOWN_ISSUES.md` and `rules/__init__.py`. Convention: **append
at the end, never renumber, never reflow**, so a merge is a concatenation rather
than a conflict. Issue ids are claimed by whoever pushes first — that already
happened once today (A10/B9 landed from the audit while this track was writing
A10/B9 for different findings; ours became A11/B10).

---

## 3. The path

Entry and exit criteria, so "done" is not a judgement call.

### M4 · Graders and correlates — *in flight, parallel agent*
**Exit:** GRADE-001/006/009 and the disturbance grader emit telemetry with
provenance; the four-panel roster resolves at one execution timeframe (GATE-007);
`check_rule_coverage.py` is green again.

### M4.5 · Vendor the two missing contract artefacts — *small, do it next*
`CONFORMANCE_SUITE.md` (78 assertions: 29 HG, 28 K, 17 C, 4 D) and
`FIDELITY_SCORECARD.md` are in the package and **are not in the repo**. Only the
registry and the telemetry schema were vendored.

**Why now rather than at M7:** every milestone between here and there is written
against assertions we are currently quoting from memory. Vendor them pinned by
sha256 exactly as the registry is, with the same drift test.
**Exit:** both files under `app/services/telemetry/contract/`, hash-pinned, and a
test that fails when a regenerated copy arrives.

### M5 · Session, timing and news gates
NY-local DST handling throughout (GATE-023 is built), session and magic-zone
windows, 19:00 flat (GATE-022/EXIT-001), news blackout (GATE-012/013/015).
**Blocked on E4** — no calendar source. The blackout gates are HARD_GATE, so this
is not deferrable past M9.
**Exit:** a decision inside a blackout window is refused *and says which rule
refused it*.

### M6 · Sizing and stops
The 3×3 `box_grade × disturbance` lookup exactly as written (GATE-032/GRADE-017),
with the `×0.5` modifier path **absent from the codebase**, not merely unused.
Five-anchor stop ladder, `argmin |RR − 3.0|` over candidates clearing 2R, ties to
the larger stop (GATE-028), terminal skip on ladder exhaustion (HG-10).

This is where the frozen `RISK_PCT = 0.01` in `fixed_config.py` goes away — it is
correct for the ICT engine and is a **HARD_GATE violation** under the contract,
where risk is a nine-cell lookup. Note the ordering consequence: **M6 cannot land
before M4**, because the lookup's two inputs are the graders.
**Exit:** HG-06/07/08/09/10/11 pass on stored telemetry.

### M9 · The cutover — *the milestone the plan was missing*

Three stages. Each is reversible; only the last removes anything.

**Stage A — shadow.** The rule engine evaluates every closed bar alongside the ICT
path and emits full contract telemetry with `deciding_rule_id`. Its verdict is
**recorded and not acted on**. Nothing about live behaviour changes.

This is the only arrangement in which the two strategies can be compared on
identical bars, and it produces the conformance data that M7 needs *before* any
behaviour change. Run it for a fixed, stated period — proposed: **20 trading days
or 300 evaluations per symbol, whichever is later**.

**Stage B — the rule engine decides.** `_tick_symbol` calls the rule engine; the
ICT path stops influencing entries. Gated on, and not before:
* the conformance suite green over the whole shadow window;
* zero unexplained decisions (scorecard §2.2) — every abstention cites a rule id;
* the deviation register reviewed by a human, not merely empty.

**Stage C — removal.** `evaluate_latest_bar_traced` leaves the live path, and the
premium/discount filter is deleted rather than defaulted off, so no config flip
can resurrect a forbidden gate. Same treatment for the `×0.5` modifier.

**Exit:** a decision record whose `deciding_rule_id` is a real registry id, from a
trade the engine actually took.

### M7 · Conformance suite in CI
Translate 78 prose assertions into tests over stored telemetry. They are prose
with structured headings, not machine-readable — this is hand work, roughly one
test per assertion, and it is the assertions that decide whether we are running
the strategy or something that resembles it.
**Exit:** the suite runs on every push against shadow-mode output.

### M8 · Scorecard and readiness gates
Weekly fidelity report, deviation register, outcome-to-rule attribution with the
mandatory confidence gating (<30 observations ⇒ raw count only, no rate, no chart
— which `RunHistoryPanel` already does), and the 8 readiness gates as the
acceptance criteria before any real order.

---

## 4. What caps precision no matter how much we build

"Best precision possible" has a ceiling, and it is set by five things that no
amount of implementation moves. Each is stated with the lever that *does* move it.

### 4.1 Fourteen rules have no number to be precise about
`ENTRY-002/004/005/006`, `EXIT-003`, `GATE-011/014/043`, `GRADE-025/039`,
`TARGET-002/004/007/009` are **OPEN** — the trader declined to fix a value. We
cannot implement them exactly; we can only choose a value, declare it as ours, and
carry `declared_parameter_used` on every record so the choice is never mistaken
for doctrine. That is 14/117 where the engine is our reading, honestly labelled.

**Lever:** the six money-ordered questions in `OPEN_ITEMS/TRADER_QUESTIONS.md`.
Each has a stated no-reply default, so none blocks the build — but each answer
converts a declared parameter into doctrine, and they are the cheapest precision
available anywhere in this document. Three of them are one word.

### 4.2 Detector quality is invisible to every test we will write
Section E of the conformance suite says this outright, and it is the single
largest risk in the project: **a systematically wrong swing or imbalance detector
scores 100% CONFORMANT while mis-grading every box and therefore mis-sizing every
trade.** Conformance checks that the record is coherent and the rules were cited.
It cannot check that the swing was the swing the trader would have marked.

**Lever:** annotated charts. A handful per primitive, marked by Salim or the
trader, turned into fixtures — so PRIM-001…006 are tested against his reading
rather than our interpretation of prose. This is readiness gate 7 and it needs a
human. It is worth asking for before M9, not after.

### 4.3 We are trading the wrong series
The roster names `BTCUSDT.P` — Binance **perpetuals**. `fixed_config.PRICE_SOURCE`
is Binance **spot**. Measured over 500 matched 1H bars: the perpetual extends
beyond the spot bar on **497 of 500 (99%)**, median bar-range difference **2.89%**
of the bar's own range — two orders of magnitude larger than the CFT/Binance
divergence we already treat as material.

Box grades are decided by wicks. Risk is decided by box grade. This is the largest
single precision lever in the plan and it is nearly free to pull.

**Lever:** switch the feed; re-run the corrected baseline on perpetual bars; mark
the spot-era baseline as a different venue rather than deleting it (A3).

### 4.4 The execution timeframe is wrong, and fixing it invalidates our history
GATE-017/019: 1H is **analysis only**; ruled execution timeframes are 30M/15M/5M.
Every backtest number, the corrected baseline and all four recorded trades came off
1H. Moving to a ruled timeframe is correct and it resets the comparison set.

**Lever:** decide it *before* M9 Stage A, so the shadow window runs on the
timeframe we intend to keep. Running the shadow on 1H would produce 20 days of
data about a configuration we are about to abandon.

### 4.5 The delivered artefacts contradict each other
`TELEMETRY_SCHEMA.json` pins `rule_registry_version` to `1.1.0`; the registry is
`1.2.0` (B8). We emit the true versions and relax exactly those two consts, with a
test that fails when a regenerated schema arrives. **Blocked on Salim.**

---

## 5. Decisions this needs

**Two of the three questions this document originally put to Malek are already
answered in the package**, and were answered before it was asked. They were
checked against `RULE_REGISTRY.json` v1.2.0 on 2026-08-08; both answers are
HARD_GATE, so neither is a preference we get to weigh.

### 5.1 The feed — ANSWERED. Perpetuals, and the tickers are named.
**GATE-008** (READY, HARD_GATE) does not hint, it enumerates:

> Canonical tickers: **BTCUSDT.P (Binance)**, **ETHUSDT.P (Binance)**,
> TOTAL (CryptoCap), USDT.D (CryptoCap).

So §4.3 is not a trade-off to weigh — running Binance spot is a hard-gate
violation, and the 2.89% median bar-range divergence is the size of the error it
introduces into every box grade. **Decision: move to perpetuals; re-baseline.**

Two riders fall out of the same rule and neither was in the original plan:

* **The correlate panels come from CryptoCap, not from us.** TOTAL and USDT.D are
  named with a source. Our dominance collector is a different series with ~8 days
  of history and point samples rather than OHLC (F1). Whether CryptoCap is
  reachable programmatically is now an M4 dependency, and it belongs to the
  parallel agent's track.
* **The roster trades BTC. ETH is a *panel*, not an instrument.** The layout is
  "main: BTC · positive: ETH and TOTAL · negative: USDT.D". We currently trade
  BTC **and** ETH as equals — and the run reviewed today took its only trade on
  ETH. GATE-008's note adds that altcoins cannot be magic-aligned at all, and Q1's
  stated no-reply default is "we trade BTC only and refuse to size any altcoin".
  **This needs settling before M9 Stage A** or the shadow window measures an
  instrument the contract does not trade.

### 5.2 The calendar — ANSWERED, and we built the wrong integration
**GATE-015** (READY, HARD_GATE): the filter is **Forex Factory RED FOLDERS ONLY**
— "growth, inflation, employment, central bank, business surveys and speeches";
for crypto "USD is enough however for extra confluence i can use EUR, GBP and
USD"; and the calendar timezone **must be New York local** so its timestamps and
the chart's agree.

We implemented **Finnhub**. E4 has therefore been mis-stated in the register since
it was written: the problem is not a missing API key, it is that the ruled source
is a different one. A Finnhub key would produce a working integration that still
fails GATE-015.

The two surrounding gates are specific and implementable today:
* **GATE-012** — no new entry within **15 minutes before** a red-folder event.
* **GATE-013** — no new entry for **30 minutes after**, *and then* additionally
  wait for the first complete **M15** candle to close. Both conditions, not either.

Worth carrying into the code comments: GATE-012's note says the 15/30/M15 constants
appear in no workspace page and in none of the 1,258 images — they are
**trader-authorised engine constants, not recovered doctrine**. They should be
emitted as declared parameters even though the rules are READY.

### 5.3 The execution timeframe — NOT answered, deliberately. And I was wrong.
I recommended 30M. The package argues against it.

* **GATE-018** (HARD_GATE) fixes the legal set at exactly **{30M, 15M, 5M}**.
  Anything below 5M is a flagged extension emitting `LTF_BELOW_RULED_SET`.
* **GATE-007** is explicit that the choice within that set is not the rule: "the
  particular member of the set is hedged three times in the source ('usually',
  'such as', 'sometimes 30-minute') — **the SAME-TF requirement is the hard part,
  not the specific 5M/15M/30M list**." GRADE-010/012 say the same: alignment
  timeframe equals execution timeframe, whatever it is.
* **The trader's own behaviour excludes 30M.** `TRADER_QUESTIONS.md`: his
  bracketed charts show **6 trades on 1M, 2 on 3M, and zero on 30M**.
* **GATE-019** notes that document 022 classifies "day trading = TFs UNDER 30Min",
  putting 30M on the *swing* side while the ruling calls it execution — a tension
  the contract flags and does not resolve.

**Revised recommendation: 5M.** It is the lowest legal member, the nearest legal
neighbour to the 1M/3M he actually trades, and the only choice not contradicted by
either his behaviour or 022. 15M is the defensible conservative alternative and
has the incidental advantage that GATE-013's post-news wait and GATE-024's session
backgrounds are both defined in M15 terms. 30M should be dropped from
consideration: legal on paper, unused in practice, and disowned by one of his own
documents.

This is a **declared parameter**, not a doctrine value. Whichever we pick is
stamped on every record as ours.

Cost worth stating before choosing 5M: twelve times the evaluations of 1H, so
twelve times the decision-record volume, and CFT's ~125-day history limit bites
sooner on the lower timeframe if we ever move the feed there.

### 5.4 Still genuinely open

**From Malek**
1. **Do we trade ETH, or is it only a panel?** (§5.1) The contract's stated default
   is BTC only.
2. **5M or 15M** as the execution timeframe (§5.3).
3. **Forex Factory access** — a scraper, a paid feed, or an equivalent red-folder
   source with NY timestamps (§5.2).

**From Salim**
1. Regenerate the v1.1.0 documents against registry v1.2.0 (§4.5).
2. **Annotated charts** — still the highest-value thing he can send (§4.2).
3. Is CryptoCap TOTAL/USDT.D reachable programmatically, or do we substitute — and
   if we substitute, does that break GATE-008?
4. The 10 rule ids the critic pass named as never adjudicated: in scope or not?

**From the trader**
The six questions in `TRADER_QUESTIONS.md` plus three one-word ratifications. Each
has a no-reply default, so silence is a decision rather than a blocker — but each
answer removes one declared parameter (§4.1). Q1 (do altcoins trade at all) is now
load-bearing for §5.1.

## 6. How we will know it worked

Not by a percentage. Four checks, in order of how easy they are to fake:

1. **A decision record whose `deciding_rule_id` is a real registry id**, from a
   trade the engine actually took. Today this is impossible to produce.
2. **The unexplained-decision rate is zero** — every abstention names the rule that
   refused it. Run `7d788ad6` would score 5 unexplained out of 137 (B10).
3. **The conformance suite green**, including the four defect tripwires, over a
   shadow window long enough to have hit the gates.
4. **Readiness gate 7 — a human replaying records against the charts.** The only
   check in the list that can catch a detector that is wrong in a consistent
   direction, and the only one that cannot be automated. Nothing ships to real
   money without it.

And one thing that will not be a measure of success: profit. Four closed trades so
far. Fidelity is measurable now; expectancy is not, and the 200-trade significance
floor stands.
