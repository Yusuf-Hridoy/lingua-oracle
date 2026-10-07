"""The suite's network guard: nothing leaves this machine, even quietly.

Each test that provokes the guard empties NETWORK_ATTEMPTS itself before it
ends - otherwise the guard would, correctly, fail it.
"""

from __future__ import annotations

import contextlib
import socket

import httpx
import pytest

from tests.conftest import NETWORK_ATTEMPTS, NetworkBlocked


def _taken() -> list[str]:
    attempts = list(NETWORK_ATTEMPTS)
    NETWORK_ATTEMPTS.clear()
    return attempts


def test_a_name_lookup_is_refused_and_recorded():
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("example.invalid", 443)
    assert _taken() == ["dns: example.invalid"]


def test_a_connection_by_address_is_refused_and_recorded():
    with socket.socket() as s, pytest.raises(NetworkBlocked):
        s.connect(("192.0.2.1", 443))  # TEST-NET-1, never routed
    assert _taken() == ["connect: ('192.0.2.1', 443)"]


def test_an_attempt_the_code_swallows_is_still_recorded():
    # What the ExactSDS client and check-updates do with a connection error.
    with contextlib.suppress(Exception):
        httpx.get("https://publications.europa.eu/webapi/rdf/sparql", timeout=1)
    assert _taken() == ["dns: publications.europa.eu"]


def test_loopback_is_allowed():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=1):
            pass
    assert socket.getaddrinfo("localhost", 80)
    assert NETWORK_ATTEMPTS == []


def test_exactsds_is_off_for_the_whole_suite():
    from lingua_oracle.ingredients.client import disabled

    assert disabled()


def test_no_proxy_can_carry_a_request_past_the_guard():
    import os

    assert not any(os.environ.get(name) for name in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy"))
