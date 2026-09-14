"""`B432` — **the test suite cannot reach the network, and says so.**

A network-dependent arm does not only flake: every arm asserting that something did NOT happen becomes satisfiable by the
code path never running at all. `_ticker_price` catches `Exception` around `urlopen` and returns `None`, so a guard that only
RAISES is swallowed exactly the same way and the test stays green (review's measurement). And a guard on `connect` alone
never sees a hostname fetch: name resolution runs first and fails before any connect (measured: `urlopen("http://
example.invalid/")` raised `URLError` in 0.02 s with zero connect calls).

So, process-wide and for every thread (a call on `B437`'s worker thread included):
  * name resolution (`getaddrinfo`, `gethostbyname*`) and every connect shape (`socket.connect`, `connect_ex`,
    `create_connection`, UDP `sendto` and `sendmsg`; asyncio's connections go through these) to anything but LOOPBACK is
    REFUSED;
  * every refused attempt is RECORDED against the running test, and the test FAILS AT TEARDOWN naming `B432` and the target
    — whatever the code under test did with the exception;
  * allowed: `127.0.0.0/8`, `::1`, the name `localhost`, and `AF_UNIX`. Not `0.0.0.0`, not the host's own interfaces.

A test that genuinely needs the network opts out BY TEST ID in `B432_NETWORK_OPT_OUTS` (`tests/conftest.py`), citing `B432`;
a whole-file entry and a stale entry are refused at collection.
"""
from __future__ import annotations

import errno
import ipaddress
import socket
import threading


def is_loopback_host(host: object) -> bool:
    """Loopback by LITERAL, never by resolving: `localhost`, `127.0.0.0/8`, `::1` (and an IPv4-mapped loopback)."""
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if not isinstance(host, str):
        return False
    name = host.strip().strip("[]").split("%", 1)[0]
    if name.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


class NetworkGuard:
    """Installed ONCE per process (`install`); a test is bracketed by `begin` / `end`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: list[str] = []
        self._allow = False
        self._in_test = False
        self._installed = False

    # -- per test ---------------------------------------------------------------------------------------------------------
    def begin(self, *, allow: bool) -> None:
        with self._lock:
            self._attempts, self._allow, self._in_test = [], allow, True

    def end(self) -> list[str]:
        with self._lock:
            attempts, self._attempts, self._allow, self._in_test = self._attempts, [], False, False
        return attempts

    @property
    def allowed(self) -> bool:
        return self._allow

    def refuse(self, what: str, target: object, *, resolution: bool = False):
        text = f"{what} {target!r}"
        with self._lock:
            if self._in_test:
                self._attempts.append(text)
        message = f"B432: outbound network is blocked in the test suite ({text}); patch the call or opt the test out by id"
        if resolution:
            raise socket.gaierror(socket.EAI_NONAME, message)
        raise OSError(errno.ENETUNREACH, message)

    # -- the patches ------------------------------------------------------------------------------------------------------
    def install(self) -> None:
        if self._installed:
            return
        self._installed = True
        guard = self
        real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
        real_sendto, real_sendmsg = socket.socket.sendto, socket.socket.sendmsg
        real_getaddrinfo, real_create_connection = socket.getaddrinfo, socket.create_connection
        real_gethostbyname, real_gethostbyname_ex = socket.gethostbyname, socket.gethostbyname_ex

        def _inet(sock) -> bool:
            return sock.family in (socket.AF_INET, socket.AF_INET6)

        def _host(address):
            return address[0] if isinstance(address, tuple) and address else address

        def connect(self, address):
            if _inet(self) and not guard.allowed and not is_loopback_host(_host(address)):
                guard.refuse("connect", address)
            return real_connect(self, address)

        def connect_ex(self, address):
            if _inet(self) and not guard.allowed and not is_loopback_host(_host(address)):
                try:
                    guard.refuse("connect_ex", address)
                except OSError as exc:
                    return exc.errno
            return real_connect_ex(self, address)

        def sendto(self, data, *args):
            address = args[-1] if args else None
            if _inet(self) and not guard.allowed and not is_loopback_host(_host(address)):
                guard.refuse("sendto", address)
            return real_sendto(self, data, *args)

        def sendmsg(self, buffers, *args):
            address = args[2] if len(args) >= 3 else None     # sendmsg(buffers, ancdata, flags, address)
            if address is not None and _inet(self) and not guard.allowed and not is_loopback_host(_host(address)):
                guard.refuse("sendmsg", address)
            return real_sendmsg(self, buffers, *args)

        def getaddrinfo(host, port, *args, **kwargs):
            if host is not None and not guard.allowed and not is_loopback_host(host):
                guard.refuse("getaddrinfo", host, resolution=True)
            return real_getaddrinfo(host, port, *args, **kwargs)

        def gethostbyname(host):
            if not guard.allowed and not is_loopback_host(host):
                guard.refuse("gethostbyname", host, resolution=True)
            return real_gethostbyname(host)

        def gethostbyname_ex(host):
            if not guard.allowed and not is_loopback_host(host):
                guard.refuse("gethostbyname_ex", host, resolution=True)
            return real_gethostbyname_ex(host)

        def create_connection(address, *args, **kwargs):
            if not guard.allowed and not is_loopback_host(_host(address)):
                guard.refuse("create_connection", address)
            return real_create_connection(address, *args, **kwargs)

        socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto = connect, connect_ex, sendto
        socket.socket.sendmsg = sendmsg
        socket.getaddrinfo, socket.gethostbyname, socket.gethostbyname_ex = getaddrinfo, gethostbyname, gethostbyname_ex
        socket.create_connection = create_connection


GUARD = NetworkGuard()
