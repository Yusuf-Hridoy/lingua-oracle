"""The Annex I rules this tool calculates, and nothing else.

Each rule names the paragraph of CLP Annex I it implements, and that citation
travels with the result so a reader can check the arithmetic against the law
rather than against this file.

Limits are inclusive at the bottom: CLP writes them as "concentration >= x %",
so an ingredient sitting exactly on a limit triggers it. Where the act gives a
band - "1 % <= C < 5 %" - the top is exclusive.

Out of scope, and reported as not calculated rather than passed over: the
physical hazards, acute toxicity (which needs ATE values and the mixture's
whole composition), aspiration, the ozone class, and the bridging principles of
Annex I 1.1.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from lingua_oracle.mixture.classes import HazardClass

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

    @property
    def triggered(self) -> bool:
        return self.hazard_class is not None


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


# -- 3.2 Skin corrosion / irritation ------------------------------------------

SKIN = "Annex I, 3.2.3.3.4, Table 3.2.3"


def skin(ingredients) -> RuleResult:
    """Skin corrosion and irritation by summation.

    Annex I 3.2.3.3.4, Table 3.2.3. Corrosive ingredients are summed within
    their sub-category where those are known, because a mixture is classified
    1A only on the strength of 1A ingredients; the sub-categories are summed
    together for the category-level result, and corrosives count ten times
    towards irritation.
    """
    result = RuleResult(hazard_class=None, citation=SKIN)
    corrosive_total = ZERO
    corrosive_contributions: list[Contribution] = []

    for sub in ("A", "B", "C"):
        total, contributions = _sum(ingredients, "Skin Corr.", "1", sub)
        if not contributions:
            continue
        result.trace.append(f"Skin Corr. 1{sub}: {total} %")
        if total >= 5 and result.hazard_class is None:
            result.hazard_class = HazardClass("Skin Corr.", f"1{sub}")
            result.total, result.limit = total, Decimal(5)
            result.contributions = contributions
            return result

    corrosive_total, corrosive_contributions = _sum(ingredients, "Skin Corr.", "1")
    irritant_total, irritant_contributions = _sum(ingredients, "Skin Irrit.", "2")
    result.trace.append(f"Skin Corr. 1 (all sub-categories): {corrosive_total} %")
    result.trace.append(f"Skin Irrit. 2: {irritant_total} %")

    if corrosive_total >= 5:
        result.hazard_class = HazardClass("Skin Corr.", "1")
        result.total, result.limit = corrosive_total, Decimal(5)
        result.contributions = corrosive_contributions
        return result
    if corrosive_total >= 1:
        result.hazard_class = HazardClass("Skin Irrit.", "2")
        result.total, result.limit = corrosive_total, Decimal(1)
        result.contributions = corrosive_contributions
        result.trace.append("Skin Corr. 1 at or above 1 % but below 5 % "
                            "classifies the mixture Skin Irrit. 2")
        return result
    if irritant_total >= 10:
        result.hazard_class = HazardClass("Skin Irrit.", "2")
        result.total, result.limit = irritant_total, Decimal(10)
        result.contributions = irritant_contributions
        return result

    combined = corrosive_total * 10 + irritant_total
    result.trace.append(f"(10 x Skin Corr. 1) + Skin Irrit. 2 = {combined} %")
    # Recorded whether or not it triggers: a reader comparing 9 % against a
    # 10 % limit learns something a bare "no" does not tell them.
    result.total, result.limit = combined, Decimal(10)
    if combined >= 10:
        result.hazard_class = HazardClass("Skin Irrit.", "2")
        result.total, result.limit = combined, Decimal(10)
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           Decimal(10)) for c in corrosive_contributions],
            *irritant_contributions]
    return result


# -- 3.3 Serious eye damage / eye irritation ----------------------------------

EYE = "Annex I, 3.3.3.3.4, Table 3.3.3"


def eye(ingredients) -> RuleResult:
    """Eye damage and irritation by summation.

    Annex I 3.3.3.3.4, Table 3.3.3. A skin corrosive is treated as seriously
    damaging to the eye for this calculation, as the table's own note says, so
    Skin Corr. 1 ingredients are counted with the Eye Dam. 1 ones.
    """
    result = RuleResult(hazard_class=None, citation=EYE)
    damage_total, damage_contributions = _sum(ingredients, "Eye Dam.", "1")
    corrosive_total, corrosive_contributions = _sum(ingredients, "Skin Corr.", "1")
    for contribution in corrosive_contributions:
        contribution.note = "Skin Corr. 1 counts as Eye Dam. 1 (Table 3.3.3)"
    damage_total += corrosive_total
    damage_contributions += corrosive_contributions
    irritant_total, irritant_contributions = _sum(ingredients, "Eye Irrit.", "2")

    result.trace.append(f"Eye Dam. 1 (with Skin Corr. 1): {damage_total} %")
    result.trace.append(f"Eye Irrit. 2: {irritant_total} %")

    if damage_total >= 3:
        result.hazard_class = HazardClass("Eye Dam.", "1")
        result.total, result.limit = damage_total, Decimal(3)
        result.contributions = damage_contributions
        return result
    if damage_total >= 1:
        result.hazard_class = HazardClass("Eye Irrit.", "2")
        result.total, result.limit = damage_total, Decimal(1)
        result.contributions = damage_contributions
        result.trace.append("Eye Dam. 1 at or above 1 % but below 3 % "
                            "classifies the mixture Eye Irrit. 2")
        return result
    if irritant_total >= 10:
        result.hazard_class = HazardClass("Eye Irrit.", "2")
        result.total, result.limit = irritant_total, Decimal(10)
        result.contributions = irritant_contributions
        return result

    combined = damage_total * 10 + irritant_total
    result.trace.append(f"(10 x Eye Dam. 1) + Eye Irrit. 2 = {combined} %")
    result.total, result.limit = combined, Decimal(10)
    if combined >= 10:
        result.hazard_class = HazardClass("Eye Irrit.", "2")
        result.total, result.limit = combined, Decimal(10)
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           Decimal(10), c.note)
              for c in damage_contributions],
            *irritant_contributions]
    return result


# -- 4.1 Hazardous to the aquatic environment ---------------------------------

AQUATIC_ACUTE = "Annex I, 4.1.3.5.5, Table 4.1.1"
AQUATIC_CHRONIC = "Annex I, 4.1.3.5.5, Table 4.1.2"


def _aquatic_sum(ingredients, name, category, use_m: bool):
    """Sum a class, multiplying by the M-factor where the act requires it."""
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


def aquatic_acute(ingredients) -> RuleResult:
    """Acute aquatic hazard by summation.

    Annex I 4.1.3.5.5, Table 4.1.1: the mixture is Aquatic Acute 1 when the sum
    of the Acute 1 ingredients, each multiplied by its M-factor, is at least
    25 %.
    """
    total, contributions, assumptions = _aquatic_sum(
        ingredients, "Aquatic Acute", "1", use_m=True)
    result = RuleResult(hazard_class=None, citation=AQUATIC_ACUTE,
                        total=total, limit=Decimal(25),
                        contributions=contributions, assumptions=assumptions)
    result.trace.append(f"Sum of (Aquatic Acute 1 x M) = {total} %")
    if total >= 25:
        result.hazard_class = HazardClass("Aquatic Acute", "1")
    return result


def aquatic_chronic(ingredients) -> RuleResult:
    """Chronic aquatic hazard by summation.

    Annex I 4.1.3.5.5, Table 4.1.2. Each category's threshold is 25 %, and the
    more severe categories are weighted into the less severe ones: ten times
    for one step, a hundred for two.
    """
    one, one_parts, assumptions = _aquatic_sum(
        ingredients, "Aquatic Chronic", "1", use_m=True)
    two, two_parts, _ = _aquatic_sum(ingredients, "Aquatic Chronic", "2", False)
    three, three_parts, _ = _aquatic_sum(ingredients, "Aquatic Chronic", "3", False)
    four, four_parts, _ = _aquatic_sum(ingredients, "Aquatic Chronic", "4", False)

    result = RuleResult(hazard_class=None, citation=AQUATIC_CHRONIC,
                        limit=Decimal(25), assumptions=assumptions)
    result.trace.append(f"Sum of (Chronic 1 x M) = {one} %")
    result.trace.append(f"Chronic 2 = {two} %, Chronic 3 = {three} %, "
                        f"Chronic 4 = {four} %")

    if one >= 25:
        result.hazard_class = HazardClass("Aquatic Chronic", "1")
        result.total, result.contributions = one, one_parts
        return result
    weighted_two = one * 10 + two
    result.trace.append(f"(10 x Chronic 1) + Chronic 2 = {weighted_two} %")
    if weighted_two >= 25:
        result.hazard_class = HazardClass("Aquatic Chronic", "2")
        result.total = weighted_two
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           c.multiplier * 10, c.note) for c in one_parts],
            *two_parts]
        return result
    weighted_three = one * 100 + two * 10 + three
    result.trace.append(
        f"(100 x Chronic 1) + (10 x Chronic 2) + Chronic 3 = {weighted_three} %")
    if weighted_three >= 25:
        result.hazard_class = HazardClass("Aquatic Chronic", "3")
        result.total = weighted_three
        result.contributions = [
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           c.multiplier * 100, c.note) for c in one_parts],
            *[Contribution(c.cas, c.name, c.percentage, c.hazard_class,
                           Decimal(10), c.note) for c in two_parts],
            *three_parts]
        return result
    everything = one + two + three + four
    result.trace.append(f"Chronic 1 + 2 + 3 + 4 = {everything} %")
    result.total = everything
    if everything >= 25:
        result.hazard_class = HazardClass("Aquatic Chronic", "4")
        result.total = everything
        result.contributions = one_parts + two_parts + three_parts + four_parts
    return result


# -- Generic concentration limits ---------------------------------------------

#: The generic concentration limit above which an ingredient's own class
#: becomes the mixture's, with the paragraph of Annex I that sets it. A limit
#: given per sub-category applies to that sub-category; the plain category's
#: limit applies where the sub-category is unknown.
GENERIC_LIMITS: dict[tuple[str, str], tuple[Decimal, str]] = {
    ("Skin Sens.", "1"): (Decimal("1.0"), "Annex I, 3.4.3.3, Table 3.4.6"),
    ("Skin Sens.", "1A"): (Decimal("0.1"), "Annex I, 3.4.3.3, Table 3.4.6"),
    ("Skin Sens.", "1B"): (Decimal("1.0"), "Annex I, 3.4.3.3, Table 3.4.6"),
    ("Resp. Sens.", "1"): (Decimal("0.2"), "Annex I, 3.4.3.3, Table 3.4.6"),
    ("Resp. Sens.", "1A"): (Decimal("0.1"), "Annex I, 3.4.3.3, Table 3.4.6"),
    ("Resp. Sens.", "1B"): (Decimal("0.2"), "Annex I, 3.4.3.3, Table 3.4.6"),
    ("Muta.", "1"): (Decimal("0.1"), "Annex I, 3.5.3.1, Table 3.5.2"),
    ("Muta.", "1A"): (Decimal("0.1"), "Annex I, 3.5.3.1, Table 3.5.2"),
    ("Muta.", "1B"): (Decimal("0.1"), "Annex I, 3.5.3.1, Table 3.5.2"),
    ("Muta.", "2"): (Decimal("1.0"), "Annex I, 3.5.3.1, Table 3.5.2"),
    ("Carc.", "1"): (Decimal("0.1"), "Annex I, 3.6.3.1, Table 3.6.2"),
    ("Carc.", "1A"): (Decimal("0.1"), "Annex I, 3.6.3.1, Table 3.6.2"),
    ("Carc.", "1B"): (Decimal("0.1"), "Annex I, 3.6.3.1, Table 3.6.2"),
    ("Carc.", "2"): (Decimal("1.0"), "Annex I, 3.6.3.1, Table 3.6.2"),
    ("Repr.", "1"): (Decimal("0.3"), "Annex I, 3.7.3.1, Table 3.7.2"),
    ("Repr.", "1A"): (Decimal("0.3"), "Annex I, 3.7.3.1, Table 3.7.2"),
    ("Repr.", "1B"): (Decimal("0.3"), "Annex I, 3.7.3.1, Table 3.7.2"),
    ("Repr.", "2"): (Decimal("3.0"), "Annex I, 3.7.3.1, Table 3.7.2"),
    ("Lact.", ""): (Decimal("0.3"), "Annex I, 3.7.3.1, Table 3.7.2"),
    ("STOT SE", "1"): (Decimal("10.0"), "Annex I, 3.8.3.4, Table 3.8.3"),
    ("STOT SE", "2"): (Decimal("10.0"), "Annex I, 3.8.3.4, Table 3.8.3"),
    ("STOT RE", "1"): (Decimal("10.0"), "Annex I, 3.9.3.4, Table 3.9.4"),
    ("STOT RE", "2"): (Decimal("10.0"), "Annex I, 3.9.3.4, Table 3.9.4"),
}

#: A category 1 ingredient between 1 % and its own limit classifies the mixture
#: in category 2 instead. Annex I, Table 3.8.3 and Table 3.9.4.
STEP_DOWN = {
    ("STOT SE", "1"): ("STOT SE", "2", Decimal("1.0")),
    ("STOT RE", "1"): ("STOT RE", "2", Decimal("1.0")),
}

STOT_SE_3 = "Annex I, 3.8.3.4.5, Table 3.8.3"


def generic_limit(ingredients, name: str, category: str) -> RuleResult:
    """One class whose limit is a concentration, not a sum.

    These classes are not additive: a single ingredient at or above the limit
    classifies the mixture, and a specific concentration limit from Annex VI
    replaces the generic one for that ingredient alone.
    """
    limit, citation = GENERIC_LIMITS[(name, category)]
    result = RuleResult(hazard_class=None, citation=citation, limit=limit)
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
        step = STEP_DOWN.get((name, category))
        if step and ingredient.percentage >= step[2]:
            stepped.append(contribution)

    if result.hazard_class is None and stepped:
        step_name, step_category, step_limit = STEP_DOWN[(name, category)]
        result.hazard_class = HazardClass(step_name, step_category)
        result.contributions = stepped
        result.limit = step_limit
        result.total = max(c.percentage for c in stepped)
        result.trace.append(
            f"At or above {step_limit} % but below the category 1 limit, "
            f"which classifies the mixture {step_name} {step_category}")
    return result


def stot_se_3(ingredients, effect: str) -> RuleResult:
    """Single-exposure narcotic effects and respiratory irritation.

    Annex I 3.8.3.4.5: these two effects are additive, and each is summed on
    its own - a mixture is classified when the ingredients causing one of them
    reach 20 % between them.
    """
    result = RuleResult(hazard_class=None, citation=STOT_SE_3,
                        limit=Decimal(20))
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
    if total >= 20:
        result.hazard_class = HazardClass("STOT SE", "3")
    return result
