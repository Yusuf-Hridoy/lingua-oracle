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
from tests.ui.waits import submit_for_report

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


def _minor_row(page, code: str):
    """The row for one code in the collapsed punctuation/capitals card.

    Statements whose words are the official words and whose only difference is
    punctuation or capital letters share a single card, so they have no
    `article.issue` of their own.
    """
    return page.locator(".minor-table tbody tr").filter(
        has=page.locator(f'.code:text-is("{code}")')
    )


def _upload(page, base: str, case: Case) -> None:
    page.goto(base + "/", wait_until="domcontentloaded")
    page.select_option("#regulation", case.regulation)
    page.select_option("#language", case.language)
    page.set_input_files("input[name=file]", f"{FIXTURES}/{case.name}.pdf")
    # The form posts to /check/html, which answers 303 to /reports/<id>: wait
    # for the report itself, not for the click (tests/ui/waits.py).
    submit_for_report(page, page.locator("#check-form button[type=submit]"))


def _compare(page, base: str, case: Case) -> None:
    page.goto(base + "/", wait_until="domcontentloaded")
    page.click(".toggle button[data-mode=two]")
    page.select_option("#creg", case.regulation)
    page.select_option("#clang", case.language)
    page.set_input_files("#file_a", f"{FIXTURES}/{case.name}.pdf")
    page.set_input_files("#file_b", f"{FIXTURES}/{case.compare_with}.pdf")
    submit_for_report(page, page.locator("#compare-form button[type=submit]"))


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
            minor = _minor_row(page, labels.code_label(code))
            assert card.count() + minor.count() >= 1, (
                f"no card on the page for {code}"
            )
            # A code can have two cards - a wording verdict and, say, a C-02
            # consistency warning - so look across all of them. A punctuation
            # difference lives in the collapsed card instead, which carries the
            # same words in its summary.
            shown = " ".join(card.all_inner_texts() + minor.all_inner_texts())
            if minor.count():
                shown += " " + page.locator(".block.minor summary").inner_text()
                shown += " " + labels.STATUS["check"].word
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
    assert "Wording ·" in page.locator(".issues-head h2").first.inner_text()
    wording = 'article.issue[data-section="wording"]'
    total = page.locator(wording).count()
    page.click('.filters button[data-filter="must"]')
    visible = page.locator(f"{wording}:not([hidden])").count()
    assert visible < total, "the Must fix filter hid nothing"
    page.click('.filters button[data-filter="all"]')
    assert page.locator(f"{wording}:not([hidden])").count() == total


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


# -- placeholder cards ---------------------------------------------------------


def test_a_placeholder_card_has_one_column(page, server, shots_dir):
    """The wording is right, so there is no second version to compare against."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_unfilled_blanks"])
    for code in ("P501", "P280"):
        card = _statement(page, code).first
        expect(card).to_be_visible()
        assert card.locator(".body.single").count() == 1, code
        assert card.locator(".side").count() == 1, code
        # The official text appears as a reference line, never as a second
        # column to compare against.
        assert card.locator(".side.official").count() == 0, code


def test_only_the_placeholder_is_highlighted(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_unfilled_blanks"])
    for code in ("P501", "P280"):
        marks = _statement(page, code).first.locator("mark")
        assert marks.count() == 1, f"{code}: {marks.count()} highlights"
        assert marks.first.inner_text().strip() == "…", code


def test_a_placeholder_card_says_what_goes_in_the_blank(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_unfilled_blanks"])
    p501 = _statement(page, "P501").first.inner_text()
    assert "Name the disposal route" in p501, p501
    p280 = _statement(page, "P280").first.inner_text()
    assert "Keep only the protection that applies" in p280, p280
    page.screenshot(path=str(shots_dir / "_placeholder_cards.png"), full_page=True)


def test_a_spacing_difference_is_never_highlighted(page, server, shots_dir):
    """"Use…" and "Use …" are the same statement written two ways."""
    from lingua_oracle.report.render import word_diff

    for official, document in [
        ("In case of fire: Use … to extinguish", "In case of fire: Use… to extinguish"),
        ("Dispose of contents/container to…", "Dispose of contents/container to …"),
        ("Store at  50 °C", "Store at 50 °C"),
    ]:
        left, right = word_diff(official, document)
        assert "<mark" not in left + right, (official, document)
    # A real difference still shows.
    left, right = word_diff("Ground and bond container.", "Ground/bond container.")
    assert "<mark" in left and "<mark" in right


@pytest.mark.parametrize("case_name", ["pattern_unfilled_blanks", "defect_a02_hazard",
                                       "defect_c15_osha_partial_key"])
def test_no_developer_wording_in_a_source_line(case_name, page, server, shots_dir):
    """The card cites the regulation and the instrument, nothing else."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME[case_name])
    jargon = ("code established", "split from a cell", "App. C;", "Annex 3 (English)",
              "fill-ins collapsed", ".pdf,", "table row for")
    for line in page.locator("article.issue .src").all_inner_texts():
        for word in jargon:
            assert word not in line, f"{word!r} in source line: {line}"


def test_the_provenance_moved_to_technical_details(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    # A closed <details> yields only its summary from inner_text().
    tech = page.locator("details.block").last
    assert "Where each wording came from" in (tech.text_content() or "")


# -- what each card explains ---------------------------------------------------


def test_out_of_scope_wording_sits_with_the_matches(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_out_of_scope"])
    assert _statement(page, "H303").count() == 0, "H303 should raise no card"
    good = page.locator("details.block.good")
    good.locator("summary").click()
    text = good.inner_text()
    assert "H303" in text
    assert "outside US OSHA HazCom's scope" in text
    assert "allowed as extra information" in text
    # And it is not something to do.
    assert "H303" not in page.locator(".todo").inner_text()


def test_a_newer_ghs_card_explains_itself(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_c15_osha_partial_key"])
    with_closest = _statement(page, "P319").first.inner_text()
    assert "Correct GHS Rev.8 wording" in with_closest
    assert "has not adopted P319" in with_closest
    assert "if not, use P314" in with_closest

    without = _statement(page, "P317").first.inner_text()
    assert "has no equivalent statement" in without
    assert "Ask whether that’s accepted." in without


def test_punctuation_differences_share_one_collapsed_card(page, server, shots_dir):
    """A dozen of these used to push the statements that matter off the screen."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_capitalisation"])
    block = page.locator("details.block.minor")
    assert block.count() == 1
    summary = block.locator("summary").inner_text()
    assert "differs only in punctuation or capital letters" in summary
    assert summary.strip().startswith("1 statement")
    # Collapsed: the detail is there, but not taking up the page.
    assert not block.locator(".minor-table").first.is_visible()
    assert _statement(page, "P303+P361+P353").count() == 0


def test_the_collapsed_card_shows_both_texts_when_opened(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_capitalisation"])
    page.locator("details.block.minor summary").click()
    row = _minor_row(page, "P303+P361+P353")
    assert row.count() == 1
    text = row.inner_text()
    assert "Rinse SKIN" in text           # the document's own wording
    assert "Rinse skin" in text           # the official wording beside it


def test_one_what_to_do_line_covers_every_punctuation_difference(page, server,
                                                                 shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_capitalisation"])
    todo = page.locator(".card.todo li").all_inner_texts()
    about_punctuation = [t for t in todo
                         if "punctuation" in t or "capital letters" in t]
    assert len(about_punctuation) == 1, todo


def test_no_card_falls_back_to_the_generic_sentence(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    for name in ("defect_c15_osha_partial_key", "pattern_capitalisation",
                 "pattern_unfilled_blanks"):
        _upload(page, server, BY_NAME[name])
        body = page.inner_text("body")
        assert "Read both and decide whether the difference matters" not in body, name


def test_the_placeholder_has_air_before_it(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_unfilled_blanks"])
    shown = _statement(page, "P501").first.locator(".side .txt").inner_text()
    assert "to …" in shown, shown
    assert "to…" not in shown, shown


def test_an_undetectable_regulation_shows_the_page(page, server, shots_dir):
    """No raw JSON in the browser, ever."""
    page.goto(server + "/", wait_until="domcontentloaded")
    page.set_input_files("#file", f"{FIXTURES}/defect_a02_hazard.pdf")
    page.click("#check-form button[type=submit]")
    page.wait_for_load_state("load")
    notice = page.locator(".notice")
    expect(notice).to_be_visible()
    assert "We couldn’t tell which regulation this sheet follows" in notice.inner_text()
    assert page.locator("#check-form").count() == 1, "the form is gone"
    assert page.evaluate("() => document.activeElement.id") == "regulation"
    page.screenshot(path=str(shots_dir / "_error_page.png"), full_page=True)


def test_a_placeholder_card_shows_the_official_wording_as_reference(page, server,
                                                                    shots_dir):
    """One column still, with the official text as a reference line.

    It is not something to compare against - the document already says it - so
    it carries no highlighting and sits under the instruction.
    """
    from lingua_oracle.keys.store import load_key
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_unfilled_blanks"])
    official = load_key("us_osha", "en").by_code()["P501"].text
    card = _statement(page, "P501").first
    assert card.locator(".body.single").count() == 1
    reference = card.locator(".reference")
    assert reference.count() == 1
    text = reference.inner_text()
    assert text.startswith("Official wording:")
    assert official in text
    assert "is the blank to fill in" in text
    # The reference carries no diff marks; only the document's own placeholder
    # is highlighted, once.
    assert reference.locator("mark").count() == 0
    assert card.locator("mark").count() == 1


def test_the_upload_page_fetches_fonts_only_from_static(page, server, shots_dir):
    """Nothing is requested from a font CDN - or from anywhere else."""
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.goto(server + "/", wait_until="load")

    external = [u for u in requests if not u.startswith(server)]
    assert external == [], external

    fonts = [u for u in requests if u.endswith(".woff2")]
    assert fonts, "no font was fetched at all"
    assert all(u.startswith(server + "/static/fonts/") for u in fonts), fonts


def test_the_served_fonts_actually_arrive(page, server, shots_dir):
    statuses: dict[str, int] = {}
    page.on("response", lambda r: statuses.__setitem__(r.url, r.status))
    page.goto(server + "/", wait_until="load")
    fonts = {u: s for u, s in statuses.items() if u.endswith(".woff2")}
    assert fonts, "no font response"
    assert all(status == 200 for status in fonts.values()), fonts


def test_a_report_page_requests_no_font_at_all(page, server, shots_dir):
    """The report carries them inside it."""
    from tests.ui.manifest import BY_NAME

    requests: list[str] = []
    _upload(page, server, BY_NAME["clean_eu_da"])
    page.on("request", lambda r: requests.append(r.url))
    page.reload(wait_until="load")
    assert [u for u in requests if u.endswith(".woff2")] == []
    assert [u for u in requests if not u.startswith(server)] == []


def test_the_ask_screen_preselects_the_suggestion(page, server, shots_dir):
    """A suggestion is somewhere to start. The reader still presses the button."""
    page.goto(server + "/", wait_until="load")
    page.set_input_files("#file", f"{FIXTURES}/pattern_only_says_ghs.pdf")
    page.click("#check-form button[type=submit]")
    page.wait_for_load_state("load")

    notice = page.locator(".notice")
    expect(notice).to_be_visible()
    text = notice.inner_text()
    assert "only says ‘GHS’" in text
    assert "Australia WHS" in text
    assert "+61 phone" in text

    assert page.locator("#regulation").input_value() == "au_whs"
    assert page.evaluate("() => document.activeElement.id") == "regulation"
    assert "/reports/" not in page.url, "it checked without being asked"
    page.screenshot(path=str(shots_dir / "_ask_screen.png"), full_page=True)


def test_confirming_the_suggestion_runs_the_check(page, server, shots_dir):
    page.goto(server + "/", wait_until="load")
    page.set_input_files("#file", f"{FIXTURES}/pattern_only_says_ghs.pdf")
    page.click("#check-form button[type=submit]")
    page.wait_for_load_state("load")
    # The file has to be chosen again; the browser will not let a page refill it.
    page.set_input_files("#file", f"{FIXTURES}/pattern_only_says_ghs.pdf")
    page.click("#check-form button[type=submit]")
    page.wait_for_url(re.compile(r"/reports/"), timeout=60_000)
    assert "Australia WHS" in page.inner_text("body")
