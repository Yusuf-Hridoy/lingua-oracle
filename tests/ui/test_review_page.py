"""The review page itself has to work, including the download button."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "reports" / "ui_review" / "index.html"


@pytest.fixture(scope="module")
def review_page_built():
    from tests.ui.build_review_page import build

    return build()


def test_download_button_writes_valid_yaml(page, review_page_built, tmp_path):
    page.goto(review_page_built.as_uri(), wait_until="load")

    # Fill one card in, the way a reviewer would.
    page.locator('input[name="v-clean_eu_da"][value="ok"]').check()
    page.locator("#n-clean_eu_da").fill("Reads clearly. No jargon in the way.")
    page.locator('input[name="v-defect_a02_hazard"][value="problem"]').check()
    page.locator("#n-defect_a02_hazard").fill('Quote " and \\ should survive')

    with page.expect_download() as info:
        page.click("#dl")
    download = info.value
    assert download.suggested_filename == "ui_review_notes.yaml"
    target = tmp_path / "ui_review_notes.yaml"
    download.save_as(str(target))

    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    notes = data["notes"]
    assert notes["clean_eu_da"]["verdict"] == "ok"
    assert notes["clean_eu_da"]["note"].startswith("Reads clearly")
    assert notes["defect_a02_hazard"]["verdict"] == "problem"
    assert notes["defect_a02_hazard"]["note"] == 'Quote " and \\ should survive'
    # Untouched cards are present but empty, so the file is a complete checklist.
    assert notes["defect_a07_broken"] == {"verdict": "", "note": ""}


def test_every_screenshot_has_a_card(review_page_built):
    html = review_page_built.read_text(encoding="utf-8")
    for png in sorted((ROOT / "reports" / "ui_review").glob("*.png")):
        assert f'src="{png.name}"' in html, f"{png.name} has no card"


def test_counter_tracks_progress(page, review_page_built):
    page.goto(review_page_built.as_uri(), wait_until="load")
    page.click("#clear")
    page.wait_for_load_state("load")
    start = page.locator("#counter").inner_text()
    assert start.startswith("0 of ")
    page.locator('input[name="v-clean_eu_en"][value="ok"]').check()
    assert page.locator("#counter").inner_text().startswith("1 of ")
