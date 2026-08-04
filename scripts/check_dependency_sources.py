#!/usr/bin/env python3
"""Assert that dependency versions are declared in exactly ONE place.

Run locally:  python scripts/check_dependency_sources.py
CI runs it on every push (.github/workflows/ci.yml).

WHY THIS EXISTS
---------------
This repo previously had three disagreeing dependency lists:

  * backend/pyproject.toml declared numpy<2.0.0 and pandas<3.0.0
  * the VPS compose inline-pinned numpy==2.2.6 and pandas==3.0.2
  * any local `pip install -e .` resolved a third set -- and in fact failed
    outright, because unpinned pandas-ta required numpy>=2.2.6

Production therefore ran versions the test suite had never been executed
against, and nobody could see it, because the authoritative list lived in a
file that was not in the repo.

That is now consolidated: backend/requirements-prod.txt is the single source,
read by pyproject.toml (setuptools dynamic metadata), by the VPS compose, and
by CI. Consolidation is easy; STAYING consolidated is the hard part -- the
natural next incident is someone "quickly" inlining a pin to unblock a deploy.
These checks make that fail loudly instead of silently.

Each check names what breaks if it regresses, because a failing lint nobody
understands just gets deleted.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy" / "compose.vps.yaml"
PYPROJECT = ROOT / "backend" / "pyproject.toml"
REQ_PROD = ROOT / "backend" / "requirements-prod.txt"
REQ_DEV = ROOT / "backend" / "requirements-dev.txt"

failures: list[str] = []
checks_run = 0


def check(name: str, ok: bool, detail: str) -> None:
    global checks_run
    checks_run += 1
    if ok:
        print(f"ok    {name}")
    else:
        print(f"FAIL  {name}")
        for line in detail.strip().splitlines():
            print(f"      {line}")
        failures.append(name)


# --------------------------------------------------------------------------
# The files themselves must exist. Every other check reads them, so a missing
# file must fail loudly rather than making the checks below vacuously pass.
# --------------------------------------------------------------------------
missing = [p for p in (COMPOSE, PYPROJECT, REQ_PROD, REQ_DEV) if not p.is_file()]
if missing:
    for p in missing:
        print(f"FAIL  missing file: {p.relative_to(ROOT)}")
    print("\nCannot verify the single-source-of-truth property with files missing.")
    sys.exit(1)

compose_raw = COMPOSE.read_text()
pyproject = PYPROJECT.read_text()

# Checks below must read CONFIG, not prose. Both the YAML header and the shell
# inside the `command:` blocks carry comments that legitimately quote the very
# strings being searched for ("was --no-frozen-lockfile", "numpy==2.2.6"), so a
# naive substring search over the whole file reports itself.
compose = "\n".join(
    line for line in compose_raw.splitlines() if not line.strip().startswith("#")
)

# --------------------------------------------------------------------------
# 1. The VPS installs FROM requirements-prod.txt.
# --------------------------------------------------------------------------
check(
    "VPS compose installs from requirements-prod.txt",
    "-r /app/requirements-prod.txt" in compose,
    """
    deploy/compose.vps.yaml no longer pip-installs from requirements-prod.txt.
    Production would install some other set, and CI would be green about a
    system that is not the one shipping -- the exact failure this repo already
    had once.
    """,
)

# --------------------------------------------------------------------------
# 2. No inline pins in the compose command blocks.
#    Matches `pkg==1.2.3` on any line that also mentions pip install, plus the
#    multi-line continuation case.
# --------------------------------------------------------------------------
inline_pins = [
    line.strip()
    for line in compose.splitlines()
    if re.search(r"[A-Za-z0-9_.\-]+(?:\[[^\]]+\])?==[0-9]", line)
]

check(
    "VPS compose contains no inline version pins",
    not inline_pins,
    "Found pinned versions inline in deploy/compose.vps.yaml:\n"
    + "\n".join(f"  {p}" for p in inline_pins[:8])
    + "\n\nThis recreates the second dependency list. Put the version in"
    "\nbackend/requirements-prod.txt instead -- the compose installs from it.",
)

# --------------------------------------------------------------------------
# 3. pyproject declares dependencies dynamically, not as its own list.
# --------------------------------------------------------------------------
check(
    "pyproject.toml reads dependencies from requirements files",
    'file = ["requirements-prod.txt"]' in pyproject
    and "dynamic" in pyproject
    and "dependencies" in pyproject,
    """
    backend/pyproject.toml no longer sources its dependencies from
    requirements-prod.txt. If it declares its own version constraints again
    they will drift from production, and `pip install -e .` will resolve
    something different from what deploys.
    """,
)

# A [tool.poetry.dependencies] table returning means someone reinstated the old
# hand-maintained list.
check(
    "pyproject.toml has no hand-maintained dependency table",
    "[tool.poetry.dependencies]" not in pyproject
    and "[project.dependencies]" not in pyproject,
    """
    A literal dependency table reappeared in backend/pyproject.toml. That is a
    second list by definition. Dependencies must come from requirements-prod.txt
    via [tool.setuptools.dynamic].
    """,
)

# --------------------------------------------------------------------------
# 4. Frontend versions come from the committed lockfile.
# --------------------------------------------------------------------------
check(
    "frontend install uses --frozen-lockfile",
    "--no-frozen-lockfile" not in compose and "--frozen-lockfile" in compose,
    """
    deploy/compose.vps.yaml uses --no-frozen-lockfile (or dropped the flag).
    Production would silently resolve frontend packages that CI never tested --
    the same drift the backend had, on the other side of the app.
    """,
)

# --------------------------------------------------------------------------
# 5. No real secret committed. The VPS copy carries the token; this one must not.
# --------------------------------------------------------------------------
PLACEHOLDER = "__SET_ON_VPS_ONLY__"

# Every secret the api service carries, not just the first one that existed.
# CFT_BRIDGE_TOKEN was added to this file later and was NOT covered here, even
# though it is the last gate before a funded trading account and has already
# leaked once (through an unredacted diff in a chat transcript). A check that
# guards one of two secrets reads as "secrets are checked" while half of them
# are not.
for secret in ("API_AUTH_TOKEN", "CFT_BRIDGE_TOKEN"):
    m = re.search(rf'{secret}:\s*"([^"]*)"', compose)
    check(
        f"no {secret} committed",
        m is not None and m.group(1) == PLACEHOLDER,
        f"""
        deploy/compose.vps.yaml carries something other than the placeholder in
        {secret} (expected "{PLACEHOLDER}"). The real value belongs only in the
        VPS copy of this file. If a real secret was committed, ROTATE IT --
        git history keeps it forever.
        """,
    )

# --------------------------------------------------------------------------
# 6. The two requirements files must not both pin the same package, which would
#    make the installed version depend on pip's argument order.
# --------------------------------------------------------------------------
def pinned(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#")[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?==(.+)$", line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


overlap = sorted(set(pinned(REQ_PROD)) & set(pinned(REQ_DEV)))
check(
    "requirements-prod.txt and requirements-dev.txt do not overlap",
    not overlap,
    f"""
    These packages are pinned in BOTH files: {', '.join(overlap)}
    Whichever pip resolves last silently wins. Pin each package in exactly one
    file -- runtime deps in requirements-prod.txt, test tooling in -dev.
    """,
)

print()
if failures:
    print(f"FAILED {len(failures)}/{checks_run}: " + ", ".join(failures))
    print("\nDependency versions must be declared in exactly one place.")
    sys.exit(1)

print(f"PASSED {checks_run}/{checks_run} — dependency versions have one source of truth.")
