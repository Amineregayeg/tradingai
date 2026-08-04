"""The running build must be identifiable, or honestly unknown (B3 / I6).

What is being replaced: `/system/health` returned `"version": "0.1.0"` — a
constant, present on every response, identical across every deploy. It was not a
missing feature so much as an actively misleading one, because nobody thinks to
double-check a field that is always populated.

So the tests that matter here are the ones about NOT lying:

  * an unresolvable build reports "unknown", never a plausible-looking default;
  * a floating deploy (`GIT_REF=main`) is reported as not pinned even though it
    has a perfectly good SHA — a commit you cannot reproduce tomorrow should not
    look like one you can.
"""
from __future__ import annotations

import pytest

from app.core import build_info as bi


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Every test starts with nothing resolvable.

    Pointing the SHA file at tmp_path matters: without it these tests would read
    /app/.build-sha, pass on a developer machine where it is absent, and behave
    differently inside the container where it exists.
    """
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.delenv("GIT_REF", raising=False)
    monkeypatch.setenv(bi._SHA_FILE_ENV, str(tmp_path / "absent"))  # noqa: SLF001
    monkeypatch.setattr(bi, "_from_git", lambda: None)
    bi.reset_cache()
    yield
    bi.reset_cache()


SHA = "1234567890abcdef1234567890abcdef12345678"


# ---------------------------------------------------------------------------
# Honesty when nothing is known
# ---------------------------------------------------------------------------
def test_an_unknown_build_says_unknown():
    info = bi.build_info()
    assert info.commit == "unknown"
    assert info.known is False
    assert info.pinned is False


def test_an_unknown_build_names_what_it_tried():
    """"unknown" alone leaves you unable to tell a deploy that forgot to stamp
    the build from a stamp being read out of the wrong path."""
    source = bi.build_info().source
    assert "env" in source and "file" in source and "git" in source


def test_a_short_sha_is_not_accepted_as_a_commit(monkeypatch):
    """A truncated or malformed value must not become the reported version."""
    monkeypatch.setenv("GIT_COMMIT", "1234567")
    bi.reset_cache()
    assert bi.build_info().commit == "unknown"


def test_a_placeholder_in_the_sha_file_is_refused(monkeypatch, tmp_path):
    f = tmp_path / "sha"
    f.write_text("unknown\n")
    monkeypatch.setenv(bi._SHA_FILE_ENV, str(f))  # noqa: SLF001
    bi.reset_cache()
    assert bi.build_info().commit == "unknown"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def test_the_env_sha_is_used(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", SHA.upper())  # case must not matter
    bi.reset_cache()
    info = bi.build_info()
    assert info.commit == SHA
    assert info.short == SHA[:9]
    assert info.source == "env:GIT_COMMIT"


def test_the_file_written_at_clone_time_is_used(monkeypatch, tmp_path):
    """The production path: the deploy records what it actually checked out."""
    f = tmp_path / "sha"
    f.write_text(f"{SHA}\n")
    monkeypatch.setenv(bi._SHA_FILE_ENV, str(f))  # noqa: SLF001
    bi.reset_cache()
    info = bi.build_info()
    assert info.commit == SHA
    assert str(f) in info.source


def test_the_file_wins_over_a_missing_env(monkeypatch, tmp_path):
    f = tmp_path / "sha"
    f.write_text(SHA)
    monkeypatch.setenv(bi._SHA_FILE_ENV, str(f))  # noqa: SLF001
    bi.reset_cache()
    assert bi.build_info().known is True


# ---------------------------------------------------------------------------
# Pinned vs floating — the field worth reading
# ---------------------------------------------------------------------------
def test_a_branch_deploy_is_not_pinned(monkeypatch):
    """`main` moves. The SHA is real, but recreating the container tomorrow
    gives different code — so this must not be reported as reproducible."""
    monkeypatch.setenv("GIT_COMMIT", SHA)
    monkeypatch.setenv("GIT_REF", "main")
    bi.reset_cache()
    info = bi.build_info()
    assert info.known is True
    assert info.pinned is False, "a floating deploy was reported as pinned"
    assert info.ref == "main"


def test_a_sha_deploy_is_pinned(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", SHA)
    monkeypatch.setenv("GIT_REF", SHA)
    bi.reset_cache()
    assert bi.build_info().pinned is True


def test_a_tag_deploy_is_not_pinned(monkeypatch):
    """Tags are movable in git. Only a full SHA is genuinely reproducible."""
    monkeypatch.setenv("GIT_COMMIT", SHA)
    monkeypatch.setenv("GIT_REF", "v1.2.0")
    bi.reset_cache()
    assert bi.build_info().pinned is False


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
def test_the_answer_is_cached(monkeypatch):
    """Read on every health check, and it cannot change while the process
    lives — the code was fixed when the container started."""
    monkeypatch.setenv("GIT_COMMIT", SHA)
    bi.reset_cache()
    first = bi.build_info()
    monkeypatch.setenv("GIT_COMMIT", "f" * 40)
    assert bi.build_info() is first
