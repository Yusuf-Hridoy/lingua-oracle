"""Every synthetic fixture, uploaded through the real page, asserted on the HTML.

A green unit suite says the checks are right. It says nothing about whether a
person opening the page can see that they are right - whether the verdict, the
code, their own text and the official text actually reach the screen. That is
what these tests cover, and why they assert on rendered HTML rather than on the
Report object.
"""

from __future__ import annotations

import json
import re

import pytest
from playwright.sync_api import expect

from lingua_oracle.models import Severity
from lingua_oracle.registry import load_registry
from lingua_oracle.report import labels
from tests.ui.manifest import CASES, Case

FIXTURES = "tests/fixtures"


def _tech(page, label: str) -> str:
    """A value from the collapsed Technical details block."""
    cell = page.locator(f"//dt[normalize-space()='{label}']/following-sibling::dd").first
    return (cell.text_content() or "").strip()


def _release(page) -> str:
    return page.locator(".verdict .banner h2").first.inner_text().strip()


def _statement(page, code: str):
    """The issue card for one code."""
    return page.locator("article.issue").filter(
        has=page.locator(f'.code:text-is("{code}")')
    )


def _upload(page, base: str, case: Case) -> None:
    page.goto(base + "/", wait_until="domcontentloaded")
    page.select_option("#regulation", case.regulation)
    page.select_option("#language", case.language)
    page.set_input_files("input[name=file]", f"{FIXTURES}/{case.name}.pdf")
    # The form posts to /check/html, which answers 303 to /reports/<id>: two
    # navigations, so wait for the destination rather than for "a navigation".
    page.click("#check-form button[type=submit]")
    page.wait_for_url(re.compile(r"/reports/"), timeout=60_000)
    page.wait_for_load_state("load")


def _compare(page, base: str, case: Case) -> None:
    page.goto(base + "/", wait_until="domcontentloaded")
    page.click(".toggle button[data-mode=two]")
    page.select_option("#creg", case.regulation)
    page.select_option("#clang", case.language)
    page.set_input_files("#file_a", f"{FIXTURES}/{case.name}.pdf")
    page.set_input_files("#file_b", f"{FIXTURES}/{case.compare_with}.pdf")
    page.click("#compare-form button[type=submit]")
    page.wait_for_url(re.compile(r"/reports/"), timeout=60_000)
    page.wait_for_load_state("load")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_fixture_report_in_the_browser(case: Case, page, server, shots_dir):
    if case.compare_with:
        _compare(page, server, case)
    else:
        _upload(page, server, case)

    assert re.search(r"/reports/[0-9a-zA-Z_-]+$", page.url), (
        f"did not land on a report page: {page.url}"
    )

    # -- the one line a reader acts on --------------------------------------
    assert _release(page) in (labels.READY, labels.REVIEW, labels.FIX)
    if case.clean:
        assert _release(page) != labels.FIX, (
            f"{case.name} is a correct document but the page says {labels.FIX}"
        )
    else:
        assert _release(page) == labels.FIX, (
            f"{case.name} plants a defect but the page does not say {labels.FIX}"
        )

    # -- what was checked, in the technical block ---------------------------
    assert _tech(page, labels.META["file"]) == f"{case.name}.pdf"
    expected_display = load_registry().get(case.expect_regulation).display_name
    assert _tech(page, labels.META["regulation"]) == expected_display
    assert _tech(page, labels.META["language"]) == case.expect_language
    assert _tech(page, labels.META["id"]), "the report has no reference on screen"

    # -- each expected finding must be visible, with its evidence -----------
    for check_id, severity, code in case.expect:
        if code:
            card = _statement(page, labels.code_label(code))
            assert card.count() >= 1, f"no card on the page for {code}"
            # A code can have two cards - a wording verdict and, say, a C-02
            # consistency warning - so look across all of them.
            shown = " ".join(card.all_inner_texts())
        else:
            shown = page.inner_text("body")
        wanted = {labels.STATUS[severity].word} if severity in labels.STATUS else {
            labels.STATUS["wrong" if severity == "fail" else "check"].word,
            labels.result_of(check_id, Severity(severity), False).word,
        }
        assert any(word in shown for word in wanted), (
            f"{check_id}/{code}: none of {sorted(wanted)} is on the page"
        )

    page.screenshot(path=str(shots_dir / f"{case.name}.png"), full_page=True)


def test_every_case_produced_a_screenshot(shots_dir):
    """Runs last in file order; a missing image means a case never rendered."""
    missing = [c.name for c in CASES if not (shots_dir / f"{c.name}.png").exists()]
    assert missing == [], missing


# -- the card layout a reviewer reads ----------------------------------------


def test_a_problem_card_shows_both_texts_and_a_copy_button(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    card = _statement(page, "H225").first
    expect(card).to_be_visible()
    text = card.inner_text()
    assert "YOUR DOCUMENT" in text.upper()
    assert "OFFICIAL WORDING" in text.upper()
    # Header: severity pill, code in mono, where it sits.
    assert card.locator("header .pill").count() == 1
    assert card.locator("header .code").count() == 1
    assert card.locator("header .where").count() == 1
    # The copy button sits on the official side, not the document's.
    assert card.locator(".side.official button.copy").count() == 1
    assert "Source:" in text


def test_the_copy_button_carries_the_official_text(page, server, shots_dir):
    from lingua_oracle.keys.store import load_key
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    official = load_key("eu_clp", "da").by_code()["H225"].text
    button = _statement(page, "H225").first.locator(".side.official button.copy").first
    assert button.get_attribute("data-text") == official


def test_correct_statements_are_collapsed_into_one_line(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    good = page.locator("details.block.good")
    assert good.count() == 1
    assert not good.first.evaluate("el => el.open"), "the correct list starts open"
    assert re.search(r"\d+ statements? match the official wording",
                     good.first.inner_text())
    # It expands to a plain list of code + text.
    good.first.locator("summary").click()
    assert good.first.locator("li").count() > 0


def test_correct_statements_get_no_card(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    assert page.locator("article.issue").count() == 0, (
        "a correct document should show no issue cards"
    )


def test_the_count_line_and_coverage_are_at_the_top(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    stats = page.locator(".verdict .stats").first.inner_text()
    for label in ("Wrong wording", "Fix this", "Check this", "Correct", "Codes checked"):
        assert label in stats, stats[:300]
    assert re.search(r"Codes checked \(\d+ of \d+\)", stats), stats[:300]


def test_no_check_ids_outside_the_technical_block(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    above = page.locator(".verdict").inner_text() + " ".join(
        page.locator("article.issue").all_inner_texts()
    )
    assert not re.search(r"\b[ABC]-\d\d\b", above), above[:300]


def test_a_fill_in_is_reported_on_its_card(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_optional_fillin"])
    body = page.inner_text("body")
    assert "You filled in:" in body
    assert "check it fits this product" in body


def test_technical_details_are_collapsed_at_the_bottom(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    tech = page.locator("details.block").last
    assert "technical details" in tech.inner_text().lower()
    assert not tech.evaluate("el => el.open"), "technical block starts open"
    assert "pymupdf" not in page.locator(".verdict").inner_text()


def test_the_page_never_strikes_through_the_official_wording(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    assert page.locator("mark.diff").count() > 0
    struck = page.evaluate(
        "() => [...document.querySelectorAll('mark')]"
        ".filter(m => getComputedStyle(m).textDecorationLine.includes('line-through')).length"
    )
    assert struck == 0, "official wording is shown struck through"


def test_whmis_sheet_reads_review_before_release(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_conditional_slots"])
    assert _release(page) == labels.REVIEW
    # The stat cell is always labelled; what matters is that it counts nothing
    # and no card claims wrong wording.
    wrong = page.locator(".verdict .stats > div").first.inner_text()
    assert wrong.startswith("0"), wrong
    assert page.locator('article.issue[data-status="wrong"]').count() == 0
    assert "Confirm the French version of this SDS exists." in page.inner_text("body")


def test_a_clean_sheet_reads_ready_to_release(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    assert _release(page) == labels.READY


def test_json_still_carries_the_statements(page, server, shots_dir):
    """The page got simpler; the data behind it did not."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    page.goto(page.url + ".json", wait_until="load")
    payload = json.loads(page.inner_text("body"))
    assert payload["statements"], "no statement verdicts in the JSON"
    assert {"code", "status", "found", "expected"} <= set(payload["statements"][0])


# -- the re-skinned pages ------------------------------------------------------


def test_the_upload_page_has_the_shell(page, server, shots_dir):
    page.goto(server + "/", wait_until="load")
    assert page.locator(".topbar .brand").inner_text().strip() == "Lingua Oracle"
    for name in ("Check", "History", "Coverage"):
        assert page.locator(f'.nav a:text-is("{name}")').count() == 1
    assert page.locator('.nav a[aria-current="page"]').inner_text().strip() == "Check"
    assert page.locator("h1").inner_text().strip() == "Check a document"
    assert page.locator(".drop").count() == 1
    assert page.locator("#file").get_attribute("multiple") is not None
    assert page.locator(".panel h2").first.inner_text().strip() == "What gets checked"
    assert "Official texts on file" in page.inner_text("body")
    assert "Recent checks" in page.inner_text("body")
    page.screenshot(path=str(shots_dir / "_upload_page.png"), full_page=True)


def test_the_toggle_switches_to_compare(page, server, shots_dir):
    page.goto(server + "/", wait_until="load")
    expect(page.locator("#check-form")).to_be_visible()
    page.click('.toggle button[data-mode="two"]')
    expect(page.locator("#compare-form")).to_be_visible()
    expect(page.locator("#check-form")).to_be_hidden()
    assert page.locator('.toggle button[data-mode="two"]').get_attribute(
        "aria-pressed") == "true"


def test_every_control_has_a_label(page, server, shots_dir):
    """Real labels and real buttons, not styled divs."""
    page.goto(server + "/", wait_until="load")
    for selector in ("#regulation", "#language"):
        field_id = selector.lstrip("#")
        assert page.locator(f'label[for="{field_id}"]').count() == 1
    assert page.locator("#check-form button[type=submit]").count() == 1
    # Only buttons on screen; the hidden compare form measures zero. The filter
    # pills on the report are deliberately smaller, so this covers the actions.
    heights = page.evaluate(
        "() => [...document.querySelectorAll('button')]"
        ".filter(b => b.offsetParent !== null)"
        ".map(b => b.getBoundingClientRect().height)"
    )
    assert heights and all(h >= 40 for h in heights), heights


def test_the_verdict_bar_has_a_banner_and_five_stats(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    verdict = page.locator(".verdict").first
    assert verdict.locator(".banner h2").count() == 1
    assert verdict.locator(".banner p").count() == 1
    cells = verdict.locator(".stats > div")
    assert cells.count() == 5, cells.count()
    labels_shown = [cells.nth(i).inner_text().split("\n")[-1] for i in range(5)]
    assert labels_shown[:4] == ["Wrong wording", "Fix this", "Check this", "Correct"]
    assert labels_shown[4].startswith("Codes checked")


def test_what_to_do_is_a_numbered_list_of_at_most_five(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    todo = page.locator(".todo")
    assert todo.count() == 1
    assert todo.locator("h2").inner_text().strip() == "What to do"
    items = todo.locator("ol li")
    assert 1 <= items.count() <= 5, items.count()


def test_the_issue_filters_hide_and_show_cards(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_c15_osha_partial_key"])
    assert "Issues ·" in page.locator(".issues-head h2").inner_text()
    total = page.locator("article.issue").count()
    page.click('.filters button[data-filter="must"]')
    visible = page.locator("article.issue:not([hidden])").count()
    assert visible < total, "the Must fix filter hid nothing"
    page.click('.filters button[data-filter="all"]')
    assert page.locator("article.issue:not([hidden])").count() == total


def test_a_newer_ghs_card_names_the_closest_statement(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_c15_newer_ghs"])
    card = _statement(page, "P317").first
    heading = card.locator(".side.official h3").inner_text()
    assert heading.lower().startswith("closest"), heading
    assert "Matches GHS Rev.8 wording exactly" in card.inner_text()


def test_a_single_column_card_for_something_with_no_official_text(page, server,
                                                                  shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_c14_english_only"])
    card = page.locator("article.issue").first
    assert card.locator(".body.single").count() == 1
    assert card.locator(".side").count() == 1


def test_both_collapsed_sections_are_present_and_shut(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    good = page.locator("details.block.good")
    tech = page.locator("details.block").last
    assert good.count() == 1
    assert "match the official wording" in good.inner_text()
    assert not good.evaluate("el => el.open")
    assert "Not checked" in tech.inner_text()
    assert not tech.evaluate("el => el.open")


def test_the_report_works_at_390px(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    page.set_viewport_size({"width": 390, "height": 844})
    _upload(page, server, BY_NAME["defect_a02_hazard"])
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 1, f"the page scrolls sideways by {overflow}px at 390px"
    # The two columns stack rather than squeezing.
    body = page.locator("article.issue .body").first
    columns = body.evaluate("el => getComputedStyle(el).gridTemplateColumns")
    assert len(columns.split()) == 1, columns
    page.screenshot(path=str(shots_dir / "_report_390.png"), full_page=True)
