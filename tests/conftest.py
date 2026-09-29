"""Shared fixtures. The whole suite runs offline against pre-built answer keys."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def no_network():
    """Fail loudly if any test tries to open a socket.

    Check time must never touch the network; only the key builders may, and they
    are not exercised here.
    """
    real = socket.socket.connect

    def guard(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"network access attempted during tests: {address}")
        return real(self, address, *args, **kwargs)

    socket.socket.connect = guard
    yield
    socket.socket.connect = real


@pytest.fixture(scope="session", autouse=True)
def fixtures_built():
    """Generate the synthetic PDFs once per session if they are missing."""
    expected = FIXTURES / "clean_eu_da.pdf"
    if not expected.exists():
        from tests.make_fixtures import build_all

        build_all()
    return FIXTURES


@pytest.fixture(scope="session")
def reports_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("reports")


def pdf(name: str) -> str:
    return str(FIXTURES / f"{name}.pdf")
