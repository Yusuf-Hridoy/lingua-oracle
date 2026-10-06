"""One upload, one report with both halves, in a real browser.

The server runs with no ExactSDS credentials reachable from the test, so the
ingredient half takes the supplier path or says it was skipped - which is the
behaviour that matters most here: the wording check must never be lost to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def _upload(page, server, name: str) -> None:
    page.goto(server + "/", wait_until="domcontentloaded")
    page.set_input_files('input[type="file"]', str(FIXTURES / f"{name}.pdf"))
    page.select_option('select[name="regulation"]', "eu_clp")
    page.locator('form button[type="submit"]').first.click()
    page.wait_for_load_state("domcontentloaded")


@pytest.fixture(scope="module", autouse=True)
def fixtures_exist():
    missing = [n for n in ("pattern_supplier_ingredients", "clean_eu_en")
               if not (FIXTURES / f"{n}.pdf").exists()]
    if missing:
        pytest.skip(f"fixtures not built: {missing}")


def test_one_upload_produces_both_sections(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    body = page.inner_text("body")
    assert "Wording" in body
    assert "Ingredients" in body


def test_the_wording_half_survives_whatever_the_app_does(page, server):
    """The half that must always work."""
    _upload(page, server, "clean_eu_en")
    assert page.locator(".verdict h2").count() == 1
    assert page.locator("details.block").count() >= 1


def test_a_supplier_sheet_is_read_from_its_own_section_three(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    heading = page.locator("#ingredients")
    assert heading.count() == 1
    assert "from Section 3 of this sheet" in heading.inner_text()


def test_the_ingredient_section_shows_its_own_counts(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    stats = page.locator(".verdict.compact .stats").first.inner_text()
    assert "Under-classified" in stats
    assert "Matches Annex VI" in stats


def test_a_sheet_with_no_ingredient_codes_says_so(page, server):
    _upload(page, server, "clean_eu_en")
    body = page.inner_text("body")
    assert "nothing to check" in body.lower() or "not reachable" in body.lower()
    assert "Ingredients" in body


def test_the_combined_report_screenshot(page, server, shots_dir):
    _upload(page, server, "pattern_supplier_ingredients")
    page.screenshot(path=str(shots_dir / "combined_report.png"), full_page=True)


def test_the_page_still_fits_a_phone(page, server):
    page.set_viewport_size({"width": 390, "height": 900})
    _upload(page, server, "pattern_supplier_ingredients")
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 391, f"the page scrolls sideways at 390px: {width}"


def test_the_wording_filters_leave_the_ingredient_cards_alone(page, server):
    """The filters belong to the Wording section, and say so by what they touch."""
    _upload(page, server, "pattern_supplier_ingredients")
    ingredient_cards = page.locator('article.issue:not([data-section="wording"])')
    before = ingredient_cards.count()
    page.click('.filters button[data-filter="must"]')
    after = page.locator(
        'article.issue:not([data-section="wording"]):not([hidden])').count()
    assert after == before


# -- the third section ---------------------------------------------------------


def test_one_upload_produces_all_three_sections(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    body = page.inner_text("body")
    for heading in ("Wording", "Ingredients", "Mixture"):
        assert heading in body, heading


def test_the_mixture_section_has_its_own_counts(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    stats = page.locator("#mixture ~ .verdict.compact .stats").first.inner_text()
    assert "Inconsistent" in stats
    assert "Can’t tell" in stats or "Can't tell" in stats
    assert "Consistent" in stats
    assert "undisclosed" in stats


def test_a_mixture_card_shows_both_sides_and_the_rule(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    card = page.locator('article.issue[data-section="mixture"]').first
    text = card.inner_text().lower()      # the headings render in capitals
    assert "section 2 says" in text
    assert "calculation gives" in text
    assert "annex i," in text


def test_a_mixture_card_lists_the_contributing_ingredients(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    card = page.locator('article.issue[data-section="mixture"]').first
    assert card.locator(".minor-table tbody tr").count() >= 1
    assert "Counted as" in card.inner_text()


def test_the_calculation_trace_is_in_the_technical_block(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    block = page.locator("details.block").filter(
        has=page.locator("summary:has-text('technical details')"))
    block.locator("summary").first.click()
    assert "Calculation trace" in block.first.inner_text()


def test_the_wording_filters_leave_the_mixture_cards_alone(page, server):
    _upload(page, server, "pattern_supplier_ingredients")
    mixture = 'article.issue[data-section="mixture"]'
    before = page.locator(mixture).count()
    page.click('.filters button[data-filter="must"]')
    assert page.locator(f"{mixture}:not([hidden])").count() == before


def test_all_three_sections_fit_a_phone(page, server):
    page.set_viewport_size({"width": 390, "height": 900})
    _upload(page, server, "pattern_supplier_ingredients")
    assert page.evaluate("document.documentElement.scrollWidth") <= 391


def test_the_three_section_screenshot(page, server, shots_dir):
    _upload(page, server, "pattern_supplier_ingredients")
    page.screenshot(path=str(shots_dir / "combined_report.png"), full_page=True)
