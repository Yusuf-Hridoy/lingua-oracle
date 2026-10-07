"""Choosing between candidate products, in a real browser.

Several products could be one uploaded sheet. The report asks which, above the
verdict, and answering fills the Ingredients and Mixture sections on the same
page - nothing is uploaded twice. The application answering here is a
stand-in, but the round trip is real: form post, re-run, re-render.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ui.waits import submit_and_wait_until_gone, submit_for_report

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
SHEET = "pattern_named_with_ingredients"


@pytest.fixture(scope="module", autouse=True)
def fixture_exists():
    if not (FIXTURES / f"{SHEET}.pdf").exists():
        pytest.skip(f"fixture not built: {SHEET}")


def _upload(page, app_server):
    page.goto(app_server + "/", wait_until="domcontentloaded")
    page.set_input_files('input[type="file"]', str(FIXTURES / f"{SHEET}.pdf"))
    page.select_option('select[name="regulation"]', "eu_clp")
    submit_for_report(page, page.locator('form button[type="submit"]').first)


def test_several_candidates_are_offered_above_the_verdict(page, app_server):
    _upload(page, app_server)
    picker = page.locator("form.picker")
    assert picker.count() == 1
    assert picker.locator("input[name=product_id]").count() == 2
    # In Section 1, the product match, ahead of everything that depends on it.
    one = page.locator("#s1")
    assert "Which product is this?" in one.inner_text()
    body = page.inner_text("body")
    assert body.index("Which product is this?") < body.index("Section 2 · Hazards")
    assert "Choose the product above" in body


def _choose(page, product_id: int) -> None:
    """Pick one candidate by its id, whatever order they were offered in."""
    page.locator(f'form.picker input[name=product_id][value="{product_id}"]').check()
    submit_and_wait_until_gone(
        page, page.locator("form.picker button[type=submit]"), "form.picker")


def test_choosing_a_product_fills_both_sections_on_the_same_page(
        page, app_server):
    _upload(page, app_server)
    before = page.url
    _choose(page, 4101)

    assert page.url == before, "the choice should land back on the same report"
    assert page.locator("form.picker").count() == 0
    three = page.locator("#s3").inner_text()
    two = page.locator("#s2").inner_text()
    assert "ExactSDS record" in three
    assert page.locator("#s3 table.ingredients tbody tr").count() >= 1
    assert "Calculated from" in two
    assert "Regulation (EC) No 1272/2008" in two


def test_the_chosen_products_own_composition_is_what_was_checked(
        page, app_server):
    """Each candidate holds a different substance, so the page says which one
    was checked and could not have come from the other."""
    _upload(page, app_server)
    _choose(page, 4102)
    # The page, not just what is on screen: a substance with no Annex VI entry
    # is listed inside a closed details block, and it is still the answer.
    body = page.content()
    assert "7664-93-9" in body
    assert "67-64-1" not in body


def test_the_choice_is_remembered_for_this_report(page, app_server):
    _upload(page, app_server)
    _choose(page, 4101)
    url = page.url
    page.goto(url, wait_until="domcontentloaded")
    assert page.locator("form.picker").count() == 0
    assert "67-64-1" in page.content()
