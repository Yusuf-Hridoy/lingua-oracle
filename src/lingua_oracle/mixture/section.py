"""The mixture half of one upload: build it from whatever composition we have."""

from __future__ import annotations

from lingua_oracle.mixture import concentration as conc
from lingua_oracle.mixture.calculate import IN_SCOPE, calculate
from lingua_oracle.mixture.limits import parse as parse_limits
from lingua_oracle.mixture.model import from_annex_vi, from_codes
from lingua_oracle.mixture.stated import stated_classes
from lingua_oracle.models import MixtureSection

NO_COMPOSITION = ("No composition to calculate from: this sheet prints no "
                  "ingredients with concentrations.")
NO_CONCENTRATIONS = ("The ingredients are listed without concentrations, so "
                     "nothing can be summed.")


def _ingredient(cas, name, raw_concentration, codes, table, index):
    """One ingredient, classified from Annex VI where it is harmonised."""
    parsed = conc.parse(raw_concentration)
    if parsed is None:
        return None, None
    entries = index.get((cas or "").strip(), []) if cas else []
    if len(entries) == 1 and not entries[0].covers_several_substances:
        entry = entries[0]
        limits = parse_limits(entry.limits)
        return from_annex_vi(cas, name, parsed.low, parsed.high, entry,
                             limits), parsed
    return from_codes(cas, name, parsed.low, parsed.high, codes), parsed


def build(rows, lines, spans, regulation: str, table) -> MixtureSection:
    """The mixture section for one document.

    `rows` carry a CAS number, a name, the codes and the concentration as
    printed - whether they came from the application or from Section 3.
    """
    if regulation not in IN_SCOPE:
        return MixtureSection(
            state="out_of_scope",
            message=f"Mixture check not yet available for {regulation}.")
    if table is None:
        return MixtureSection(state="skipped",
                              message="No Annex VI table on file.")
    if not rows:
        return MixtureSection(state="nothing", message=NO_COMPOSITION)

    index = table.by_cas()
    ingredients = []
    assumptions: list[str] = []
    without_concentration = 0
    for row in rows:
        ingredient, parsed = _ingredient(
            row.get("cas"), row.get("name"), row.get("concentration"),
            row.get("h_codes") or [], table, index)
        if ingredient is None:
            without_concentration += 1
            continue
        if parsed.assumption:
            assumptions.append(f"{ingredient.label}: {parsed.assumption}")
        ingredients.append(ingredient)

    if not ingredients:
        return MixtureSection(state="nothing", message=NO_CONCENTRATIONS)

    stated = stated_classes(lines, spans)
    results, summary = calculate(ingredients, stated, regulation)
    counts = {
        "inconsistent": sum(1 for r in results if r.verdict == "inconsistent"),
        "cannot_tell": sum(1 for r in results if r.verdict == "cannot_tell"),
        "consistent": sum(1 for r in results if r.verdict == "consistent"),
        "not_calculated": sum(1 for r in results if r.verdict == "not_calculated"),
        "ingredients": len(ingredients),
    }
    if without_concentration:
        assumptions.append(
            f"{without_concentration} ingredient(s) had no concentration and "
            "were left out of the calculation")
    return MixtureSection(
        state="calculated", counts=counts,
        declared_total=summary.get("declared_total", "0"),
        undisclosed=summary.get("undisclosed", "0"),
        stated=[str(c) for c in stated],
        assumptions=assumptions,
        results=[_as_dict(r) for r in results])


def _as_dict(result) -> dict:
    return {
        "verdict": result.verdict, "hazard_class": result.hazard_class,
        "citation": result.citation, "stated": result.stated,
        "calculated_low": result.calculated_low,
        "calculated_high": result.calculated_high,
        "message": result.message, "contributions": result.contributions,
        "assumptions": result.assumptions, "trace": result.trace,
    }


def rows_from_app(ingredients) -> list[dict]:
    return [{"cas": i.cas, "name": i.name, "h_codes": i.h_codes,
             "concentration": i.concentration} for i in ingredients]


def rows_from_pdf(ingredients) -> list[dict]:
    return [{"cas": i.cas, "name": None, "h_codes": i.h_codes,
             "concentration": i.concentration} for i in ingredients]


def worst(section: MixtureSection | None) -> str | None:
    if section is None or not section.counts:
        return None
    if section.counts.get("inconsistent"):
        return "inconsistent"
    if section.counts.get("cannot_tell"):
        return "cannot_tell"
    return "consistent" if section.counts.get("consistent") else None
