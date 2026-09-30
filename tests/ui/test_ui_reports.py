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
    return page.locator(".verdict .release").first.inner_text().strip()


def _statement(page, code: str):
    """The card for one code."""
    return page.locator(".stmt").filter(
        has=page.locator(f'.code:text-is("{code}")')
    )


def _upload(page, base: str, case: Case) -> None:
    page.goto(base + "/", wait_until="domcontentloaded")
    page.select_option("#regulation", case.regulation)
    page.select_option("#language", case.language)
    page.set_input_files("input[name=file]", f"{FIXTURES}/{case.name}.pdf")
    # The form posts to /check/html, which answers 303 to /reports/<id>: two
    # navigations, so wait for the destination rather than for "a navigation".
    page.click("form[action='/check/html'] button[type=submit]")
    page.wait_for_url(re.compile(r"/reports/"), timeout=60_000)
    page.wait_for_load_state("load")


def _compare(page, base: str, case: Case) -> None:
    page.goto(base + "/", wait_until="domcontentloaded")
    page.select_option("#creg", case.regulation)
    page.select_option("#clang", case.language)
    page.set_input_files("input[name=file_a]", f"{FIXTURES}/{case.name}.pdf")
    page.set_input_files("input[name=file_b]", f"{FIXTURES}/{case.compare_with}.pdf")
    page.click("form[action='/compare'] button[type=submit]")
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
        wanted = {
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
    assert "You have" in text and "Correct text" in text, text[:300]
    button = card.locator("button.copy")
    assert button.count() == 1, "no copy button on the card"
    assert button.first.inner_text().strip() == "Copy correct text"
    assert "Source:" in text


def test_the_copy_button_carries_the_official_text(page, server, shots_dir):
    from lingua_oracle.keys.store import load_key
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    official = load_key("eu_clp", "da").by_code()["H225"].text
    button = _statement(page, "H225").first.locator("button.copy").first
    assert button.get_attribute("data-text") == official


def test_correct_statements_are_collapsed_into_one_line(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    good = page.locator("details.allgood")
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
    assert page.locator(".stmt").count() == 0, (
        "a correct document should show no problem cards"
    )


def test_the_count_line_and_coverage_are_at_the_top(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    banner = page.locator(".verdict").first.inner_text()
    assert re.search(r"\d+ correct", banner), banner[:200]
    assert re.search(r"\d+ wrong", banner), banner[:200]
    assert re.search(r"\d+ to check", banner), banner[:200]
    assert "% of the codes" in banner


def test_no_check_ids_outside_the_technical_block(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    above = page.locator(".verdict").inner_text() + " ".join(
        page.locator(".stmt").all_inner_texts()
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
    tech = page.locator("details.tech")
    assert tech.count() == 1
    assert not tech.first.evaluate("el => el.open"), "technical block starts open"
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
    assert "Wrong wording" not in page.inner_text("body")
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
