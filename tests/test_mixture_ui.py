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
