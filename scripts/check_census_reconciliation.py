#!/usr/bin/env python3
"""C-13 — reconcile `scan_census` against the population it claims (T-0011, B41).

    python3 scripts/check_census_reconciliation.py --self-test        # prove it can FAIL
    python3 scripts/check_census_reconciliation.py --jsonl export.jsonl
    python3 scripts/check_census_reconciliation.py --api              # the live store

WHY THIS SCRIPT EXISTS AT ALL, WHICH IS THE WHOLE POINT OF THE TASK IT CAME FROM

The contract specified three defences against an engine controlling its own denominator:
an `emission_policy_id` declaring the coverage, a `scan_census` measuring it, and C-13
reconciling the two. All three were documented. **None was built**, and each one's absence
was invisible because the layer above it never ran — the policy id was simply false, the
census had no caller, and C-13 existed only as six mentions in schema prose.

Emitting the census and leaving nothing to read it would have reproduced that exact
failure one layer up. So this is the third layer, and it is the one that makes the second
worth having.

WHAT IT CHECKS — the schema's own words, turned into assertions

  * `bars_observed == evaluations_emitted + len(unemitted_bars)`. A population that does
    not add up means no fidelity number over that window has a known denominator.
  * Every `unemitted_bars` entry cites a rule in `RULE_REGISTRY.json`, or it is
    undocumented logic (MAJOR). In practice none of them can: the real omission
    population is "the grader declined" and "something threw", and neither is a clause of
    Salim's strategy. **That is the finding, not a bug in the check** — those omissions
    genuinely are unauthorised, and the honest output says so rather than inventing a
    rule id that would read as permission.
  * Every entry carries an `omission_class` from the closed set {DECLINED, ERRORED} and a
    non-empty reason. A missing class means the bar was dropped and nothing recorded why;
    an unknown one means a suppression path was added without updating the census.

WHY "EXAMINED 0" IS A DISTINCT OUTCOME AND NOT A PASS

On the day this shipped the production store held 156 telemetry records and **zero**
censuses. A check that reported only pass/fail would have printed green from an empty set
and stayed green until the first census existed — which is precisely the window in which
someone reads the green and concludes the mechanism works. That is the failure this whole
chain was built to stop, arriving inside the check written to stop it.

So there are three outcomes and three exit codes:

    PASS           examined >0, no findings          0
    FAIL           examined >0, findings             1
    NOT_EXERCISED  examined 0                        3   (with --require-records)

`--require-records` is what a production verification uses; without it, examining zero is
reported loudly and exits 0, because a CI run with no corpus available has not discovered
a defect and should not claim to have.

MUTATION
`--self-test` builds a census whose omission cites nothing and whose arithmetic is short,
and requires the checker to report BOTH. A checker that returns "no findings" because it
always returns "no findings" is indistinguishable from this one on today's real data —
which is empty — and that is the exact failure shape this project has hit before.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.telemetry import census  # noqa: E402

DEFAULT_API = os.environ.get("TRADINGAI_API", "http://31.97.183.142:8095/api")


def _from_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _from_api(api: str, token: str, limit: int) -> list[dict[str, Any]]:
    url = f"{api}/engine/shadow?limit={limit}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
    if isinstance(body, dict):
        body = body.get("records") or body.get("items") or []
    return [r for r in body if isinstance(r, dict)]


def _self_test_corpus() -> list[dict[str, Any]]:
    """Three censuses covering the three things this check must be able to say.

    The first is THE one that matters: an empty `unemitted_bars` with an unexplained
    shortfall. That is the honest-looking census the whole chain exists to prevent, and it
    is indistinguishable from a correct one to anything that only reads the array.
    """
    return [
        {
            # SILENT: 12 bars, 9 evaluations, no omissions declared and nothing explaining
            # the missing three.
            "record_type": "scan_census", "scan_id": "self-test-silent-shortfall",
            "bars_observed": 12, "evaluations_emitted": 9, "unemitted_bars": [],
        },
        {
            # DECLARED, and still a finding: three bars were not evaluated because
            # something failed. Accounted for to the bar, so it is reported as the
            # contract gap it is rather than as a census that does not add up.
            "record_type": "scan_census", "scan_id": "self-test-declared-failures",
            "bars_observed": 12, "evaluations_emitted": 9, "unemitted_bars": [],
            "notes": f"{census.ACCOUNTING_PREFIX} policy_excluded=0 failures=3 unattributed=0",
        },
        {
            # A census whose notes disagree with its own arithmetic.
            "record_type": "scan_census", "scan_id": "self-test-notes-disagree",
            "bars_observed": 12, "evaluations_emitted": 9, "unemitted_bars": [],
            "notes": f"{census.ACCOUNTING_PREFIX} policy_excluded=1 failures=0 unattributed=0",
        },
    ]


def _report(records: Iterable[dict[str, Any]], scope: str, require: bool) -> int:
    report = census.reconcile(records)

    print("=" * 78)
    print("C-13 — scan_census reconciliation")
    print(f"  scope     {scope}")
    # THE DENOMINATOR IS PRINTED WHETHER OR NOT ANYTHING FAILED. "no findings" over an
    # unstated population is the claim this check exists to stop being made.
    print(f"  examined  {report.examined} census record(s)")
    print("=" * 78)

    for f in report.findings:
        print(f"  {f}")

    if report.outcome == "NOT_EXERCISED":
        print(
            "\nNOT EXERCISED — examined 0 censuses. This check has not been run against "
            "anything.\nIt is not a pass: a census that does not reconcile would look "
            "identical from here.\nThe first census is emitted when a NY session date "
            "rolls over with the engine running."
        )
        return 3 if require else 0

    if report.outcome == "FAIL":
        print(
            f"\nFAILED — {len(report.findings)} finding(s) across {report.examined} "
            "census record(s).\nAn omission with no rule authorising it is undocumented "
            "logic: the engine ran on something\nnobody has seen, and the fidelity score "
            "for that window has an unknown denominator."
        )
        return 1

    print(f"\nPASSED — {report.examined} census record(s) reconcile, every omission attributed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jsonl", type=Path, help="a JSONL export of telemetry records")
    ap.add_argument("--api", action="store_true", help="read the live store over HTTP")
    ap.add_argument("--api-url", default=DEFAULT_API)
    ap.add_argument("--token", default=os.environ.get("API_AUTH_TOKEN", ""))
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument(
        "--require-records", action="store_true",
        help="exit 3 when zero censuses were examined (use for production verification)",
    )
    ap.add_argument(
        "--self-test", action="store_true",
        help="run against a deliberately broken census; the checker must report it",
    )
    args = ap.parse_args()

    if args.self_test:
        report = census.reconcile(_self_test_corpus())
        by_scan = {f.scan_id: {g.check for g in report.findings if g.scan_id == f.scan_id}
                   for f in report.findings}
        checks = [
            ("examined exactly 3 censuses", report.examined == 3),
            ("reported the SILENT shortfall — an empty array hiding three missing bars",
             "reconciliation" in by_scan.get("self-test-silent-shortfall", set())),
            ("reported declared failures as the contract gap, not as bad arithmetic",
             by_scan.get("self-test-declared-failures") == {"unrepresentable-omission"}),
            ("reported notes that disagree with the record's own arithmetic",
             "reconciliation" in by_scan.get("self-test-notes-disagree", set())),
            ("outcome is FAIL", report.outcome == "FAIL"),
        ]
        print("SELF-TEST — the checker must FAIL on a census that is wrong\n")
        for label, ok in checks:
            print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
        for f in report.findings:
            print(f"        {f}")
        if all(ok for _, ok in checks):
            print("\nSELF-TEST PASSED — the checker can report a broken census.")
            return 0
        print("\nSELF-TEST FAILED — this checker cannot detect a census it is meant to reject.")
        return 1

    if args.jsonl:
        return _report(_from_jsonl(args.jsonl), str(args.jsonl), args.require_records)

    if args.api:
        if not args.token:
            print("--api needs --token or API_AUTH_TOKEN", file=sys.stderr)
            return 2
        try:
            records = _from_api(args.api_url, args.token, args.limit)
        except Exception as exc:  # noqa: BLE001
            print(f"Could not reach {args.api_url}: {exc}", file=sys.stderr)
            return 2
        return _report(records, f"{args.api_url} (limit {args.limit})", args.require_records)

    # No source named. Reported as examined-zero rather than as a usage error, because
    # that is the true state of the corpus and it is the line a reader needs to see.
    return _report([], "no corpus given", args.require_records)


if __name__ == "__main__":
    raise SystemExit(main())
