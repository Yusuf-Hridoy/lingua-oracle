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

from lingua_oracle.mixture import families, rule_table, rules
from lingua_oracle.mixture.classes import HazardClass, parse_class
from lingua_oracle.mixture.rule_table import RuleTable
from lingua_oracle.mixture.rules import RuleResult
from lingua_oracle.mixture.state import applicable, state_of


def in_scope(regulation: str) -> bool:
    """True where a rule table was built for this regulation."""
    return rule_table.load(regulation) is not None


@dataclass
class ClassResult:
    """What the calculation concluded about one hazard family.

    One endpoint, one verdict. `hazard_class` is the family's name, which is
    what the card is headed with; `stated_class` and `calculated_class` are
    the two classifications being compared, either of which may be absent.
    """

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
    #: The endpoint this is about, where it is one this tool compares.
    family: str = ""
    #: What Section 2 says about this endpoint, and what the ingredients give.
    stated_class: str = ""
    calculated_class: str = ""
    #: Where a stated class was read into the sheet rather than printed on it.
    implied_from: str = ""
    #: What the sheet itself says about test data, bridging or expert
    #: judgement, quoted, where Section 2 differs from the calculation.
    justification: list[str] = field(default_factory=list)


#: Which hazard classes each rule can produce. A rule is only run where the
#: regulation has at least one of them: calculating an aquatic classification
#: under a standard that has no aquatic classes would be inventing a finding.
RULE_CLASSES = {
    "skin": ("Skin Corr.", "Skin Irrit."),
    "eye": ("Eye Dam.", "Eye Irrit."),
    "aquatic_acute": ("Aquatic Acute",),
    "aquatic_chronic": ("Aquatic Chronic",),
}


def _run_all(ingredients, table: RuleTable, variant: int = 0,
             state: str | None = None) -> dict[str, RuleResult]:
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
                                       variant, state)
    if table.covers_class("STOT SE"):
        for effect in ("respiratory irritation", "narcotic effects"):
            out[f"STOT SE 3 {effect}"] = rules.stot_se_3(
                ingredients, effect, table, variant, state)
    return out


def _variants(table: RuleTable, state: str | None = None) -> int:
    """How many readings the regulation's own table supports.

    A published table that gives two limits for the same class is read both
    ways, the way a concentration range is read at both ends. Where the two
    readings agree there is an answer; where they do not, that is what the
    report says.
    """
    return max((len(applicable(values, state))
                for keys in table.values.values()
                for values in keys.values()), default=1)


def _declared_total(ingredients) -> Decimal:
    return sum((i.high for i in ingredients), Decimal(0))


def calculate(ingredients, stated: list[HazardClass], regulation: str,
              state: str | None = None, *,
              declared: Decimal | None = None,
              acute_inputs: dict | None = None,
              justification: list[str] | None = None) -> tuple[list[ClassResult], dict]:
    """Compare what the ingredients give with what Section 2 states.

    The comparison is per hazard family, not per class: a sheet that states
    Skin Corr. 1 where the declared ingredients give Skin Irrit. 2 has not
    made two mistakes, it has been stricter about the skin than the part of
    the mixture it declares, and that is one verdict about the skin.

    `state` is what Section 9 says the mixture is - a gas, or a solid or a
    liquid - where it says anything. Two of the sensitisation limits depend on
    it; where it is not known, both are calculated and the disagreement, if
    there is one, is what the report says.

    `declared` is the sum of the upper bounds of every range Section 3 gives,
    the ingredients no rule can use (water, say) included. What is undisclosed
    is what that leaves of 100 %, and nothing when the upper bounds reach it:
    then the uncertainty is the ranges', and both ends of each are evaluated.
    """
    table = rule_table.load(regulation)
    if table is None:
        return [], {"scope": regulation, "in_scope": False}

    ends = {"low": [i.at("low") for i in ingredients],
            "high": [i.at("high") for i in ingredients]}
    readings = _variants(table, state)
    runs: list[tuple[str, int, dict[str, RuleResult]]] = [
        (end, variant, _run_all(ingredients_at, table, variant, state))
        for end, ingredients_at in ends.items()
        for variant in range(readings)]

    if declared is None:
        declared = _declared_total(ingredients)
    undisclosed = max(Decimal(100) - declared, Decimal(0))

    results: list[ClassResult] = []
    not_on_file: list[str] = []
    calculated: dict[str, _Family] = {}

    for key in dict.fromkeys(k for _, _, run in runs for k in run):
        by_run = {(end, variant): run[key]
                  for end, variant, run in runs if key in run}
        missing = sorted({m for r in by_run.values() for m in r.missing})
        if missing:
            not_on_file.append(key)
            if _worth_saying(key, by_run.values(), stated):
                results.append(ClassResult(
                    verdict="not_calculated", hazard_class=key, citation="",
                    stated=False, family=families.family_of(key) or "",
                    message=("Not calculated: "
                             f"{_display(regulation)} has no rule on file for "
                             f"{', '.join(missing)}.")))
            continue
        _collect(key, by_run, readings, state, calculated)

    stated_families = families.by_family(stated)
    implied = _implied(stated, table)
    for family, (hazard_class, _) in implied.items():
        stated_families.setdefault(family, []).append(hazard_class)

    for family, names in families.FAMILIES:
        found = calculated.get(family)
        said = families.strictest(stated_families.get(family, []))
        if found is None and said is None:
            continue
        if found is None and not any(table.covers_class(n) for n in names):
            # Not a gap in the calculation: the regulation has no such class.
            results.append(ClassResult(
                verdict="not_calculated", hazard_class=family, family=family,
                citation="", stated=True, stated_class=str(said),
                message=f"Not covered by {_display(regulation)}."))
            continue
        results.append(_verdict(family, found, said, implied.get(family),
                                undisclosed, declared, regulation,
                                justification or []))

    # Acute toxicity, by additivity, one family per route.
    acute_rules = _acute_rules(regulation)
    if acute_rules is not None and acute_inputs is not None:
        results += _acute_results(acute_rules, acute_inputs, stated, state,
                                  undisclosed, declared, regulation,
                                  justification or [])

    # Classes the sheet states that this tool does not compare at all.
    for hazard_class in stated:
        if families.family_of(hazard_class) is not None:
            continue
        if acute_rules is not None and hazard_class.name.startswith("Acute Tox"):
            continue   # compared above, route by route, from the codes
        name = str(hazard_class)
        if (hazard_class.name in _ALL_CLASSES
                and not table.covers_class(hazard_class.name)):
            results.append(ClassResult(
                verdict="not_calculated", hazard_class=name, citation="",
                stated=True, stated_class=name,
                message=f"Not covered by {_display(regulation)}."))
            continue
        results.append(ClassResult(
            verdict="not_calculated", hazard_class=name, citation="",
            stated=True, stated_class=name,
            message="This tool does not calculate this hazard class yet."))

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


@dataclass
class _Family:
    """What the rules gave for one endpoint, gathered from all of them."""

    hazard_class: HazardClass
    winner: RuleResult
    disagreed: bool = False
    message: str = ""
    at_low: str = ""
    at_high: str = ""
    assumptions: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    contributions: list[dict] = field(default_factory=list)


def _collect(key: str, by_run, readings: int, state, out: dict[str, _Family]
             ) -> None:
    """Fold one rule's result into what is known about its family.

    Several rules can speak for one endpoint - the skin summation and nothing
    else for the skin, but four separate concentration limits for
    carcinogenicity - and what the family is classified as is the strictest of
    what they gave.
    """
    outcomes = {str(r.hazard_class) if r.hazard_class else ""
                for r in by_run.values()}
    if outcomes == {""}:
        return
    winner = _winner(by_run)
    hazard_class = winner.hazard_class
    family = families.family_of(hazard_class)
    if family is None:
        return
    found = _Family(
        hazard_class=hazard_class, winner=winner,
        disagreed=len(outcomes) > 1,
        message=_depends(by_run, readings, state) if len(outcomes) > 1 else "",
        at_low=_at(by_run, "low"), at_high=_at(by_run, "high"),
        assumptions=sorted({a for r in by_run.values() for a in r.assumptions}),
        trace=list(dict.fromkeys(t for r in by_run.values() for t in r.trace)),
        contributions=_as_dicts(winner))
    standing = out.get(family)
    if standing is None:
        out[family] = found
        return
    # Keep the strictest classification, and the uncertainty of either.
    if families.stricter(hazard_class, standing.hazard_class):
        found.disagreed = found.disagreed or standing.disagreed
        found.message = found.message or standing.message
        found.assumptions = sorted({*found.assumptions, *standing.assumptions})
        found.trace = [*standing.trace, *found.trace]
        out[family] = found
    else:
        standing.disagreed = standing.disagreed or found.disagreed
        standing.message = standing.message or found.message
        standing.assumptions = sorted({*standing.assumptions,
                                       *found.assumptions})
        standing.trace = [*standing.trace, *found.trace]


def _implied(stated: list[HazardClass], table: RuleTable
             ) -> dict[str, tuple[HazardClass, str]]:
    """Classifications a regulation says a stated one carries with it.

    Only where the regulation says so in its own text: CLP and the retained GB
    act both say a skin corrosive is to be considered as seriously damaging to
    the eye, and the rule tables carry the paragraph. Where a regulation does
    not say it, nothing is read into the sheet.
    """
    out: dict[str, tuple[HazardClass, str]] = {}
    for hazard_class in stated:
        found = table.implied_by(str(hazard_class.generic))
        if found is None:
            continue
        implied = parse_class(found.implied)
        family = families.family_of(implied)
        if implied is None or family is None:
            continue
        out[family] = (implied, f"{hazard_class} in Section 2 is also "
                                f"{implied} - {found.citation}")
    return out


def _acute_rules(regulation: str):
    from lingua_oracle.mixture import acute_table

    return acute_table.load(regulation)


@dataclass(frozen=True)
class _Cited:
    citation: str


def _words(name: str, values) -> str:
    return " or ".join(f"{name} {v}" if v else "no classification" for v in values)


def _acute_results(rules, inputs: dict, stated, state, undisclosed: Decimal,
                   declared: Decimal, regulation: str,
                   justification: list[str]) -> list[ClassResult]:
    """One verdict per route, from the additivity runs, in the common model."""
    from lingua_oracle.mixture import acute

    # A category the regulation does not have (Category 5 outside the GHS
    # itself) is outside its classification: C-12 says so as a note, and no
    # verdict is formed on it here.
    stated = [c for c in stated if c.name not in acute.CLASS_NAME.values()
              or c.category in rules.categories]
    calculated = acute.calculate(
        inputs["ingredients"], rules, state, entries=inputs.get("entries"),
        section_11=inputs.get("section_11"), unknown=inputs.get("unknown"))
    said_by_route = acute.stated_categories(stated)
    out: list[ClassResult] = []
    for route in acute.ROUTES:
        name, family = acute.CLASS_NAME[route], acute.FAMILY[route]
        said_cats = said_by_route.get(route, set())
        data = calculated.get(route)
        if data is None and not said_cats:
            continue
        runs = data["runs"] if data else []
        cats = {r.category for r in runs}
        found = None
        if runs and cats != {None}:
            ranked = sorted((c for c in cats if c), key=int)
            hazard_class = HazardClass(name, ranked[0])
            by_end = {end: sorted({r.category or "" for r in runs if r.end == end})
                      for end in ("low", "high")}

            disagreed = len(cats) > 1
            message = ""
            if disagreed:
                reasons = []
                if by_end["low"] != by_end["high"]:
                    reasons.append(f"at the low end of the declared ranges the "
                                   f"mixture is {_words(name, by_end['low'])}, at "
                                   f"the high end {_words(name, by_end['high'])}")
                if data["variants"] > 1:
                    reasons.append("an ingredient's H code covers two categories, "
                                   "and they give different answers")
                if len(data["forms"]) > 1:
                    reasons.append("Section 9 does not say whether the mixture is "
                                   "a liquid or a solid, and vapour and dust/mist "
                                   "give different answers")
                message = ("Depends on the exact composition: "
                           + "; ".join(reasons or ["the runs disagree"]) + ".")
            found = _Family(
                hazard_class=hazard_class,
                winner=_Cited(f"{rules.citations['formula']}; bands "
                              f"{rules.citations['bands']}"),
                disagreed=disagreed, message=message,
                at_low=_words(name, by_end["low"]),
                at_high=_words(name, by_end["high"]),
                assumptions=[f"ingredients below {rules.relevance} % are not "
                             f"relevant ({rules.citations['relevance']})"],
                trace=[line for r in runs for line in r.trace],
                contributions=data["contributions"])
        said = None
        if said_cats:
            calc = found.hazard_class.category if found and not found.disagreed else None
            if calc in said_cats:
                said = HazardClass(name, calc)
            elif calc is not None and int(calc) < min(map(int, said_cats)):
                said = HazardClass(name, str(min(map(int, said_cats))))
            else:
                said = HazardClass(name, str(max(map(int, said_cats)) if calc
                                             else min(map(int, said_cats))))
        result = _verdict(family, found, said, None, undisclosed, declared,
                          regulation, justification)
        if found is None and runs:
            result.trace = [line for r in runs for line in r.trace]
        out.append(result)
    return out


def _differs(said_text: str, calculated_text: str) -> str:
    """The sentence for a Section 2 that differs from the calculation.

    The calculation from the law is the reference; Section 2 may differ from
    it only for a reason the sheet can give - bridging principles, test data
    on the mixture, expert judgement - and the sheet is asked for it.
    """
    stated = said_text or "nothing for this hazard"
    subject = said_text or "leaving it out"
    calculated = calculated_text or "no classification"
    return (f"Section 2 states {stated}; calculated from the ingredients: "
            f"{calculated}. If {subject} is based on bridging principles, test "
            "data or expert judgement, the SDS must be able to justify it \u2014 "
            "confirm which principle and which reference mixture.")


def _verdict(family: str, found: _Family | None, said: HazardClass | None,
             implied, undisclosed: Decimal, declared: Decimal,
             regulation: str, justification: list[str] | None = None) -> ClassResult:
    """One endpoint, one verdict, in the words a reader can act on.

    Where Section 2 and the calculation agree, that is the verdict. Where they
    differ, Section 2 is never taken as right for differing:

    * Section 2 stricter than the calculation - including a hazard the
      declared ingredients do not give - is one to check;
    * Section 2 weaker, or silent on a hazard the ingredients give, is a fault
      to fix - unless the sheet itself cites test data, bridging or expert
      judgement, in which case it is one to check, with that text shown.
    """
    justification = list(justification or [])
    said_text = str(said) if said else ""
    calculated_text = str(found.hazard_class) if found else ""
    common = {
        "hazard_class": family, "family": family,
        "stated_class": said_text, "calculated_class": calculated_text,
        "stated": bool(said), "implied_from": implied[1] if implied else "",
        "citation": found.winner.citation if found else "",
        "contributions": found.contributions if found else [],
        "assumptions": found.assumptions if found else [],
        "trace": found.trace if found else [],
        "calculated_low": found.at_low if found else "",
        "calculated_high": found.at_high if found else "",
    }
    undisclosed_note = (f" The declared ingredients total {declared} %; the "
                        f"undisclosed {undisclosed} % may also carry it."
                        if undisclosed > 0 else "")

    def stricter_section_two() -> ClassResult:
        return ClassResult(verdict="cannot_tell",
                           message=_differs(said_text, calculated_text) + undisclosed_note,
                           justification=justification, **common)

    def weaker_section_two() -> ClassResult:
        return ClassResult(verdict="cannot_tell" if justification else "inconsistent",
                           message=_differs(said_text, calculated_text),
                           justification=justification, **common)

    if found is None:
        # Section 2 states a hazard the declared ingredients do not give.
        return stricter_section_two()

    if found.disagreed:
        return ClassResult(verdict="cannot_tell", message=found.message, **common)

    if said is None:
        return weaker_section_two()

    narcotic = _stot_se_3_against_1_or_2(found.hazard_class, said)
    if narcotic:
        return ClassResult(verdict="cannot_tell", message=narcotic, **common)

    if families.stricter(found.hazard_class, said):
        return weaker_section_two()

    if families.stricter(said, found.hazard_class):
        return stricter_section_two()

    return ClassResult(
        verdict="consistent",
        message="Section 2 lists this hazard and the ingredients give it.",
        **common)


def _stot_se_3_against_1_or_2(calculated: HazardClass,
                              said: HazardClass) -> str:
    """Category 3 is a different injury from categories 1 and 2.

    Narcotic effects and respiratory irritation are not an organ. A sheet
    whose Section 2 names a target organ at category 1 or 2 may well have
    covered the same exposure, and may not; neither this tool nor the rule
    tables can tell which, and calling it a contradiction would be wrong.
    """
    if calculated.name != "STOT SE" or calculated.category != "3":
        return ""
    if said.name != "STOT SE" or said.category not in ("1", "2"):
        return ""
    return ("Check this: STOT SE 3 (respiratory irritation/narcotic) is "
            f"calculated; Section 2's {said} may cover it if it targets the "
            "same organ.")


def _worth_saying(key, results, stated) -> bool:
    """Whether a rule that could not run is worth a card.

    A rule with nothing to work on - no ingredient carrying the class, nothing
    stated about it - would be a card saying that nothing was calculated about
    nothing. One that had something to say is reported.
    """
    if any(str(c) == key or str(c.generic) == key for c in stated):
        return True
    return any(r.contributions or r.trace for r in results)


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


def _depends(by_run: dict[tuple[str, int], RuleResult], readings: int,
             state: str | None = None) -> str:
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
            states = sorted({s for s in (state_of(a) for r in by_run.values()
                                         for a in r.assumptions)
                             if s and s != "all physical states"})
            if state is None and len(states) > 1:
                reasons.append(
                    "the physical state: the table sets a different limit for "
                    + " and for ".join(states)
                    + f" ({', '.join(limits)} %), and Section 9 does not say "
                      "which this mixture is")
            else:
                reasons.append(
                    "the published table gives more than one limit for this "
                    f"class ({' and '.join(limits)} %) and the answer differs "
                    "between them")
    if not reasons:
        reasons.append("the rules do not agree on one answer")
    return "Depends on " + "; and ".join(reasons) + "."


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
