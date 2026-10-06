"""One upload, both checks.

ExactSDS is mocked throughout: these tests never reach the network, and the
fixtures are synthetic documents with fictional products. The Annex VI entries
are real, because they are public law.
"""

from __future__ import annotations

import pytest

from lingua_oracle.ingredients.client import Ingredient
from lingua_oracle.ingredients.matching import (
    match_product,
    product_id_in_file_name,
    product_name_in,
)
from lingua_oracle.models import IngredientSection
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf

PRODUCT = "Synthetic Test Solvent SDS-TEST-001"


class Line:
    def __init__(self, text: str):
        self.text = text
        self.page = 1


class FakeApp:
    """An ExactSDS that answers from a dict. Records what it was asked."""

    def __init__(self, library=None, ingredients=None, products=None):
        self.library = library if library is not None else []
        self._ingredients = ingredients or {}
        self._products = products or {}
        self.asked: list[str] = []

    def login(self):
        pass

    def get(self, path, **params):
        self.asked.append(path)
        if path == "/library":
            query = (params.get("q") or "").casefold()
            rows = [r for r in self.library
                    if query in (r.get("product_name") or "").casefold()]
            return {"count": len(rows), "results": rows}
        return None

    def product(self, product_id):
        self.asked.append(f"/products/{product_id}")
        return self._products.get(product_id, {})

    def ingredients(self, product_id):
        return self._ingredients.get(product_id, [])

    def substance_source(self, cas):
        return "stub"

    def close(self):
        pass


def row(product_id: int, name: str) -> dict:
    return {"primary_product_id": product_id, "product_name": name}


# -- reading the sheet ---------------------------------------------------------


@pytest.mark.parametrize(("file_name", "expected"), [
    ("eu_clp_en_4250.pdf", 4250),
    ("us_osha_en_58677.pdf", 58677),
    ("some-supplier-sheet.pdf", None),
    ("50-85-1.pdf", None),
])
def test_an_application_download_carries_its_product_id(file_name, expected):
    assert product_id_in_file_name(file_name) == expected


@pytest.mark.parametrize(("lines", "expected"), [
    (["1.1 Product identifier", "Product name: <fictional product>"],
     "<fictional product>"),
    (["Product name", "<fictional product>"], "<fictional product>"),
    (["Trade name : <fictional product>"], "<fictional product>"),
    (["Produktname: <fictional product>"], "<fictional product>"),
    (["Nothing useful here"], None),
])
def test_the_product_name_is_read_from_its_label(lines, expected):
    assert product_name_in([Line(t) for t in lines]) == expected


# -- matching ------------------------------------------------------------------


def test_one_match_is_used():
    app = FakeApp(library=[row(7, "<fictional product>")])
    match = match_product(app, "sheet.pdf", [Line("Product name: <fictional product>")])
    assert match.state == "matched"
    assert match.product_id == 7
    assert match.is_app_product


def test_several_matches_are_offered_not_guessed():
    app = FakeApp(library=[row(7, "<fictional product> A"),
                           row(8, "<fictional product> B")])
    match = match_product(app, "sheet.pdf", [Line("Product name: <fictional product>")])
    assert match.state == "ambiguous"
    assert {c.product_id for c in match.candidates} == {7, 8}
    assert match.product_id is None


def test_no_match_is_a_supplier_sheet_not_a_problem():
    app = FakeApp(library=[])
    match = match_product(app, "sheet.pdf", [Line("Product name: <fictional product>")])
    assert match.state == "none"
    assert "no product named" in match.evidence


def test_the_file_name_beats_the_product_name():
    """An application download carries its own id, which is better evidence."""
    app = FakeApp(library=[row(7, "<fictional product>")],
                  products={4250: {"product_name": "<the real one>"}})
    match = match_product(app, "eu_clp_en_4250.pdf",
                          [Line("Product name: <fictional product>")])
    assert match.product_id == 4250
    assert "file name" in match.evidence


def test_a_file_name_id_that_does_not_exist_falls_back_to_the_name():
    app = FakeApp(library=[row(7, "<fictional product>")], products={})
    match = match_product(app, "eu_clp_en_9999.pdf",
                          [Line("Product name: <fictional product>")])
    assert match.product_id == 7


# -- the section on a real upload ---------------------------------------------


def _check(fixture, regulation, app):
    return check_pdf(pdf(fixture), regulation, ingredients=True,
                     client_factory=lambda: app)


def test_an_app_product_is_checked_against_its_record():
    app = FakeApp(
        library=[row(7, PRODUCT)],
        products={7: {"product_name": PRODUCT}},
        ingredients={7: [Ingredient(cas="67-64-1", name="<substance>",
                                    h_codes=["H225", "H319"],
                                    concentration="60")]})
    report = _check("clean_eu_en", "eu_clp", app)
    section = report.ingredients
    assert section.source == "app"
    assert section.match_state == "matched"
    assert section.product_id == 7
    assert section.counts["fix"] == 1          # acetone is missing H336, EUH066
    assert section.under_classified == 1


def test_a_supplier_sheet_is_read_from_its_own_section_three():
    report = _check("pattern_supplier_ingredients", "eu_clp", FakeApp())
    section = report.ingredients
    assert section.source == "pdf"
    assert section.match_state == "none"
    assert section.counts["substances"] >= 1


def test_a_sheet_without_ingredient_codes_says_so_and_does_not_fail():
    report = _check("clean_eu_en", "eu_clp", FakeApp())
    section = report.ingredients
    assert section.source == "nothing"
    assert "nothing to check" in section.message.lower()
    assert section.counts == {}
    assert section.under_classified == 0


def test_an_unreachable_app_does_not_cost_the_wording_check():
    class Broken(FakeApp):
        def login(self):
            raise OSError("connection refused")

    report = _check("clean_eu_en", "eu_clp", Broken())
    assert report.statements, "the wording check must still have run"
    assert report.ingredients.source == "skipped"
    assert "not reachable" in report.ingredients.message.lower()


def test_the_wording_check_runs_even_when_the_section_explodes():
    class Exploding(FakeApp):
        def login(self):
            raise RuntimeError("something nobody predicted")

    report = _check("clean_eu_en", "eu_clp", Exploding())
    assert report.statements
    assert report.ingredients.source == "skipped"


def test_nothing_runs_when_ingredients_are_not_asked_for():
    report = check_pdf(pdf("clean_eu_en"), "eu_clp")
    assert report.ingredients is None


# -- the verdict over both halves ---------------------------------------------


def _verdict(report):
    from lingua_oracle.report import labels
    from lingua_oracle.report.render import _statement_cards

    return labels.verdict_of(report, "EU CLP",
                             counts=_statement_cards(report)["counts"])


def test_an_under_classified_ingredient_reaches_the_verdict():
    app = FakeApp(
        library=[row(7, PRODUCT)],
        products={7: {"product_name": PRODUCT}},
        ingredients={7: [Ingredient(cas="67-64-1", name="<substance>",
                                    h_codes=["H225", "H319"],
                                    concentration="60")]})
    report = _check("clean_eu_en", "eu_clp", app)
    verdict = _verdict(report)
    assert verdict.release == "Fix before release"
    assert "Annex VI" in verdict.detail


def test_a_clean_sheet_with_clean_ingredients_stays_clean():
    app = FakeApp(
        library=[row(7, PRODUCT)],
        products={7: {"product_name": PRODUCT}},
        ingredients={7: [Ingredient(cas="67-64-1", name="<substance>",
                                    h_codes=["H225", "H319", "H336", "EUH066"],
                                    concentration="60")]})
    report = _check("clean_eu_en", "eu_clp", app)
    assert report.ingredients.counts["fix"] == 0
    assert _verdict(report).release != "Fix before release"


def test_the_two_halves_keep_their_own_counts():
    app = FakeApp(
        library=[row(7, PRODUCT)],
        products={7: {"product_name": PRODUCT}},
        ingredients={7: [Ingredient(cas="67-64-1", name="<substance>",
                                    h_codes=["H225"], concentration="60")]})
    report = _check("clean_eu_en", "eu_clp", app)
    from lingua_oracle.report.render import _statement_cards

    wording = _statement_cards(report)["counts"]
    assert wording["wrong"] == 0                     # the sheet's wording is right
    assert report.ingredients.counts["fix"] == 1     # its ingredients are not


# -- the rendered page ---------------------------------------------------------


def test_the_report_names_the_product_it_matched():
    from lingua_oracle.report.render import render_html

    app = FakeApp(
        library=[row(7, PRODUCT)],
        products={7: {"product_name": PRODUCT}},
        ingredients={7: [Ingredient(cas="67-64-1", name="<substance>",
                                    h_codes=["H225"], concentration="60")]})
    body = render_html(_check("clean_eu_en", "eu_clp", app))
    assert "Matched to ExactSDS product" in body
    assert PRODUCT in body
    assert "(7)" in body
    assert "Not this product?" in body


def test_the_report_has_both_sections():
    from lingua_oracle.report.render import render_html

    body = render_html(_check("pattern_supplier_ingredients", "eu_clp", FakeApp()))
    assert "Wording" in body
    assert "Ingredients" in body
    assert "read from Section 3" in body


def test_a_skipped_section_says_why_on_the_page():
    from lingua_oracle.report.render import render_html

    class Broken(FakeApp):
        def login(self):
            raise OSError("connection refused")

    body = render_html(_check("clean_eu_en", "eu_clp", Broken()))
    assert "ExactSDS not reachable" in body


def test_an_old_report_without_the_section_still_renders():
    from lingua_oracle.report.render import render_html

    report = check_pdf(pdf("clean_eu_en"), "eu_clp")
    assert report.ingredients is None
    assert "Ingredients &middot;" not in render_html(report)


# -- "nothing to check" is not a verdict --------------------------------------


def test_an_empty_run_is_not_a_failure():
    from lingua_oracle.ingredients.report import headline

    release, tone, detail = headline(
        {"substances": 0, "ingredients": 0, "fix": 0, "with_entry": 0,
         "ok": 0, "info": 0, "not_checked": 0, "products": 3, "uses": 0,
         "uses_under_classified": 0, "inconsistent_substances": 0})
    assert release == "Nothing to check"
    assert tone == "check"
    assert "nothing was compared" in detail


def test_a_section_with_no_counts_contributes_nothing():
    from lingua_oracle.ingredients.section import worst

    assert worst(None) is None
    assert worst(IngredientSection(source="nothing")) is None


def test_a_classification_cell_is_not_read_as_a_statement():
    """Section 3 prints "Flam. Liq. 2, H225; Eye Irrit. 2, H319".

    The text between one code and the next is the following substance's hazard
    class. Compared with the statement's official wording it reports a supplier
    for something their sheet does not say - and every sheet with a
    classification column in Section 3 would get it.
    """
    report = check_pdf(pdf("pattern_supplier_ingredients"), "eu_clp")
    wrong = [s for s in report.statements if s.status == "wrong"]
    assert wrong == [], [(s.code, s.found) for s in wrong]


@pytest.mark.parametrize("phrase", [
    "Press. Gas", "Eye Irrit. 2", "STOT SE 3", "Flam. Liq. 2", "Water-react. 1",
])
def test_a_bare_hazard_class_never_becomes_a_statement(phrase):
    from lingua_oracle.detect.codes import extract_hits

    class Line:
        def __init__(self, text):
            self.text, self.page = text, 1

    hits = extract_hits([Line(f"H220 {phrase}; H225 Flam. Liq. 1")])
    assert hits[0].code == "H220"
    assert hits[0].text == ""


def test_the_card_says_where_the_codes_came_from():
    from lingua_oracle.report.render import render_html

    supplier = render_html(
        _check("pattern_supplier_ingredients", "eu_clp", FakeApp()))
    assert "This sheet says" in supplier

    app = FakeApp(
        library=[row(7, PRODUCT)], products={7: {"product_name": PRODUCT}},
        ingredients={7: [Ingredient(cas="67-64-1", name="<substance>",
                                    h_codes=["H225"], concentration="60")]})
    assert "The app says" in render_html(_check("clean_eu_en", "eu_clp", app))


# -- the third section ---------------------------------------------------------


def test_a_supplier_sheet_gets_a_mixture_section():
    report = _check("pattern_supplier_ingredients", "eu_clp", FakeApp())
    mixture = report.mixture
    assert mixture.state == "calculated"
    assert mixture.counts["ingredients"] == 3
    assert mixture.declared_total != "0"
    assert mixture.results


def test_the_mixture_section_names_its_paragraphs():
    report = _check("pattern_supplier_ingredients", "eu_clp", FakeApp())
    cited = [r for r in report.mixture.results if r["citation"]]
    assert cited
    for result in cited:
        assert result["citation"].startswith("Regulation (EC) No 1272/2008")
        assert "Annex I, " in result["citation"]


def test_an_osha_sheet_is_calculated_against_oshas_own_appendix():
    """Every supported regulation gets a mixture section, not only CLP."""
    report = _check("pattern_supplier_ingredients", "us_osha", FakeApp())
    assert report.mixture.state == "calculated"
    assert report.mixture.source_document == "29 CFR 1910.1200 Appendix A"
    for result in report.mixture.results:
        assert "1272/2008" not in result["citation"]


def test_a_regulation_with_no_rules_on_file_says_so():
    report = _check("clean_eu_en", "jp_jis", FakeApp())
    assert report.mixture.state == "out_of_scope"
    assert "Japan JIS Z 7252/7253" in report.mixture.message
    assert "no document on file" in report.mixture.message


def test_a_sheet_with_no_composition_has_nothing_to_calculate():
    report = _check("clean_eu_en", "eu_clp", FakeApp())
    assert report.mixture.state == "nothing"
    assert report.mixture.results == []


def test_the_mixture_reaches_the_overall_verdict():
    report = _check("pattern_supplier_ingredients", "eu_clp", FakeApp())
    verdict = _verdict(report)
    assert report.mixture.counts["inconsistent"] >= 1
    assert "inconsistent with the ingredients" in verdict.detail


def test_the_report_renders_all_three_sections():
    from lingua_oracle.report.render import render_html

    body = render_html(_check("pattern_supplier_ingredients", "eu_clp", FakeApp()))
    assert "Wording &middot;" in body
    assert "Ingredients &middot;" in body
    assert "Mixture &middot;" in body
    assert "Section 2 says" in body
    assert "Calculation gives" in body
    assert "Calculation trace" in body


def test_each_section_keeps_its_own_counts():
    from lingua_oracle.report.render import _statement_cards

    report = _check("pattern_supplier_ingredients", "eu_clp", FakeApp())
    wording = _statement_cards(report)["counts"]
    assert set(wording) >= {"wrong", "fix", "check"}
    assert set(report.ingredients.counts) >= {"fix", "ok"}
    assert set(report.mixture.counts) >= {"inconsistent", "consistent"}


def test_an_old_report_without_a_mixture_still_renders():
    from lingua_oracle.report.render import render_html

    report = check_pdf(pdf("clean_eu_en"), "eu_clp")
    assert report.mixture is None
    assert "Mixture &middot;" not in render_html(report)


def test_the_mixture_card_shows_the_contributing_ingredients():
    from lingua_oracle.report.render import render_html

    body = render_html(_check("pattern_supplier_ingredients", "eu_clp", FakeApp()))
    assert "Counted as" in body
    assert "67-64-1" in body or "Synthetic component A" in body
