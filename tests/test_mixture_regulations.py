"""Each regulation's rules, against cases worked out by hand from its own text.

One case per rule family per regulation, with the limit it turns on named in
the test and checked against the citation the rule carries, so a wrong number
in a rule table fails here rather than on somebody's sheet. Boundaries are
tested on both sides: the published limits are inclusive at the bottom, and a
rule that is wrong by one is wrong at exactly one concentration.

Ingredients are fictional. The limits are the law, or - where a published
table hedges one - the law's own words about it.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from lingua_oracle.mixture import rules
from lingua_oracle.mixture.model import from_codes
from lingua_oracle.mixture.rule_table import load

#: Every regulation a table was built for, with the document each was read
#: from. If a regulation is added without rules, this list fails first.
TABLES = {
    "eu_clp": "Regulation (EC) No 1272/2008, Annex I",
    "uk_clp": "Regulation (EC) No 1272/2008 as retained in GB law, Annex I",
    "un_ghs": "UN GHS Rev.11 (2025)",
    "au_whs": "UN GHS Rev.7 (2017)",
    "ca_whmis": "UN GHS Rev.7 (2017)",
    "us_osha": "29 CFR 1910.1200 Appendix A",
}

ALL = sorted(TABLES)


def ing(percent, *codes, cas="100-00-5"):
    return from_codes(cas, f"<{cas}>", D(str(percent)), D(str(percent)),
                      list(codes)).at("low")


def table(regulation):
    found = load(regulation)
    assert found is not None, f"no rule table for {regulation}"
    return found


def said(result):
    return str(result.hazard_class) if result.hazard_class else None


# -- what every table has to carry ---------------------------------------------


@pytest.mark.parametrize("regulation", ALL)
def test_every_rule_table_names_the_document_it_was_read_from(regulation):
    assert TABLES[regulation] in table(regulation).document


@pytest.mark.parametrize("regulation", ALL)
def test_every_number_carries_a_citation(regulation):
    """A value without a source is a value somebody has to take on trust."""
    for rule, keys in table(regulation).values.items():
        for key, values in keys.items():
            for value in values:
                assert value.document, f"{regulation} {rule} {key}"
                assert value.section, f"{regulation} {rule} {key}"


@pytest.mark.parametrize("regulation", ["un_ghs", "au_whs", "ca_whmis"])
def test_a_value_read_from_a_pdf_carries_its_page(regulation):
    value = table(regulation).one("skin", "Skin Corr. 1")
    assert value.page and value.page > 1
    assert "Table 3.2.3" in value.section


# -- skin, by summation --------------------------------------------------------


@pytest.mark.parametrize("regulation", ALL)
@pytest.mark.parametrize(("percent", "expected"), [
    (5, "Skin Corr. 1"),        # at the 5 % limit
    ("4.999", "Skin Irrit. 2"),  # below 5 %, at or above 1 %
    (1, "Skin Irrit. 2"),       # at the 1 % limit
    ("0.999", None),            # 10 x 0.999 = 9.99, under the 10 % weighted sum
])
def test_skin_corrosive_summation(regulation, percent, expected):
    """Skin Corr. 1 at >= 5 %, else >= 1 % is Skin Irrit. 2.

    GHS Table 3.2.3, Appendix A Table A.2.3 and CLP Annex I Table 3.2.3 all set
    the same two limits; each table says so in its own words and its own place.
    """
    result = rules.skin([ing(percent, "H314")], table(regulation))
    assert said(result) == expected


@pytest.mark.parametrize("regulation", ALL)
@pytest.mark.parametrize(("percent", "expected"), [
    (10, "Skin Irrit. 2"), ("9.99", None)])
def test_skin_irritant_summation(regulation, percent, expected):
    """Skin Irrit. 2 ingredients classify the mixture at >= 10 % between them."""
    result = rules.skin([ing(percent, "H315")], table(regulation))
    assert said(result) == expected


# -- eye, by summation ---------------------------------------------------------


@pytest.mark.parametrize("regulation", ALL)
@pytest.mark.parametrize(("percent", "expected"), [
    (3, "Eye Dam. 1"),          # at the 3 % limit
    ("2.99", "Eye Irrit. 2"),   # below 3 %, at or above 1 %
    (1, "Eye Irrit. 2"),
    ("0.99", None),             # 10 x 0.99 = 9.9, under 10 %
])
def test_eye_damage_summation(regulation, percent, expected):
    result = rules.eye([ing(percent, "H318")], table(regulation))
    assert said(result) == expected


@pytest.mark.parametrize("regulation", ALL)
def test_a_skin_corrosive_counts_towards_eye_damage(regulation):
    """Every one of these tables gives the eye rule a skin corrosion row."""
    result = rules.eye([ing(3, "H314")], table(regulation))
    assert said(result) == "Eye Dam. 1"


# -- the aquatic classes, where a regulation has them --------------------------

WITH_AQUATIC = ["eu_clp", "uk_clp", "un_ghs", "au_whs"]
WITHOUT_AQUATIC = ["us_osha", "ca_whmis"]


@pytest.mark.parametrize("regulation", WITH_AQUATIC)
@pytest.mark.parametrize(("percent", "expected"), [
    (25, "Aquatic Acute 1"), ("24.99", None)])
def test_acute_aquatic_summation(regulation, percent, expected):
    """The sum of the Acute 1 ingredients, each times its M-factor, at 25 %."""
    result = rules.aquatic_acute([ing(percent, "H400")], table(regulation))
    assert said(result) == expected


@pytest.mark.parametrize("regulation", WITH_AQUATIC)
def test_chronic_one_weighs_ten_times_into_chronic_two(regulation):
    """2.5 % of Chronic 1 is 25 % once weighted, which is Chronic 2."""
    result = rules.aquatic_chronic([ing("2.5", "H410")], table(regulation))
    assert said(result) == "Aquatic Chronic 2"


@pytest.mark.parametrize("regulation", WITHOUT_AQUATIC)
def test_a_regulation_without_aquatic_classes_has_no_aquatic_rule(regulation):
    assert not table(regulation).covers_class("Aquatic Acute")
    assert not table(regulation).covers_class("Aquatic Chronic")


# -- concentration limits, where the regulations part company -----------------


@pytest.mark.parametrize(("regulation", "percent", "expected"), [
    # CLP Annex I Table 3.8.3: category 1 at >= 10 %, and 1 % to 10 % steps the
    # mixture down to category 2.
    ("eu_clp", 10, "STOT SE 1"),
    ("eu_clp", 2, "STOT SE 2"),
    ("uk_clp", 2, "STOT SE 2"),
    # Appendix A Table A.8.2 sets one limit, 1.0 %, and no step-down band:
    # the same 2 % ingredient classifies the mixture category 1 outright.
    ("us_osha", 2, "STOT SE 1"),
    ("us_osha", "0.99", None),
])
def test_the_target_organ_limit_is_the_regulations_own(regulation, percent,
                                                       expected):
    result = rules.generic_limit([ing(percent, "H370")], "STOT SE", "1",
                                 table(regulation))
    assert said(result) == expected


@pytest.mark.parametrize(("regulation", "section"), [
    ("eu_clp", "3.8.3.4, Table 3.8.3"), ("us_osha", "Table A.8.2")])
def test_a_limit_cites_the_table_it_came_from(regulation, section):
    result = rules.generic_limit([ing(2, "H370")], "STOT SE", "1",
                                 table(regulation))
    assert section in result.citation
    assert TABLES[regulation] in result.citation


@pytest.mark.parametrize("regulation", ALL)
@pytest.mark.parametrize(("percent", "expected"), [
    ("0.1", "Carc. 1"), ("0.09", None)])
def test_a_category_1_carcinogen_at_a_tenth_of_a_per_cent(regulation, percent,
                                                          expected):
    """Every one of these tables sets 0.1 % for a category 1 carcinogen.

    H350 says category 1 without saying which sub-category, and the GHS tables
    print a row per sub-category under a column headed "Category 1
    carcinogen". Both sub-categories carry 0.1 %, so that is what the column
    sets, and the builder records it rather than leaving the common case with
    no limit at all.
    """
    result = rules.generic_limit([ing(percent, "H350", cas="200-00-0")],
                                 "Carc.", "1", table(regulation))
    assert said(result) == expected


@pytest.mark.parametrize("regulation", ALL)
@pytest.mark.parametrize(("percent", "expected"), [
    (20, "STOT SE 3"), ("19.9", None)])
def test_narcotic_effects_are_additive_to_twenty_per_cent(regulation, percent,
                                                          expected):
    """CLP sets 20 % in Annex I 3.8.3.4.5. GHS and Appendix A give the same
    number in a sentence, and hedge it - "has been suggested", "is appropriate"
    - which the rule records as an assumption rather than hiding."""
    result = rules.stot_se_3([ing(percent, "H336")], "narcotic effects",
                             table(regulation))
    assert said(result) == expected
    if regulation not in ("eu_clp", "uk_clp"):
        assert any("suggested" in a for a in result.assumptions)


# -- where a published table gives two limits ---------------------------------


def test_two_limits_for_one_class_are_both_kept():
    """GHS Table 3.6.1 gives category 2 carcinogens 0.1 % or 1.0 %, by note,
    because the choice is the adopting authority's. Both are on file."""
    amounts = [v.amount for v in
               table("un_ghs").variants("generic_limits", "Carc. 2")]
    assert amounts == [D("0.1"), D("1.0")]


def test_each_reading_is_calculated_and_the_disagreement_is_reported():
    """0.5 % is above the first limit and below the second, so under UN GHS
    this cannot be settled from the text alone."""
    from lingua_oracle.mixture.calculate import calculate

    ingredients = [from_codes("200-00-0", "<x>", D("0.5"), D("0.5"), ["H351"])]
    results, _ = calculate(ingredients, [], "un_ghs")
    carc = next(r for r in results if r.hazard_class == "Carc. 2")
    assert carc.verdict == "cannot_tell"
    assert "more than one limit" in carc.message
    assert "0.1" in carc.message and "1.0" in carc.message


def test_the_same_ingredient_is_settled_where_the_regulation_chose():
    """OSHA Table A.6.1 prints one limit, so there is nothing to weigh up."""
    from lingua_oracle.mixture.calculate import calculate

    ingredients = [from_codes("200-00-0", "<x>", D("0.5"), D("0.5"), ["H351"])]
    results, _ = calculate(ingredients, [], "us_osha")
    carc = next(r for r in results if r.hazard_class == "Carc. 2")
    assert carc.verdict == "inconsistent"
