"""Shared fixtures. The whole suite runs offline against pre-built answer keys."""

from __future__ import annotations

import hashlib
import json
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


#: Records which fixtures the current make_fixtures.py produced. Keyed on a
#: hash of that file, so adding or changing a fixture rebuilds on the next run
#: instead of silently testing against a stale set.
STAMP = FIXTURES / ".build-stamp.json"
MAKER = Path(__file__).parent / "make_fixtures.py"


def _fixtures_are_current() -> bool:
    """True when the built set matches the generator that is on disk.

    Checking one well-known file was not enough: on a fresh clone with an older
    fixture set, clean_eu_da.pdf existed while a newly added fixture did not, so
    nothing was rebuilt and the test that needed it failed. Both halves matter -
    the generator's hash catches a changed fixture, the file list catches a
    deleted one.
    """
    if not STAMP.exists():
        return False
    try:
        stamp = json.loads(STAMP.read_text())
    except (OSError, ValueError):
        return False
    if stamp.get("digest") != hashlib.sha256(MAKER.read_bytes()).hexdigest():
        return False
    return all((FIXTURES / name).exists() for name in stamp.get("files", []))


@pytest.fixture(scope="session", autouse=True)
def fixtures_built():
    """Generate the synthetic PDFs once per session, whenever they are stale."""
    if not _fixtures_are_current():
        from tests.make_fixtures import build_all

        built = build_all()
        STAMP.write_text(json.dumps({
            "digest": hashlib.sha256(MAKER.read_bytes()).hexdigest(),
            "files": sorted(p.name for p in built.values()),
        }, indent=1))
    return FIXTURES


@pytest.fixture(scope="session")
def reports_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("reports")


def pdf(name: str) -> str:
    return str(FIXTURES / f"{name}.pdf")
