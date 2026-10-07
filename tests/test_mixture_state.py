"""The physical state, where a limit depends on it.

CLP Annex I Table 3.4.5 sets a respiratory sensitiser's limit at 1,0 % for a
solid or a liquid and 0,2 % for a gas. Nothing in a composition says which the
mixture is; Section 9 does. Where it does not, both limits stay in play and
the report says the answer depends on it rather than picking one.

Fixtures are synthetic; ExactSDS is mocked.
"""

from __future__ import annotations

import pytest

from lingua_oracle.mixture.rule_table import Value, load
from lingua_oracle.mixture.state import applicable, physical_state
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf
from tests.test_combined_report import FakeApp, Line


def _check(fixture, regulation="eu_clp"):
    return check_pdf(pdf(fixture), regulation, ingredients=True,
                     client_factory=lambda: FakeApp(library=[]))


def _class(report, name):
    """The card about one classification, whichever side of it it appears on.

    Cards are per hazard family now, so a class is found by what the family
    was calculated as or by what Section 2 said about it.
    """
    return next((r for r in report.mixture.results
                 if name in (r["hazard_class"], r["calculated_class"],
                             r["stated_class"])), None)


# -- reading Section 9 ---------------------------------------------------------


@pytest.mark.parametrize(("fixture", "expected"), [
    ("pattern_sensitiser_liquid", "solid/liquid"),
    ("pattern_sensitiser_gas", "gas"),
    ("pattern_sensitiser_unstated", ""),
])
def test_the_state_is_read_from_section_nine(fixture, expected):
    assert _check(fixture).mixture.physical_state == expected


def test_a_value_on_the_line_below_its_label_is_still_the_answer():
    """A two-column Section 9 flattens to "State :" and then "liquid"."""
    lines = [Line("SECTION 9: Physical and chemical properties"),
             Line("State :"), Line("liquid")]
    assert physical_state(lines) == "solid/liquid"


def test_nothing_is_read_from_outside_section_nine():
    lines = [Line("SECTION 2: Hazards identification"),
             Line("Physical state : gas"),
             Line("SECTION 9: Physical and chemical properties"),
             Line("Odour : characteristic")]
    assert physical_state(lines) is None


# -- what it changes -----------------------------------------------------------


def test_a_liquid_is_not_classified_by_the_limit_for_a_gas():
    """0,5 % of a respiratory sensitiser is under the 1,0 % a liquid has to
    clear. Reporting it would be a finding the act does not support."""
    assert _class(_check("pattern_sensitiser_liquid"), "Resp. Sens. 1") is None


def test_the_same_mixture_as_a_gas_is_classified():
    """0,5 % is over the 0,2 % a gas has to clear."""
    result = _class(_check("pattern_sensitiser_gas"), "Resp. Sens. 1")
    assert result is not None
    assert result["verdict"] == "inconsistent"


def test_a_sheet_that_does_not_say_gets_both_answers_and_neither():
    report = _check("pattern_sensitiser_unstated")
    result = _class(report, "Resp. Sens. 1")
    assert result["verdict"] == "cannot_tell"
    assert "physical state" in result["message"]
    assert "0.2" in result["message"] and "1.0" in result["message"]
    assert "Section 9 does not say" in result["message"]


def test_the_limit_used_is_named_in_the_assumptions():
    report = _check("pattern_sensitiser_gas")
    result = _class(report, "Resp. Sens. 1")
    assert any("0.2 %" in a and "gas" in a for a in result["assumptions"])


def test_the_report_says_which_state_it_read():
    from lingua_oracle.report.render import render_html

    body = render_html(_check("pattern_sensitiser_liquid"))
    assert "read as a solid or a liquid" in body


# -- choosing the limits that apply --------------------------------------------


def _value(amount, qualifier):
    return Value(amount=amount, document="<doc>", section="<section>",
                 page=None, qualifier=qualifier)


def test_a_limit_for_the_other_state_is_not_this_mixtures():
    values = (_value(1, "solid/liquid"), _value(2, "gas"))
    assert [v.amount for v in applicable(values, "gas")] == [2]
    assert [v.amount for v in applicable(values, "solid/liquid")] == [1]


def test_a_limit_for_all_physical_states_applies_whatever_the_state():
    values = (_value(1, "all physical states"),)
    assert applicable(values, "gas") == values
    assert applicable(values, None) == values


def test_without_a_state_every_limit_stays_in_play():
    values = (_value(1, "solid/liquid"), _value(2, "gas"))
    assert applicable(values, None) == values


# -- the act's own split -------------------------------------------------------


@pytest.mark.parametrize("regulation", ["eu_clp", "uk_clp", "un_ghs", "au_whs",
                                        "ca_whmis", "us_osha"])
@pytest.mark.parametrize("hazard_class", ["Resp. Sens. 1", "Resp. Sens. 1B"])
def test_both_halves_of_a_state_split_are_on_file(regulation, hazard_class):
    """Every one of these documents prints a solid/liquid column and a gas
    column for respiratory sensitisers. Keeping one and dropping the other is
    how a liquid gets judged by a gas's limit."""
    values = load(regulation).variants("generic_limits", hazard_class)
    states = {v.qualifier.split()[0] for v in values if v.qualifier}
    assert {"solid/liquid", "gas"} <= states, [str(v) for v in values]
