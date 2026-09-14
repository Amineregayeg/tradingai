"""`B432` — the suite cannot reach the network, and says so. Arms named by review's rows (`_runs/b437b/KILL_SET.md`: S).

The guard's plants live in files the suite does not collect (`tests/unit/b432_plants.py`, `tests/integration/b432_plants.py`,
`tests/b432_plants.py`). These arms run them EXPLICITLY in a CHILD pytest from `backend/` — so the real conftest chain applies,
placement included — and read every outcome. A plant SWALLOWS the refusal and must still ERROR at teardown naming `B432`; a
must-miss (loopback, AF_UNIX, localhost resolution) must pass with no error.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
PLANT_FILES = ["tests/unit/b432_plants.py", "tests/integration/b432_plants.py", "tests/b432_plants.py"]


def _child(files=PLANT_FILES, *, extra_opt_outs: dict | None = None):
    env = {k: v for k, v in os.environ.items() if k != "B432_TEST_EXTRA_OPT_OUTS"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["COLUMNS"] = "1000"   # pytest truncates `-rA` summary lines to the terminal width, which cut "B432" off the reason
    if extra_opt_outs is not None:
        env["B432_TEST_EXTRA_OPT_OUTS"] = json.dumps(extra_opt_outs)
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA", "-p", "no:randomly", *files],
                         cwd=BACKEND, capture_output=True, text=True, env=env, timeout=240)
    outcomes: dict[str, set[str]] = {}
    for line in run.stdout.splitlines():
        match = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+::\S+)", line)
        if match:
            outcomes.setdefault(match.group(2), set()).add(match.group(1))
    return run, outcomes


@pytest.fixture(scope="module")
def plants():
    run, outcomes = _child()
    names = [n for n in outcomes if "::test_plant_" in n]
    assert len(names) == 19 and len([n for n in outcomes if "::test_mustmiss_" in n]) == 5, (
        f"the child run did not collect the plants: {sorted(outcomes)}\n{run.stdout[-2000:]}")
    return run, outcomes


def _failed_by_guard(run, outcomes, test: str) -> bool:
    nodeids = [n for n in outcomes if n.endswith(f"::{test}")]
    assert len(nodeids) == 1, (test, sorted(outcomes))
    lines = [l for l in run.stdout.splitlines() if l.startswith(("ERROR", "FAILED")) and f"::{test}" in l]
    return bool(outcomes[nodeids[0]] & {"ERROR", "FAILED"}) and any("B432" in l for l in lines)


@pytest.mark.parametrize("plant", [
    "test_plant_S1_S2_an_IP_fetch_swallowed",
    "test_plant_S1_a_new_fetch_INSIDE_a_driven_tick",
    "test_plant_S3_a_HOSTNAME_fetch_swallowed",
    "test_plant_S3_gethostbyname_swallowed",
    "test_plant_S3_gethostbyname_ex_swallowed",
    "test_plant_S4_socket_connect",
    "test_plant_S4_socket_connect_ex",
    "test_plant_S4_create_connection",
    "test_plant_S4_asyncio_open_connection",
    "test_plant_S4_asyncio_sock_connect",
    "test_plant_S4_udp_sendto",
    "test_plant_S4_udp_sendmsg",
    "test_plant_S5_a_fetch_on_an_ACCOUNT_WORKER_thread",
    "test_plant_S10_the_ZERO_address",
    "test_plant_S10_a_PRIVATE_non_loopback_address",
    "test_plant_S10_the_HOST_S_OWN_interface_address",
    "test_plant_S11_resolving_a_real_name",
    "test_plant_S7a_an_integration_fetch_swallowed",
    "test_plant_S7b_a_top_level_fetch_swallowed",
])
def test_S1_to_S5_S7_S10_S11_a_SWALLOWED_attempt_still_FAILS_its_test_naming_B432(plants, plant):
    run, outcomes = plants
    assert _failed_by_guard(run, outcomes, plant), (
        f"{plant} passed although it reached for the network (its exception was swallowed): {run.stdout[-3000:]}")


@pytest.mark.parametrize("mustmiss", [
    "test_mustmiss_S6_loopback_127_0_0_1",
    "test_mustmiss_S10_loopback_127_0_0_2_the_whole_slash_8",
    "test_mustmiss_S10_ipv6_loopback",
    "test_mustmiss_S10_af_unix_socketpair",
    "test_mustmiss_S11_localhost_resolves",
])
def test_S6_S10_S11_LOOPBACK_AF_UNIX_and_LOCALHOST_stay_allowed(plants, mustmiss):
    """Paired with the plants above in the SAME child run, so a zero here is not an unreached one."""
    run, outcomes = plants
    nodeids = [n for n in outcomes if n.endswith(f"::{mustmiss}")]
    assert len(nodeids) == 1 and outcomes[nodeids[0]] in ({"PASSED"}, {"SKIPPED"}), (mustmiss, outcomes.get(nodeids[0] if nodeids else ""))
    if mustmiss != "test_mustmiss_S10_ipv6_loopback":
        assert outcomes[nodeids[0]] == {"PASSED"}, f"{mustmiss} did not run clean: {outcomes[nodeids[0]]}"


def test_S7_the_guard_lives_in_the_ROOT_conftest_and_no_sub_conftest_touches_it():
    root = (BACKEND / "tests/conftest.py").read_text()
    assert "def _b432_no_network(" in root and "_NETWORK_GUARD.install()" in root
    for sub in ("tests/unit/conftest.py", "tests/integration/conftest.py"):
        text = (BACKEND / sub).read_text()
        assert "_b432" not in text and "_network_guard" not in text.lower(), f"{sub} overrides or disables the guard"


def test_S8_an_OPT_OUT_is_BY_TEST_ID_and_exempts_ONLY_that_test():
    # the opted-out plant really does reach out, so it is the one whose call is BOUNDED (urlopen, 2 s, to TEST-NET-2)
    target = "tests/unit/b432_plants.py::test_plant_S1_S2_an_IP_fetch_swallowed"
    run, outcomes = _child(["tests/unit/b432_plants.py"], extra_opt_outs={target: "B432: arm — one named test only"})
    assert outcomes[target] == {"PASSED"}, (outcomes.get(target), run.stdout[-1500:])
    other = "tests/unit/b432_plants.py::test_plant_S4_socket_connect_ex"
    assert "ERROR" in outcomes[other], f"the opt-out exempted more than its one test: {outcomes[other]}"


@pytest.mark.parametrize("bad,why", [
    ({"tests/unit/b432_plants.py": "B432: a whole file"}, "names a FILE"),
    ({"tests/unit/b432_plants.py::test_plant_that_does_not_exist": "B432: stale"}, "STALE"),
    ({"tests/unit/b432_plants.py::test_plant_S4_socket_connect": "no citation here"}, "must cite B432"),
])
def test_S8_a_FILE_a_STALE_or_an_UNCITED_opt_out_is_REFUSED_at_collection(bad, why):
    run, _outcomes = _child(["tests/unit/b432_plants.py"], extra_opt_outs=bad)
    assert run.returncode != 0 and why in (run.stdout + run.stderr), (run.returncode, (run.stdout + run.stderr)[-1500:])


def test_S8_every_REAL_opt_out_names_a_test_and_cites_B432():
    from tests.conftest import B432_NETWORK_OPT_OUTS

    for test_id, reason in B432_NETWORK_OPT_OUTS.items():
        assert "::" in test_id and "B432" in reason, (test_id, reason)
