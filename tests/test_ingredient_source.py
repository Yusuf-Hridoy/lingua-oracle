"""Which composition a check reads, and why.

A product we hold is checked against the composition we hold. A sheet from
someone else is checked against its own Section 3. The two are never mixed, and
neither is read while the reader is still being asked which product this is.

ExactSDS is mocked throughout; the fixtures are synthetic.
"""

from __future__ import annotations

from lingua_oracle.ingredients.client import Ingredient
from lingua_oracle.ingredients.section import PENDING
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf
from tests.test_combined_report import FakeApp, row

PRODUCT = "Synthetic Test Solvent SDS-TEST-001"

# Nothing like what any fixture prints in its own Section 3, so a section
# built from this cannot have come from the sheet.
ONLY_IN_THE_APP = [
    Ingredient(cas="7647-01-0", name="<app substance>", h_codes=["H314"],
               concentration="12"),
]


def _cas_in(section) -> set[str]:
    """Every CAS number the section worked from, whichever section it is."""
    found = {s.get("cas") for s in getattr(section, "substances", [])}
    for result in getattr(section, "results", []):
        found |= {c.get("cas") for c in result.get("contributions", [])}
    return {c for c in found if c}


def _check(fixture, regulation, app_):
    return check_pdf(pdf(fixture), regulation, ingredients=True,
                     client_factory=lambda: app_)


def _matched_app(ingredients=None):
    return FakeApp(
        library=[row(1, PRODUCT)],
        products={1: {"product_name": PRODUCT}},
        ingredients={1: list(ONLY_IN_THE_APP if ingredients is None
                             else ingredients)})


def _ambiguous_app():
    return FakeApp(
        library=[row(1, f"{PRODUCT} A"), row(2, f"{PRODUCT} B")],
        products={1: {"product_name": f"{PRODUCT} A"},
                  2: {"product_name": f"{PRODUCT} B"}},
        ingredients={1: list(ONLY_IN_THE_APP), 2: list(ONLY_IN_THE_APP)})


# -- a product we hold ---------------------------------------------------------


def test_a_matched_product_is_checked_against_the_app_not_section_three():
    """The sheet prints a table of its own; the record is what gets checked."""
    report = _check("pattern_named_with_ingredients", "eu_clp", _matched_app())
    assert report.ingredients.source == "app"
    assert _cas_in(report.ingredients) == {"7647-01-0"}


def test_the_mixture_uses_the_same_composition_as_the_ingredients():
    """One report, one composition. Two would be two answers to one question."""
    report = _check("pattern_named_with_ingredients", "eu_clp", _matched_app())
    assert report.ingredients.source == "app"
    assert _cas_in(report.mixture) == {"7647-01-0"}


def test_an_empty_record_is_not_quietly_replaced_by_the_sheet():
    """No entries on file is a fact about the product, not a reason to guess."""
    report = _check("pattern_named_with_ingredients", "eu_clp",
                    _matched_app(ingredients=[]))
    assert report.ingredients.source == "app"
    assert not _cas_in(report.ingredients)


# -- somebody else's sheet -----------------------------------------------------


def test_an_unmatched_sheet_is_checked_against_its_own_section_three():
    report = _check("pattern_supplier_ingredients", "eu_clp",
                    FakeApp(library=[]))
    assert report.ingredients.source == "pdf"
    assert "67-64-1" in _cas_in(report.ingredients)
    assert "7647-01-0" not in _cas_in(report.ingredients)


def test_the_mixture_of_an_unmatched_sheet_comes_from_the_sheet_too():
    report = _check("pattern_supplier_ingredients", "eu_clp",
                    FakeApp(library=[]))
    assert "67-64-1" in _cas_in(report.mixture)
    assert "7647-01-0" not in _cas_in(report.mixture)


# -- while a choice is pending -------------------------------------------------


def test_a_pending_choice_reads_neither_source():
    report = _check("clean_eu_en", "eu_clp", _ambiguous_app())
    assert report.ingredients.source == "nothing"
    assert report.ingredients.message == PENDING
    assert not _cas_in(report.ingredients)


def test_the_mixture_asks_for_the_choice_rather_than_reading_the_sheet():
    report = _check("clean_eu_en", "eu_clp", _ambiguous_app())
    assert report.mixture.state == "nothing"
    assert "Choose the product above" in report.mixture.message
    assert not _cas_in(report.mixture)


def test_a_pending_choice_still_records_what_section_two_states():
    """So choosing a product needs nothing from the uploaded file again."""
    report = _check("clean_eu_en", "eu_clp", _ambiguous_app())
    assert report.mixture.stated
