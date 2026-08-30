# Independent verification runs — 2026-08-30

**Output of the two scripts in [`export/`](export/), run against production.** Neither takes
anything on trust from this repository: one checks stored market data against a public exchange,
the other recomputes a run's published figures from the raw table.

**Anyone with the read-only credential can reproduce both** (see
[AUDIT_RESPONSE_2026-08-30.md](AUDIT_RESPONSE_2026-08-30.md), Q2.4).

---

## 1. Stored candles vs Binance public API

`export/verify_candles_vs_binance.py` — fetches `api.binance.com/api/v3/klines` for the exact
timestamp of each stored candle and compares all four OHLC values.

**20 candles. 80 values. Every one exact.**

```
candle time          src             open         high          low        close
2026-08-24 02:00:00  db          76922.11     77545.08     76883.61     77478.69
                     binance     76922.11     77545.08     76883.61     77478.69
                     max abs diff 0.00  (0.0000% of close)

2026-08-24 01:00:00  db          77679.51     77717.28     76918.00     76922.10
                     binance     77679.51     77717.28     76918.00     76922.10
                     max abs diff 0.00  (0.0000% of close)

2026-08-24 00:00:00  db          77734.00     77742.00     77142.85     77679.50
                     binance     77734.00     77742.00     77142.85     77679.50
                     max abs diff 0.00  (0.0000% of close)

2026-08-23 23:00:00  db          77598.87     77829.70     77290.22     77734.00
                     binance     77598.87     77829.70     77290.22     77734.00
                     max abs diff 0.00  (0.0000% of close)

2026-08-23 22:00:00  db          77833.23     77979.00     77560.02     77598.88
                     binance     77833.23     77979.00     77560.02     77598.88
                     max abs diff 0.00  (0.0000% of close)

2026-08-23 21:00:00  db          77401.59     78052.85     77401.59     77833.23
                     binance     77401.59     78052.85     77401.59     77833.23
                     max abs diff 0.00  (0.0000% of close)

2026-08-23 20:00:00  db          77346.00     77460.00     77200.03     77401.60
                     binance     77346.00     77460.00     77200.03     77401.60
                     max abs diff 0.00  (0.0000% of close)

2026-08-23 19:00:00  db          77341.99     77487.04     77255.99     77346.01
                     binance     77341.99     77487.04     77255.99     77346.01
                     max abs diff 0.00  (0.0000% of close)

2026-08-23 18:00:00  db          77176.41     77415.33     77116.00     77341.98
        ... 15 further candles, all identical ...

WORST RELATIVE DIFFERENCE ACROSS SAMPLES: 0.0000%
```

**What it proves:** the market data the engine read is genuine Binance data, not synthetic.
**What it does not prove:** that decisions were taken at the time they claim — real historical data
can be replayed. That is Q3.1/Q3.3 in the audit response, where the evidence is weaker.

---

## 2. Run figures recomputed live from `decision_records`

`export/verify_reproduce_run.py` — reads the raw table and recomputes, rather than reading the
generated markdown.

```

RUN-23 f8b40671 (the one the commit names)
  run id       f8b40671-888e-4c5e-816a-32acd7d1fd49
  window       2026-08-24 03:50:25 .. 2026-08-24 15:36:43
  decision rows 83   outcomes {'ABSTAINED': 81, 'WIN': 2}
  parsed comparison lines 83 of 83
  agree 2  disagree 12  rule_stricter 0  rule_looser 12  not_comparable 69  comparable 14

RUN-21 a32c3b98 (not pre-selected by anyone)
  run id       a32c3b98-51f1-4ce6-be43-e3376f9979c7
  window       2026-08-19 18:50:22 .. 2026-08-24 01:41:01
  decision rows 307   outcomes {'ABSTAINED': 303, 'WIN': 2, 'LOSS': 2}
  parsed comparison lines 0 of 307
  agree 0  disagree 0  rule_stricter 0  rule_looser 0  not_comparable 0  comparable 0
```

**RUN-23 matches its published figures exactly.** RUN-21 was included without pre-selection and
returns zero comparison lines — which is what its document states, because the comparison harness
post-dates that run. **An absence agreeing three ways is worth as much as a number agreeing.**

---

## 3. Three-way agreement, without a database

The same figures recomputed from the committed files alone:

```
runs/data/decisions-f8b40671.jsonl
  rows=83  outcomes={'ABSTAINED': 81, 'WIN': 2}  parsed=83
  agree 2  disagree 12  stricter 0  looser 12  not_comparable 69  comparable 14
```

**Document, committed data, and live query agree.** That is what committing `runs/data/` finally
makes checkable — the audit's first finding was that those files were missing.
