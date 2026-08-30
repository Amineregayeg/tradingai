# The export scripts

**These are the scripts that produced `runs/`.** They were requested in the owner's audit (Q2.1).

```
1_extract.py                    the four SELECTs, dumps JSON to stdout
2_generate_run_docs.py          JSON -> RUN-NN__*.md + data/*.jsonl + data/trades.csv
3_generate_index.py             JSON -> README.md
verify_reproduce_run.py         recomputes a run's figures LIVE from the DB
verify_candles_vs_binance.py    compares stored candles to Binance's public API
```

**No credentials are embedded.** Every script reads `os.environ["DATABASE_URL"]`.
`METHOD.md` said the extract script was withheld "because it embeds a database connection" —
**that was wrong, and it is corrected here.** The scripts were simply not committed.

Run them inside the API container, which already has `DATABASE_URL` set:

```
docker exec -i <api-container> python - < 1_extract.py > raw.txt
```

`2_` and `3_` expect `./_work/runs.json` (the extracted JSON) and write into `./runs`.

**`verify_*` are the ones an auditor wants.** They take nothing on trust from this repository:
one recomputes a run's published figures directly from `decision_records`, the other checks the
stored candles against a public exchange API.
