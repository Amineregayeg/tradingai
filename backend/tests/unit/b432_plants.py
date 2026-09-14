"""`B432`'s PLANTS for the unit directory. NOT collected by the suite — the file name matches no test pattern — and run
EXPLICITLY, in a child pytest, by `test_b432_network_guard.py`, which reads each outcome.

Every `plant_*` SWALLOWS whatever the guard raises, exactly as `_ticker_price` does: the guard must fail the TEST anyway
(at teardown). Every `mustmiss_*` is an allowed connection that must pass cleanly. The functions are named `test_*` so a
child run given this file collects them.
"""
import asyncio
import socket
import threading
import urllib.request

import pytest

TEST_NET = "198.51.100.7"   # TEST-NET-2: an address that is never a real host


def _swallow(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - the point: code under test that swallows the refusal
        return None


def test_plant_S1_S2_an_IP_fetch_swallowed():
    _swallow(lambda: urllib.request.urlopen(f"http://{TEST_NET}/", timeout=2))


async def test_plant_S1_a_new_fetch_INSIDE_a_driven_tick(monkeypatch):
    from app.services.live import crypto_loop as mod

    loop = mod.LiveCryptoLoop(broker_mode="paper")
    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: 100.0)   # the known route is patched; a NEW one is not

    async def _session_end_with_a_new_fetch(*_a, **_k):
        _swallow(lambda: urllib.request.urlopen(f"http://{TEST_NET}/new-route", timeout=2))

    async def _no_bars(*_a, **_k):
        import pandas as pd

        return pd.DataFrame()

    async def _noop(*_a, **_k):
        return None

    for name in ("push_tick", "push_position_close"):
        monkeypatch.setattr(mod.ws_manager, name, _noop)
    monkeypatch.setattr(loop, "_close_at_session_end", _session_end_with_a_new_fetch)
    monkeypatch.setattr(loop, "_fetch_bars", _no_bars)
    await asyncio.wait_for(loop._tick_symbol("BTC/USD", "BTCUSDT"), 10)


def test_plant_S3_a_HOSTNAME_fetch_swallowed():
    _swallow(lambda: urllib.request.urlopen("http://example.invalid/", timeout=2))


def test_plant_S3_gethostbyname_swallowed():
    _swallow(lambda: socket.gethostbyname("example.invalid"))


def test_plant_S3_gethostbyname_ex_swallowed():
    _swallow(lambda: socket.gethostbyname_ex("example.invalid"))


def test_plant_S4_socket_connect():
    s = socket.socket()
    s.settimeout(2)   # bounded: with connect UNGUARDED (the S-4a mutant) a blackholed connect must not outlast the child run
    try:
        _swallow(lambda: s.connect((TEST_NET, 80)))
    finally:
        s.close()


def test_plant_S4_socket_connect_ex():
    s = socket.socket()
    s.settimeout(2)
    try:
        _swallow(lambda: s.connect_ex((TEST_NET, 80)))
    finally:
        s.close()


def test_plant_S4_create_connection():
    _swallow(lambda: socket.create_connection((TEST_NET, 80), timeout=2))


async def test_plant_S4_asyncio_open_connection():
    try:
        await asyncio.wait_for(asyncio.open_connection(TEST_NET, 80), 3)
    except Exception:  # noqa: BLE001
        pass


async def test_plant_S4_asyncio_sock_connect():
    s = socket.socket()
    s.setblocking(False)
    try:
        await asyncio.wait_for(asyncio.get_running_loop().sock_connect(s, (TEST_NET, 80)), 3)
    except Exception:  # noqa: BLE001
        pass
    finally:
        s.close()


def test_plant_S4_udp_sendto():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _swallow(lambda: s.sendto(b"x", (TEST_NET, 53)))
    finally:
        s.close()


def test_plant_S4_udp_sendmsg():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _swallow(lambda: s.sendmsg([b"x"], [], 0, (TEST_NET, 53)))
    finally:
        s.close()


async def test_plant_S5_a_fetch_on_an_ACCOUNT_WORKER_thread():
    from app.services.broker.alpaca import account_executor

    executor = account_executor("b432-plant")
    await asyncio.wait_for(executor.run(lambda: _swallow(
        lambda: urllib.request.urlopen(f"http://{TEST_NET}/worker", timeout=2))), 10)


def test_plant_S10_the_ZERO_address():
    s = socket.socket()
    s.settimeout(2)
    try:
        _swallow(lambda: s.connect(("0.0.0.0", 9)))
    finally:
        s.close()


def test_plant_S10_a_PRIVATE_non_loopback_address():
    s = socket.socket()
    s.settimeout(2)
    try:
        _swallow(lambda: s.connect(("10.255.255.1", 9)))
    finally:
        s.close()


def _own_non_loopback_ipv4() -> list[str]:
    """This machine's OWN interface addresses, read from the kernel (SIOCGIFADDR) — no resolution, no packet sent."""
    import fcntl
    import ipaddress
    import struct

    found = []
    for _index, name in socket.if_nameindex():
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack("256s", name[:15].encode()))
        except OSError:
            continue
        finally:
            probe.close()
        address = socket.inet_ntoa(packed[20:24])
        if not ipaddress.ip_address(address).is_loopback:
            found.append(address)
    return found


def test_plant_S10_the_HOST_S_OWN_interface_address():
    """Not "local": a connect to this machine's own non-loopback address is outbound as far as the suite is concerned.
    With no such interface the plant FAILS without naming B432, so the arm reading it cannot pass vacuously."""
    own = _own_non_loopback_ipv4()
    assert own, "no non-loopback IPv4 interface on this host: the plant cannot run"
    s = socket.socket()
    s.settimeout(2)
    try:
        _swallow(lambda: s.connect((own[0], 9)))
    finally:
        s.close()


def test_plant_S11_resolving_a_real_name():
    _swallow(lambda: socket.getaddrinfo("example.invalid", 80))


def _loopback_echo(host: str, family=socket.AF_INET):
    server = socket.socket(family, socket.SOCK_STREAM)
    server.bind((host, 0))
    server.listen(1)
    port = server.getsockname()[1]
    accepted = threading.Thread(target=lambda: server.accept()[0].close(), daemon=True)
    accepted.start()
    client = socket.socket(family, socket.SOCK_STREAM)
    client.settimeout(3)
    client.connect((host, port))
    client.close()
    accepted.join(3)
    server.close()


def test_mustmiss_S6_loopback_127_0_0_1():
    _loopback_echo("127.0.0.1")


def test_mustmiss_S10_loopback_127_0_0_2_the_whole_slash_8():
    _loopback_echo("127.0.0.2")


def test_mustmiss_S10_ipv6_loopback():
    if not socket.has_ipv6:
        pytest.skip("IPv6 unavailable on this host")
    try:
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        probe.bind(("::1", 0))
        probe.close()
    except OSError:
        pytest.skip("::1 is not bindable on this host")
    _loopback_echo("::1", socket.AF_INET6)


def test_mustmiss_S10_af_unix_socketpair(tmp_path):
    """An AF_UNIX CONNECT (a socketpair never calls connect, so it could not see a guard that blocks AF_UNIX)."""
    path = str(tmp_path / "b432.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    accepted = threading.Thread(target=lambda: server.accept()[0].close(), daemon=True)
    accepted.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(3)
    client.connect(path)
    client.close()
    accepted.join(3)
    server.close()


def test_mustmiss_S11_localhost_resolves():
    assert socket.getaddrinfo("localhost", 80)
