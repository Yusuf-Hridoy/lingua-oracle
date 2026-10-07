"""Comparing Section 2 with the ingredients one hazard family at a time.

The case this is built from is a real WHMIS sheet's shape: Section 2 calls the
mixture corrosive and a category 1 target organ toxicant, the 61 % of it that
is declared is two irritant, narcotic ingredients, and 39 % is not declared at
all. Compared class by class that sheet is wrong three times over. Compared
per family it is a sheet that is stricter than the part of the mixture it
discloses, which is a different thing and is usually not a fault.

Fixtures are synthetic; ExactSDS is mocked.
"""

from __future__ import annotations

import pytest

from lingua_oracle.mixture.classes import parse_class as P
from lingua_oracle.mixture.families import (
    by_family,
    family_of,
    stricter,
    strictest,
)
from lingua_oracle.mixture.rule_table import load
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf
from tests.test_combined_report import FakeApp

SHEET = "pattern_stricter_than_declared"


def _check(regulation, fixture=SHEET):
    return check_pdf(pdf(fixture), regulation, ingredients=True,
                     client_factory=lambda: FakeApp(library=[]))


def _family(report, name):
    return next((r for r in report.mixture.results
                 if r["hazard_class"] == name), None)


# -- which class is the stricter -----------------------------------------------


@pytest.mark.parametrize(("stricter_one", "milder"), [
    ("Skin Corr. 1", "Skin Irrit. 2"),
    ("Skin Corr. 1A", "Skin Corr. 1B"),
    ("Skin Corr. 1B", "Skin Corr. 1C"),
    ("Skin Irrit. 2", "Skin Irrit. 3"),
    ("Eye Dam. 1", "Eye Irrit. 2"),
    ("Eye Irrit. 2A", "Eye Irrit. 2B"),
    ("Carc. 1A", "Carc. 1B"),
    ("Carc. 1B", "Carc. 2"),
    ("Muta. 1", "Muta. 2"),
    ("Repr. 1A", "Repr. 2"),
    ("Skin Sens. 1A", "Skin Sens. 1B"),
    ("STOT SE 1", "STOT SE 2"),
    ("STOT RE 1", "STOT RE 2"),
    ("Aquatic Acute 1", "Aquatic Acute 2"),
    ("Aquatic Chronic 1", "Aquatic Chronic 4"),
])
def test_the_order_inside_a_family(stricter_one, milder):
    assert stricter(P(stricter_one), P(milder))
    assert not stricter(P(milder), P(stricter_one))


def test_a_category_without_its_sub_division_is_not_the_weaker_reading():
    """A sheet that writes "Skin Corr. 1" has not said 1C, and is not wrong
    for declining to guess."""
    assert not stricter(P("Skin Corr. 1B"), P("Skin Corr. 1"))
    assert not stricter(P("Skin Corr. 1"), P("Skin Corr. 1B"))


def test_classes_from_different_families_are_not_compared():
    assert not stricter(P("Skin Corr. 1"), P("Eye Irrit. 2"))
    assert family_of(P("Skin Corr. 1")) != family_of(P("Eye Dam. 1"))


def test_the_strictest_of_several_is_the_one_kept():
    assert str(strictest([P("Skin Irrit. 2"), P("Skin Corr. 1B")])) \
        == "Skin Corr. 1B"


def test_a_class_this_tool_does_not_compare_has_no_family():
    assert family_of(P("Flam. Liq. 2")) is None
    assert by_family([P("Flam. Liq. 2")]) == {}


# -- the sheet that started it -------------------------------------------------


def test_the_declared_total_and_what_is_missing_from_it():
    report = _check("eu_clp")
    assert report.mixture.declared_total == "61"
    assert report.mixture.undisclosed == "39"


def test_section_two_being_stricter_about_the_skin_is_consistent():
    skin = _family(_check("eu_clp"), "Skin")
    assert skin["verdict"] == "consistent"
    assert skin["stated_class"] == "Skin Corr. 1"
    assert skin["calculated_class"] == "Skin Irrit. 2"
    assert "stricter than the declared ingredients" in skin["message"]
    assert "undisclosed 39 %" in skin["message"]


def test_the_eye_follows_from_the_skin_where_the_act_says_so():
    """CLP says a skin corrosive is to be considered as seriously damaging to
    the eye, so a sheet stating Skin Corr. 1 has stated Eye Dam. 1 too."""
    eye = _family(_check("eu_clp"), "Eye")
    assert eye["verdict"] == "consistent"
    assert eye["stated_class"] == "Eye Dam. 1"
    assert eye["calculated_class"] == "Eye Irrit. 2"
    assert "Skin Corr. 1 in Section 2 is also Eye Dam. 1" in eye["implied_from"]
    assert "Annex I, 3.3.2.2.2" in eye["implied_from"]


def test_the_same_sheet_under_a_regulation_that_does_not_say_so():
    """WHMIS incorporates GHS Rev.7, and neither it nor the Hazardous Products
    Regulations says a skin corrosive damages the eye. The implication is not
    borrowed from another regulation, so the eye is a finding there."""
    assert load("ca_whmis").implied_by("Skin Corr. 1") is None
    eye = _family(_check("ca_whmis"), "Eye")
    assert eye["verdict"] == "inconsistent"
    assert eye["implied_from"] == ""


def test_narcotic_effects_against_a_target_organ_are_never_a_contradiction():
    stot = _family(_check("eu_clp"),
                   "Target organ toxicity, single exposure")
    assert stot["verdict"] == "cannot_tell"
    assert stot["message"].startswith("Check this: STOT SE 3")
    assert "may cover it if it targets the same organ" in stot["message"]


def test_the_whole_sheet_produces_one_verdict_per_family():
    report = _check("eu_clp")
    assert [(r["hazard_class"], r["verdict"]) for r in report.mixture.results] == [
        ("Target organ toxicity, single exposure", "cannot_tell"),
        ("Eye", "consistent"),
        ("Skin", "consistent"),
    ]


# -- the other way round -------------------------------------------------------


def test_the_ingredients_being_stricter_is_a_finding():
    """The direction that matters: a mixture more hazardous than it says."""
    report = _check("eu_clp", "pattern_supplier_ingredients")
    stot = _family(report, "Target organ toxicity, single exposure")
    assert stot is None or stot["verdict"] != "consistent"
    skin = _family(report, "Eye")
    assert skin["verdict"] in ("consistent", "inconsistent", "cannot_tell")


def test_a_hazard_the_ingredients_give_and_section_two_omits():
    report = _check("eu_clp", "pattern_sensitiser_gas")
    found = _family(report, "Respiratory sensitisation")
    assert found["verdict"] == "inconsistent"
    assert found["stated_class"] == ""
    assert "Section 2 does not list this hazard" in found["message"]
