"""Runs the real server in a subprocess and drives it with a real browser.

Nothing here stubs the app: `lingua serve` is started the way a user starts it,
the file goes through the upload form, and the assertions are made against the
HTML the browser received.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "reports" / "ui_review"

pytest.importorskip(
    "playwright",
    reason="UI tests need Playwright: uv pip install playwright && playwright install chromium",
)


def _stop(proc: subprocess.Popen) -> None:
    """Signal the whole group, so uvicorn goes with its parent."""
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        if proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal_number)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def server(tmp_path_factory) -> str:
    """Start `lingua serve` on a free port and yield its base URL."""
    env = dict(os.environ)
    # Reports written by the browser runs go to a temp dir, not the repo's.
    env["LINGUA_REPORTS_DIR"] = str(tmp_path_factory.mktemp("ui-reports"))
    # No ExactSDS from the browser suite. It was reaching the real application
    # on every upload - a two-and-a-half second login each time, which took the
    # suite from thirty seconds to three and a half minutes - and a test suite
    # has no business depending on a live external service. The ingredient
    # section still runs: it reads the sheet's own Section 3, and says the
    # application was not consulted. The matched-product path is covered
    # without a browser, in tests/test_combined_report.py.
    env["LINGUA_EXACTSDS"] = "off"
    yield from _serve(env)


def _serve(env: dict[str, str]):
    """Run the server the way a user runs it, and yield its base URL."""
    import tempfile

    port = _free_port()
    env.setdefault("LINGUA_REPORTS_DIR", tempfile.mkdtemp(prefix="ui-reports-"))
    # Its own process group: "uv run" spawns uvicorn as a child, and
    # terminating only the parent leaves the server alive holding its port and
    # competing for the machine. Interrupted runs used to leak one each time,
    # which showed up later as goto timeouts in a perfectly good suite.
    proc = subprocess.Popen(
        ["uv", "run", "lingua", "serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            out = (proc.stdout.read() or b"").decode(errors="replace")
            raise RuntimeError(f"lingua serve exited early:\n{out[-3000:]}")
        try:
            with urllib.request.urlopen(base + "/", timeout=2) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    else:
        proc.kill()
        raise RuntimeError("lingua serve did not come up within 90s")
    try:
        yield base
    finally:
        _stop(proc)


@pytest.fixture(scope="session")
def app_server():
    """A `lingua serve` wired to a stand-in ExactSDS, for the picker flow.

    Kept apart from the main `server` fixture, which stays switched off: this
    one costs a second process and only two tests need an application to
    answer.
    """
    from tests.ui.stub_exactsds import start

    base, stub = start()
    env = dict(os.environ)
    env["LINGUA_EXACTSDS"] = "on"
    env["EXACTSDS_URL"] = base
    env["EXACTSDS_USER"] = "nobody@example.invalid"
    env["EXACTSDS_PASSWORD"] = "not-a-password"
    try:
        yield from _serve(env)
    finally:
        stub.shutdown()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    # The review page remembers answers in localStorage. Clearing it before any
    # page script runs keeps each test independent of the ones before it,
    # without a reload to race against.
    ctx.add_init_script("try { localStorage.clear(); } catch (e) {}")
    pg = ctx.new_page()
    try:
        yield pg
    finally:
        ctx.close()


@pytest.fixture(scope="session")
def shots_dir():
    if SHOTS.exists():
        shutil.rmtree(SHOTS)
    SHOTS.mkdir(parents=True, exist_ok=True)
    return SHOTS
