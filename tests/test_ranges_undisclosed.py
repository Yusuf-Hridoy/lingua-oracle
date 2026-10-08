"""Ranges and what is undisclosed.

undisclosed = max(0, 100 - the sum of the UPPER bounds of every range Section
3 gives), the ingredients no rule can use included. When the upper bounds reach
100 % nothing is undisclosed and the uncertainty is the ranges' own, which is
why every hazard is evaluated at both ends of every range.

The coolant fixture has a real GB coolant's shape - ethylene glycol 40-60 %,
water 40-60 %, diethylene glycol < 2.5 %, two minor salts - with an invented
product.
"""

from __future__ import annotations

from decimal import Decimal

from lingua_oracle.keys.builders.annex_vi import load_table
from lingua_oracle.mixture import section as mixture
from lingua_oracle.mixture.calculate import calculate
from lingua_oracle.mixture.classes import parse_class
from lingua_oracle.mixture.model import from_codes
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf


def _coolant():
    return check_pdf(pdf("pattern_glycol_coolant_gb"), ingredients=True).mixture


def test_upper_bounds_reaching_100_leave_nothing_undisclosed():
    found = _coolant()
    assert found.declared_total == "124.5"
    assert found.undisclosed == "0"


def test_an_ingredient_no_rule_can_use_still_counts_as_declared():
    # Water has no classification and no list entry. It used to drop out of
    # the total, and 37.5 % of a fully declared mixture was called undisclosed.
    found = _coolant()
    assert any("count towards the total" in a and "Water" in a
               for a in found.assumptions)


def test_nothing_is_said_to_come_from_an_undisclosed_zero():
    for result in _coolant().results:
        assert "may come from the undisclosed" not in result["message"], result["message"]


def test_a_mixture_short_of_100_still_names_what_is_undisclosed():
    # Section 2 states an eye hazard the declared 30 % does not give: it may
    # come from the 70 % the sheet does not declare, and says so with the number.
    rows = [{"cas": None, "name": "irritant", "h_codes": ["H315"],
             "concentration": "20 - 30 %"}]
    built = mixture.build(rows, [], [], "eu_clp", load_table(),
                          stated_override=["Skin Irrit. 2", "Eye Irrit. 2"])
    assert built.undisclosed == "70"
    eye = next(r for r in built.results if r["family"] == "Eye")
    assert "undisclosed 70 %" in eye["message"]


def test_the_declared_total_is_what_the_caller_says_when_it_says():
    irritant = from_codes(None, "irritant", Decimal(40), Decimal(60), ["H315"])
    _, summary = calculate([irritant], [parse_class("Skin Irrit. 2")], "eu_clp",
                           declared=Decimal(120))
    assert (summary["declared_total"], summary["undisclosed"]) == ("120", "0")


def test_each_hazard_is_evaluated_at_both_ends_of_every_range():
    report = check_pdf(pdf("pattern_supplier_ingredients"), "eu_clp",
                       ingredients=True)
    stot = next(r for r in report.mixture.results
                if r["family"] == "Target organ toxicity, single exposure")
    # Acetone 30 - 60 %: the narcotic-effects sum at each end.
    assert "STOT SE 3 (narcotic effects): 30 %" in stot["trace"]
    assert "STOT SE 3 (narcotic effects): 60 %" in stot["trace"]
