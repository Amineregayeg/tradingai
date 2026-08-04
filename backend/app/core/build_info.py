"""What code is actually running (KNOWN_ISSUES B3, task I6).

THE PROBLEM THIS SOLVES
Containers fetched `main` at startup and recorded nothing. `main` moves, so two
containers recreated ten minutes apart could be running different code with no
way to tell — and `/system/health` answered `"version": "0.1.0"`, a constant
that had never changed and therefore described nothing. You cannot debug or roll
back what you cannot identify.

THE RULE THIS FILE FOLLOWS
An unknown version is reported as unknown. It is never guessed, and never
defaulted to something plausible-looking.

That matters more than it sounds. The failure mode being replaced is not "no
version" — it is a version string that was always present, always the same, and
always wrong. A confident wrong answer is worse than a blank, because nobody
thinks to check it. So when the commit cannot be established, `commit` is
`"unknown"` and `source` says which lookups were tried and failed.

PINNED VERSUS FLOATING
`pinned` is the field worth reading. A deploy that asked for an exact 40-character
SHA is reproducible: recreate the container and you get identical code. A deploy
that asked for `main` is not — it gets whatever `main` says at that instant. Both
report a commit, and only one of them can be trusted to still be true tomorrow,
so the distinction is surfaced rather than left to be inferred.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

UNKNOWN = "unknown"

#: A full commit SHA, the only ref that makes a deploy reproducible.
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

#: Written by the deploy at clone time — see deploy/compose.vps.yaml. Overridable
#: so tests never depend on a path that exists only in the container.
_SHA_FILE_ENV = "BUILD_INFO_FILE"
_DEFAULT_SHA_FILE = "/app/.build-sha"


@dataclass(frozen=True)
class BuildInfo:
    """The running build, and how confident we are about it."""

    commit: str
    ref: str
    #: Which lookup answered — or, when nothing did, which ones were tried. Kept
    #: because "unknown" alone leaves you guessing whether the deploy forgot to
    #: stamp the build or the stamp is being read from the wrong place.
    source: str
    pinned: bool

    @property
    def known(self) -> bool:
        return self.commit != UNKNOWN

    @property
    def short(self) -> str:
        return self.commit[:9] if self.known else UNKNOWN

    def as_dict(self) -> dict:
        return {
            "commit": self.commit,
            "short": self.short,
            "ref": self.ref,
            "source": self.source,
            "pinned": self.pinned,
            "known": self.known,
        }


def _from_env() -> tuple[str, str] | None:
    """A SHA the deploy passed in directly."""
    sha = (os.getenv("GIT_COMMIT") or "").strip().lower()
    return (sha, "env:GIT_COMMIT") if _FULL_SHA.match(sha) else None


def _from_file() -> tuple[str, str] | None:
    """A SHA the deploy wrote at clone time.

    This is the one that matters in production: it records what was actually
    checked out, which is not necessarily what was requested — asking for `main`
    and recording the resulting SHA is precisely the gap being closed.
    """
    path = Path(os.getenv(_SHA_FILE_ENV) or _DEFAULT_SHA_FILE)
    try:
        sha = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    return (sha, f"file:{path}") if _FULL_SHA.match(sha) else None


def _from_git() -> tuple[str, str] | None:
    """A working tree — development only; containers ship no `.git`."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip().lower()
    return (sha, "git:rev-parse") if out.returncode == 0 and _FULL_SHA.match(sha) else None


@lru_cache(maxsize=1)
def build_info() -> BuildInfo:
    """Resolve the running build once per process.

    Cached because it is read on every health check and the answer cannot change
    while the process lives — the code was fixed when the container started.
    Tests clear it via :func:`reset_cache`.
    """
    ref = (os.getenv("GIT_REF") or "").strip() or UNKNOWN

    # Labels are explicit rather than read off `lookup.__name__`. The name of a
    # function is not a stable description of it — patch or wrap one and the
    # diagnostic silently degrades to "<lambda>", which is exactly the kind of
    # quietly-useless message this module exists to stop producing.
    lookups: tuple[tuple[str, object], ...] = (
        ("env", _from_env),
        ("file", _from_file),
        ("git", _from_git),
    )

    tried: list[str] = []
    for name, lookup in lookups:
        found = lookup()
        if found:
            commit, source = found
            return BuildInfo(
                commit=commit,
                ref=ref,
                source=source,
                # Only an exact SHA is reproducible. A branch name resolves to
                # something different tomorrow.
                pinned=bool(_FULL_SHA.match(ref.lower())),
            )
        tried.append(name)

    return BuildInfo(
        commit=UNKNOWN,
        ref=ref,
        source=f"unavailable (tried: {', '.join(tried)})",
        pinned=False,
    )


def reset_cache() -> None:
    """Forget the resolved build. For tests only."""
    build_info.cache_clear()
