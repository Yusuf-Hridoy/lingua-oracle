"""Shared fixtures. The whole suite runs offline against pre-built answer keys."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# No test talks to ExactSDS, whatever .env holds. A test of the application
# path passes a stand-in client, and the few that need the switch on set it
# themselves. Before this, one test was resolving the staging host from .env
# on every run, and passing, because the client treats a failure as "offline".
os.environ["LINGUA_EXACTSDS"] = "off"

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

#: Every attempt to reach a host other than this machine, as "kind: target".
#: The guards record before they refuse, so an attempt is caught even where the
#: code under test swallows the refusal - the ExactSDS client, the pipeline's
#: ingredient half and `sources check-updates` all turn a connection error into
#: a quiet "unavailable", which is the right thing in production and exactly
#: what let a lookup through here. Each test fails if its list is not empty.
NETWORK_ATTEMPTS: list[str] = []


class NetworkBlocked(OSError):
    """Raised in place of a real connection. An OSError, so callers see a
    connection failure rather than something they would never meet in use."""


def _local(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    return host is None or host in _LOOPBACK or str(host).startswith("127.")


def _refuse(kind: str, target) -> None:
    NETWORK_ATTEMPTS.append(f"{kind}: {target}")
    raise NetworkBlocked(f"network access attempted during tests ({kind}: {target})")


@pytest.fixture(scope="session", autouse=True)
def no_network():
    """Refuse every connection and name lookup that leaves this machine.

    Check time must never touch the network; only the key builders may, and no
    test runs them against a real publisher. Loopback stays open for the
    browser tests' own server, and Unix sockets are local by definition.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname

    def connect(self, address, *args, **kwargs):
        if self.family != getattr(socket, "AF_UNIX", None):
            host = address[0] if isinstance(address, tuple) else address
            if not _local(host):
                _refuse("connect", address)
        return real_connect(self, address, *args, **kwargs)

    def connect_ex(self, address, *args, **kwargs):
        if self.family != getattr(socket, "AF_UNIX", None):
            host = address[0] if isinstance(address, tuple) else address
            if not _local(host):
                _refuse("connect", address)
        return real_connect_ex(self, address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if not _local(host):
            _refuse("dns", host)
        return real_getaddrinfo(host, *args, **kwargs)

    def gethostbyname(host):
        if not _local(host):
            _refuse("dns", host)
        return real_gethostbyname(host)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    yield
    socket.socket.connect = real_connect
    socket.socket.connect_ex = real_connect_ex
    socket.getaddrinfo = real_getaddrinfo
    socket.gethostbyname = real_gethostbyname
    if NETWORK_ATTEMPTS:
        pytest.fail("network access attempted outside any test: "
                    + "; ".join(NETWORK_ATTEMPTS), pytrace=False)


@pytest.fixture(autouse=True)
def _fail_on_network_attempt(no_network):
    """Fail the test that tried, even if the code it ran caught the refusal."""
    NETWORK_ATTEMPTS.clear()
    yield
    attempts = list(NETWORK_ATTEMPTS)
    NETWORK_ATTEMPTS.clear()
    if attempts:
        pytest.fail("network access attempted: " + "; ".join(attempts),
                    pytrace=False)


#: Records which fixtures the current inputs produced. Keyed on a hash of
#: everything they are built from, so a change to any of it rebuilds them on
#: the next run instead of silently testing against a stale set.
STAMP = FIXTURES / ".build-stamp.json"
MAKER = Path(__file__).parent / "make_fixtures.py"
DATA = Path(__file__).resolve().parents[1] / "data"


def _inputs_digest() -> str:
    """Hash of every file a fixture is built from.

    The generator, and the answer keys it reads the official wording out of.
    Hashing the generator alone was not enough: amending P280 in the keys
    changed what a correct sheet says, the fixtures kept the old wording, and
    the suite passed against documents that no longer matched the law.
    """
    digest = hashlib.sha256()
    digest.update(MAKER.read_bytes())
    for path in sorted((DATA / "answer_keys").rglob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    for name in ("regulations.yaml", "ghs_index/en.json"):
        path = DATA / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


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
    if stamp.get("digest") != _inputs_digest():
        return False
    return all((FIXTURES / name).exists() for name in stamp.get("files", []))


@pytest.fixture(scope="session", autouse=True)
def fixtures_built():
    """Generate the synthetic PDFs once per session, whenever they are stale."""
    if not _fixtures_are_current():
        from tests.make_fixtures import build_all

        built = build_all()
        STAMP.write_text(json.dumps({
            "digest": _inputs_digest(),
            "files": sorted(p.name for p in built.values()),
        }, indent=1))
    return FIXTURES


@pytest.fixture(scope="session")
def reports_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("reports")


def pdf(name: str) -> str:
    return str(FIXTURES / f"{name}.pdf")
