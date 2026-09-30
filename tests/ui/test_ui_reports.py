"""Every synthetic fixture, uploaded through the real page, asserted on the HTML.

A green unit suite says the checks are right. It says nothing about whether a
person opening the page can see that they are right - whether the verdict, the
code, the expected text and the found text actually reach the screen. That is
what these tests cover, and why they assert on rendered HTML rather than on the
Report object.
"""

from __future__ import annotations

import json
import re

import pytest

from lingua_oracle.models import Severity
from lingua_oracle.registry import load_registry
from lingua_oracle.report import labels
from tests.ui.manifest import CASES, Case

FIXTURES = "tests/fixtures"


def _meta(page, label: str) -> str:
    return page.locator(f"//dt[normalize-space()='{label}']/following-sibling::dd").first.inner_text().strip()


def _fail_count(page) -> int:
    return int(page.locator(".tile.t-fail .n").first.inner_text().strip())


def _card(page, check_id: str):
    """The heading leads with the plain-language title; the id follows it."""
    return page.locator(".card").filter(
        has=page.locator(f'h2:has-text("check {check_id}")')
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
    with page.expect_navigation(wait_until="load"):
        page.click("form[action='/compare'] button[type=submit]")
    # /compare answers with JSON; the report itself is at /reports/<id>.
    payload = json.loads(page.inner_text("body"))
    page.goto(f"{base}/reports/{payload['id']}", wait_until="load")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_fixture_report_in_the_browser(case: Case, page, server, shots_dir):
    if case.compare_with:
        _compare(page, server, case)
    else:
        _upload(page, server, case)

    assert re.search(r"/reports/[0-9a-zA-Z_-]+$", page.url), (
        f"did not land on a report page: {page.url}"
    )

    # -- the header must identify what was checked --------------------------
    # Labels come from the presentation module, so renaming one cannot leave a
    # test asserting on wording the page no longer uses.
    assert _meta(page, labels.META["file"]) == f"{case.name}.pdf"
    expected_display = load_registry().get(case.expect_regulation).display_name
    assert _meta(page, labels.META["regulation"]) == expected_display
    assert _meta(page, labels.META["language"]) == case.expect_language
    assert _meta(page, labels.META["id"]), "the report has no reference on screen"

    # -- the verdict --------------------------------------------------------
    if case.clean:
        assert _fail_count(page) == 0, (
            f"{case.name} is a correct document but the page shows "
            f"{_fail_count(page)} failure(s)"
        )
    else:
        assert _fail_count(page) > 0, f"{case.name} plants a defect but nothing failed"

    # -- each expected finding must be visible, with its evidence -----------
    for check_id, severity, code in case.expect:
        card = _card(page, check_id)
        assert card.count() == 1, f"no card on the page for {check_id}"
        # Our internal placeholders are shown under their plain name, so look
        # for what the reader sees rather than for the raw code.
        shown_code = labels.code_label(code)
        row = card.locator("tbody tr").filter(
            has=page.locator(f'td.code:text-is("{shown_code}")')
        ) if code else card.locator("tbody tr")
        assert row.count() >= 1, (
            f"{check_id}: no row for code {code!r} (shown as {shown_code!r})"
        )
        first = row.first
        # The result cell carries an icon AND a word, never colour alone.
        cell = first.locator("td").first
        want = labels.SEVERITY[Severity(severity)]
        shown = cell.inner_text().strip()
        assert want.word in shown, (
            f"{check_id}/{code}: result shown as {shown!r}, expected {want.word!r}"
        )
        assert cell.locator(".result .ico").count() == 1, (
            f"{check_id}/{code}: the result has no icon, so colour is the only signal"
        )
        cells = first.locator("td")
        expected_text = cells.nth(5).inner_text().strip()
        found_text = cells.nth(6).inner_text().strip()
        if check_id in ("A-01", "A-02", "A-03", "A-04"):
            assert expected_text, f"{check_id}/{code}: Expected column is empty"
            assert found_text, f"{check_id}/{code}: Found column is empty"
            assert expected_text != found_text, (
                f"{check_id}/{code}: Expected and Found are identical on screen"
            )
        source = first.locator("td .src")
        if source.count():
            # The cell carries the letter and the words, e.g. "A" + "Official".
            shown = " ".join(source.first.inner_text().split())
            assert any(lbl.word in shown for lbl in labels.SOURCE.values()), shown
            assert source.first.locator(".k").count() == 1

    page.screenshot(path=str(shots_dir / f"{case.name}.png"), full_page=True)


def test_every_case_produced_a_screenshot(shots_dir):
    """Runs last in file order; a missing image means a case never rendered."""
    missing = [c.name for c in CASES if not (shots_dir / f"{c.name}.png").exists()]
    assert missing == [], missing
