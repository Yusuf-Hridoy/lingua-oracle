"""The mixture rules this tool calculates, and nothing else.

The arithmetic is here; the numbers are not. Every limit comes from the
regulation's own rule table - `mixture/rule_table.py`, built out of the
published text - and the citation it carries travels with the result, so a
reader checks the answer against the law rather than against this file. A rule
whose limit the document does not give is not calculated, and says so.

Limits are inclusive at the bottom: the published tables write them as
"concentration >= x %", so an ingredient sitting exactly on a limit triggers
it. Where a table gives a band - "1 % <= C < 5 %" - the top is exclusive.

Out of scope, and reported as not calculated rather than passed over: the
physical hazards, acute toxicity (which needs ATE values and the mixture's
whole composition), aspiration, the ozone class, and the bridging principles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from lingua_oracle.mixture.classes import HazardClass
from lingua_oracle.mixture.rule_table import RuleTable, Value
from lingua_oracle.mixture.state import applicable as for_state

ZERO = Decimal(0)


@dataclass
class Contribution:
    """One ingredient's part in one rule, and what it contributed."""

    cas: str | None
    name: str | None
    percentage: Decimal
    hazard_class: str
    multiplier: Decimal = Decimal(1)
    note: str = ""

    @property
    def contributed(self) -> Decimal:
        return self.percentage * self.multiplier


@dataclass
class RuleResult:
    """What one rule concluded, and everything it used to get there."""

    hazard_class: HazardClass | None
    citation: str
    total: Decimal = ZERO
    limit: Decimal | None = None
    contributions: list[Contribution] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    #: The limits this rule needed and the document did not give. A rule with
    #: anything here was not calculated, and nothing else about it is a result.
    missing: list[str] = field(default_factory=list)

    @property
    def triggered(self) -> bool:
        return self.hazard_class is not None

    @property
    def calculated(self) -> bool:
        return not self.missing


def _need(table: RuleTable, rule: str, keys: dict[str, str]
          ) -> tuple[dict[str, Value], list[str]]:
    """Fetch a rule's limits, and name the ones the document does not give."""
    found: dict[str, Value] = {}
    missing: list[str] = []
    for name, key in keys.items():
        value = table.one(rule, key)
        if value is None:
            missing.append(key)
        else:
            found[name] = value
    return found, missing


def _not_on_file(rule: str, missing: list[str]) -> RuleResult:
    return RuleResult(hazard_class=None, citation="", missing=missing)


def _matching(ingredients, name: str, category: str | None = None,
              sub_category: str | None = None):
    """Ingredients carrying a class, optionally a category or sub-category."""
    for ingredient in ingredients:
        for hazard_class in ingredient.classes:
            if hazard_class.name.casefold() != name.casefold():
                continue
            if category is not None and hazard_class.generic.category != category:
                continue
            if sub_category is not None and hazard_class.sub_category != sub_category:
                continue
            yield ingredient, hazard_class
            break


def _sum(ingredients, name, category=None, sub_category=None, multiplier=Decimal(1)):
    """Total percentage of the ingredients carrying a class, and who they were."""
    total = ZERO
    contributions: list[Contribution] = []
    for ingredient, hazard_class in _matching(ingredients, name, category,
                                              sub_category):
        total += ingredient.percentage * multiplier
        contributions.append(Contribution(
            cas=ingredient.cas, name=ingredient.name,
            percentage=ingredient.percentage, hazard_class=str(hazard_class),
            multiplier=multiplier))
    return total, contributions


# -- Skin corrosion / irritation ----------------------------------------------

#: What the skin rule needs, and the name each limit has in a rule table.
SKIN_KEYS = {
    "corrosive": "Skin Corr. 1",
    "corrosive_to_irritant": "Skin Corr. 1 to Skin Irrit. 2",
    "irritant": "Skin Irrit. 2",
    "weighted": "weighted Skin Irrit. 2",
    "multiplier": "Skin Corr. 1 multiplier",
}


def skin(ingredients, table: RuleTable) -> RuleResult:
    """Skin corrosion and irritation by summation.

    Corrosive ingredients are summed within their sub-category where those are
    known, because a mixture is classified 1A only on the strength of 1A
    ingredients; the sub-categories are summed together for the category-level
    result, and corrosives count towards irritation at the multiplier the
    regulation's own table gives.
    """
    limits, missing = _need(table, "skin", SKIN_KEYS)
    if missing:
        return _not_on_file("skin", missing)
    result = RuleResult(hazard_class=None, citation=limits["corrosive"].citation)

    for sub in ("A", "B", "C"):
        total, contributions = _sum(ingredients, "Skin Corr.", "1", sub)
        if not contributions:
            continue
        result.trace.append(f"Skin Corr. 1{sub}: {total} %")
        if total >= limits["corrosive"].amount and result.hazard_class is None:
            result.hazard_class = HazardClass("Skin Corr.", f"1{sub}")
            result.total = total
            result.limit = limits["corrosive"].amount
            result.contributions = contributions
            return result

    corrosive_total, corrosive_contributions = _sum(ingredients, "Skin Corr.", "1")
    irritant_total, irritant_contributions = _sum(ingredients, "Skin Irrit.", "2")
    result.trace.append(f"Skin Corr. 1 (all sub-categories): {corrosive_total} %")
    result.trace.append(f"Skin Irrit. 2: {irritant_total} %")

    if corrosive_total >= limits["corrosive"].amount:
        result.hazard_class = HazardClass("Skin Corr.", "1")
        result.total = corrosive_total
        result.limit = limits["corrosive"].amount
        result.contributions = corrosive_contributions
        return result
    if corrosive_total >= limits["corrosive_to_irritant"].amount:
        result.hazard_class = HazardClass("Skin Irrit.", "2")
        result.total = corrosive_total
        result.limit = limits["corrosive_to_irritant"].amount
        result.contributions = corrosive_contributions
        result.trace.append(
            f"Skin Corr. 1 at or above {result.limit} % but below "
            f"{limits['corrosive'].amount} % classifies the mixture "
            "Skin Irrit. 2")
        return result
    if irritant_total >= limits["irritant"].amount:
        result.hazard_class = HazardClass("Skin Irrit.", "2")
        result.total = irritant_total
        result.limit = limits["irritant"].amount
        result.contributions = irritant_contributions
        return result

    multiplier = limits["multiplier"].amount
    combined = corrosive_total * multiplier + irritant_total
    result.trace.append(
        f"({multiplier} x Skin Corr. 1) + Skin Irrit. 2 = {combined} %")
    # Recorded whether or not it triggers: a reader comparing 9 % against a
    # 10 % limit learns something a bare "no" does not tell them.
    result.total, result.limit = combined, limits["weighted"].amount
    if combined >= limits["weighted"].amount:
        result.hazard_class = HazardClass("Skin Irrit.", "2")
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           multiplier) for c in corrosive_contributions],
            *irritant_contributions]
    return result


# -- Serious eye damage / eye irritation --------------------------------------

EYE_KEYS = {
    "damage": "Eye Dam. 1",
    "damage_to_irritant": "Eye Dam. 1 to Eye Irrit. 2",
    "irritant": "Eye Irrit. 2",
    "weighted": "weighted Eye Irrit. 2",
    "multiplier": "Eye Dam. 1 multiplier",
}


def eye(ingredients, table: RuleTable) -> RuleResult:
    """Eye damage and irritation by summation.

    A skin corrosive is treated as seriously damaging to the eye for this
    calculation, as the published tables' own rows say, so Skin Corr. 1
    ingredients are counted with the Eye Dam. 1 ones.
    """
    limits, missing = _need(table, "eye", EYE_KEYS)
    if missing:
        return _not_on_file("eye", missing)
    result = RuleResult(hazard_class=None, citation=limits["damage"].citation)
    damage_total, damage_contributions = _sum(ingredients, "Eye Dam.", "1")
    corrosive_total, corrosive_contributions = _sum(ingredients, "Skin Corr.", "1")
    for contribution in corrosive_contributions:
        contribution.note = "Skin Corr. 1 counts as Eye Dam. 1"
    damage_total += corrosive_total
    damage_contributions += corrosive_contributions
    irritant_total, irritant_contributions = _sum(ingredients, "Eye Irrit.", "2")

    result.trace.append(f"Eye Dam. 1 (with Skin Corr. 1): {damage_total} %")
    result.trace.append(f"Eye Irrit. 2: {irritant_total} %")

    if damage_total >= limits["damage"].amount:
        result.hazard_class = HazardClass("Eye Dam.", "1")
        result.total, result.limit = damage_total, limits["damage"].amount
        result.contributions = damage_contributions
        return result
    if damage_total >= limits["damage_to_irritant"].amount:
        result.hazard_class = HazardClass("Eye Irrit.", "2")
        result.total = damage_total
        result.limit = limits["damage_to_irritant"].amount
        result.contributions = damage_contributions
        result.trace.append(
            f"Eye Dam. 1 at or above {result.limit} % but below "
            f"{limits['damage'].amount} % classifies the mixture Eye Irrit. 2")
        return result
    if irritant_total >= limits["irritant"].amount:
        result.hazard_class = HazardClass("Eye Irrit.", "2")
        result.total, result.limit = irritant_total, limits["irritant"].amount
        result.contributions = irritant_contributions
        return result

    multiplier = limits["multiplier"].amount
    combined = damage_total * multiplier + irritant_total
    result.trace.append(
        f"({multiplier} x Eye Dam. 1) + Eye Irrit. 2 = {combined} %")
    result.total, result.limit = combined, limits["weighted"].amount
    if combined >= limits["weighted"].amount:
        result.hazard_class = HazardClass("Eye Irrit.", "2")
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           multiplier, c.note) for c in damage_contributions],
            *irritant_contributions]
    return result


# -- Hazardous to the aquatic environment -------------------------------------


def _aquatic_sum(ingredients, name, category, use_m: bool):
    """Sum a class, multiplying by the M-factor where the rule requires it."""
    total = ZERO
    contributions: list[Contribution] = []
    assumptions: list[str] = []
    for ingredient, hazard_class in _matching(ingredients, name, category):
        multiplier = Decimal(1)
        if use_m:
            factor = ingredient.m_factor_for(hazard_class)
            if factor is None:
                multiplier = Decimal(1)
                assumptions.append(
                    f"{ingredient.label} has no M-factor on record for "
                    f"{hazard_class}; M = 1 assumed")
            else:
                multiplier = factor
        total += ingredient.percentage * multiplier
        contributions.append(Contribution(
            cas=ingredient.cas, name=ingredient.name,
            percentage=ingredient.percentage, hazard_class=str(hazard_class),
            multiplier=multiplier,
            note=f"M = {multiplier}" if use_m else ""))
    return total, contributions, assumptions


def aquatic_acute(ingredients, table: RuleTable) -> RuleResult:
    """Acute aquatic hazard by summation.

    The mixture is acutely hazardous when the sum of the category 1
    ingredients, each multiplied by its M-factor, reaches the limit the
    regulation sets.
    """
    limit = table.one("aquatic_acute", "Aquatic Acute 1")
    if limit is None:
        return _not_on_file("aquatic_acute", ["Aquatic Acute 1"])
    total, contributions, assumptions = _aquatic_sum(
        ingredients, "Aquatic Acute", "1", use_m=True)
    result = RuleResult(hazard_class=None, citation=limit.citation,
                        total=total, limit=limit.amount,
                        contributions=contributions, assumptions=assumptions)
    result.trace.append(f"Sum of (Aquatic Acute 1 x M) = {total} %")
    if total >= limit.amount:
        result.hazard_class = HazardClass("Aquatic Acute", "1")
    return result


CHRONIC_KEYS = {
    "one": "Aquatic Chronic 1",
    "two": "Aquatic Chronic 2",
    "three": "Aquatic Chronic 3",
    "four": "Aquatic Chronic 4",
    "one_into_two": "Aquatic Chronic 1 into 2",
    "one_into_three": "Aquatic Chronic 1 into 3",
    "two_into_three": "Aquatic Chronic 2 into 3",
}


def aquatic_chronic(ingredients, table: RuleTable) -> RuleResult:
    """Chronic aquatic hazard by summation.

    Each category has its own trigger, and the more severe categories are
    weighted into the less severe ones by the factors the regulation's table
    prints in the row itself.
    """
    limits, missing = _need(table, "aquatic_chronic", CHRONIC_KEYS)
    if missing:
        return _not_on_file("aquatic_chronic", missing)
    one, one_parts, assumptions = _aquatic_sum(
        ingredients, "Aquatic Chronic", "1", use_m=True)
    two, two_parts, _ = _aquatic_sum(ingredients, "Aquatic Chronic", "2", False)
    three, three_parts, _ = _aquatic_sum(ingredients, "Aquatic Chronic", "3", False)
    four, four_parts, _ = _aquatic_sum(ingredients, "Aquatic Chronic", "4", False)

    result = RuleResult(hazard_class=None, citation=limits["one"].citation,
                        limit=limits["one"].amount, assumptions=assumptions)
    result.trace.append(f"Sum of (Chronic 1 x M) = {one} %")
    result.trace.append(f"Chronic 2 = {two} %, Chronic 3 = {three} %, "
                        f"Chronic 4 = {four} %")

    if one >= limits["one"].amount:
        result.hazard_class = HazardClass("Aquatic Chronic", "1")
        result.total, result.contributions = one, one_parts
        return result

    into_two = limits["one_into_two"].amount
    weighted_two = one * into_two + two
    result.trace.append(
        f"({into_two} x Chronic 1) + Chronic 2 = {weighted_two} %")
    if weighted_two >= limits["two"].amount:
        result.hazard_class = HazardClass("Aquatic Chronic", "2")
        result.total, result.limit = weighted_two, limits["two"].amount
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           c.multiplier * into_two, c.note) for c in one_parts],
            *two_parts]
        return result

    one_into_three = limits["one_into_three"].amount
    two_into_three = limits["two_into_three"].amount
    weighted_three = one * one_into_three + two * two_into_three + three
    result.trace.append(
        f"({one_into_three} x Chronic 1) + ({two_into_three} x Chronic 2) + "
        f"Chronic 3 = {weighted_three} %")
    if weighted_three >= limits["three"].amount:
        result.hazard_class = HazardClass("Aquatic Chronic", "3")
        result.total, result.limit = weighted_three, limits["three"].amount
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           c.multiplier * one_into_three, c.note)
              for c in one_parts],
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           two_into_three, c.note) for c in two_parts],
            *three_parts]
        return result

    everything = one + two + three + four
    result.trace.append(f"Chronic 1 + 2 + 3 + 4 = {everything} %")
    result.total, result.limit = everything, limits["four"].amount
    if everything >= limits["four"].amount:
        result.hazard_class = HazardClass("Aquatic Chronic", "4")
        result.contributions = one_parts + two_parts + three_parts + four_parts
    return result


# -- Concentration limits -----------------------------------------------------

#: The classes whose limit is a concentration rather than a sum, with the
#: categories each can be classified in. Which of these a regulation actually
#: sets a limit for is its rule table's business, not this list's.
LIMIT_CLASSES: tuple[tuple[str, str], ...] = (
    ("Skin Sens.", "1"), ("Skin Sens.", "1A"), ("Skin Sens.", "1B"),
    ("Resp. Sens.", "1"), ("Resp. Sens.", "1A"), ("Resp. Sens.", "1B"),
    ("Muta.", "1"), ("Muta.", "1A"), ("Muta.", "1B"), ("Muta.", "2"),
    ("Carc.", "1"), ("Carc.", "1A"), ("Carc.", "1B"), ("Carc.", "2"),
    ("Repr.", "1"), ("Repr.", "1A"), ("Repr.", "1B"), ("Repr.", "2"),
    ("Lact.", ""),
    ("STOT SE", "1"), ("STOT SE", "2"),
    ("STOT RE", "1"), ("STOT RE", "2"),
)

#: A category 1 ingredient below its own limit classifies the mixture in
#: category 2 instead, where the regulation gives that band.
STEP_DOWN = {("STOT SE", "1"): ("STOT SE", "2"),
             ("STOT RE", "1"): ("STOT RE", "2")}


def limit_key(name: str, category: str) -> str:
    return f"{name} {category}".strip()


def generic_limit(ingredients, name: str, category: str, table: RuleTable,
                  variant: int = 0, state: str | None = None) -> RuleResult:
    """One class whose limit is a concentration, not a sum.

    These classes are not additive: a single ingredient at or above the limit
    classifies the mixture, and a specific concentration limit from Annex VI
    replaces the generic one for that ingredient alone.

    Where the regulation's table gives more than one limit for the class -
    because the answer turns on the physical state, or on which option an
    authority took - `variant` picks which of them this run uses. The
    calculation runs them all and reports the disagreement rather than
    choosing. A `state` the sheet stated settles the physical half of that:
    the limits for the other state are not this mixture's.
    """
    key = limit_key(name, category)
    values = for_state(table.variants("generic_limits", key), state)
    if not values:
        return _not_on_file("generic_limits", [key])
    value = values[min(variant, len(values) - 1)]
    limit = value.amount
    result = RuleResult(hazard_class=None, citation=value.citation, limit=limit)
    if value.qualifier:
        result.assumptions.append(
            f"{key}: the limit of {limit} % is the one given for "
            f"{value.qualifier}")
    stepped: list[Contribution] = []

    # _matching filters on the generic category; the sub-category is checked
    # below, because "Skin Sens. 1A" has generic category "1".
    generic = "".join(c for c in category if c.isdigit()) or None
    for ingredient, hazard_class in _matching(ingredients, name, generic):
        # The limit is per sub-category where one is known, and per category
        # where it is not: "Skin Sens. 1A" is judged by the 1A limit and
        # "Skin Sens. 1" by the 1 limit, never by each other's.
        if category and hazard_class.category != category:
            continue
        applicable = limit
        specific = ingredient.specific_limit_for(hazard_class)
        if specific is not None and specific.low is not None:
            applicable = specific.low
            result.assumptions.append(
                f"{ingredient.label}: Annex VI gives a specific limit for "
                f"{hazard_class} - {specific.source} - which replaces the "
                f"generic {limit} %")
        result.trace.append(
            f"{ingredient.label} {ingredient.percentage} % as {hazard_class}, "
            f"limit {applicable} %")
        contribution = Contribution(
            cas=ingredient.cas, name=ingredient.name,
            percentage=ingredient.percentage, hazard_class=str(hazard_class),
            note=f"limit {applicable} %")
        if ingredient.percentage >= applicable:
            result.hazard_class = HazardClass(name, category)
            result.total = max(result.total, ingredient.percentage)
            result.contributions.append(contribution)
            continue
        band = table.one("generic_limits", f"{key} step down")
        if (name, category) in STEP_DOWN and band is not None \
                and ingredient.percentage >= band.amount:
            stepped.append(contribution)

    if result.hazard_class is None and stepped:
        band = table.one("generic_limits", f"{key} step down")
        step_name, step_category = STEP_DOWN[(name, category)]
        result.hazard_class = HazardClass(step_name, step_category)
        result.contributions = stepped
        result.limit = band.amount
        result.citation = band.citation
        result.total = max(c.percentage for c in stepped)
        result.trace.append(
            f"At or above {band.amount} % but below the category 1 limit, "
            f"which classifies the mixture {step_name} {step_category}")
    return result


def stot_se_3(ingredients, effect: str, table: RuleTable,
              variant: int = 0, state: str | None = None) -> RuleResult:
    """Single-exposure narcotic effects and respiratory irritation.

    These two effects are additive, and each is summed on its own - a mixture
    is classified when the ingredients causing one of them reach the limit
    between them.
    """
    values = for_state(table.variants("stot_se_3", "STOT SE 3"), state)
    if not values:
        return _not_on_file("stot_se_3", ["STOT SE 3"])
    value = values[min(variant, len(values) - 1)]
    result = RuleResult(hazard_class=None, citation=value.citation,
                        limit=value.amount)
    if value.qualifier:
        result.assumptions.append(
            f"the {value.amount} % limit is {value.qualifier} by "
            f"{value.document}")
    total = ZERO
    for ingredient in ingredients:
        share = ingredient.stot_se_3_share(effect)
        if share is None:
            continue
        total += ingredient.percentage
        result.contributions.append(Contribution(
            cas=ingredient.cas, name=ingredient.name,
            percentage=ingredient.percentage, hazard_class="STOT SE 3",
            note=effect))
    result.total = total
    result.trace.append(f"STOT SE 3 ({effect}): {total} %")
    if total >= value.amount:
        result.hazard_class = HazardClass("STOT SE", "3")
    return result
