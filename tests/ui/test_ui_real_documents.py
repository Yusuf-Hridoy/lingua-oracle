"""The real app exports, through the same page, screenshotted for review.

These documents are company data. They are discovered at run time from
data/validation/, which is gitignored, and this file names none of them - so
nothing about a real product reaches the repository. The suite skips entirely
when that folder is not present, which is the normal state of a fresh clone.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from lingua_oracle.registry import load_registry

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "data" / "validation" / "ui_review"


def _real_cases() -> list[tuple[str, str, str]]:
    try:
        from lingua_oracle.validate import load_cases, validation_dir
    except Exception:  # pragma: no cover - harness not available
        return []
    root = validation_dir()
    if not root.exists():
        return []
    try:
        cases = load_cases().cases
    except Exception:
        return []
    out = []
    for c in cases:
        if c.confirmed and c.file.startswith("app/") and (root / c.file).exists():
            out.append((c.file, c.regulation, c.language or ""))
    return out


REAL = _real_cases()
pytestmark = pytest.mark.skipif(
    not REAL, reason="no confirmed app documents under data/validation/"
)


@pytest.fixture(scope="module")
def real_shots_dir():
    if SHOTS.exists():
        shutil.rmtree(SHOTS)
    SHOTS.mkdir(parents=True, exist_ok=True)
    return SHOTS


@pytest.mark.parametrize(("rel", "regulation", "language"), REAL,
                         ids=[Path(r).stem for r, _, _ in REAL])
def test_real_document_renders(rel, regulation, language, page, server, real_shots_dir):
    from lingua_oracle.validate import validation_dir

    page.goto(server + "/", wait_until="domcontentloaded")
    page.select_option("#regulation", regulation)
    page.select_option("#language", language)
    page.set_input_files("input[name=file]", str(validation_dir() / rel))
    page.click("#check-form button[type=submit]")
    page.wait_for_url(re.compile(r"/reports/"), timeout=60_000)
    page.wait_for_load_state("load")

    # The regulation lives in the collapsed technical block, where inner_text()
    # returns nothing for hidden elements.
    display = load_registry().get(regulation).display_name
    cell = page.locator(
        "//dt[normalize-space()='Regulation']/following-sibling::dd"
    ).first
    shown = (cell.text_content() or "").strip()
    assert shown == display, f"regulation shown as {shown!r}, expected {display!r}"

    # The page must actually render a verdict, not an empty shell.
    assert page.locator(".verdict .banner h2").count() == 1
    assert page.locator("article.issue").count() or \
        page.locator("details.block.good").count(), \
        "neither an issue card nor a list of correct statements"

    page.screenshot(path=str(real_shots_dir / f"{Path(rel).stem}.png"), full_page=True)
