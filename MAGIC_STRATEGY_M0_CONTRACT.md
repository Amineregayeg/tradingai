# M0 — our answers to the six integration points

The engine contract (`ENGINE_CONTRACT/README.md` §"Integration points we still need to agree
with you") lists six interfaces it deliberately does not fix. This is our side of that
agreement.

Five are answered here with measurements rather than preferences. One needs a decision
that costs money, and is marked.

**Status: proposed. Send to Salim for confirmation before M1 starts.**

---

## 1 · Data feed and bar semantics

### 1.1 Feed — MOVE TO THE PERPETUAL. This is not a preference.

The roster names `BTCUSDT.P` / `ETHUSDT.P` — Binance **USD-M perpetual futures**. We
currently read Binance **spot** (`api.binance.com/api/v3/klines`).

Measured, 500 matched 1H bars, BTC ≈ 64,400:

| | |
|---|---|
| close, perp vs spot | −0.0443% mean (near-constant, harmless — structure is scale-invariant) |
| bar range difference | **median 2.89%** of the bar's own range · p90 7.92% · max 61.87% |
| in absolute terms | median 6.9 USDT · p90 18.2 · max 777 |
| **bars where the perp extends beyond the spot bar** | **497 / 500 (99%)** |

For comparison, our measured CFT-vs-Binance divergence (`KNOWN_ISSUES` A3) is a mean
bar-range difference of **0.013%**. Spot-vs-perp is over two orders of magnitude larger.

The contract warns that every geometric primitive — swing points, imbalance boxes, sweep
penetration — is wick-sensitive. At 99% of bars having different extremes, staying on spot
means computing the strategy's primitives on **different geometry from the documented
strategy, almost every bar**. That is not a divergence to record; it is a different chart.

**Decision: switch the roster symbols to Binance USD-M futures (`fapi.binance.com`).**
History is sufficient — `BTCUSDT` perpetual has monthly bars from 2019-09 (~83), `ETHUSDT`
from 2019-11 (~81); both `contractType=PERPETUAL`, `status=TRADING`. Enough for a Monthly →
1H stack.

*Open consequence to flag, not hide:* our historical backtests and the existing baseline
were computed on spot. Moving the live feed to perp makes them measure different series.
`KNOWN_ISSUES` A3 already tracks the venue-divergence problem; this adds a second axis to
it, and the corrected-baseline comparison must be re-run rather than assumed to carry over.

### 1.2 Bar close semantics — ALREADY COMPLIANT, verified

`GRADE-007` / conformance HG-25 require grading on completed price action strictly left of
the decision bar.

Verified in `market_data/sources/binance.py`: the fetch drops any partial bar
(`df = df[df.index < end]`), and the live path documents and implements evaluation on "the
most recent closed bar". Our Tier 0.2 mutation prober already enforces the causality guards
that depend on this, and it is CI-enforced on every push.

**We evaluate on bar close. There is no intra-bar policy to write.**

### 1.3 Session and day boundary — NY local, to be built
We will use `America/New_York` for PDH/PDL, Asia/London ranges and all session primitives.
See §3 — this does not exist yet.

### 1.4 History depth at engine start
Monthly → 1H for the roster. Available from the futures API as above. The constraint is not
BTC/ETH — it is TOTAL and USDT.D; see §2.3.

---

## 2 · Symbol naming and instrument mapping

### 2.1 Proposed canonical strings

| Contract name | Our internal symbol | Source | Tradeable |
|---|---|---|---|
| `BTCUSDT.P` | `BTC/USDT.P` | Binance USD-M futures | yes |
| `ETHUSDT.P` | `ETH/USDT.P` | Binance USD-M futures | yes |
| `TOTAL` | `CRYPTOCAP:TOTAL` | our dominance collector | **no** |
| `USDT.D` | `CRYPTOCAP:USDT.D` | our dominance collector | **no** |

`correlates.states[].symbol` will be emitted using the **contract's** names
(`BTCUSDT.P`, `ETHUSDT.P`, `TOTAL`, `USDT.D`) so HG-14 asserts against the roster directly;
the mapping table above lives in one place in our code.

### 2.2 `instrument_class` and the altcoin switch
`GRADE-019` / HG-24 require `ALTCOIN` to be refused until the `Risk Altcoin` column is
ruled, and the contract asks that this be a hard switch rather than a config default.

**Confirmed: it will be a hard refusal in code** — an `ALTCOIN` instrument raises rather
than falling through to a default. Our roster is BTC-only for v1, so the switch is
unreachable in normal operation and exists to stay unreachable.

### 2.3 TOTAL and USDT.D — we have them, with three honest limits

We already collect both, every 60 s:

```
ts_utc,TOTAL,TOTAL2,TOTAL3,BTC_D,ETH_D,USDT_D,coverage_pct,supplies_age_h
```

This is normally the hardest part of the roster to source, and it is already running and
healthy. The limits:

1. **Point samples, not OHLC.** We will aggregate to bars (open = first, high = max,
   low = min, close = last). At 60 s sampling this is credible at **1H** (60 samples/bar),
   marginal at 15m, and **not credible at 5m** (5 samples). Compare `KNOWN_ISSUES` F1.
2. **History starts 2026-07-27** — about 8 days. **Higher-timeframe structure on TOTAL and
   USDT.D is unavailable and cannot be backfilled.** It accrues from here.
3. Aggregated bars will be flagged in telemetry as `derived_from_samples` so no conformance
   result silently treats them as exchange bars.

**Consequence:** the four-panel alignment (`GATE-007`/`GATE-008`) can be evaluated at 1H
today only over the last ~8 days, and at HTF not at all. We propose starting the census on
1H and letting the HTF panels become available with time rather than faking them.

---

## 3 · Timezone handling — TO BE BUILT

`GATE-023` requires `America/New_York`, DST-aware, never a hardcoded offset.

**We currently have none.** A grep for `America/New_York`, `ZoneInfo`, `zoneinfo` or `pytz`
across the backend returns nothing — the platform is UTC end to end.

Proposed:
- All internal storage stays **UTC** (unchanged).
- A single NY-local boundary layer using `zoneinfo.ZoneInfo("America/New_York")` for every
  session, window and calendar comparison. DST comes from the tz database; no offset is ever
  written in code.
- All telemetry timestamps ISO-8601 **with offset**, so HG-23 can prove which zone was used.
- A test that runs both DST transition days and asserts the windows move with them — the
  contract notes a fixed offset shifts the news blackout, magic zone, 19:00 close and
  session ranges by an hour twice a year.

**M15 grid for `GATE-013`:** we propose **exchange-aligned** (Binance's own M15 boundaries),
because the "first complete M15 close" is then the same object the exchange publishes and is
reproducible from the feed alone. Please confirm this matches the trader's charts.

---

## 4 · How rule ids are referenced in our code

The contract calls this the load-bearing one and asks for a static link it can grep.

Proposed convention:

```python
class NewsBlackoutGate(Gate):
    RULE_ID = "GATE-012"          # module-level constant, greppable
```

- Every gate, grader, selector and sizer carries `RULE_ID` as a class constant.
- The id is emitted into the `rule_evaluation` from that same constant, so code and
  telemetry cannot drift apart.
- **A CI check** loads `RULE_REGISTRY.json` and fails the build on: an emitted id absent
  from the registry, a `HARD_GATE` rule with no implementation, or a `RULE_ID` that
  duplicates another. This mirrors `scripts/check_dependency_sources.py`, which already
  enforces single-source-of-truth for dependencies and is CI-enforced.
- Registry loaded at **build time**, pinned by version, never fetched at runtime.

`values` and `value_provenance` are treated as mandatory: a verdict whose `values` do not
bind to an object in the same record fails our own check, not just theirs.

---

## 5 · The emission boundary

The contract is right that this is where a well-behaved and a badly-behaved engine are
indistinguishable, because we control the denominator.

**Proposed `emission_policy_id`: `every-closed-bar-roster-v1`**

> A `setup_evaluation` is emitted for **every closed bar, on every execution timeframe, for
> every roster symbol**. No pre-filter. Nothing is skipped for being uninteresting.

We take the contract's own suggestion — the simplest policy to audit — deliberately. A
narrower policy would be cheaper to run and impossible to trust.

- `scan_census` emitted per (instrument, signal_tf, session_date): bars observed,
  evaluations emitted, and any unemitted bar carrying the registry rule id that authorises
  the omission. With this policy that list should be empty; if it ever is not, that is the
  finding.
- `scan_context.sequence_no` append-only and strictly increasing per (build, instrument,
  TF). We already have run-scoped, append-only decision records and never delete on reset —
  `test_reset_deletes_nothing` pins that.
- `data_as_of_ny` and `bar_close_time_ny` emitted on every record as the look-ahead anchors.
- `declared_parameters.virtual_account_size` **frozen** per run and snapshotted into the run
  config, which our `engine_runs` table already does for every setting. K-26 satisfied by
  construction.

---

## 6 · Version pinning and the telemetry sink

| Field | Our value |
|---|---|
| `engine_version` | the running commit SHA, already served at `/api/system/version` and recorded in `/app/.build-sha` (B3/I6) |
| `rule_registry_version` | `meta.version` of the pinned registry (currently **1.2.0**) |
| `telemetry_schema_version` | `$id` of the pinned schema (currently **v1.1.0**) |

**Sink:** the contract assumes append-only JSONL. We propose **Postgres/TimescaleDB**, which
is where `decision_records` already live, with daily verified backups and a test-restore.
We will provide a **JSONL export** so their harness runs unchanged — the suite is a pure
function of stored records either way.

**Who runs the suite:** we propose **we run it in CI** against paper-trading output on every
push, using their harness, and Salim's team runs it independently over an export whenever
they want. CI already runs four jobs on every push, so this is an addition to an existing
gate rather than a new process.

**Retention:** indefinite. Records are evidence; `test_reset_deletes_nothing` exists because
deleting them on a button press would be worse than any crash.

**Out-of-band detector audit (readiness gate 7):** we cannot do this — nothing in the suite
tests whether our chart read is *correct*, and a wrong box grader scores 100% CONFORMANT
while mis-sizing every trade. **This needs the trader, on a schedule, sampled and blind.**
We propose quarterly with a stated sample size. This is the largest residual risk in the
whole contract and it is not closeable from our side.

---

## 7 · The one decision that needs Malek

**Economic calendar.** `GATE-012`, `GATE-013` and `GATE-015` are all HARD_GATE and all need
a calendar feed. We have **no `FINNHUB_API_KEY`** (`KNOWN_ISSUES` E4), so today these three
gates cannot be evaluated at all — and an unevaluated HARD_GATE fails readiness gate 5.

The doctrine names **Forex Factory / Crypto Craft red folders**. We implemented **Finnhub**.
Whether Finnhub's impact classification maps onto Forex Factory's red folder is unverified.

Options:

| | Cost | Risk |
|---|---|---|
| **A.** Finnhub key + verify its impact mapping against Forex Factory | free tier exists | mapping may not match doctrine; needs a measured comparison |
| **B.** Source Forex Factory / Crypto Craft directly | scraping or a paid feed | matches doctrine exactly; more to build and maintain |

**Recommendation: A first**, with the mapping measured and reported rather than assumed —
and if it does not match, B becomes a costed decision with evidence behind it.

---

## 8 · Questions back to Salim

1. **Regenerate the v1.1.0 documents against registry v1.2.0.** `ENGINE_CONTRACT/README.md`
   counts, `meta.open_items.ids` (still lists 34 OPEN; 14 are), and scorecard readiness gate
   3 (asks for trader rulings on defects the triage already cleared).
2. Does the **telemetry schema (v1.1.0)** need any change for the 20 rules that moved
   OPEN → READY, or is it version-independent?
3. The critic pass named **ten rule ids never adjudicated** — are they in scope for us, or
   held on your side?
4. Confirm **exchange-aligned M15** (§3) matches the trader's charts.
5. Confirm the **perpetual** is what the trader actually charts (§1.1). The roster says
   `.P`, and our measurement says it matters enormously — but it is worth one sentence of
   confirmation before we move the feed.
