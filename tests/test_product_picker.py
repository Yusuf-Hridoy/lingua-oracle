"""Choosing between candidate products, and what that recalculates.

ExactSDS is mocked throughout; the fixtures are synthetic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lingua_oracle.api.app import app
from lingua_oracle.ingredients.client import Ingredient
from lingua_oracle.ingredients.matching import (
    Candidate,
    match_product,
    normalised,
    rank,
)
from lingua_oracle.ingredients.section import PENDING
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf
from tests.test_combined_report import FakeApp, Line, row

PRODUCT = "Synthetic Test Solvent SDS-TEST-001"


# -- ranking -------------------------------------------------------------------


@pytest.mark.parametrize(("a", "b"), [
    ("WD-40 Specialist (Aerosol)", "WD 40 specialist aerosol"),
    ("Thing  Two", "thing two"),
    ("A/B-C", "a b c"),
])
def test_names_that_differ_only_in_punctuation_are_one_name(a, b):
    assert normalised(a) == normalised(b)


def test_the_exact_name_comes_first():
    ranked = rank([Candidate(1, "Thing Extra"), Candidate(2, "Thing")], "Thing")
    assert [c.product_id for c in ranked] == [2, 1]


def test_then_the_same_regulation():
    ranked = rank([Candidate(1, "Thing", "us_osha", "2026-09-01"),
                   Candidate(2, "Thing", "eu_clp", "2026-01-01")],
                  "Thing", "eu_clp")
    assert [c.product_id for c in ranked] == [2, 1]


def test_then_the_most_recent():
    ranked = rank([Candidate(1, "Thing", "eu_clp", "2026-01-01"),
                   Candidate(2, "Thing", "eu_clp", "2026-09-01")],
                  "Thing", "eu_clp")
    assert [c.product_id for c in ranked] == [2, 1]


def test_one_exact_name_settles_it_even_among_many():
    app_ = FakeApp(library=[row(1, "Thing"), row(2, "Thing Extra"),
                            row(3, "Another Thing")])
    match = match_product(app_, "sheet.pdf", [Line("Product name: Thing")])
    assert match.state == "matched"
    assert match.product_id == 1


def test_several_equally_good_names_are_offered():
    app_ = FakeApp(library=[row(1, "Thing A"), row(2, "Thing B")])
    match = match_product(app_, "sheet.pdf", [Line("Product name: Thing")])
    assert match.state == "ambiguous"
    assert [c.product_id for c in match.candidates] == [1, 2]


# -- what the report does while a choice is pending ----------------------------


def _check(fixture, regulation, app_, **kwargs):
    return check_pdf(pdf(fixture), regulation, ingredients=True,
                     client_factory=lambda: app_, **kwargs)


def _ambiguous_app():
    return FakeApp(
        library=[row(1, f"{PRODUCT} A"), row(2, f"{PRODUCT} B")],
        products={1: {"product_name": f"{PRODUCT} A"},
                  2: {"product_name": f"{PRODUCT} B"}},
        ingredients={
            1: [Ingredient(cas="67-64-1", name="<a>", h_codes=["H225"],
                           concentration="60")],
            2: [Ingredient(cas="1333-74-0", name="<b>", h_codes=["H220"],
                           concentration="30")]})


def test_a_pending_choice_says_so_rather_than_nothing_to_check():
    report = _check("clean_eu_en", "eu_clp", _ambiguous_app())
    section = report.ingredients
    assert section.match_state == "ambiguous"
    assert section.message == PENDING
    assert len(section.candidates) == 2


def test_the_candidates_carry_what_a_person_needs_to_choose():
    report = _check("clean_eu_en", "eu_clp", _ambiguous_app())
    for candidate in report.ingredients.candidates:
        assert candidate["product_id"]
        assert candidate["name"]
        assert "regulation" in candidate


def test_what_section_two_states_is_kept_for_the_re_run():
    """So choosing a product needs nothing from the uploaded file."""
    report = _check("clean_eu_en", "eu_clp", _ambiguous_app())
    assert report.mixture is not None
    assert report.mixture.stated


# -- choosing ------------------------------------------------------------------


def test_choosing_a_product_fills_both_sections():
    from lingua_oracle.ingredients.section import recheck

    app_ = _ambiguous_app()
    report = _check("clean_eu_en", "eu_clp", app_)
    assert report.ingredients.source == "nothing"

    recheck(report, 1, client_factory=lambda: app_)
    assert report.ingredients.source == "app"
    assert report.ingredients.product_id == 1
    assert report.ingredients.evidence == "chosen by you"
    assert report.mixture.state in ("calculated", "nothing")


def test_choosing_uses_the_apps_composition_not_the_sheets():
    from lingua_oracle.ingredients.section import recheck

    app_ = _ambiguous_app()
    report = _check("pattern_supplier_ingredients", "eu_clp", app_)
    recheck(report, 2, client_factory=lambda: app_)
    cas = {s["cas"] for s in report.ingredients.substances}
    assert cas == {"1333-74-0"}          # the app's, not Section 3's three


def test_the_choice_is_remembered_on_the_report(tmp_path, monkeypatch):
    from lingua_oracle.ingredients.section import recheck
    from lingua_oracle.report import render

    monkeypatch.setattr(render, "reports_dir", lambda: tmp_path)
    app_ = _ambiguous_app()
    report = _check("clean_eu_en", "eu_clp", app_)
    recheck(report, 2, client_factory=lambda: app_)
    render.save(report)
    again = render.load(report.id)
    assert again.ingredients.product_id == 2
    assert again.ingredients.evidence == "chosen by you"


def test_forcing_a_product_skips_the_search_entirely():
    app_ = _ambiguous_app()
    report = check_pdf(pdf("clean_eu_en"), "eu_clp", ingredients=True,
                       client_factory=lambda: app_)
    assert report.ingredients.match_state == "ambiguous"


# -- the route -----------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_choosing_an_unknown_report_is_a_404(client):
    assert client.post("/reports/nope/product",
                       data={"product_id": "1"}).status_code == 404


def test_a_failure_while_choosing_is_reported_not_swallowed(tmp_path,
                                                            monkeypatch, client):
    from lingua_oracle.report import render

    monkeypatch.setattr(render, "reports_dir", lambda: tmp_path)
    report = _check("clean_eu_en", "eu_clp", _ambiguous_app())
    render.save(report)
    monkeypatch.setenv("LINGUA_EXACTSDS", "off")
    response = client.post(f"/reports/{report.id}/product",
                           data={"product_id": "1"}, follow_redirects=False)
    assert response.status_code == 303
    again = render.load(report.id)
    assert again.ingredients.source == "skipped"
    assert "Could not check that product" in again.ingredients.message
