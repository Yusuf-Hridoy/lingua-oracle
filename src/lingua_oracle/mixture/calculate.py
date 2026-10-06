"""Running every rule at both ends of every range, and comparing the result.

A concentration range makes the question "what is this mixture classified as"
have two answers, one at each end. Where they agree there is an answer; where
they do not, the honest report is that it depends on the exact concentration,
with both ends shown.

The undisclosed remainder is the other source of uncertainty. A mixture whose
declared ingredients do not reach 100 % has something in it that this
calculation cannot see, so a class Section 2 states and the calculation does
not may come from there - which is a reason to say nothing rather than to
contradict the sheet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from lingua_oracle.mixture import rules
from lingua_oracle.mixture.classes import HazardClass
from lingua_oracle.mixture.rules import RuleResult

#: The regulations whose Annex I this implements. CLP and its GB retention share
#: the text; everything else has its own rules and is not guessed at.
IN_SCOPE = {"eu_clp", "uk_clp"}


@dataclass
class ClassResult:
    """What the calculation concluded about one hazard class."""

    #: "consistent", "inconsistent", "cannot_tell", "not_calculated"
    verdict: str
    hazard_class: str
    citation: str
    stated: bool
    calculated_low: str | None = None
    calculated_high: str | None = None
    message: str = ""
    contributions: list[dict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)


def _run_all(ingredients) -> dict[str, RuleResult]:
    """Every rule, keyed by the family of classes it decides."""
    out = {
        "skin": rules.skin(ingredients),
        "eye": rules.eye(ingredients),
        "aquatic_acute": rules.aquatic_acute(ingredients),
        "aquatic_chronic": rules.aquatic_chronic(ingredients),
    }
    for (name, category) in rules.GENERIC_LIMITS:
        out[f"{name} {category}".strip()] = rules.generic_limit(
            ingredients, name, category)
    for effect in ("respiratory irritation", "narcotic effects"):
        out[f"STOT SE 3 {effect}"] = rules.stot_se_3(ingredients, effect)
    return out


def _declared_total(ingredients) -> Decimal:
    return sum((i.high for i in ingredients), Decimal(0))


def calculate(ingredients, stated: list[HazardClass], regulation: str
              ) -> tuple[list[ClassResult], dict]:
    """Compare what the ingredients give with what Section 2 states."""
    if regulation not in IN_SCOPE:
        return [], {"scope": regulation, "in_scope": False}

    low = [i.at("low") for i in ingredients]
    high = [i.at("high") for i in ingredients]
    at_low, at_high = _run_all(low), _run_all(high)
    declared = _declared_total(ingredients)
    undisclosed = max(Decimal(100) - declared, Decimal(0))
    stated_names = {str(c) for c in stated}
    stated_generic = {str(c.generic) for c in stated}

    results: list[ClassResult] = []
    seen: set[str] = set()

    for key, low_result in at_low.items():
        high_result = at_high[key]
        low_class = low_result.hazard_class
        high_class = high_result.hazard_class
        if low_class is None and high_class is None:
            continue
        name = str(high_class or low_class)
        seen.add(name)
        seen.add(str((high_class or low_class).generic))
        citation = (high_result if high_class else low_result).citation
        winner = high_result if high_class else low_result

        if str(low_class or "") != str(high_class or ""):
            low_text = str(low_class) if low_class else "no classification"
            high_text = str(high_class) if high_class else "no classification"
            results.append(ClassResult(
                verdict="cannot_tell", hazard_class=name, citation=citation,
                stated=name in stated_names,
                calculated_low=low_text, calculated_high=high_text,
                message=("Depends on the exact concentration: at the low end "
                         f"of the declared ranges the mixture is {low_text}, "
                         f"at the high end {high_text}."),
                contributions=_as_dicts(winner),
                assumptions=sorted({*low_result.assumptions,
                                    *high_result.assumptions}),
                trace=[*low_result.trace, *high_result.trace]))
            continue

        if name in stated_names or str((high_class or low_class).generic) in stated_generic:
            results.append(ClassResult(
                verdict="consistent", hazard_class=name, citation=citation,
                stated=True, calculated_low=name, calculated_high=name,
                message="Section 2 states this and the ingredients give it.",
                contributions=_as_dicts(winner),
                assumptions=sorted(set(winner.assumptions)),
                trace=list(winner.trace)))
            continue

        results.append(ClassResult(
            verdict="inconsistent", hazard_class=name, citation=citation,
            stated=False, calculated_low=name, calculated_high=name,
            message=("The ingredients give this classification and Section 2 "
                     "does not state it."),
            contributions=_as_dicts(winner),
            assumptions=sorted(set(winner.assumptions)),
            trace=list(winner.trace)))

    # Classes the sheet states that the calculation did not produce.
    for hazard_class in stated:
        name = str(hazard_class)
        if name in seen or str(hazard_class.generic) in seen:
            continue
        if not _is_calculable(hazard_class):
            results.append(ClassResult(
                verdict="not_calculated", hazard_class=name,
                citation="", stated=True,
                message="This tool does not calculate this hazard class yet."))
            continue
        if undisclosed > 0:
            results.append(ClassResult(
                verdict="cannot_tell", hazard_class=name, citation="",
                stated=True,
                message=(f"Section 2 states this and the declared ingredients "
                         f"do not give it. It may come from the undisclosed "
                         f"{undisclosed} %."),
                assumptions=[f"the declared ingredients total {declared} %"]))
            continue
        results.append(ClassResult(
            verdict="inconsistent", hazard_class=name, citation="", stated=True,
            message=("Section 2 states this and the ingredients do not give "
                     "it, with nothing undisclosed to explain it.")))

    order = {"inconsistent": 0, "cannot_tell": 1, "consistent": 2,
             "not_calculated": 3}
    results.sort(key=lambda r: (order.get(r.verdict, 9), r.hazard_class))
    summary = {
        "scope": regulation, "in_scope": True,
        "declared_total": str(declared), "undisclosed": str(undisclosed),
        "ingredients": len(ingredients),
    }
    return results, summary


def _is_calculable(hazard_class: HazardClass) -> bool:
    """True when a rule here decides this class at all."""
    name = hazard_class.name
    if name in {"Skin Corr.", "Skin Irrit.", "Eye Dam.", "Eye Irrit.",
                "Aquatic Acute", "Aquatic Chronic"}:
        return True
    return any(name == key[0] for key in rules.GENERIC_LIMITS)


def _as_dicts(result: RuleResult) -> list[dict]:
    return [{"cas": c.cas, "name": c.name, "percentage": str(c.percentage),
             "hazard_class": c.hazard_class, "multiplier": str(c.multiplier),
             "contributed": str(c.contributed), "note": c.note}
            for c in result.contributions]
