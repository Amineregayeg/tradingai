import json, re, csv, pathlib, collections, datetime
from decimal import Decimal

S = pathlib.Path("./_work")
OUT = pathlib.Path("./runs")
d = json.load(open(S / "runs.json"))
runs, dec, tr, tel = d["runs"], d["decisions"], d["trades"], d["telemetry_by_run"]
EXPORTED_AT = "2026-08-25T18:09:55Z"

by_run_d = collections.defaultdict(list)
for x in dec: by_run_d[x["run_id"]].append(x)
by_run_t = collections.defaultdict(list)
for x in tr: by_run_t[x["run_id"]].append(x)
by_run_tel = collections.defaultdict(list)
for x in tel: by_run_tel[x["run_id"]].append(x)

CMP = re.compile(r"disagree=(\d+) \(rule_stricter=(\d+) rule_looser=(\d+)(?P<extra>[^)]*)\) "
                 r"agree=(\d+) not_comparable=(\d+)")
GATE = re.compile(r"^(PASS|FAIL|OBSERVED|NOT-EVALUATED|BLOCK|SKIP) ([a-z0-9_]+):")

def num(v):
    return None if v in (None, "") else Decimal(str(v))

def dur(a, b):
    if not a or not b: return None
    t0 = datetime.datetime.fromisoformat(a); t1 = datetime.datetime.fromisoformat(b)
    s = int((t1 - t0).total_seconds())
    return f"{s//3600}h {(s%3600)//60}m {s%60}s"

def modal_config():
    c = collections.Counter(json.dumps(r.get("config"), sort_keys=True) for r in runs if r.get("config"))
    return json.loads(c.most_common(1)[0][0]) if c else {}
MODAL = modal_config()

def cfg_delta(cfg):
    if not cfg: return "(no config recorded)"
    diff = {k: v for k, v in cfg.items() if MODAL.get(k) != v}
    missing = [k for k in MODAL if k not in cfg]
    bits = []
    if diff: bits.append(", ".join(f"`{k}` = `{json.dumps(v)}`" for k, v in sorted(diff.items())))
    if missing: bits.append("absent: " + ", ".join(f"`{k}`" for k in sorted(missing)))
    return "; ".join(bits) if bits else "identical to the common configuration"

def cmp_totals(rows):
    t = collections.Counter(); n = 0; extra = 0
    for r in rows:
        for line in (r.get("reasons") or []):
            m = CMP.search(line)
            if m:
                n += 1
                t["disagree"] += int(m.group(1)); t["stricter"] += int(m.group(2))
                t["looser"] += int(m.group(3)); t["agree"] += int(m.group(5))
                t["not_comparable"] += int(m.group(6))
                if m.group("extra").strip(): extra += 1
    return t, n, extra

def gate_hist(rows):
    h = collections.Counter()
    for r in rows:
        for line in (r.get("reasons") or []):
            m = GATE.match(line)
            if m: h[(m.group(2), m.group(1))] += 1
    return h

def positions(trows):
    g = collections.defaultdict(list)
    for t in trows: g[t.get("broker_id")].append(t)
    return g

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "data").mkdir(exist_ok=True)

index = []
for i, r in enumerate(sorted(runs, key=lambda x: x["started_at"]), 1):
    rid = r["id"]; short = rid[:8]
    drows = sorted(by_run_d[rid], key=lambda x: x["created_at"])
    trows = sorted(by_run_t[rid], key=lambda x: x["entry_time"] or "")
    oc = collections.Counter(x["outcome"] for x in drows)
    pnl = sum((num(t["pnl_dollars"]) or Decimal(0)) for t in trows)
    pos = positions(trows)
    started = r["started_at"][:19]; ended = (r["ended_at"] or "")[:19]
    slug = f"RUN-{i:02d}__{started[:10]}__{short}"
    index.append(dict(n=i, short=short, started=started, ended=ended or "— still open at export",
                      dur=dur(r["started_at"], r["ended_at"]) or "—",
                      dec=len(drows), abst=oc.get("ABSTAINED", 0),
                      entries=len(drows) - oc.get("ABSTAINED", 0),
                      trades=len(trows), positions=len(pos), pnl=pnl, slug=slug,
                      cfg=cfg_delta(r.get("config"))))

    L = []
    L.append(f"# Run {i:02d} — `{short}` — {started[:10]}\n")
    L.append(f"**Full id:** `{rid}`  \n**Started:** `{r['started_at']}`  \n"
             f"**Ended:** `{r['ended_at'] or 'NOT ENDED — still open when this was exported'}`  \n"
             f"**Duration:** {dur(r['started_at'], r['ended_at']) or '— (open)'}\n")
    if r.get("label"): L.append(f"**Label:** {r['label']}\n")
    if r.get("note"): L.append(f"**Note:** {r['note']}\n")
    L.append(f"\n**Configuration:** {cfg_delta(r.get('config'))}\n")
    L.append("\n```json\n" + json.dumps(r.get("config"), indent=2) + "\n```\n")

    L.append("\n## Decisions\n")
    if not drows:
        L.append("\n**No decision records.** The run produced no evaluated bars — "
                 "either it was stopped before the first bar closed, or it predates decision recording.\n")
    else:
        L.append(f"\n| outcome | rows |\n|---|---|\n")
        for k, v in oc.most_common(): L.append(f"| `{k}` | {v} |\n")
        L.append(f"| **total** | **{len(drows)}** |\n")
        L.append(f"\nFirst decision `{drows[0]['created_at'][:19]}`, "
                 f"last `{drows[-1]['created_at'][:19]}`.\n")

        t, n, extra = cmp_totals(drows)
        L.append("\n### Entry-rule comparison (shadow)\n")
        if n == 0:
            L.append("\n**Not present in this run.** No decision row carries an "
                     "`entry_rule_comparison` line — the comparison harness had not shipped, "
                     "or produced no line on any bar.\n")
        else:
            comparable = t["agree"] + t["disagree"]
            L.append(f"\nParsed from `{n}` of `{len(drows)}` decision rows.\n\n"
                     f"| field | value |\n|---|---|\n"
                     f"| agree | {t['agree']} |\n| disagree | {t['disagree']} |\n"
                     f"| rule_stricter | {t['stricter']} |\n| rule_looser | {t['looser']} |\n"
                     f"| not_comparable | {t['not_comparable']} |\n"
                     f"| comparable (agree+disagree) | {comparable} |\n")
            L.append(f"\n**`rule_stricter` requires the live path to have produced a signal, and "
                     f"`rule_looser` requires it not to** — so the two counts have different "
                     f"denominators and are not comparable to each other (`B268`, `B270`).\n")
            if extra:
                L.append(f"\n**{extra} row(s) carried an extra term inside the parentheses** "
                         f"(`direction_unknown`), which the parse captured.\n")

        h = gate_hist(drows)
        if h:
            L.append("\n### Gate verdicts across all bars\n\n| gate | verdict | count |\n|---|---|---|\n")
            for (g, v), c2 in sorted(h.items(), key=lambda kv: (-kv[1], kv[0])):
                L.append(f"| `{g}` | {v} | {c2} |\n")

        nonabs = [x for x in drows if x["outcome"] != "ABSTAINED"]
        L.append(f"\n### Decisions that produced a signal — {len(nonabs)}\n")
        if not nonabs:
            L.append("\n**None.** Every bar abstained.\n")
        else:
            L.append("\n| time | symbol | dir | outcome | signal_entry | fill_price | signal_sl "
                     "| sized_units | realized_r | expected_r |\n|---|---|---|---|---|---|---|---|---|---|\n")
            for x in nonabs:
                L.append(f"| `{x['created_at'][:19]}` | {x['symbol']} | {x['signal_dir'] or '—'} "
                         f"| `{x['outcome']}` | {x['signal_entry'] or '—'} | {x['fill_price'] or '—'} "
                         f"| {x['signal_sl'] or '—'} | {x['sized_units'] or '—'} "
                         f"| {x['realized_r'] or '—'} | {x['expected_r'] or '—'} |\n")

    L.append(f"\n## Trades — {len(trows)} row(s) across {len(pos)} position(s)\n")
    if not trows:
        L.append("\n**No trades.** No position was opened in this run.\n")
    else:
        L.append(f"\n**Realised P&L: `{pnl}`**\n")
        L.append("\nRows sharing a `broker_id` are tranches of ONE position "
                 "(`B225`) — the 70/30 split `EXIT-001` specifies.\n")
        L.append("\n| broker_id | pair | dir | entry_time | exit_time | entry | exit | lot_size "
                 "| r_multiple | outcome | pnl |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
        for bid, group in sorted(pos.items(), key=lambda kv: kv[1][0]["entry_time"] or ""):
            for t2 in group:
                L.append(f"| `{(bid or '—')[:14]}` | {t2['pair']} | {t2['direction']} "
                         f"| `{(t2['entry_time'] or '')[:19]}` | `{(t2['exit_time'] or 'OPEN')[:19]}` "
                         f"| {t2['entry_price']} | {t2['exit_price'] or '—'} | {t2['lot_size']} "
                         f"| {t2['r_multiple'] or '—'} | {t2['outcome'] or '—'} | {t2['pnl_dollars']} |\n")

    tl = by_run_tel[rid]
    L.append("\n## Telemetry\n")
    if not tl:
        L.append("\n**No telemetry records.**\n")
    else:
        L.append("\n| record_type | rows | first | last |\n|---|---|---|---|\n")
        for x in sorted(tl, key=lambda y: -y["n"]):
            L.append(f"| `{x['record_type']}` | {x['n']} | `{x['first_at'][:19]}` "
                     f"| `{x['last_at'][:19]}` |\n")

    L.append(f"\n---\n\n**Machine-readable:** every decision row for this run, all columns, at "
             f"[`data/decisions-{short}.jsonl`](data/decisions-{short}.jsonl). "
             f"Trades for all runs at [`data/trades.csv`](data/trades.csv).\n")
    L.append(f"\n*Exported {EXPORTED_AT} from the production database. "
             f"See [METHOD.md](METHOD.md) for what is and is not included.*\n")

    (OUT / f"{slug}.md").write_text("".join(L), encoding="utf-8")
    with (OUT / "data" / f"decisions-{short}.jsonl").open("w", encoding="utf-8") as f:
        for x in drows: f.write(json.dumps(x) + "\n")

with (OUT / "data" / "trades.csv").open("w", newline="", encoding="utf-8") as f:
    if tr:
        w = csv.DictWriter(f, fieldnames=list(tr[0].keys())); w.writeheader()
        for t2 in sorted(tr, key=lambda x: x["entry_time"] or ""): w.writerow(t2)

json.dump(index, open(S / "index.json", "w"), default=str)
print("wrote", len(runs), "run documents +", len(runs), "jsonl +Trades csv")
