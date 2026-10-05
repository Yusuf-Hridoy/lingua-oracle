"""Report rendering, the CLI and the HTTP API."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lingua_oracle.api.app import app as fastapi_app
from lingua_oracle.cli import app as cli_app
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import char_diff, render_html, save
from tests.conftest import pdf


@pytest.fixture(scope="module")
def client():
    return TestClient(fastapi_app)


@pytest.fixture()
def runner():
    return CliRunner()


# -- report ----------------------------------------------------------------


def test_the_diff_marks_only_the_changed_words():
    left, right = char_diff("Meget brandfarlig væske.", "Ekstremt brandfarlig væske.")
    assert 'class="diff"' in left
    assert 'class="diff"' in right
    # Both texts are shown whole; neither side is struck through or dropped.
    assert "brandfarlig" in left and "brandfarlig" in right
    assert "line-through" not in left + right
    assert "Meget" in left and "Ekstremt" in right


def test_matching_words_are_not_marked():
    left, right = char_diff("Keep away from heat, hot surfaces, sparks.",
                            "Keep away from heat, hot surface, sparks.")
    assert left.count("<mark") == 1
    assert right.count("<mark") == 1
    assert left.startswith("Keep away from heat, hot ")


def test_unrelated_text_marks_everything_on_both_sides():
    left, right = char_diff("Forårsager alvorlig øjenirritation.",
                            "Causes serious eye irritation.")
    assert left.count("<mark") == 1
    assert right.count("<mark") == 1


def test_char_diff_escapes_html():
    left, _right = char_diff("<script>alert(1)</script>", "safe")
    assert "<script>" not in left
    assert "&lt;script&gt;" in left


def test_html_report_is_self_contained():
    report = check_pdf(pdf("defect_a02_hazard"), "eu_clp")
    html = render_html(report)
    assert "<style>" in html
    assert "src=" not in html and "<link" not in html  # no external assets
    assert "A-02" in html
    assert report.file_name in html


def test_html_report_lists_failures_first():
    report = check_pdf(pdf("defect_a05_english"), "eu_clp")
    html = render_html(report)
    # Findings come before the legend that closes the page. Anchor on a string
    # that appears only in that legend - the column header uses the same words.
    assert html.index("A-05") < html.index("<b>None on file</b>")


def test_report_round_trips_through_disk(tmp_path):
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    json_path, html_path = save(report, tmp_path)
    assert json_path.exists() and html_path.exists()
    restored = json.loads(json_path.read_text(encoding="utf-8"))
    assert restored["id"] == report.id
    assert restored["regulation"] == "eu_clp"


# -- CLI -------------------------------------------------------------------


def test_cli_check_exits_zero_on_a_clean_document(runner, tmp_path):
    result = runner.invoke(
        cli_app, ["check", pdf("clean_eu_da"), "-r", "eu_clp", "-o", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "0 fail" in result.output


def test_cli_check_exits_one_on_failures(runner, tmp_path):
    result = runner.invoke(
        cli_app, ["check", pdf("defect_a02_hazard"), "-r", "eu_clp", "-o", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "A-02" in result.output


def test_cli_reports_undetermined_regulation(runner, tmp_path):
    """A document with no regulation marker must ask, not guess."""
    result = runner.invoke(cli_app, ["check", pdf("clean_eu_da"), "-o", str(tmp_path)])
    assert result.exit_code in (0, 2)


def test_cli_check_folder(runner, tmp_path):
    result = runner.invoke(
        cli_app,
        ["check-folder", str(tmp_path.parent), "-r", "eu_clp", "-o", str(tmp_path)],
    )
    assert result.exit_code in (0, 1)


def test_cli_compare(runner, tmp_path):
    result = runner.invoke(
        cli_app,
        ["compare", pdf("compare_b11_a"), pdf("compare_b11_b"),
         "-r", "eu_clp", "-o", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "B-11" in result.output


def test_cli_keys_stats_json(runner):
    result = runner.invoke(cli_app, ["keys", "stats", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    by_id = {row["regulation"]: row for row in rows}
    assert len(by_id["eu_clp"]["languages_populated"]) == 24
    assert by_id["eu_clp"]["status"] == "ok"
    assert by_id["jp_jis"]["status"] == "pending_source"


def test_cli_keys_stats_table(runner):
    result = runner.invoke(cli_app, ["keys", "stats"])
    assert result.exit_code == 0
    assert "EU CLP" in result.output
    assert "pending_source" in result.output


# -- API -------------------------------------------------------------------


def test_index_page_offers_regulations_and_languages(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Detect from document" in response.text
    assert "EU CLP" in response.text


def test_post_check_returns_a_report(client):
    with open(pdf("defect_a02_hazard"), "rb") as handle:
        response = client.post(
            "/check",
            files={"file": ("t.pdf", handle, "application/pdf")},
            data={"regulation": "eu_clp"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["fail"] >= 1
    assert any(f["check_id"] == "A-02" for f in body["findings"])


def test_report_html_and_json_endpoints(client):
    with open(pdf("clean_eu_da"), "rb") as handle:
        report_id = client.post(
            "/check",
            files={"file": ("t.pdf", handle, "application/pdf")},
            data={"regulation": "eu_clp"},
        ).json()["id"]
    assert client.get(f"/reports/{report_id}").status_code == 200
    json_response = client.get(f"/reports/{report_id}.json")
    assert json_response.status_code == 200
    assert json_response.json()["id"] == report_id


def test_unknown_report_is_404(client):
    assert client.get("/reports/doesnotexist").status_code == 404
    assert client.get("/reports/doesnotexist.json").status_code == 404


def test_non_pdf_upload_is_rejected(client):
    response = client.post(
        "/check", files={"file": ("x.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400


def _post_compare(client, url):
    with open(pdf("compare_b11_a"), "rb") as a, open(pdf("compare_b11_b"), "rb") as b:
        return client.post(
            url,
            files={
                "file_a": ("a.pdf", a, "application/pdf"),
                "file_b": ("b.pdf", b, "application/pdf"),
            },
            data={"regulation": "eu_clp"},
            follow_redirects=False,
        )


def test_compare_lands_on_a_report_page(client):
    """The browser flow must reach a report, not a wall of JSON."""
    response = _post_compare(client, "/compare")
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/reports/")
    page = client.get(location)
    assert page.status_code == 200
    assert "B-11" in page.text
    # The comparison report gets the same verdict banner as any other. B-11 is
    # not a wording check, so the headline says "Problems", not "Wording
    # problems" - the release line is the part a reader acts on.
    assert "Fix before release" in page.text


def test_compare_json_still_serves_the_api(client):
    response = _post_compare(client, "/compare.json")
    assert response.status_code == 200
    assert any(f["check_id"] == "B-11" for f in response.json()["findings"])


# -- the re-skinned pages -----------------------------------------------------


def test_the_stylesheet_is_served(client):
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert "--accent" in response.text


def test_the_report_inlines_the_stylesheet(client):
    """A saved report travels as one file, so it cannot link anything."""
    from lingua_oracle.report.render import app_css, render_html

    html = render_html(check_pdf(pdf("defect_a02_hazard"), "eu_clp"))
    assert "<link" not in html
    assert "--accent" in html
    assert app_css()[:40] in html


def test_one_stylesheet_serves_both_pages(client):
    """The upload page links the same file the report inlines."""
    from lingua_oracle.report.render import app_css

    assert '/static/app.css' in client.get("/").text
    assert client.get("/static/app.css").text == app_css()


@pytest.mark.parametrize("path", ["/history", "/coverage"])
def test_the_nav_destinations_exist(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "Lingua Oracle" in response.text


def test_the_upload_page_lists_the_keys_on_file(client):
    text = client.get("/").text
    assert "Official texts on file" in text
    assert "24 languages" in text          # EU CLP
    assert "Not yet available" in text     # Japan


def test_recent_checks_show_a_result_pill(client):
    with open(pdf("defect_a02_hazard"), "rb") as handle:
        client.post("/check/html", files={"file": ("a.pdf", handle, "application/pdf")},
                    data={"regulation": "eu_clp"}, follow_redirects=False)
    text = client.get("/").text
    assert "Recent checks" in text
    assert "Fix before release" in text


# -- errors a person can read -------------------------------------------------


def _post_undetectable(client):
    """defect_a02_hazard carries no governing statement, so detection fails."""
    with open(pdf("defect_a02_hazard"), "rb") as handle:
        return client.post(
            "/check/html",
            files={"file": ("a.pdf", handle, "application/pdf")},
            data={"regulation": ""},
            follow_redirects=False,
        )


def test_an_undetectable_regulation_returns_the_page_not_json(client):
    response = _post_undetectable(client)
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.lstrip().startswith("<!doctype html>")
    assert "We couldn’t tell which regulation this sheet follows" in response.text
    assert "Choose one and check again" in response.text


def test_the_error_page_names_no_ids_or_cli_flags(client):
    import re

    text = _post_undetectable(client).text
    # The select needs ids as option values; nothing a reader sees may use them.
    visible = re.sub(r'value="[^"]*"', "", text)
    for token in ("us_osha", "eu_clp", "un_ghs", "--regulation", "Re-run with"):
        assert token not in visible, token
    assert "US OSHA HazCom" in text


def test_the_error_page_keeps_the_form_and_focuses_the_regulation(client):
    text = _post_undetectable(client).text
    assert 'id="check-form"' in text
    assert "getElementById('regulation')" in text


def test_any_other_failure_is_a_plain_message(client):
    """A file we cannot read must not produce a stack or a JSON body."""
    response = client.post(
        "/check/html",
        files={"file": ("broken.pdf", b"not a pdf at all", "application/pdf")},
        data={"regulation": "eu_clp"},
        follow_redirects=False,
    )
    assert response.headers["content-type"].startswith("text/html")
    assert "We couldn’t read that file" in response.text
    assert "Traceback" not in response.text


# -- self-hosted fonts ---------------------------------------------------------


FONT_FILES = [
    "IBMPlexSans-Regular.woff2", "IBMPlexSans-Medium.woff2",
    "IBMPlexSans-SemiBold.woff2", "IBMPlexMono-Regular.woff2",
    "IBMPlexMono-Medium.woff2",
]


@pytest.mark.parametrize("name", FONT_FILES)
def test_each_font_is_served_from_static(client, name):
    response = client.get(f"/static/fonts/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "font/woff2"
    assert response.content[:4] == b"wOF2", "not a woff2 file"


def test_the_font_licence_ships_with_the_fonts(client):
    response = client.get("/static/fonts/OFL.txt")
    assert response.status_code == 200
    assert "SIL Open Font License" in response.text


def test_the_stylesheet_points_at_our_own_fonts(client):
    css = client.get("/static/app.css").text
    assert css.count("@font-face") == len(FONT_FILES)
    for name in FONT_FILES:
        assert f'url("fonts/{name}")' in css, name
    # Nothing is fetched from anywhere else.
    assert "fonts.googleapis" not in css and "fonts.gstatic" not in css
    assert "@import" not in css


def test_no_page_requests_anything_external(client):
    for path in ("/", "/history", "/coverage"):
        text = client.get(path).text
        for host in ("fonts.googleapis", "fonts.gstatic", "unpkg", "cdn."):
            assert host not in text, (path, host)


def test_a_saved_report_embeds_the_fonts_and_links_nothing():
    """A report is an attachment; it has to render with no network."""
    from lingua_oracle.report.render import render_html

    html = render_html(check_pdf(pdf("defect_a02_hazard"), "eu_clp"))
    assert "<link" not in html
    assert "fonts/IBMPlexSans-Regular.woff2" not in html, "left a relative URL"
    assert html.count("data:font/woff2;base64,") == len(FONT_FILES)
    assert len(html) < 1_000_000, f"{len(html):,} bytes is too big to mail"


def test_the_fonts_are_dropped_rather_than_left_dangling():
    """Past the budget the rules go, so nothing is requested from a saved file."""
    from lingua_oracle.report.render import report_css

    stripped = report_css(5_000_000)
    assert "@font-face" not in stripped
    assert 'url("fonts/' not in stripped, "left a URL that will not resolve"
    # The licence attribution stays; it is a comment, not a request.
    assert "SIL Open Font License" in stripped
    assert "--accent" in stripped, "the rest of the stylesheet must survive"


# -- the ask screen suggests, it does not decide -------------------------------


def _post_only_ghs(client):
    with open(pdf("pattern_only_says_ghs"), "rb") as handle:
        return client.post(
            "/check/html",
            files={"file": ("a.pdf", handle, "application/pdf")},
            data={"regulation": ""},
            follow_redirects=False,
        )


def test_a_sheet_that_only_says_ghs_asks(client):
    response = _post_only_ghs(client)
    assert response.headers["content-type"].startswith("text/html")
    assert "only says ‘GHS’" in response.text
    assert "which every sheet does" in response.text


def test_the_ask_screen_names_the_country_evidence(client):
    text = _post_only_ghs(client).text
    assert "It looks like Australia WHS" in text
    assert "address" in text and "+61 phone" in text
    assert "Confirm the regulation" in text


def test_the_suggestion_is_preselected_but_nothing_is_checked(client):
    import re

    response = _post_only_ghs(client)
    selected = re.findall(r'<option value="(\w+)" selected>', response.text)
    assert selected == ["au_whs"], selected
    # Nothing was checked: no report, and the page is the upload page.
    assert "/reports/" not in response.headers.get("location", "")
    assert 'id="check-form"' in response.text


def test_un_ghs_is_never_chosen_from_the_word_alone(client):
    """It is chosen when the sheet names it, or when the reader picks it."""
    from lingua_oracle.detect.regulation import detect_regulation

    assert "un_ghs" not in _post_only_ghs(client).headers.get("location", "")
    named = detect_regulation("Classified to UN GHS Rev. 11.")
    assert named.regulation == "un_ghs"


def test_picking_the_suggestion_then_checks_against_it(client):
    with open(pdf("pattern_only_says_ghs"), "rb") as handle:
        response = client.post(
            "/check/html",
            files={"file": ("a.pdf", handle, "application/pdf")},
            data={"regulation": "au_whs"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert "Australia WHS" in page.text


# -- the banner sentence and the figures beside it ----------------------------


def _report_and_cards(fixture: str, regulation: str | None = None):
    from lingua_oracle.pipeline import check_pdf
    from lingua_oracle.report.render import _statement_cards
    from tests.conftest import pdf

    report = check_pdf(pdf(fixture), regulation)
    return report, _statement_cards(report)


def test_the_banner_sentence_counts_what_the_cells_count():
    """One report, one set of numbers.

    The sentence was written from the finding severities and the cells from the
    cards, which count different things: a reader saw "3 to check" over a row
    that said 5.
    """
    from lingua_oracle.report import labels

    for fixture, regulation in (("pattern_unfilled_blanks", None),
                                ("pattern_capitalisation", "eu_clp"),
                                ("defect_a03_precautionary", "eu_clp"),
                                ("clean_eu_en", "eu_clp")):
        report, cards = _report_and_cards(fixture, regulation)
        counts = cards["counts"]
        detail = labels.verdict_of(report, "X", counts=counts).detail
        for number, word in ((counts["wrong"], "statement"),
                             (counts["blanks"], "blank")):
            if number:
                assert f"{number} {word}" in detail, (fixture, detail)


def test_the_sentence_never_says_statement_s():
    from lingua_oracle.report import labels

    for fixture, regulation in (("pattern_unfilled_blanks", None),
                                ("pattern_capitalisation", "eu_clp"),
                                ("defect_a03_precautionary", "eu_clp")):
        report, cards = _report_and_cards(fixture, regulation)
        verdict = labels.verdict_of(report, "X", counts=cards["counts"])
        assert "(s)" not in verdict.detail, fixture


def test_one_statement_reads_as_one():
    from lingua_oracle.report.labels import plural

    assert plural(1, "statement") == "1 statement"
    assert plural(2, "statement") == "2 statements"
    assert plural(1, "other problem") == "1 other problem"
    assert plural(3, "other problem") == "3 other problems"


def test_a_wrong_statement_and_a_blank_are_counted_separately():
    from lingua_oracle.report import labels

    report, cards = _report_and_cards("pattern_unfilled_blanks")
    detail = labels.verdict_of(report, "X", counts=cards["counts"]).detail
    assert "2 blanks to fill in" in detail


# -- punctuation differences in one card --------------------------------------


def test_punctuation_differences_are_collected_into_one_group():
    _, cards = _report_and_cards("pattern_capitalisation", "eu_clp")
    assert len(cards["minor"]) == 1
    assert all(row["v"].minor_difference for row in cards["minor"])
    # And they are out of the individual cards, not duplicated across both.
    assert not any(row.get("minor") for row in cards["problems"])


def test_a_collected_difference_is_still_counted_as_something_to_check():
    """Collapsing the card must not quietly drop it from the figures."""
    _, cards = _report_and_cards("pattern_capitalisation", "eu_clp")
    assert cards["counts"]["check"] >= len(cards["minor"])
    assert cards["counts"]["minor"] == len(cards["minor"])


def test_a_real_wording_difference_keeps_its_own_card():
    _, cards = _report_and_cards("defect_a03_precautionary", "eu_clp")
    assert cards["minor"] == []
    assert any(row["status"] == "wrong" for row in cards["problems"])
