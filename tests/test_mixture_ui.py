"""What the Mixture section shows, and whose rules it says it used.

Every regulation is calculated against its own published text, so the page has
to name that text rather than one regulation's for all of them. Fixtures are
synthetic; ExactSDS is mocked.
"""

from __future__ import annotations

import pytest

from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import render_html
from tests.conftest import pdf
from tests.test_combined_report import FakeApp


def _page(fixture, regulation):
    report = check_pdf(pdf(fixture), regulation, ingredients=True,
                       client_factory=lambda: FakeApp(library=[]))
    return report, render_html(report)


@pytest.mark.parametrize(("regulation", "document"), [
    ("eu_clp", "Regulation (EC) No 1272/2008, Annex I"),
    ("us_osha", "29 CFR 1910.1200 Appendix A"),
    ("un_ghs", "UN GHS Rev.11 (2025)"),
])
def test_the_section_names_the_document_its_rules_came_from(regulation, document):
    _, body = _page("pattern_supplier_ingredients", regulation)
    assert document in body


def test_a_card_cites_the_section_and_page_behind_its_limit():
    """A number a reader cannot look up is a number they have to take on trust."""
    report, body = _page("pattern_supplier_ingredients", "un_ghs")
    cited = [r["citation"] for r in report.mixture.results if r["citation"]]
    assert any("page" in c for c in cited)
    assert any(c in body for c in cited)


@pytest.mark.parametrize(("regulation", "display"), [
    ("us_osha", "US OSHA HazCom"), ("ca_whmis", "Canada WHMIS")])
def test_a_class_the_regulation_does_not_have_says_so_on_the_page(
        regulation, display):
    """Not a gap in the calculation: those standards have no aquatic classes."""
    _, body = _page("pattern_aquatic_statement", regulation)
    assert f"Not covered by {display}" in body
    assert regulation not in body


def test_the_same_class_is_calculated_where_the_regulation_has_it():
    report, body = _page("pattern_aquatic_statement", "eu_clp")
    aquatic = next(r for r in report.mixture.results
                   if r["hazard_class"] == "Aquatic Chronic 2")
    assert aquatic["verdict"] != "not_calculated"
    assert "Not covered by" not in body


def test_a_class_nothing_was_calculated_for_shows_no_empty_comparison():
    """Not calculated has one thing to say, not two sides to put side by side."""
    report, body = _page("pattern_aquatic_statement", "us_osha")
    assert [r for r in report.mixture.results
            if r["verdict"] == "not_calculated"]
    message = "Not covered by US OSHA HazCom"
    card = body[body.rindex("<article", 0, body.index(message)):
                body.index(message)]
    assert "Calculation gives" not in card


def test_japan_says_the_check_is_not_available_rather_than_borrowing_rules():
    report, body = _page("pattern_supplier_ingredients", "jp_jis")
    assert report.mixture.state == "out_of_scope"
    assert "Japan JIS Z 7252/7253" in body
    assert "no document on file" in body


# -- every section, every time -------------------------------------------------


SECTIONS = ("Wording", "Ingredients", "Mixture")


@pytest.mark.parametrize("regulation", ["eu_clp", "us_osha", "un_ghs",
                                        "ca_whmis", "au_whs", "uk_clp",
                                        "jp_jis"])
def test_all_three_sections_are_on_every_report(regulation):
    """A reader should never have to work out whether a check ran."""
    _, body = _page("pattern_supplier_ingredients", regulation)
    for section in SECTIONS:
        assert f"<h2>{section}" in body


@pytest.mark.parametrize("regulation", ["eu_clp", "us_osha", "jp_jis"])
def test_every_section_says_in_one_line_what_it_did(regulation):
    _, body = _page("pattern_supplier_ingredients", regulation)
    said = _statuses(body)
    assert len(said) == 3
    for word, reason in said:
        assert word in ("checked", "nothing to check", "can&#39;t check")
        assert len(reason) > 10, reason


def test_a_section_that_could_not_run_says_why_in_plain_words():
    report = check_pdf(pdf("pattern_supplier_ingredients"), "jp_jis",
                       ingredients=True, client_factory=lambda: FakeApp(library=[]))
    body = render_html(report)
    word, reason = _statuses(body)[2]
    assert word == "can&#39;t check"
    assert "Japan JIS Z 7252/7253" in reason
    assert "no document on file" in reason


def test_a_report_without_the_ingredient_check_still_shows_both_sections():
    """The sections are the page's shape, not a side effect of what was run."""
    body = render_html(check_pdf(pdf("clean_eu_en"), "eu_clp"))
    for section in SECTIONS:
        assert f"<h2>{section}" in body
    assert "the ingredient check was not run" in body
    assert "the mixture calculation was not run" in body


def _statuses(body):
    import re

    return [(m.group(1).strip(), " ".join(m.group(2).split()))
            for m in re.finditer(
                r'class="status s-[a-z]+">\s*([^<&]*(?:&#39;[^<&]*)?)\s*&mdash;'
                r'([^<]*)<', body)]
