"""The ingredient check in a real browser.

The run itself reads the ExactSDS API, so these tests never start one: a
synthetic run - fictional products, fictional substance names, real Annex VI
codes because they are public law - is written to the runs directory and the
pages are driven over it. The run machinery is covered without a browser in
tests/test_ingredient_app.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "reports" / "ingredients"
RUN_ID = "uitest-synthetic"

SYNTHETIC = {
    "started_at": "2026-10-06T09:00:00+00:00",
    "annex_vi_source": "02008R1272-20260701",
    "counts": {"products": 3, "substances": 4, "ingredients": 4,
               "with_entry": 3, "fix": 1, "info": 1, "ok": 1, "not_checked": 1,
               "uses": 5, "uses_under_classified": 2,
               "inconsistent_substances": 1},
    "not_checked_reasons": {"no_harmonised_entry": 1},
    "missing_code_patterns": [["H336", 2], ["EUH066", 2]],
    "missing_code_by_substance": [["EUH066", 1], ["H336", 1]],
    "data_sources": {"stub": 4},
    "under_classified_reach": [["67-64-1", 2]],
    "substances": [
        {"cas": "67-64-1", "name": "<fictional substance A>",
         "product_count": 3, "uses_checked": 3, "uses_under_classified": 2,
         "missing_code_counts": {"H336": 2, "EUH066": 2},
         "distinct_code_sets": 2,
         "code_sets": [
             {"codes": ["H225", "H319", "H335"], "products": [101, 102],
              "count": 2, "missing": ["EUH066", "H336"], "status": "fix"},
             {"codes": ["EUH066", "H225", "H319", "H336"], "products": [103],
              "count": 1, "missing": [], "status": "ok"}],
         "affected_products": [101, 102], "inconsistent": True,
         "harmonised_codes": ["H225", "H319", "H336", "EUH066"],
         "status": "fix", "reason": None, "entry_index_no": "606-001-00-8",
         "missing_codes": ["EUH066", "H336"],
         "source_ref": "Annex VI, Table 3, Index No 606-001-00-8 "
                       "(02008R1272-20260701)",
         "data_source": "stub"},
        {"cas": "1333-74-0", "name": "<fictional substance B>",
         "product_count": 1, "uses_checked": 1, "uses_under_classified": 0,
         "missing_code_counts": {}, "distinct_code_sets": 2,
         "code_sets": [
             {"codes": ["H220"], "products": [101], "count": 1,
              "missing": [], "status": "ok"},
             {"codes": ["H220", "H280"], "products": [102], "count": 1,
              "missing": [], "status": "ok"}],
         "affected_products": [], "inconsistent": True,
         "harmonised_codes": ["H220"], "status": "ok", "reason": None,
         "entry_index_no": "001-001-00-9", "missing_codes": [],
         "source_ref": "Annex VI, Table 3, Index No 001-001-00-9 "
                       "(02008R1272-20260701)",
         "data_source": "stub"},
        {"cas": "7439-93-2", "name": "<fictional substance C>",
         "product_count": 1, "uses_checked": 1, "uses_under_classified": 0,
         "missing_code_counts": {}, "distinct_code_sets": 1,
         "code_sets": [{"codes": ["H260", "H314", "H319"], "products": [103],
                        "count": 1, "missing": [], "status": "info"}],
         "affected_products": [], "inconsistent": False,
         "harmonised_codes": ["H260", "H314"], "status": "info",
         "reason": None, "entry_index_no": "003-001-00-4",
         "missing_codes": [],
         "source_ref": "Annex VI, Table 3, Index No 003-001-00-4 "
                       "(02008R1272-20260701)",
         "data_source": "stub"},
        {"cas": "7732-18-5", "name": "<fictional substance D>",
         "product_count": 1, "uses_checked": 1, "uses_under_classified": 0,
         "missing_code_counts": {}, "distinct_code_sets": 1,
         "code_sets": [{"codes": [], "products": [103], "count": 1,
                        "missing": [], "status": "not_checked"}],
         "affected_products": [], "inconsistent": False,
         "harmonised_codes": [], "status": "not_checked",
         "reason": "no_harmonised_entry", "entry_index_no": None,
         "missing_codes": [], "source_ref": "", "data_source": "stub"},
    ],
}


@pytest.fixture(scope="module", autouse=True)
def synthetic_run():
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{RUN_ID}.json"
    path.write_text(json.dumps(SYNTHETIC, indent=1), encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _open(page, server):
    page.goto(f"{server}/ingredients/runs/{RUN_ID}", wait_until="domcontentloaded")


# -- the way in ----------------------------------------------------------------


def test_the_navigation_offers_ingredients(page, server):
    page.goto(server + "/", wait_until="domcontentloaded")
    link = page.locator('.nav a[href="/ingredients"]')
    assert link.count() == 1
    assert link.first.inner_text().strip() == "Ingredients"


def test_the_run_page_asks_what_to_check(page, server):
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    assert page.locator('input[name="scope"][value="product"]').count() == 1
    assert page.locator('input[name="scope"][value="library"]').count() == 1
    assert page.locator('input[name="product_id"]').count() == 1
    assert "Run check" in page.locator("form.run-form button").inner_text()


def test_a_product_run_with_nothing_chosen_says_so(page, server):
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    page.locator("form.run-form button").click()
    page.wait_for_load_state("domcontentloaded")
    assert "Search for a product and choose one" in page.inner_text("body")


def test_a_previous_run_is_listed_and_opens(page, server):
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    row = page.locator(f'a[href="/ingredients/runs/{RUN_ID}"]')
    assert row.count() == 1
    row.first.click()
    page.wait_for_load_state("domcontentloaded")
    assert "Ingredient check" in page.inner_text("h1")


def test_runs_show_up_in_history(page, server):
    page.goto(server + "/history", wait_until="domcontentloaded")
    assert page.locator(f'a[href="/ingredients/runs/{RUN_ID}"]').count() == 1


# -- the report ----------------------------------------------------------------


def test_the_verdict_line_and_the_counts_agree(page, server):
    _open(page, server)
    assert "Fix before release" in page.locator(".verdict h2").inner_text()
    stats = page.locator(".verdict .stats").inner_text()
    assert "Under-classified" in stats
    assert "Inconsistent codes" in stats
    assert "Not checked" in stats


def test_an_under_classified_substance_has_a_card(page, server):
    _open(page, server)
    card = page.locator('article.issue[data-cas="67-64-1"][data-status="fix"]')
    assert card.count() == 1
    text = card.inner_text()
    assert "67-64-1" in text
    assert "<fictional substance A>" in text
    assert "2 of 3 uses" in text
    assert "H336" in text and "EUH066" in text
    assert "annex vi requires" in text.lower()
    assert "Index No 606-001-00-8" in text


def test_the_card_lists_the_affected_products_when_opened(page, server):
    _open(page, server)
    card = page.locator('article.issue[data-cas="67-64-1"]')
    details = card.locator("details.affected")
    assert "2 affected products" in details.locator("summary").inner_text()
    assert not details.locator(".ids").first.is_visible()
    details.locator("summary").click()
    assert "101, 102" in details.locator(".ids").first.inner_text()


def test_a_substance_with_different_codes_has_its_own_card(page, server):
    _open(page, server)
    card = page.locator('article.issue[data-cas="1333-74-0"][data-status="check"]')
    assert card.count() == 1
    text = card.inner_text()
    assert "2 different code sets" in text
    assert "H220" in text
    rows = card.locator(".minor-table tbody tr")
    assert rows.count() == 2


def test_an_under_classified_substance_is_not_listed_twice(page, server):
    """It is already a Fix card; a second card would double the apparent work."""
    _open(page, server)
    assert page.locator('article.issue[data-cas="67-64-1"]').count() == 1


def test_matches_and_extras_and_not_checked_are_collapsed(page, server):
    _open(page, server)
    summaries = [s.strip() for s in
                 page.locator("details.block > summary").all_inner_texts()]
    assert any("matches Annex VI" in s or "match Annex VI" in s
               for s in summaries)
    assert any("Annex VI does not cover" in s for s in summaries)
    assert any("not checked" in s for s in summaries)
    assert any("Technical details" in s for s in summaries)
    for block in page.locator("details.block").all():
        assert not block.locator(".inner").first.is_visible()


def test_the_reason_a_substance_was_not_checked_is_given(page, server):
    _open(page, server)
    block = page.locator("details.block").filter(
        has=page.locator("summary:has-text('not checked')"))
    block.locator("summary").first.click()
    assert "no harmonised entry" in block.first.inner_text()


def test_the_technical_block_names_the_source_and_the_data_sources(page, server):
    _open(page, server)
    block = page.locator("details.block").filter(
        has=page.locator("summary:has-text('Technical details')"))
    block.locator("summary").first.click()
    text = block.first.inner_text()
    assert "02008R1272-20260701" in text
    assert "stub: 4" in text


def test_the_page_works_on_a_narrow_screen(page, server):
    page.set_viewport_size({"width": 390, "height": 900})
    _open(page, server)
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 391, f"the page scrolls sideways at 390px: {width}"


def test_the_report_screenshot(page, server, shots_dir):
    _open(page, server)
    page.screenshot(path=str(shots_dir / "ingredients_report.png"),
                    full_page=True)
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    page.screenshot(path=str(shots_dir / "ingredients_run_page.png"),
                    full_page=True)


# -- the run form's product search --------------------------------------------


def test_the_run_form_searches_by_name_not_by_id(page, server):
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    assert page.locator('input[name="product_name"]').count() == 1
    assert page.locator('input[type="number"][name="product_id"]').count() == 0
    assert page.locator('input[type="hidden"][name="product_id"]').count() == 1


def test_run_check_is_a_primary_button(page, server):
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    button = page.locator("form.run-form button.primary")
    assert button.count() == 1
    assert "Run check" in button.inner_text()


def test_the_matches_list_starts_hidden(page, server):
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    assert not page.locator("#product-matches").is_visible()
    assert page.locator("#product-search").get_attribute("aria-expanded") == "false"


def test_typing_fewer_than_two_characters_asks_nothing(page, server):
    asked = []
    page.on("request", lambda r: asked.append(r.url)
            if "/ingredients/search" in r.url else None)
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    page.fill("#product-search", "a")
    page.wait_for_timeout(400)
    assert asked == []


def test_choosing_a_match_fills_the_hidden_id(page, server):
    """The typeahead is driven with a stubbed response: no ExactSDS here."""
    page.route("**/ingredients/search*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"results": [{"id": 4250, "name": "<fictional product>"}]}'))
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    page.fill("#product-search", "fictional")
    page.wait_for_selector("#product-matches li")
    page.locator("#product-matches li").first.click()
    assert page.locator("#product-id").input_value() == "4250"
    assert "4250" in page.locator("#chosen").inner_text()
    assert not page.locator("#product-matches").is_visible()


def test_editing_the_name_again_clears_the_chosen_product(page, server):
    """A stale id must never be submitted beside a different name."""
    page.route("**/ingredients/search*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"results": [{"id": 4250, "name": "<fictional product>"}]}'))
    page.goto(server + "/ingredients", wait_until="domcontentloaded")
    page.fill("#product-search", "fictional")
    page.wait_for_selector("#product-matches li")
    page.locator("#product-matches li").first.click()
    page.fill("#product-search", "something else")
    assert page.locator("#product-id").input_value() == ""


def test_a_run_with_nothing_to_check_does_not_say_fix(page, server,
                                                      synthetic_run):
    """An empty run is not a verdict on the product."""
    import json

    empty = dict(SYNTHETIC)
    empty["counts"] = {**SYNTHETIC["counts"], "substances": 0, "ingredients": 0,
                       "fix": 0, "with_entry": 0, "ok": 0, "info": 0,
                       "not_checked": 0, "uses": 0, "uses_under_classified": 0,
                       "inconsistent_substances": 0}
    empty["substances"] = []
    path = RUNS / "uitest-empty.json"
    path.write_text(json.dumps(empty), encoding="utf-8")
    try:
        page.goto(f"{server}/ingredients/runs/uitest-empty",
                  wait_until="domcontentloaded")
        banner = page.locator(".verdict h2").inner_text()
        assert banner == "Nothing to check"
        assert "Fix before release" not in page.inner_text("body")
    finally:
        path.unlink(missing_ok=True)
