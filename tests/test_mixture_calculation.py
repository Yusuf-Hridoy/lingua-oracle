"""Ranges, the undisclosed remainder, scope, and the verdicts they produce."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from lingua_oracle.mixture.calculate import calculate
from lingua_oracle.mixture.classes import parse_class
from lingua_oracle.mixture.concentration import parse as parse_concentration
from lingua_oracle.mixture.model import from_codes


def ing(low, high, *codes, cas="100-00-5"):
    return from_codes(cas, f"<{cas}>", D(str(low)), D(str(high)), list(codes))


def verdicts(results):
    return {r.hazard_class: r.verdict for r in results}


# -- both ends of every range --------------------------------------------------


def test_a_range_that_agrees_at_both_ends_is_decided():
    results, _ = calculate([ing(6, 8, "H314")], [parse_class("Skin Corr. 1")],
                           "eu_clp")
    assert verdicts(results)["Skin Corr. 1"] == "consistent"


def test_a_range_that_straddles_a_limit_cannot_be_decided():
    """3 % of a corrosive gives Skin Irrit. 2, 8 % gives Skin Corr. 1."""
    results, _ = calculate([ing(3, 8, "H314")], [], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Skin Corr. 1")
    assert result.verdict == "cannot_tell"
    assert result.calculated_low == "Skin Irrit. 2"
    assert result.calculated_high == "Skin Corr. 1"
    assert "low end" in result.message and "high end" in result.message


def test_a_range_that_only_triggers_at_the_top_says_so():
    results, _ = calculate([ing(5, 30, "H400")], [], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Aquatic Acute 1")
    assert result.verdict == "cannot_tell"
    assert result.calculated_low == "no classification"
    assert result.calculated_high == "Aquatic Acute 1"


def test_a_single_value_is_a_range_with_equal_ends():
    assert parse_concentration("60").low == parse_concentration("60").high
    results, _ = calculate([ing(60, 60, "H400")], [], "eu_clp")
    assert verdicts(results)["Aquatic Acute 1"] == "inconsistent"


# -- what Section 2 says, against what the ingredients give ---------------------


def test_a_calculated_class_the_sheet_lacks_is_inconsistent():
    results, _ = calculate([ing(30, 30, "H400")], [], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Aquatic Acute 1")
    assert result.verdict == "inconsistent"
    assert "does not state it" in result.message


def test_a_class_the_sheet_states_and_the_calculation_gives_is_consistent():
    results, _ = calculate([ing(30, 30, "H400")],
                           [parse_class("Aquatic Acute 1")], "eu_clp")
    assert verdicts(results)["Aquatic Acute 1"] == "consistent"


def test_a_stated_class_may_come_from_the_undisclosed_part():
    """Declared ingredients reach 40 %; the other 60 % is not ours to see."""
    results, summary = calculate([ing(40, 40, "H315")],
                                 [parse_class("Carc. 1")], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Carc. 1")
    assert result.verdict == "cannot_tell"
    assert "undisclosed 60 %" in result.message
    assert summary["undisclosed"] == "60"


def test_with_nothing_undisclosed_a_stated_class_is_inconsistent():
    results, _ = calculate([ing(100, 100, "H315")], [parse_class("Carc. 1")],
                           "eu_clp")
    result = next(r for r in results if r.hazard_class == "Carc. 1")
    assert result.verdict == "inconsistent"
    assert "nothing undisclosed" in result.message


def test_a_class_outside_the_rules_is_not_calculated_rather_than_contradicted():
    results, _ = calculate([ing(100, 100, "H315")],
                           [parse_class("Flam. Liq. 2")], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Flam. Liq. 2")
    assert result.verdict == "not_calculated"
    assert "does not calculate" in result.message


# -- scope ---------------------------------------------------------------------


@pytest.mark.parametrize("regulation", ["eu_clp", "uk_clp", "us_osha",
                                        "un_ghs", "au_whs", "ca_whmis"])
def test_every_regulation_with_rules_on_file_is_calculated(regulation):
    """One upload, one answer, whichever regulation the sheet is written to."""
    results, summary = calculate([ing(30, 30, "H315")], [], regulation)
    assert summary["in_scope"] is True
    assert results


@pytest.mark.parametrize("regulation", ["eu_clp", "uk_clp", "un_ghs", "au_whs"])
def test_the_aquatic_classes_are_calculated_where_a_regulation_has_them(
        regulation):
    results, _ = calculate([ing(30, 30, "H400")], [], regulation)
    assert any(r.hazard_class.startswith("Aquatic") for r in results)


@pytest.mark.parametrize("regulation", ["us_osha", "ca_whmis"])
def test_an_aquatic_class_is_not_a_finding_where_a_regulation_has_none(
        regulation):
    """Not a gap in what we know: those standards have no aquatic classes."""
    results, summary = calculate([ing(30, 30, "H400")], [], regulation)
    assert summary["in_scope"] is True
    assert not [r for r in results if r.hazard_class.startswith("Aquatic")]
    assert "Aquatic Acute" in summary["not_covered"]


def test_a_class_a_regulation_does_not_have_is_said_to_be_so():
    results, _ = calculate([ing(30, 30, "H315")],
                           [parse_class("Aquatic Chronic 2")], "us_osha")
    result = next(r for r in results if r.hazard_class == "Aquatic Chronic 2")
    assert result.verdict == "not_calculated"
    assert result.message == "Not covered by US OSHA HazCom."


def test_japan_has_no_rules_on_file_and_is_not_guessed_at():
    results, summary = calculate([ing(30, 30, "H400")], [], "jp_jis")
    assert results == []
    assert summary["in_scope"] is False


# -- what the result carries ---------------------------------------------------


def test_a_result_names_the_paragraph_it_came_from():
    results, _ = calculate([ing(30, 30, "H400")], [], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Aquatic Acute 1")
    assert result.citation.endswith("Annex I, 4.1.3.5.5, Table 4.1.1")
    assert result.citation.startswith("Regulation (EC) No 1272/2008")


def test_a_result_names_the_ingredients_that_caused_it():
    results, _ = calculate([ing(30, 30, "H400", cas="7440-00-0")], [], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Aquatic Acute 1")
    assert result.contributions[0]["cas"] == "7440-00-0"
    assert result.contributions[0]["percentage"] == "30"


def test_every_assumption_is_recorded():
    results, _ = calculate([ing(30, 30, "H400")], [], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Aquatic Acute 1")
    assert any("M = 1 assumed" in a for a in result.assumptions)


def test_the_trace_shows_the_arithmetic():
    results, _ = calculate([ing(30, 30, "H400")], [], "eu_clp")
    result = next(r for r in results if r.hazard_class == "Aquatic Acute 1")
    assert any("Sum of (Aquatic Acute 1 x M)" in line for line in result.trace)


def test_the_worst_verdicts_come_first():
    results, _ = calculate(
        [ing(30, 30, "H400"), ing(3, 8, "H314", cas="2-00-0")],
        [parse_class("Aquatic Acute 1")], "eu_clp")
    order = [r.verdict for r in results]
    assert order == sorted(order, key=lambda v: {
        "inconsistent": 0, "cannot_tell": 1, "consistent": 2,
        "not_calculated": 3}[v])


# -- concentrations ------------------------------------------------------------


@pytest.mark.parametrize(("text", "low", "high"), [
    ("100", "100", "100"),
    ("30 - 60", "30", "60"),
    ("5-10%", "5", "10"),
    (">= 90 - <= 100", "90", "100"),
    ("50-<75", "50", "75"),
])
def test_concentrations_become_ranges(text, low, high):
    parsed = parse_concentration(text)
    assert (str(parsed.low), str(parsed.high)) == (low, high)


def test_an_open_bound_is_closed_and_the_assumption_recorded():
    upper = parse_concentration("< 15")
    assert (str(upper.low), str(upper.high)) == ("0", "15")
    assert "0 to 15" in upper.assumption
    lower = parse_concentration(">= 90")
    assert (str(lower.low), str(lower.high)) == ("90", "100")
    assert "90 to 100" in lower.assumption


@pytest.mark.parametrize("text", ["", None, "N/A", "trade secret", "-"])
def test_text_with_no_number_is_no_concentration(text):
    assert parse_concentration(text) is None
