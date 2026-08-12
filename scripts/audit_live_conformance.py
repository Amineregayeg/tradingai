#!/usr/bin/env python3
"""How many of Salim's 117 contract rules decided a trade that was actually taken?

    python3 scripts/audit_live_conformance.py                      # whole corpus
    python3 scripts/audit_live_conformance.py --run <uuid>         # one run
    python3 scripts/audit_live_conformance.py --self-test          # prove it can print non-zero

Today the answer is 0, and it has been 0 for every trade this platform has ever
taken. That number is the point of this script, and the reason it is a script
rather than a sentence in a register is that a sentence goes stale silently while
a command can be re-run in six months and compared.

WHY IT READS `reasons` AND NOT A RULE-ID COLUMN
`decision_records` has no column for a rule id. Not an empty one — none:

    id, created_at, symbol, timeframe, inputs_hash, code_path_hash, score,
    abstained, reasons, signal_dir, signal_entry, signal_sl, signal_tp,
    sized_units, expected_r, realized_r, gap_r, outcome, correction_json,
    cohort, fill_price, run_id

So the only place a rule id could appear on a decision that was acted on is the
free-text `reasons` array. This script therefore scans that text for any of the
117 ids in RULE_REGISTRY.json. **The absence of the column is itself part of the
answer**: the live path has no structured way to say "this rule decided this
trade", which is the same finding as A10 approached from the data rather than
from the source.

The contract engine, by contrast, has `telemetry_records.deciding_rule_id` — a
first-class column. Two decision paths, one with rule citation as a schema
feature and one with no way to express it at all.

WHY THE SCAN IS DELIBERATELY GENEROUS
A substring match over free text will count a rule id that appears in a comment,
a log line, or an explanation of a rule that was *removed*. That biases the
number UPWARD. That is the right direction to be wrong in: this script exists to
support the claim "zero rules decide live trades", and a generous scan that still
returns zero is stronger evidence than a strict one. If it ever returns non-zero,
read the citations before believing them.

MUTATION
`--self-test` injects one synthetic acted-on decision citing a real registry id.
The acted-on count must move off zero. A script that prints 0 because it always
prints 0 would be indistinguishable from this one on today's data, and that is
exactly the failure shape this project has hit before: an implementation that
returns the expected value regardless of reality.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "backend/app/services/telemetry/contract/RULE_REGISTRY.json"
DEFAULT_API = os.environ.get("TRADINGAI_API", "http://31.97.183.142:8095/api")


def load_rule_ids() -> tuple[set[str], str]:
    """Every rule id in the contract, and the registry version they came from."""
    doc = json.loads(REGISTRY.read_text())
    ids = {r["id"] for r in doc["rules"]}
    version = (doc.get("meta") or {}).get("version", "unknown")
    return ids, version


def get(api: str, path: str, token: str, **params) -> object:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{api}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def cited_rules(record: dict, rule_ids: set[str]) -> set[str]:
    """Registry ids mentioned anywhere in this decision's free text.

    `reasons` is a JSON array of strings. Joining and scanning is intentional —
    see the module docstring on why the scan errs generous.
    """
    blob = json.dumps(record.get("reasons") or "")
    # Word-boundary so GATE-01 does not match inside GATE-017.
    return {rid for rid in rule_ids if re.search(rf"\b{re.escape(rid)}\b", blob)}


def audit(decisions: list[dict], rule_ids: set[str]) -> dict:
    acted = [d for d in decisions if not d.get("abstained")]
    abstained = [d for d in decisions if d.get("abstained")]

    cited_on_acted: dict[str, int] = {}
    for d in acted:
        for rid in cited_rules(d, rule_ids):
            cited_on_acted[rid] = cited_on_acted.get(rid, 0) + 1

    cited_on_abstained: dict[str, int] = {}
    for d in abstained:
        for rid in cited_rules(d, rule_ids):
            cited_on_abstained[rid] = cited_on_abstained.get(rid, 0) + 1

    return {
        "decisions_total": len(decisions),
        "acted_on": len(acted),
        "abstained": len(abstained),
        "rules_cited_on_acted_decisions": cited_on_acted,
        "rules_cited_on_abstains": cited_on_abstained,
        "n_rules_deciding_a_taken_trade": len(cited_on_acted),
    }


SYNTHETIC = {
    "id": "synthetic-self-test",
    "abstained": False,
    "reasons": [
        "PASS GATE-023: session window open",
        "synthetic record injected by --self-test; not from the database",
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--token", default=os.environ.get("TRADINGAI_TOKEN", ""))
    ap.add_argument("--run", help="restrict to one run id (scoped by the run's time window)")
    ap.add_argument("--limit", type=int, default=500, help="max decisions to pull (API cap is 500)")
    ap.add_argument("--self-test", action="store_true",
                    help="inject a synthetic acted-on decision citing a real rule id")
    args = ap.parse_args()

    rule_ids, registry_version = load_rule_ids()

    if args.self_test:
        decisions = [dict(SYNTHETIC)]
        shadow: dict = {}
        scope = "SELF-TEST (synthetic record, no database)"
    else:
        if not args.token:
            print("No token. Set TRADINGAI_TOKEN or pass --token.", file=sys.stderr)
            return 2
        try:
            decisions = get(args.api, "/engine/decisions", args.token, limit=args.limit)
            shadow = get(args.api, "/engine/shadow", args.token, limit=args.limit)
        except urllib.error.URLError as e:
            print(f"Could not reach {args.api}: {e}", file=sys.stderr)
            return 2
        scope = f"{args.api}  (up to {args.limit} most recent decisions)"

        if args.run:
            runs = get(args.api, "/engine/runs", args.token)
            match = [r for r in runs if str(r.get("id")) == args.run]
            if not match:
                print(f"No run {args.run}", file=sys.stderr)
                return 2
            started, ended = match[0].get("started_at"), match[0].get("ended_at")
            before = len(decisions)
            decisions = [d for d in decisions
                         if d.get("created_at") and d["created_at"] >= started
                         and (not ended or d["created_at"] <= ended)]
            scope = (f"run {args.run}  [{started} .. {ended or 'open'}]  "
                     f"{len(decisions)} of {before} decisions in window")

    result = audit(decisions, rule_ids)

    print("=" * 74)
    print("LIVE CONFORMANCE AUDIT — how many contract rules decide a real trade?")
    print("=" * 74)
    print(f"registry            RULE_REGISTRY.json v{registry_version}, {len(rule_ids)} rules")
    print(f"scope               {scope}")
    print()
    print(f"decisions           {result['decisions_total']}")
    print(f"  acted on          {result['acted_on']}")
    print(f"  abstained         {result['abstained']}")
    print()
    print(f"RULES DECIDING A TAKEN TRADE:  {result['n_rules_deciding_a_taken_trade']}")
    if result["rules_cited_on_acted_decisions"]:
        for rid, n in sorted(result["rules_cited_on_acted_decisions"].items()):
            print(f"    {rid}  cited on {n} acted-on decision(s)")
    else:
        print("    (none — no acted-on decision cites any registry rule id)")
    print()
    print(f"rules cited on abstains:       {len(result['rules_cited_on_abstains'])}")
    for rid, n in sorted(result["rules_cited_on_abstains"].items()):
        print(f"    {rid}  cited on {n} abstain(s)")

    if shadow:
        ev = shadow.get("rules_evaluated") or {}
        dec = shadow.get("deciding_rules") or {}
        blocked = shadow.get("blocked") or shadow.get("rules_blocked") or {}
        print()
        print("THE OTHER ENGINE, ON THE SAME BARS (M9 Stage A shadow):")
        print(f"    evaluations        {shadow.get('n')}")
        print(f"    decisions          {shadow.get('decisions')}")
        print(f"    rules evaluated    {len(ev)}  {dict(sorted(ev.items()))}")
        print(f"    deciding rules     {len(dec)}  {dict(sorted(dec.items()))}")
        print(f"    blocked            {len(blocked)}  {dict(sorted(blocked.items()))}")
        print()
        print("    The shadow path cites rules because `telemetry_records` has a")
        print("    `deciding_rule_id` COLUMN. The live path has no such column, so it")
        print("    could not cite a rule even if it evaluated one.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
