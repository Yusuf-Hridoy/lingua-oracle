"""Which list an ingredient is judged against, and what a difference means.

A classification list is somebody's law. Annex VI is the EU's and the GB MCL
is Great Britain's, and each says a substance in it shall be classified as the
entry says. HCIS is Australia's and says of itself that it is guidance. US
OSHA, WHMIS and the GHS publish no list at all: they publish criteria.

So the same missing code is a fault on an EU sheet and a thing worth checking
on an American one, and the report has to say which it is showing.

Fixtures are synthetic; ExactSDS is mocked.
"""

from __future__ import annotations

import pytest

from lingua_oracle.ingredients.compare import Status
from lingua_oracle.ingredients.section import worst
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import ingredient_status, render_html
from lingua_oracle.substances.lists import LISTS, for_regulation
from lingua_oracle.substances.load import for_check
from tests.conftest import pdf
from tests.test_combined_report import FakeApp

SHEET = "pattern_supplier_ingredients"


def _check(regulation, fixture=SHEET):
    return check_pdf(pdf(fixture), regulation, ingredients=True,
                     client_factory=lambda: FakeApp(library=[]))


# -- one list per regulation ---------------------------------------------------


@pytest.mark.parametrize(("regulation", "name", "binding"), [
    ("eu_clp", "annex_vi", True),
    ("uk_clp", "gb_mcl", True),
    ("au_whs", "au_hcis", False),
    ("us_osha", "annex_vi", False),
    ("ca_whmis", "annex_vi", False),
    ("un_ghs", "annex_vi", False),
])
def test_each_regulation_has_one_list_and_a_reason(regulation, name, binding):
    use = for_regulation(regulation)
    assert use.name == name
    assert use.binding is binding
    assert len(use.authority) > 40, "every line of the table is cited"


def test_japan_has_no_list_and_borrows_none():
    assert for_regulation("jp_jis") is None
    assert for_check("jp_jis") == (None, None)


def test_every_list_named_in_the_table_is_on_file():
    for regulation in LISTS:
        use, table = for_check(regulation)
        assert table is not None, f"{regulation}: {use.name} is not built"
        assert table.entries


def test_the_australian_list_says_of_itself_that_it_is_guidance():
    """Not assumed from the fact that it is a database: HCIS states it."""
    assert "guidance only" in for_regulation("au_whs").authority


def test_the_binding_lists_cite_the_article_that_binds_them():
    assert "Article 4(3)" in for_regulation("eu_clp").authority
    assert "Article 4(3)" in for_regulation("uk_clp").authority


# -- what a difference from each list means ------------------------------------


def test_a_missing_code_against_a_binding_list_is_a_fault():
    report = _check("eu_clp")
    assert report.ingredients.counts["fix"] >= 1
    assert worst(report.ingredients) is Status.FIX


def test_the_same_code_against_a_reference_list_is_worth_checking():
    report = _check("us_osha")
    assert report.ingredients.counts["fix"] >= 1
    assert worst(report.ingredients) is Status.INFO


def test_the_card_says_which_list_and_that_it_does_not_bind():
    body = render_html(_check("us_osha"))
    assert "CLP Annex VI Part 3, Table 3 lists" in body
    assert "US OSHA HazCom has no binding list" in body


def test_the_card_against_a_binding_list_still_says_requires():
    body = render_html(_check("eu_clp"))
    assert "CLP Annex VI Part 3, Table 3 requires" in body
    assert "has no binding list" not in body


@pytest.mark.parametrize(("regulation", "expected"), [
    ("eu_clp", "CLP Annex VI Part 3, Table 3 (binding)"),
    ("uk_clp", "GB mandatory classification and labelling list (binding)"),
    ("us_osha", "CLP Annex VI Part 3, Table 3 (reference only)"),
])
def test_the_section_states_which_list_was_used(regulation, expected):
    _, reason = ingredient_status(_check(regulation).ingredients)
    assert expected in reason


def test_a_regulation_with_no_list_says_so_rather_than_borrowing_one():
    word, reason = ingredient_status(_check("jp_jis").ingredients)
    assert word == "nothing to check"
    assert "No list of classified substances is on file" in reason


# -- the mixture takes its classifications from the same list ------------------


def test_the_mixture_classifies_an_ingredient_as_its_own_list_does():
    """Australia classifies toluene for reproductive toxicity in category 1A;
    Great Britain has category 2. The same sheet gets each regulation's own
    answer, not the EU's for all of them."""
    from decimal import Decimal

    from lingua_oracle.mixture.section import _ingredient
    from lingua_oracle.substances.load import for_check as lists_for

    for regulation, expected in (("uk_clp", "Repr. 2"), ("au_whs", "Repr. 1A")):
        _, table = lists_for(regulation)
        ingredient, _ = _ingredient("108-88-3", "toluene", "50", [], table,
                                    table.by_cas())
        assert any(str(c) == expected for c in ingredient.classes), (
            f"{regulation}: {[str(c) for c in ingredient.classes]}")
        assert ingredient.high == Decimal(50)


def test_an_ingredient_with_no_classification_anywhere_is_undisclosed():
    """A trade secret is part of the mixture and no rule can use it. Counting
    it as declared would make the calculation look better informed than it is."""
    report = check_pdf("data/validation/third_party/us_osha_1.pdf", "us_osha",
                       ingredients=True, client_factory=lambda: FakeApp(library=[]))
    said = [a for a in report.mixture.assumptions if "no classification" in a]
    assert said, report.mixture.assumptions
    assert "counted with the undisclosed part" in said[0]
    assert int(report.mixture.undisclosed) > 50
