"""The review page itself has to work, including the download button.

Every assertion here goes through Playwright's `expect`, which retries until it
holds or times out. There are no sleeps and no reloads to race against: the
browser context clears localStorage before any page script runs, so each test
starts from an empty page regardless of what ran before it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from playwright.sync_api import expect

from tests.ui.manifest import CASES

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "reports" / "ui_review"


@pytest.fixture(scope="module")
def review_page_built():
    from tests.ui.build_review_page import build

    return build()


def test_download_button_writes_valid_yaml(page, review_page_built, tmp_path):
    page.goto(review_page_built.as_uri(), wait_until="load")

    ok = page.locator('input[name="v-clean_eu_da"][value="ok"]')
    expect(ok).to_be_attached()
    ok.check()
    page.locator("#n-clean_eu_da").fill("Reads clearly. No jargon in the way.")

    bad = page.locator('input[name="v-defect_a02_hazard"][value="problem"]')
    expect(bad).to_be_attached()
    bad.check()
    page.locator("#n-defect_a02_hazard").fill('Quote " and \\ should survive')

    with page.expect_download() as info:
        page.click("#dl")
    download = info.value
    assert download.suggested_filename == "ui_review_notes.yaml"
    target = tmp_path / "ui_review_notes.yaml"
    download.save_as(str(target))

    notes = yaml.safe_load(target.read_text(encoding="utf-8"))["notes"]
    assert notes["clean_eu_da"]["verdict"] == "ok"
    assert notes["clean_eu_da"]["note"].startswith("Reads clearly")
    assert notes["defect_a02_hazard"]["verdict"] == "problem"
    assert notes["defect_a02_hazard"]["note"] == 'Quote " and \\ should survive'
    # Untouched cards are present but empty, so the file is a complete checklist.
    assert notes["defect_a07_broken"] == {"verdict": "", "note": ""}


def test_every_case_has_a_card(review_page_built):
    """The page is built from the manifest, not from whatever happens to exist.

    Building only the cards whose screenshot was already on disk made this page
    depend on whether the browser tests had run first. On a cold checkout there
    were no screenshots, so there were no cards, so the controls this file drives
    did not exist - and a second run passed because the first had left images
    behind. The manifest is the source of truth now.
    """
    html = review_page_built.read_text(encoding="utf-8")
    missing = [c.name for c in CASES if f'id="c-{c.name}"' not in html]
    assert missing == [], missing


def test_every_screenshot_on_disk_is_shown(review_page_built):
    html = review_page_built.read_text(encoding="utf-8")
    missing = [p.name for p in sorted(SHOTS.glob("*.png"))
               if f'src="{p.name}"' not in html]
    assert missing == [], missing


def test_counter_tracks_progress(page, review_page_built):
    page.goto(review_page_built.as_uri(), wait_until="load")
    # The total also counts the real-document cards, which are present only on a
    # machine that has them. Assert on the progress, not on the total.
    counter = page.locator("#counter")
    expect(counter).to_have_text(re.compile(r"^0 of \d+ reviewed$"))

    first = page.locator('input[name="v-clean_eu_en"][value="ok"]')
    expect(first).to_be_attached()
    first.check()
    expect(counter).to_have_text(re.compile(r"^1 of \d+ reviewed$"))

    second = page.locator('input[name="v-clean_eu_da"][value="problem"]')
    second.check()
    expect(counter).to_have_text(re.compile(r"^2 of \d+ reviewed$"))


def test_answers_do_not_leak_between_tests(page, review_page_built):
    """If localStorage were shared, this would see the previous test's answers."""
    page.goto(review_page_built.as_uri(), wait_until="load")
    expect(page.locator("#counter")).to_have_text(re.compile(r"^0 of \d+ reviewed$"))
