"""One upload, one report with both halves, in a real browser.

The server runs with no ExactSDS credentials reachable from the test, so the
ingredient half takes the supplier path or says it was skipped - which is the
behaviour that matters most here: the wording check must never be lost to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.ui.waits import submit_for_report

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def _upload(page, server, name: str) -> None:
    page.goto(server + "/", wait_until="domcontentloaded")
    page.set_input_files('input[type="file"]', str(FIXTURES / f"{name}.pdf"))
    page.select_option('select[name="regulation"]', "eu_clp")
    submit_for_report(page, page.locator('form button[type="submit"]').first)


@pytest.fixture(scope="module", autouse=True)
def fixtures_exist():
    missing = [n for n in ("pattern_supplier_ingredients", "clean_eu_en")
               if not (FIXTURES / f"{n}.pdf").exists()]
    if missing:
        pytest.skip(f"fixtures not built: {missing}")


def test_one_upload_produces_both_sections(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    # The report's own sections, not words the upload page could also show.
    expect(page.locator(".verdict h2").first).to_be_visible()
    expect(page.locator("#s2")).to_be_visible()
    expect(page.locator("#s3 table.ingredients")).to_be_visible()
    expect(page.locator('#s2 [data-section="mixture"]').first).to_be_visible()


def test_the_wording_half_survives_whatever_the_app_does(page, server):
    """The half that must always work."""
    _upload(page, server, "clean_eu_en")
    assert page.locator(".verdict h2").count() == 1
    assert page.locator("details.block").count() >= 1


def test_a_supplier_sheet_is_read_from_its_own_section_three(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    three = page.locator("#s3")
    assert three.count() == 1
    assert "from Section 3 of this sheet" in three.inner_text()


def test_the_ingredient_section_shows_its_own_counts(page, server):
    """Every ingredient is a row of the table, its result beside it."""
    _upload(page, server, "pattern_supplier_ingredients")
    rows = page.locator("#s3 table.ingredients tbody tr")
    assert rows.count() == 3
    statuses = sorted(rows.nth(i).get_attribute("data-status") for i in range(3))
    assert statuses == ["fix", "ok", "ok"]
    head = page.locator("#s3 table.ingredients thead").inner_text().upper()
    for column in ("INGREDIENT", "CAS", "%", "THIS SHEET SAYS", "ANNEX VI", "RESULT"):
        assert column in head, head
    assert "Missing" in page.locator("#s3").inner_text()


def test_a_sheet_with_no_ingredient_codes_says_so(page, server):
    _upload(page, server, "clean_eu_en")
    three = page.locator("#s3").inner_text()
    assert "nothing to check" in three.lower() or "not reachable" in three.lower()


def test_the_combined_report_screenshot(page, server, shots_dir):
    _upload(page, server, "pattern_supplier_ingredients")
    page.screenshot(path=str(shots_dir / "combined_report.png"), full_page=True)


def test_the_page_still_fits_a_phone(page, server):
    page.set_viewport_size({"width": 390, "height": 900})
    _upload(page, server, "pattern_supplier_ingredients")
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 391, f"the page scrolls sideways at 390px: {width}"


def test_the_wording_filters_leave_the_ingredient_cards_alone(page, server):
    """No filters any more: every result is on the page, in its section."""
    _upload(page, server, "pattern_supplier_ingredients")
    assert page.locator(".filters").count() == 0
    assert page.locator("#s3 table.ingredients tbody tr:visible").count() == 3


# -- the third section ---------------------------------------------------------


def test_one_upload_produces_all_three_sections(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    for anchor in ("#s1", "#s2", "#s3", "#s9", "#s16"):
        expect(page.locator(anchor)).to_be_visible()


def test_the_mixture_section_has_its_own_counts(page, server):
    """The mixture's verdicts are rows of 2.1, with what was calculated from."""
    _upload(page, server, "pattern_supplier_ingredients")
    two = page.locator("#s2")
    statuses = [r.get_attribute("data-status") for r in
                two.locator('[data-section="mixture"]').all()]
    assert "fix" in statuses and "check" in statuses and "ok" in statuses
    assert "Calculated from" in two.inner_text()


def test_a_mixture_card_shows_both_sides_and_the_rule(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    row = page.locator('[data-section="mixture"].problem').first
    text = row.inner_text().lower()      # the headings render in capitals
    assert "section 2 says" in text
    assert "calculated from declared ingredients" in text
    assert "annex i," in text


def test_a_mixture_card_lists_the_contributing_ingredients(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    row = page.locator('[data-section="mixture"].problem').first
    assert row.locator("table.ingredients tbody tr").count() >= 1
    assert "COUNTED AS" in row.inner_text().upper()   # headings render in capitals


def test_the_calculation_trace_is_in_the_technical_block(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    block = page.locator("details.block").filter(
        has=page.locator("summary:has-text('technical details')"))
    block.locator("summary").first.click()
    assert "Calculation trace" in block.first.inner_text()


def test_the_wording_filters_leave_the_mixture_cards_alone(page, server):
    """Each mixture verdict names its section in "What to do"."""
    _upload(page, server, "pattern_supplier_ingredients")
    todo = page.locator(".todo li").all_inner_texts()
    assert any(t.startswith("Section 2: check Target organ toxicity") for t in todo), todo
    assert any(t.startswith("Section 3: add") for t in todo), todo


def test_all_three_sections_fit_a_phone(page, server):
    page.set_viewport_size({"width": 390, "height": 900})
    _upload(page, server, "pattern_supplier_ingredients")
    assert page.evaluate("document.documentElement.scrollWidth") <= 391


def test_the_three_section_screenshot(page, server, shots_dir):
    _upload(page, server, "pattern_supplier_ingredients")
    page.screenshot(path=str(shots_dir / "combined_report.png"), full_page=True)
