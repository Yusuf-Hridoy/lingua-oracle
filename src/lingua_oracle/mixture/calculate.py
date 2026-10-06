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

from lingua_oracle.mixture import rule_table, rules
from lingua_oracle.mixture.classes import HazardClass
from lingua_oracle.mixture.rule_table import RuleTable
from lingua_oracle.mixture.rules import RuleResult


def in_scope(regulation: str) -> bool:
    """True where a rule table was built for this regulation."""
    return rule_table.load(regulation) is not None


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


#: Which hazard classes each rule can produce. A rule is only run where the
#: regulation has at least one of them: calculating an aquatic classification
#: under a standard that has no aquatic classes would be inventing a finding.
RULE_CLASSES = {
    "skin": ("Skin Corr.", "Skin Irrit."),
    "eye": ("Eye Dam.", "Eye Irrit."),
    "aquatic_acute": ("Aquatic Acute",),
    "aquatic_chronic": ("Aquatic Chronic",),
}


def _run_all(ingredients, table: RuleTable, variant: int = 0
             ) -> dict[str, RuleResult]:
    """Every rule this regulation has classes for, keyed by what it decides."""
    out: dict[str, RuleResult] = {}
    if table.covers_class("Skin Corr.") or table.covers_class("Skin Irrit."):
        out["skin"] = rules.skin(ingredients, table)
    if table.covers_class("Eye Dam.") or table.covers_class("Eye Irrit."):
        out["eye"] = rules.eye(ingredients, table)
    if table.covers_class("Aquatic Acute"):
        out["aquatic_acute"] = rules.aquatic_acute(ingredients, table)
    if table.covers_class("Aquatic Chronic"):
        out["aquatic_chronic"] = rules.aquatic_chronic(ingredients, table)
    for (name, category) in rules.LIMIT_CLASSES:
        if not table.covers_class(name):
            continue
        key = rules.limit_key(name, category)
        if not table.variants("generic_limits", key):
            continue
        out[key] = rules.generic_limit(ingredients, name, category, table,
                                       variant)
    if table.covers_class("STOT SE"):
        for effect in ("respiratory irritation", "narcotic effects"):
            out[f"STOT SE 3 {effect}"] = rules.stot_se_3(
                ingredients, effect, table, variant)
    return out


def _variants(table: RuleTable) -> int:
    """How many readings the regulation's own table supports.

    A published table that gives two limits for the same class is read both
    ways, the way a concentration range is read at both ends. Where the two
    readings agree there is an answer; where they do not, that is what the
    report says.
    """
    return max((len(values)
                for keys in table.values.values()
                for values in keys.values()), default=1)


def _declared_total(ingredients) -> Decimal:
    return sum((i.high for i in ingredients), Decimal(0))


def calculate(ingredients, stated: list[HazardClass], regulation: str
              ) -> tuple[list[ClassResult], dict]:
    """Compare what the ingredients give with what Section 2 states."""
    table = rule_table.load(regulation)
    if table is None:
        return [], {"scope": regulation, "in_scope": False}

    ends = {"low": [i.at("low") for i in ingredients],
            "high": [i.at("high") for i in ingredients]}
    readings = _variants(table)
    runs: list[tuple[str, int, dict[str, RuleResult]]] = [
        (end, variant, _run_all(ingredients_at, table, variant))
        for end, ingredients_at in ends.items()
        for variant in range(readings)]

    declared = _declared_total(ingredients)
    undisclosed = max(Decimal(100) - declared, Decimal(0))
    stated_names = {str(c) for c in stated}
    stated_generic = {str(c.generic) for c in stated}

    results: list[ClassResult] = []
    seen: set[str] = set()
    not_on_file: list[str] = []

    for key in dict.fromkeys(k for _, _, run in runs for k in run):
        by_run = {(end, variant): run[key]
                  for end, variant, run in runs if key in run}
        missing = sorted({m for r in by_run.values() for m in r.missing})
        if missing:
            not_on_file.append(key)
            if _worth_saying(key, by_run.values(), stated_names, stated_generic):
                results.append(ClassResult(
                    verdict="not_calculated", hazard_class=key, citation="",
                    stated=key in stated_names,
                    message=("Not calculated: "
                             f"{_display(regulation)} has no rule on file for "
                             f"{', '.join(missing)}.")))
            continue

        outcomes = {str(r.hazard_class) if r.hazard_class else ""
                    for r in by_run.values()}
        if outcomes == {""}:
            continue
        winner = _winner(by_run)
        name = str(winner.hazard_class)
        seen.add(name)
        seen.add(str(winner.hazard_class.generic))
        assumptions = sorted({a for r in by_run.values() for a in r.assumptions})
        trace = list(dict.fromkeys(t for r in by_run.values() for t in r.trace))

        if len(outcomes) > 1:
            results.append(ClassResult(
                verdict="cannot_tell", hazard_class=name,
                citation=winner.citation, stated=name in stated_names,
                calculated_low=_at(by_run, "low"), calculated_high=_at(by_run, "high"),
                message=_depends(by_run, readings),
                contributions=_as_dicts(winner),
                assumptions=assumptions, trace=trace))
            continue

        if name in stated_names or str(winner.hazard_class.generic) in stated_generic:
            results.append(ClassResult(
                verdict="consistent", hazard_class=name,
                citation=winner.citation, stated=True,
                calculated_low=name, calculated_high=name,
                message="Section 2 states this and the ingredients give it.",
                contributions=_as_dicts(winner),
                assumptions=assumptions, trace=trace))
            continue

        results.append(ClassResult(
            verdict="inconsistent", hazard_class=name, citation=winner.citation,
            stated=False, calculated_low=name, calculated_high=name,
            message=("The ingredients give this classification and Section 2 "
                     "does not state it."),
            contributions=_as_dicts(winner),
            assumptions=assumptions, trace=trace))

    # Classes the sheet states that the calculation did not produce.
    for hazard_class in stated:
        name = str(hazard_class)
        if name in seen or str(hazard_class.generic) in seen:
            continue
        if (hazard_class.name in _ALL_CLASSES
                and not table.covers_class(hazard_class.name)):
            results.append(ClassResult(
                verdict="not_calculated", hazard_class=name, citation="",
                stated=True,
                message=f"Not covered by {_display(regulation)}."))
            continue
        if not _is_calculable(hazard_class, table):
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
        "document": table.document,
        "not_on_file": sorted(not_on_file),
        "not_covered": sorted(set(_ALL_CLASSES) - table.covers),
    }
    return results, summary


#: Every class a rule table can carry, so a report can say which ones this
#: regulation does not have.
_ALL_CLASSES = ("Skin Corr.", "Skin Irrit.", "Eye Dam.", "Eye Irrit.",
                "Resp. Sens.", "Skin Sens.", "Muta.", "Carc.", "Repr.",
                "Lact.", "STOT SE", "STOT RE", "Aquatic Acute",
                "Aquatic Chronic")


def _display(regulation: str) -> str:
    from lingua_oracle.registry import load_registry

    try:
        return load_registry().get(regulation).display_name
    except KeyError:
        return regulation


def _winner(by_run: dict[tuple[str, int], RuleResult]) -> RuleResult:
    """The run whose result the cards are built from.

    The high end of the declared ranges, read the regulation's first way, is
    the one a reader is shown, because that is the reading that classifies.
    """
    for key in sorted(by_run, key=lambda k: (k[0] != "high", k[1])):
        if by_run[key].hazard_class is not None:
            return by_run[key]
    return next(iter(by_run.values()))


def _at(by_run: dict[tuple[str, int], RuleResult], end: str) -> str:
    found = {str(r.hazard_class) for (e, _), r in by_run.items()
             if e == end and r.hazard_class is not None}
    return ", ".join(sorted(found)) if found else "no classification"


def _depends(by_run: dict[tuple[str, int], RuleResult], readings: int) -> str:
    """Why the answer is not one answer, in the words that caused it."""
    low, high = _at(by_run, "low"), _at(by_run, "high")
    reasons = []
    if low != high:
        reasons.append(f"at the low end of the declared ranges the mixture is "
                       f"{low}, at the high end {high}")
    if readings > 1:
        by_variant = {}
        for (_, variant), result in by_run.items():
            by_variant.setdefault(variant, set()).add(
                str(result.hazard_class) if result.hazard_class else
                "no classification")
        if len({frozenset(v) for v in by_variant.values()}) > 1:
            limits = sorted({str(r.limit) for r in by_run.values()
                             if r.limit is not None})
            reasons.append("the published table gives more than one limit for "
                           f"this class ({' and '.join(limits)} %) and the "
                           "answer differs between them")
    if not reasons:
        reasons.append("the rules do not agree on one answer")
    return "Depends on " + "; and ".join(reasons) + "."


def _worth_saying(key, results, stated_names, stated_generic) -> bool:
    """Whether a rule that could not run is worth a card.

    A rule with nothing to work on - no ingredient carrying the class, nothing
    stated about it - would be a card saying that nothing was calculated about
    nothing. One that had something to say is reported.
    """
    if key in stated_names or key in stated_generic:
        return True
    return any(r.contributions or r.trace for r in results)


def _is_calculable(hazard_class: HazardClass, table: RuleTable) -> bool:
    """True when a rule decides this class under this regulation at all."""
    name = hazard_class.name
    if name in {"Skin Corr.", "Skin Irrit.", "Eye Dam.", "Eye Irrit.",
                "Aquatic Acute", "Aquatic Chronic"}:
        return bool(table.values.get("skin") or table.values.get("eye")
                    or table.values.get("aquatic_acute")
                    or table.values.get("aquatic_chronic"))
    return any(name == key[0] for key in rules.LIMIT_CLASSES)


def _as_dicts(result: RuleResult) -> list[dict]:
    return [{"cas": c.cas, "name": c.name, "percentage": str(c.percentage),
             "hazard_class": c.hazard_class, "multiplier": str(c.multiplier),
             "contributed": str(c.contributed), "note": c.note}
            for c in result.contributions]
