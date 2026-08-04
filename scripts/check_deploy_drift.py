#!/usr/bin/env python3
"""Compare what the repo says is deployed against what actually is (C4).

Three compose files in this repo each claim to be "the record of what runs" on
the VPS. Nothing checked that, and the claim was untrue in three separate ways
before anyone went looking:

  * the api kept its own inline pip pin list on the server (C1);
  * the frontend installed with --no-frozen-lockfile there (C2);
  * the repo copy was missing CFT_BRIDGE_URL and CFT_BRIDGE_TOKEN entirely, so
    the committed record described an api with no route to its broker.

Each was found by hand, months apart. This makes it one command.

WHY IT COMPARES PARSED YAML AND NOT TEXT
A raw diff of these files is ~91 lines of comment noise, because the repo copies
carry long explanatory headers and the server copies do not. Comments do not
run. Worse, the useful content — the shell script inside each `command:` block —
is a YAML *string*, so its own `#` comment lines survive parsing and would still
swamp the comparison. Both are stripped before anything is compared, leaving
only lines that actually execute.

SECRETS ARE COMPARED BY PRESENCE, NEVER BY VALUE
The repo carries `__SET_ON_VPS_ONLY__` where the server carries the real thing;
that difference is correct and expected. What matters is that neither side is
MISSING a secret the other has — a variable present only on the server is
exactly how the CFT bridge wiring went unrecorded. Values are never printed.

USAGE
    python3 scripts/check_deploy_drift.py            # all three pairs
    python3 scripts/check_deploy_drift.py --host X   # non-default ssh host

Exit 0 = the repo matches production. Exit 1 = drift. Exit 2 = could not check.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: ./scripts/dev_env.sh installs it, or pip install pyyaml")

REPO = Path(__file__).resolve().parent.parent

#: repo copy -> the path it claims to mirror on the VPS.
PAIRS: list[tuple[str, str]] = [
    ("deploy/compose.vps.yaml", "/docker/tradingai/docker-compose.yml"),
    ("deploy/compose.cft-bridge.yaml", "/docker/tradingai/compose.cft-bridge.yaml"),
    ("deploy/compose.dominance.yaml", "/home/deploy/tradingai-dominance/compose.yaml"),
]

SECRET_HINTS = ("TOKEN", "PASSWORD", "SECRET", "KEY", "PASSPHRASE")
PLACEHOLDER = "__SET_ON_VPS_ONLY__"


def is_secret(key: str) -> bool:
    return any(h in key.upper() for h in SECRET_HINTS)


def effective_script(value) -> list[str]:
    """The lines of a command/entrypoint block that actually execute.

    Shell comments inside these blocks survive YAML parsing (the block is just a
    string), and the repo copies are heavily commented while the server copies
    are not. Comparing raw would report drift on every single file.
    """
    if value is None:
        return []
    text = "\n".join(value) if isinstance(value, list) else str(value)
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            out.append(stripped)
    return out


def normalise(service: dict) -> dict:
    """A service reduced to what a machine would act on."""
    svc = dict(service or {})
    for key in ("command", "entrypoint"):
        if key in svc:
            svc[key] = effective_script(svc[key])
    env = svc.get("environment")
    if isinstance(env, list):  # both KEY=value and KEY forms are legal
        parsed = {}
        for item in env:
            k, _, v = str(item).partition("=")
            parsed[k] = v
        env = parsed
    if isinstance(env, dict):
        # Presence is compared; the value of a secret never is.
        svc["environment"] = {
            k: ("<secret>" if is_secret(k) else v) for k, v in env.items()
        }
    return svc


def fetch(host: str, path: str) -> str | None:
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, f"cat {path}"],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  ERROR could not reach {host}: {exc}")
        return None
    if r.returncode != 0:
        print(f"  ERROR could not read {path} on {host}: {r.stderr.strip()[:120]}")
        return None
    return r.stdout


def compare(repo_rel: str, server_path: str, host: str) -> tuple[int, int]:
    """Returns (drift_count, error_count)."""
    print(f"\n{repo_rel}")
    print(f"  vs {host}:{server_path}")

    repo_file = REPO / repo_rel
    if not repo_file.exists():
        print(f"  ERROR {repo_rel} does not exist in this repo")
        return 0, 1

    raw = fetch(host, server_path)
    if raw is None:
        return 0, 1

    try:
        server = yaml.safe_load(raw) or {}
        local = yaml.safe_load(repo_file.read_text()) or {}
    except yaml.YAMLError as exc:
        print(f"  ERROR could not parse: {exc}")
        return 0, 1

    drift = 0
    lsvc, ssvc = local.get("services") or {}, server.get("services") or {}

    for name in sorted(set(lsvc) | set(ssvc)):
        if name not in ssvc:
            print(f"  DRIFT {name}: in the repo, NOT deployed")
            drift += 1
            continue
        if name not in lsvc:
            print(f"  DRIFT {name}: deployed, NOT in the repo")
            drift += 1
            continue

        a, b = normalise(lsvc[name]), normalise(ssvc[name])
        if a == b:
            print(f"  ok    {name}")
            continue

        drift += 1
        print(f"  DRIFT {name}:")
        for key in sorted(set(a) | set(b)):
            av, bv = a.get(key), b.get(key)
            if av == bv:
                continue
            if key == "environment":
                av, bv = av or {}, bv or {}
                for k in sorted(set(av) | set(bv)):
                    if av.get(k) == bv.get(k):
                        continue
                    if k not in bv:
                        print(f"          env {k}: in repo, missing on server")
                    elif k not in av:
                        print(f"          env {k}: on server, MISSING FROM REPO")
                    elif is_secret(k):
                        pass  # presence matched; values deliberately not compared
                    else:
                        print(f"          env {k}: repo={av[k]!r} server={bv[k]!r}")
            elif key in ("command", "entrypoint"):
                import difflib

                print(f"          {key} (comments stripped):")
                for line in list(difflib.unified_diff(
                        av or [], bv or [], "repo", "server", lineterm="", n=0))[2:12]:
                    print(f"            {line[:120]}")
            else:
                print(f"          {key}: repo={str(av)[:90]!r} server={str(bv)[:90]!r}")

    lv, sv = set((local.get("volumes") or {})), set((server.get("volumes") or {}))
    if lv != sv:
        drift += 1
        print(f"  DRIFT volumes: repo={sorted(lv)} server={sorted(sv)}")

    return drift, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="pfe-vps", help="ssh host (default: pfe-vps)")
    args = ap.parse_args()

    print("Deploy drift — does the repo describe what actually runs? (C4)")
    print("=" * 66)

    drift = errors = 0
    for repo_rel, server_path in PAIRS:
        d, e = compare(repo_rel, server_path, args.host)
        drift += d
        errors += e

    print("\n" + "=" * 66)
    if errors:
        print(f"COULD NOT CHECK {errors} file(s) — treat this as unknown, not as clean.")
        return 2
    if drift:
        print(f"DRIFT: {drift} service(s) differ. The repo does not describe production.")
        print("Either update the repo copy, or fix the server — but do not leave it.")
        return 1
    print("IN SYNC — every deployed service matches its committed description.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
