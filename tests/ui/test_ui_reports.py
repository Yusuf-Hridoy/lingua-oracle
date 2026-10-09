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
    """The row for one code, in whichever SDS section it sits."""
    return page.locator(".srow").filter(
        has=page.locator(f'.key:text-is("{code}")')
    )


def _minor_row(page, code: str):
    """A row whose only difference is punctuation or capital letters."""
    return _statement(page, code).filter(has=page.locator(".pill.check"))


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

    # -- each expected finding must be visible as a row, with its evidence ---
    wanted = {"fail": {"Wrong", "Fix"}, "wrong": {"Wrong", "Fix"}, "fix": {"Fix"},
              "warn": {"Check"}, "check": {"Check"}, "info": {"Note", "Check"}}
    for check_id, severity, code in case.expect:
        if code:
            rows = _statement(page, labels.code_label(code))
            assert rows.count() >= 1, f"no row on the page for {code}"
            shown = " ".join(rows.all_inner_texts())
        else:
            shown = " ".join(page.locator(".srow").all_inner_texts())
        assert any(word in shown for word in wanted[severity]), (
            f"{check_id}/{code}: none of {sorted(wanted[severity])} on the page"
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
    row = _statement(page, "H225").first
    expect(row).to_be_visible()
    text = row.inner_text()
    assert "YOUR DOCUMENT" in text.upper()
    assert "OFFICIAL WORDING" in text.upper()
    # Code in mono, one verdict pill, and the copy button on the official side.
    assert row.locator(".key.mono").count() == 1
    assert row.locator(".pill").count() == 1
    assert row.locator(".official button.copy").count() == 1
    assert "Source:" in text
    # It sits in the section it is about.
    assert page.locator("#s2").locator(".srow").filter(has_text="H225").count() >= 1


def test_the_copy_button_carries_the_official_text(page, server, shots_dir):
    from lingua_oracle.keys.store import load_key
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    official = load_key("eu_clp", "da").by_code()["H225"].text
    button = _statement(page, "H225").first.locator(".official button.copy").first
    assert button.get_attribute("data-text") == official


def test_correct_statements_are_collapsed_into_one_line(page, server, shots_dir):
    """Every correct statement is its own compact row - none hidden away."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    assert page.locator("details.block.good").count() == 0
    correct = page.locator('.srow[data-status="ok"]')
    assert correct.count() >= 7
    # Compact: one line of text, no comparison block.
    assert correct.first.locator(".cmp").count() == 0
    for code in ("H225", "H319", "P210"):
        assert _statement(page, code).first.is_visible(), code


def test_correct_statements_get_no_card(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    assert page.locator(".srow.problem").count() == 0, (
        "a correct document should show no problem rows"
    )


def test_the_count_line_and_coverage_are_at_the_top(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    stats = page.locator(".verdict .stats").first.inner_text()
    for label in ("Must fix", "To check", "Correct", "Codes checked"):
        assert label in stats, stats[:300]
    assert re.search(r"Codes checked \(\d+ of \d+\)", stats), stats[:300]
    # Structure and depth counted apart: a section whose structure alone was
    # judged is not a section "checked".
    assert re.search(r"16 of 16\s+sections — structure; \d+ in depth", stats), stats[:300]
    assert re.search(r"\d+ of 16", stats), stats[:300]


def test_no_check_ids_outside_the_technical_block(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    above = page.locator(".verdict").inner_text() + " ".join(
        page.locator(".sds-section").all_inner_texts()
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
    must_fix = page.locator(".verdict .stats > div").first.inner_text()
    assert must_fix.startswith("0"), must_fix
    assert page.locator('.srow[data-status="wrong"]').count() == 0
    assert "Confirm the French version of this SDS exists" in page.inner_text("body")


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
    assert labels_shown[:3] == ["Must fix", "To check", "Correct"]
    assert re.fullmatch(r"sections — structure; \d+ in depth", labels_shown[3]), labels_shown
    assert labels_shown[4].startswith("Codes checked")


def test_what_to_do_is_a_numbered_list_of_at_most_five(page, server, shots_dir):
    """Each action names the SDS section it is carried out in."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    todo = page.locator(".todo")
    assert todo.count() == 1
    assert todo.locator("h2").inner_text().strip() == "What to do"
    items = todo.locator("ol li")
    assert 1 <= items.count() <= 5, items.count()
    first = items.first.inner_text()
    assert first.startswith("Section 2: correct H225 to"), first


def test_the_issue_filters_hide_and_show_cards(page, server, shots_dir):
    """Replaced by the navigator: one link per SDS section, with its status."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    nav = page.locator(".navigator")
    assert nav.evaluate("el => getComputedStyle(el).position") == "sticky"
    links = nav.locator("a")
    assert [links.nth(i).get_attribute("href") for i in range(links.count())] == [
        f"#s{n}" for n in range(1, 17)]
    assert nav.locator('a[href="#s2"] .dot').get_attribute("class") == "dot d-fix"
    assert nav.locator('a[href="#s7"] .dot').get_attribute("class") == "dot d-ok"
    assert "not checked" not in nav.inner_text()
    nav.locator('a[href="#s2"]').click()
    assert page.url.endswith("#s2")


def test_a_newer_ghs_card_names_the_closest_statement(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_c15_newer_ghs"])
    row = _statement(page, "P317").first
    heading = row.locator(".official .sub").inner_text()
    assert heading.lower().startswith("closest"), heading
    assert "Matches GHS Rev.8 wording exactly" in row.inner_text()


def test_a_single_column_card_for_something_with_no_official_text(page, server,
                                                                  shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_c14_english_only"])
    row = page.locator(".srow.problem").first
    assert row.locator(".official").count() == 0
    assert "French" in row.inner_text()


def test_both_collapsed_sections_are_present_and_shut(page, server, shots_dir):
    """Only Technical details is collapsed; every result is on the page."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    collapsed = page.locator("details")
    assert collapsed.count() == 1
    tech = collapsed.first
    assert "Technical details" in tech.inner_text()
    assert not tech.evaluate("el => el.open")


def test_the_report_works_at_390px(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    page.set_viewport_size({"width": 390, "height": 844})
    _upload(page, server, BY_NAME["defect_a02_hazard"])
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 1, f"the page scrolls sideways by {overflow}px at 390px"
    # The two wordings stack rather than squeezing, and the navigator stops
    # being sticky.
    cmp = page.locator(".srow.problem .cmp").first
    columns = cmp.evaluate("el => getComputedStyle(el).gridTemplateColumns")
    assert len(columns.split()) == 1, columns
    nav = page.locator(".navigator")
    assert nav.evaluate("el => getComputedStyle(el).position") == "static"
    page.screenshot(path=str(shots_dir / "_report_390.png"), full_page=True)


# -- placeholder cards ---------------------------------------------------------


def test_a_placeholder_card_has_one_column(page, server, shots_dir):
    """The wording is right, so there is no second version to compare against."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_unfilled_blanks"])
    for code in ("P501", "P280"):
        row = _statement(page, code).first
        expect(row).to_be_visible()
        assert row.locator(".cmp.single").count() == 1, code
        assert row.locator(".official").count() == 0, code


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
    """The row cites the regulation and the instrument, nothing else."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME[case_name])
    jargon = ("code established", "split from a cell", "App. C;", "Annex 3 (English)",
              "fill-ins collapsed", ".pdf,", "table row for")
    lines = page.locator(".srow .src").all_inner_texts()
    assert lines, "no source line on any problem row"
    for line in lines:
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
    row = _statement(page, "H303").first
    assert row.get_attribute("data-status") == "ok"
    text = row.inner_text()
    assert "outside US OSHA HazCom's scope" in text
    assert "allowed as extra information" in text
    # And it is not something to do.
    # Nothing to do about its wording; Section 16 not writing it out is a
    # separate thing to check, said in Section 16's own line.
    todo = page.locator(".todo li").all_inner_texts()
    assert not [t for t in todo if "H303" in t and not t.startswith("Section 16")], todo


def test_a_newer_ghs_card_explains_itself(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_c15_osha_partial_key"])
    with_closest = _statement(page, "P319").first.inner_text()
    assert "Correct GHS Rev.8 wording" in with_closest
    assert "has not adopted P319" in with_closest

    without = _statement(page, "P317").first.inner_text()
    assert "has no equivalent statement" in without
    assert "Ask whether that’s accepted." in without


def test_punctuation_differences_share_one_collapsed_card(page, server, shots_dir):
    """Each is its own row now - shown, not hidden - and they share one action."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_capitalisation"])
    assert page.locator("details.block.minor").count() == 0
    row = _minor_row(page, "P303+P361+P353")
    assert row.count() == 1
    assert row.first.is_visible()


def test_the_collapsed_card_shows_both_texts_when_opened(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_capitalisation"])
    row = _minor_row(page, "P303+P361+P353")
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
    shown = _statement(page, "P501").first.locator(".cmp .txt").first.inner_text()
    assert "to …" in shown, shown
    assert "to…" not in shown, shown


def test_an_undetectable_regulation_shows_the_page(page, server, shots_dir):
    """No raw JSON in the browser, ever."""
    page.goto(server + "/", wait_until="domcontentloaded")
    page.set_input_files("#file", f"{FIXTURES}/pattern_undetectable.pdf")
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
    """One column still, with the official text as a reference line."""
    from lingua_oracle.keys.store import load_key
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["pattern_unfilled_blanks"])
    official = load_key("us_osha", "en").by_code()["P501"].text
    row = _statement(page, "P501").first
    assert row.locator(".cmp.single").count() == 1
    reference = row.locator(".reference")
    assert reference.count() == 1
    text = reference.inner_text()
    assert text.startswith("Official wording:")
    assert official in text
    assert "is the blank to fill in" in text
    assert reference.locator("mark").count() == 0
    assert row.locator("mark").count() == 1


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


def test_every_checked_item_is_a_row_in_its_section(page, server, shots_dir):
    """The page is the SDS, in order, with the unread sections said."""
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["clean_eu_da"])
    headings = page.locator(".sds-section > header h2").all_inner_texts()
    assert len(headings) == 16
    assert headings[3] == "Section 4 · First aid measures"
    assert headings[-1] == "Section 16 · Other information"
    two = page.locator("#s2")
    assert "SIGNAL WORD & HAZARD STATEMENTS" in two.inner_text().upper()
    assert "PRECAUTIONARY STATEMENTS" in two.inner_text().upper()
    assert two.locator(".srow").filter(has_text="Signal word").count() == 1
    assert page.locator(".skipped").count() == 0     # every section is judged
    four = page.locator("#s4")
    assert four.locator(".srow").filter(has_text="Heading").count() == 1
    assert "4.1 Beskrivelse af førstehjælpsforanstaltninger" in four.inner_text()  # da


def test_a_section_judged_only_by_its_structure_never_says_correct(page, server, shots_dir):
    from tests.ui.manifest import BY_NAME

    _upload(page, server, BY_NAME["defect_a02_hazard"])
    five = page.locator("section#s5 header .pills").first.inner_text()
    assert "Structure correct" in five and five.strip() != "✓ Correct", five
    assert "have correct structure" in page.locator(".verdict .banner p").first.inner_text()
    page.locator("summary", has_text="Technical details").first.click()
    details = page.locator("details.block").filter(has_text="Technical details").first
    text = details.inner_text()
    assert "Checked: the wording of each statement" in text, text[:400]
    assert "Pictograms, layout and Sections 4-8" not in text
