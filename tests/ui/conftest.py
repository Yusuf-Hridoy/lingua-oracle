"""Runs the real server in a subprocess and drives it with a real browser.

Nothing here stubs the app: `lingua serve` is started the way a user starts it,
the file goes through the upload form, and the assertions are made against the
HTML the browser received.
"""

from __future__ import annotations

import os
import shutil
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def server(tmp_path_factory) -> str:
    """Start `lingua serve` on a free port and yield its base URL."""
    port = _free_port()
    env = dict(os.environ)
    # Reports written by the browser runs go to a temp dir, not the repo's.
    env["LINGUA_REPORTS_DIR"] = str(tmp_path_factory.mktemp("ui-reports"))
    proc = subprocess.Popen(
        ["uv", "run", "lingua", "serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


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
