"""The Annex I rules, against cases worked out by hand.

Every case names the paragraph it tests and the arithmetic it expects, so a
reader can check the rule against the law rather than against the code. The
boundaries are tested on both sides, because CLP's limits are inclusive at the
bottom and a rule that is wrong by one is wrong at exactly one concentration.

Ingredients are fictional. The hazard classes and the limits are the law.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from lingua_oracle.mixture import rules
from lingua_oracle.mixture.classes import parse_class
from lingua_oracle.mixture.limits import ParsedLimits, SpecificLimit
from lingua_oracle.mixture.model import MixtureIngredient, from_codes
from lingua_oracle.mixture.rule_table import load

#: These cases are CLP's own, so they are run against CLP's rule table. The
#: same arithmetic against another regulation's table is in
#: tests/test_mixture_regulations.py, with that regulation's numbers.
CLP = load("eu_clp")


def ing(percent, *codes, cas="100-00-5", name=None):
    """One ingredient at one concentration, classified by its codes."""
    return from_codes(cas, name or f"<{cas}>", D(str(percent)),
                      D(str(percent)), list(codes)).at("low")


def classed(percent, *classes, cas="100-00-5", limits=None):
    """One ingredient whose classes are given directly, as Annex VI gives them."""
    parsed = [parse_class(c) for c in classes]
    return MixtureIngredient(
        cas=cas, name=f"<{cas}>", low=D(str(percent)), high=D(str(percent)),
        classes=parsed, h_codes=[], limits=limits,
        classification_source="annex_vi", percentage=D(str(percent)))


# -- 3.2 Skin corrosion / irritation, Table 3.2.3 ------------------------------


@pytest.mark.parametrize(("percent", "expected"), [
    (5, "Skin Corr. 1"),       # at the 5 % limit
    ("5.0", "Skin Corr. 1"),
    ("4.999", "Skin Irrit. 2"),  # below 5 %, at or above 1 %
    (1, "Skin Irrit. 2"),      # at the 1 % limit
    ("0.999", None),           # below 1 %: 10 x 0.999 = 9.99, under 10
])
def test_skin_corrosive_summation(percent, expected):
    """Annex I 3.2.3.3.4, Table 3.2.3: Skin Corr. 1 at >= 5 %, else >= 1 % is
    Skin Irrit. 2."""
    result = rules.skin([ing(percent, "H314")], CLP)
    assert (str(result.hazard_class) if result.hazard_class else None) == expected
    assert result.citation.endswith("Annex I, 3.2.3.3.4, Table 3.2.3")


@pytest.mark.parametrize(("percent", "expected"), [
    (10, "Skin Irrit. 2"),     # at the 10 % limit
    ("9.99", None),
])
def test_skin_irritant_summation(percent, expected):
    """Table 3.2.3: Skin Irrit. 2 ingredients summing to >= 10 %."""
    result = rules.skin([ing(percent, "H315")], CLP)
    assert (str(result.hazard_class) if result.hazard_class else None) == expected


def test_a_corrosive_counts_ten_times_towards_irritation():
    """Table 3.2.3: (10 x Skin Corr. 1) + Skin Irrit. 2 >= 10 %.

    0.5 % corrosive is 5 after weighting, plus 5 % irritant is 10 exactly.
    """
    result = rules.skin([ing("0.5", "H314"), ing(5, "H315", cas="200-00-0")], CLP)
    assert str(result.hazard_class) == "Skin Irrit. 2"
    assert result.total == D(10)


def test_just_under_the_weighted_limit_classifies_nothing():
    result = rules.skin([ing("0.4", "H314"), ing(5, "H315", cas="200-00-0")], CLP)
    assert result.hazard_class is None
    assert result.total == D(9)


def test_sub_categories_are_summed_within_themselves():
    """Table 3.2.3 gives 1A, 1B and 1C their own rows at 5 %."""
    result = rules.skin([classed(3, "Skin Corr. 1A"),
                         classed(3, "Skin Corr. 1A", cas="200-00-0")], CLP)
    assert str(result.hazard_class) == "Skin Corr. 1A"


def test_different_sub_categories_fall_back_to_the_category():
    """3 % of 1A and 3 % of 1B is 6 % of Skin Corr. 1, not 6 % of either."""
    result = rules.skin([classed(3, "Skin Corr. 1A"),
                         classed(3, "Skin Corr. 1B", cas="200-00-0")], CLP)
    assert str(result.hazard_class) == "Skin Corr. 1"


def test_a_code_alone_gives_no_sub_category():
    """H314 says Skin Corr. 1 and nothing about 1A, 1B or 1C."""
    result = rules.skin([ing(6, "H314")], CLP)
    assert str(result.hazard_class) == "Skin Corr. 1"


# -- 3.3 Eye damage / irritation, Table 3.3.3 ---------------------------------


@pytest.mark.parametrize(("percent", "expected"), [
    (3, "Eye Dam. 1"),         # at the 3 % limit
    ("2.99", "Eye Irrit. 2"),  # between 1 and 3
    (1, "Eye Irrit. 2"),
    ("0.99", None),
])
def test_eye_damage_summation(percent, expected):
    """Annex I 3.3.3.3.4, Table 3.3.3."""
    result = rules.eye([ing(percent, "H318")], CLP)
    assert (str(result.hazard_class) if result.hazard_class else None) == expected
    assert result.citation.endswith("Annex I, 3.3.3.3.4, Table 3.3.3")


def test_a_skin_corrosive_is_counted_as_damaging_to_the_eye():
    """Table 3.3.3 counts Skin Corr. 1 with Eye Dam. 1."""
    result = rules.eye([ing(3, "H314")], CLP)
    assert str(result.hazard_class) == "Eye Dam. 1"
    assert any("Skin Corr. 1 counts as Eye Dam. 1" in c.note
               for c in result.contributions)


def test_eye_irritants_sum_to_ten_per_cent():
    assert str(rules.eye([ing(10, "H319")], CLP).hazard_class) == "Eye Irrit. 2"
    assert rules.eye([ing("9.9", "H319")], CLP).hazard_class is None


def test_eye_damage_counts_ten_times_towards_irritation():
    """(10 x Eye Dam. 1) + Eye Irrit. 2 >= 10 %."""
    result = rules.eye([ing("0.5", "H318"), ing(5, "H319", cas="200-00-0")], CLP)
    assert str(result.hazard_class) == "Eye Irrit. 2"
    assert result.total == D(10)


# -- 4.1 Aquatic, Tables 4.1.1 and 4.1.2 --------------------------------------


def with_m(percent, code, m, cas="100-00-5"):
    """An ingredient whose Annex VI entry gives an M-factor."""
    from lingua_oracle.mixture.limits import MFactor

    ingredient = from_codes(cas, f"<{cas}>", D(str(percent)), D(str(percent)),
                            [code])
    ingredient.limits = ParsedLimits(
        specific=[], m_factors=[MFactor(D(str(m)), f"M = {m}")], ates=[],
        unparsed=[])
    return ingredient.at("low")


@pytest.mark.parametrize(("percent", "expected"), [
    (25, "Aquatic Acute 1"),
    ("24.99", None),
])
def test_acute_aquatic_summation(percent, expected):
    """Annex I 4.1.3.5.5, Table 4.1.1: sum of (Acute 1 x M) >= 25 %."""
    result = rules.aquatic_acute([ing(percent, "H400")], CLP)
    assert (str(result.hazard_class) if result.hazard_class else None) == expected
    assert result.citation.endswith("Annex I, 4.1.3.5.5, Table 4.1.1")


def test_an_m_factor_multiplies_the_contribution():
    """2.5 % at M = 10 is 25 %, which is the limit exactly."""
    result = rules.aquatic_acute([with_m("2.5", "H400", 10)], CLP)
    assert str(result.hazard_class) == "Aquatic Acute 1"
    assert result.total == D(25)


def test_an_unknown_m_factor_is_taken_as_one_and_said_so():
    result = rules.aquatic_acute([ing(25, "H400")], CLP)
    assert str(result.hazard_class) == "Aquatic Acute 1"
    assert any("M = 1 assumed" in a for a in result.assumptions)


def test_chronic_one_at_the_limit():
    """Table 4.1.2: sum of (Chronic 1 x M) >= 25 %."""
    assert str(rules.aquatic_chronic([ing(25, "H410")], CLP).hazard_class) == \
        "Aquatic Chronic 1"


def test_chronic_two_weights_chronic_one_ten_times():
    """(10 x Chronic 1) + Chronic 2 >= 25 %: 2 % and 5 % gives exactly 25."""
    result = rules.aquatic_chronic([ing(2, "H410"), ing(5, "H411", cas="2-00-0")], CLP)
    assert str(result.hazard_class) == "Aquatic Chronic 2"
    assert result.total == D(25)


def test_chronic_three_weights_a_hundred_and_ten():
    """(100 x C1) + (10 x C2) + C3 >= 25 %: 0.1, 1 and 5 gives exactly 25."""
    result = rules.aquatic_chronic([
        ing("0.1", "H410"), ing(1, "H411", cas="2-00-0"),
        ing(5, "H412", cas="3-00-0")], CLP)
    assert str(result.hazard_class) == "Aquatic Chronic 3"
    assert result.total == D(25)


def test_chronic_four_is_the_plain_sum():
    result = rules.aquatic_chronic([ing(25, "H413")], CLP)
    assert str(result.hazard_class) == "Aquatic Chronic 4"


def test_the_most_severe_aquatic_category_wins():
    result = rules.aquatic_chronic([ing(30, "H410"), ing(30, "H413", cas="2-00-0")], CLP)
    assert str(result.hazard_class) == "Aquatic Chronic 1"


# -- generic concentration limits ---------------------------------------------


@pytest.mark.parametrize(("name", "category", "limit", "code"), [
    ("Skin Sens.", "1", "1.0", "H317"),
    ("Resp. Sens.", "1", "0.2", "H334"),
    ("Carc.", "1", "0.1", "H350"),
    ("Carc.", "2", "1.0", "H351"),
    ("Muta.", "1", "0.1", "H340"),
    ("Muta.", "2", "1.0", "H341"),
    ("Repr.", "1", "0.3", "H360"),
    ("Repr.", "2", "3.0", "H361"),
    ("STOT RE", "1", "10.0", "H372"),
    ("STOT RE", "2", "10.0", "H373"),
])
def test_a_generic_limit_triggers_at_the_limit(name, category, limit, code):
    """Annex I's generic concentration limits are ">=", so exactly on is in."""
    at = rules.generic_limit([ing(limit, code)], name, category, CLP)
    assert str(at.hazard_class) == f"{name} {category}"
    assert at.limit == D(limit)


@pytest.mark.parametrize(("name", "category", "below", "code"), [
    ("Skin Sens.", "1", "0.99", "H317"),
    ("Carc.", "1", "0.09", "H350"),
    ("Repr.", "1", "0.29", "H360"),
    ("Muta.", "2", "0.99", "H341"),
])
def test_just_below_a_generic_limit_classifies_nothing(name, category, below, code):
    assert rules.generic_limit([ing(below, code)], name, category, CLP).hazard_class is None


def test_a_sub_category_has_its_own_limit():
    """Skin Sens. 1A is limited at 0.1 %, not at the category's 1 %."""
    result = rules.generic_limit([classed("0.1", "Skin Sens. 1A")],
                                 "Skin Sens.", "1A", CLP)
    assert str(result.hazard_class) == "Skin Sens. 1A"
    assert result.limit == D("0.1")


def test_a_category_one_stot_between_one_and_ten_steps_down():
    """Table 3.9.4: STOT RE 1 at 1 % to 10 % classifies the mixture STOT RE 2."""
    result = rules.generic_limit([ing(5, "H372")], "STOT RE", "1", CLP)
    assert str(result.hazard_class) == "STOT RE 2"
    assert result.limit == D(1)


def test_below_the_step_down_nothing_is_classified():
    assert rules.generic_limit([ing("0.9", "H372")], "STOT RE", "1", CLP).hazard_class \
        is None


def test_an_annex_vi_specific_limit_replaces_the_generic_one():
    """A substance whose entry gives its own limit is judged by that limit."""
    limits = ParsedLimits(
        specific=[SpecificLimit(parse_class("STOT RE 1"), D("1.0"), None,
                                "STOT RE 1; H372: C >= 1 %")],
        m_factors=[], ates=[], unparsed=[])
    ingredient = classed(2, "STOT RE 1", limits=limits)
    result = rules.generic_limit([ingredient], "STOT RE", "1", CLP)
    assert str(result.hazard_class) == "STOT RE 1"
    assert any("specific limit" in a for a in result.assumptions)


def test_without_the_specific_limit_the_same_ingredient_only_steps_down():
    result = rules.generic_limit([classed(2, "STOT RE 1")], "STOT RE", "1", CLP)
    assert str(result.hazard_class) == "STOT RE 2"


# -- 3.8 STOT SE 3, additive per effect ----------------------------------------


def test_the_two_stot_se_3_effects_are_summed_separately():
    """Annex I 3.8.3.4.5: respiratory irritation and narcotic effects each
    reach their own 20 %."""
    ingredients = [ing(15, "H335"), ing(15, "H336", cas="200-00-0")]
    assert rules.stot_se_3(ingredients, "respiratory irritation", CLP).hazard_class is None
    assert rules.stot_se_3(ingredients, "narcotic effects", CLP).hazard_class is None


def test_one_effect_reaching_twenty_per_cent_classifies():
    ingredients = [ing(12, "H336"), ing(8, "H336", cas="200-00-0")]
    result = rules.stot_se_3(ingredients, "narcotic effects", CLP)
    assert str(result.hazard_class) == "STOT SE 3"
    assert result.total == D(20)
    assert result.citation.endswith("Annex I, 3.8.3.4.5, Table 3.8.3")


def test_just_under_twenty_per_cent_does_not():
    assert rules.stot_se_3([ing("19.9", "H336")], "narcotic effects", CLP) \
        .hazard_class is None


def test_every_rule_names_its_document_and_its_paragraph():
    """A result a reader cannot check against the text is half an answer."""
    for result in (rules.skin([], CLP), rules.eye([], CLP),
                   rules.aquatic_acute([], CLP), rules.aquatic_chronic([], CLP),
                   rules.stot_se_3([], "narcotic effects", CLP)):
        assert result.citation.startswith("Regulation (EC) No 1272/2008")
        assert "Annex I, " in result.citation
    for name, category in rules.LIMIT_CLASSES:
        value = CLP.one("generic_limits", rules.limit_key(name, category))
        assert value is not None, f"no CLP limit for {name} {category}"
        assert "Annex I, " in value.citation
