# Magic Strategy — integration plan

Analysis of `MagicStrategy_EngineKnowledge` (delivered 2026-08-04) and the plan for
building it into this platform.

**Status: proposal. Nothing below has been implemented.**

---

## 1. What we have been given

A knowledge layer, not code. ~1.4 MB across 19 files:

| Artefact | What it is |
|---|---|
| `RULE_REGISTRY.json` | **117 rules**, stable ids, each cited to a source. The authoritative artefact. |
| `TELEMETRY_SCHEMA.json` | JSON Schema for 3 record types the engine must emit |
| `CONFORMANCE_SUITE.md` | 78 assertions over that telemetry |
| `FIDELITY_SCORECARD.md` | How conformance becomes a capability measure + 8 readiness gates |
| `EXPERTISE_CODEX.md` | 682 KB of methodology; reference, not executable |

Rule breakdown, computed from the registry rather than taken from the prose:

```
117 total   READY 100 (93 full + 7 partial) · OPEN 14 · CALIBRATED 1 · WITHDRAWN 2 · DEFECT 0
enforceability:  HARD_GATE 91 · SOFT_PREFERENCE 15 · ADVISORY 11
families:        GATE 48 · GRADE 39 · TARGET 9 · ENTRY 6 · EXIT 5 · SIZE 4 · PRIM 6
```

**The package's own framing, which we should adopt: the objective is FIDELITY, not
profit.** It is not asking us to build a money-maker. It is asking us to build something
that can *prove* it applied the documented strategy, and attach outcomes to specific rule
ids so a learning loop evaluates rules rather than one P&L number.

---

## 2. Five findings that change how we should plan

### 2.1 The package is internally inconsistent by one version — implement against the registry

`RULE_REGISTRY.json` is **v1.2.0**. Every prose document and the telemetry schema are
**v1.1.0**, written before a corpus triage that cleared all 8 DEFECTs and moved 20 rules
from OPEN to READY.

Concretely wrong if followed:

| Says | Actually |
|---|---|
| `ENGINE_CONTRACT/README.md`: "READY 75 · OPEN 34 · DEFECT 8" | READY 100 · OPEN 14 · DEFECT 0 |
| `meta.open_items.ids` lists 34 ids | 14 are OPEN; **20 of those listed have shipped** |
| Scorecard readiness gate 3: "blocker defects ruled on by the trader" | Resolved by triage with no trader input |

This matters because `ENGINE_CONTRACT/README.md` is the file the package tells you to read
first, and it would have us treat 20 shippable rules as blocked and wait on the trader for
three defects that are already settled.

**Decision: the registry is authoritative. Prose is commentary.** We should ask Salim to
regenerate the v1.1.0 documents, and until then treat any count in them as stale.

### 2.2 Three HARD_GATE rules need an economic calendar we do not have

`GATE-012` (no entry within 15 min before a red-folder event), `GATE-013` (30-min cooldown
plus first complete M15 close), `GATE-015` (the filter definition) are all HARD_GATE and all
require a calendar feed.

We have **no `FINNHUB_API_KEY`** — that is `KNOWN_ISSUES` E4, previously filed as "a page of
the app is permanently non-functional". It is now a **strategy blocker**: without a calendar
these three gates cannot be evaluated, and a HARD_GATE that is never evaluated fails
readiness gate 5.

Worse, the strategy names **Forex Factory / Crypto Craft red folders**. We implemented
**Finnhub**. Whether Finnhub's impact classification maps onto Forex Factory's red folder is
an open question — not just a missing key.

**E4 is promoted from cosmetic to blocking.**

### 2.3 The corpus contains four trades. This cannot validate an edge, and we must not imply it does

The package is emphatic and correct about this:

- 4 executed trades total (Feb: 3 trades 1W/2L; Mar: 1 ETH long)
- Every other journal row is a byte-identical copied template
- The trader's own guidance calls for ~100 trades before judging expectancy

This aligns exactly with our existing Tier gates and with `RunHistoryPanel`'s
`MEANINGFUL_SAMPLE = 200`. **Nothing here lets us skip the sample-size discipline we already
built.** If anything it strengthens it — and the report header must say so.

There is also a doctrine-versus-practice gap worth carrying: the ruled preference is ≈3R,
the teaching material draws ≈2.9R, and the trader's own realised trades ran **1.4–1.7R**.
Three different numbers; fidelity scoring keeps them as separate fields instead of silently
picking one.

### 2.4 The largest residual risk is one nothing in the contract can test

From the scorecard, §7.2, quoted because it is the single most important sentence in the
package:

> Nothing tests whether a box the engine called Manipulated actually is one. The grade keys
> the risk matrix, so a systematically wrong grader mis-sizes every trade while scoring 100%
> CONFORMANT.

So a perfect conformance score is compatible with sizing every trade wrongly. The only
mitigation is readiness gate 7 — a human replaying a sample of records against the charts,
ideally the trader. That is a **standing quarterly process**, not a one-off.

This is the same class of problem as our Tier 0.2 mutation prober: a green check that proves
the check ran, not that the answer is right.

### 2.5 We already collect the two hardest data series — but not in a usable shape yet

The roster is exactly four panels (`GATE-008`): `BTCUSDT.P`, `ETHUSDT.P`, `TOTAL`, `USDT.D`.
TOTAL and USDT.D are **CryptoCap indices, not tradeable instruments** — normally the hardest
part to source.

Our dominance collector already emits both:

```
ts_utc,TOTAL,TOTAL2,TOTAL3,BTC_D,ETH_D,USDT_D,coverage_pct,supplies_age_h
```

That is a genuine head start. Three gaps before it is usable:

1. **Point samples, not OHLC.** The rules need swing points, imbalances and structure on
   TOTAL/USDT.D, which need bars. At 60 s sampling we can aggregate honestly to 1H (60
   samples/bar) and marginally to 15m; 5m would be 5 samples and is not credible. Compare
   `KNOWN_ISSUES` F1 on degenerate 1-minute bars.
2. **~8 days of history** (since 2026-07-27). The analysis stack is Monthly → 1H. HTF
   structure on TOTAL/USDT.D is simply not available yet and cannot be backfilled.
3. **Symbol mismatch.** We trade `BTC/USD` sourced from Binance spot; the roster names
   `BTCUSDT.P` — the *perpetual*. Wicks differ between spot and perp, and the contract warns
   explicitly that every geometric primitive is wick-sensitive.

---

## 3. What we already have that fits

More than I expected. The contract's four hard requirements land on things we built for
other reasons:

| Contract requirement | What we already have |
|---|---|
| "Log rejected setups, not just fills" (the single most important telemetry rule) | `decision_records` with `abstained` + `reasons`, and run-scoped cohorts |
| "Emit the decision path; `deciding_rule_id` is the *first* rule that failed" | `DecisionTrace` with ordered `Gate`s and `.reasons` |
| "Records must outlive the process; append-only" | Postgres/Timescale + daily verified backups |
| Version pinning per record (`engine_version`, `rule_registry_version`) | `/api/system/version`, `.build-sha`, `GIT_REF` (B3) |
| Emission population / census | `engine_runs` + run-scoped metrics |
| Conformance suite "should run in CI against your paper-trading output" | CI with 4 jobs; a local runner (B7) |
| Detectors | swing points, FVG, BOS/CHoCH, liquidity, order blocks, S/D zones |

**The primitives we already detect cover roughly half of PRIM-001…006.** Missing:
sweep events with measured penetration (PRIM-004), S/R flips as zones (PRIM-006), and the
full four named inefficiency types (PRIM-002 — we do FVG only).

The honest gap is scale, not concept: our live path evaluates **3 gates**. The contract has
**91 HARD_GATE rules**.

---

## 4. The plan

Ordered by the package's own instruction — telemetry before strategy logic, because
everything downstream reads from it and retrofitting is expensive.

### M0 · Agree the integration points *(blocked on decisions — see §5)*
The contract lists six interfaces it deliberately does not fix: data feed and bar
semantics, symbol mapping, timezone handling, how rule ids appear in our code, the emission
policy, and where telemetry lands. **None of the rest should start before these are
answered**, because each one silently changes what the telemetry means.

### M1 · Telemetry (the foundation)
Implement `TELEMETRY_SCHEMA.json` as a first-class store: `setup_evaluation`,
`trade_execution`, `scan_census`. Extend `decision_records` rather than replacing it —
adding `rule_evaluations`, `declared_parameters`, `primitives`, `correlates`,
`decision_path`, `deciding_rule_id`, `value_provenance`. Validate every emitted record
against the schema in CI.

*Deliverable: a record we emit validates against their schema, with our existing abstention
logging carried into it.*

### M2 · Rule registry as a build-time artefact
Load `RULE_REGISTRY.json` at build time. Every gate carries its rule id as a constant.
A CI check greps for registry rules that are unimplemented and for emitted ids absent from
the registry — the same single-source-of-truth discipline as
`scripts/check_dependency_sources.py`.

### M3 · Primitives to contract standard
Extend the detectors to PRIM-001…006 with the contract's field requirements. This is where
detector *quality* risk lives (§2.4), so each gets a test fixture drawn from the trader's
own annotated charts.

### M4 · Graders and the correlate layout
Structure box grading (Manipulated/Super/Standard — note `GRADE-006`: use the workspace key,
the imbalance tap is mandatory in all three), disturbance grading, and the four-panel
alignment at a single execution timeframe (`GATE-007`). Needs the dominance work in §2.5.

### M5 · Session, timing and news gates
NY-local DST-aware handling throughout (`GATE-023`), session/magic-zone windows, and the
news blackout (`GATE-012/013/015`) — **blocked on E4**.

### M6 · Sizing and stops — last, deliberately
The 3×3 risk lookup exactly as written (`GATE-032`), with the `×0.5` modifier path **absent
from the codebase entirely**, not merely unused. Stop ladder with
`argmin |RR − 3.0|` over candidates clearing 2R, ties to the larger stop (`GATE-028`).
Frozen `virtual_account_size`.

*This is last because M1–M5 make it auditable. Building it first would be a sizer nobody
can check.*

### M7 · Conformance suite in CI
The 78 assertions as a test harness over stored telemetry, running against paper-trading
output on every push. They validate behaviour, not profit, so they are meaningful before any
money is involved.

### M8 · Fidelity scorecard and the readiness gates
The weekly report, the deviation register, outcome-to-rule attribution with the mandatory
confidence gating (<30 observations ⇒ raw count only, no rate, no chart — which matches what
`RunHistoryPanel` already does), and the 8 readiness gates as the acceptance criteria before
any real order.

---

## 5. What we need, and from whom

### From Malek — engineering decisions (blocking M0)
1. **Feed and instrument.** Do we move BTC/ETH to Binance **perpetuals** (`BTCUSDT.P`) to
   match the roster, or stay on our current series and record the divergence? Wicks differ,
   and wicks decide box grades, which decide risk.
2. **Economic calendar.** Finnhub key, or a Forex Factory / Crypto Craft source that matches
   the doctrine? This unblocks three HARD_GATE rules.
3. **Dominance bars.** Confirm we aggregate the collector to 1H bars for TOTAL/USDT.D, and
   accept that HTF structure on those panels is unavailable until history accumulates.
4. **Emission policy.** I propose "every closed bar on every execution TF for every roster
   symbol" — the contract calls this the simplest to audit.

### From Salim — package hygiene
1. **Regenerate the v1.1.0 documents against registry v1.2.0.** Specifically
   `ENGINE_CONTRACT/README.md` counts, `meta.open_items.ids`, and scorecard readiness gate 3.
2. Confirm the telemetry schema (v1.1.0) needs no change for the 20 rules that moved to
   READY.
3. The **10 ids never adjudicated** that the critic pass named — are they in scope for us?

### From the trader — 6 money-ordered questions + 3 ratifications
Already written up in `OPEN_ITEMS/TRADER_QUESTIONS.md`, each with a stated no-reply default,
so **none of them blocks the build**. The three ratifications are one word each.

---

## 6. What this plan does not promise

- **It does not promise profit.** Four trades. Fidelity is measurable; expectancy is not.
- **It does not make the engine "correct".** A perfect conformance score is compatible with
  a systematically wrong box grader mis-sizing every trade (§2.4).
- **It does not replace the Tier gates.** Our existing acceptance criteria and the 200-trade
  significance floor stand unchanged.
- **It will not be quick.** 91 HARD_GATE rules against our current 3 gates, with telemetry
  and conformance underneath. M1–M2 are the honest starting point.
