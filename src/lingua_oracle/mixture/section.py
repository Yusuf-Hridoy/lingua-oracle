"""The mixture half of one upload: build it from whatever composition we have."""

from __future__ import annotations

from decimal import Decimal

from lingua_oracle.mixture import concentration as conc
from lingua_oracle.mixture.calculate import calculate, in_scope
from lingua_oracle.mixture.classes import parse_class
from lingua_oracle.mixture.limits import parse as parse_limits
from lingua_oracle.mixture.model import from_annex_vi, from_codes
from lingua_oracle.mixture.state import physical_state
from lingua_oracle.mixture.stated import stated_classes
from lingua_oracle.models import MixtureSection

NO_COMPOSITION = ("No composition to calculate from: this sheet prints no "
                  "ingredients with concentrations.")
NO_CONCENTRATIONS = "Can't calculate: Section 3 gives no concentrations."
NO_CLASSIFIED = ("Can't calculate: no ingredient with a concentration has a "
                 "classification on the sheet or in the list.")


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


def display_name(regulation: str) -> str:
    """A regulation's display name. Its id is a database key, not a word."""
    from lingua_oracle.registry import load_registry

    try:
        return load_registry().get(regulation).display_name
    except KeyError:
        return regulation


def build(rows, lines, spans, regulation: str, table,
          stated_override: list[str] | None = None,
          state_override: str | None = None, *,
          upcoming=None, on=None) -> MixtureSection:
    """The mixture section for one document.

    `rows` carry a CAS number, a name, the codes and the concentration as
    printed - whether they came from the application or from Section 3.

    `upcoming` is the list's adopted amendment that does not apply yet. From
    its date on, the amended table is the one calculated with. Before it, the
    calculation is made with both where the amendment touches an ingredient: a
    hazard family consistent with either passes, and whatever the amendment
    changes is said, with its date.
    """
    from lingua_oracle.substances.upcoming import today

    on = on or today()
    if upcoming is not None and upcoming.binding_on(on):
        return _build(rows, lines, spans, regulation, upcoming.table,
                      stated_override, state_override)
    section = _build(rows, lines, spans, regulation, table,
                     stated_override, state_override)
    touched = upcoming is not None and section.state == "calculated" and any(
        (row.get("cas") or "").strip() in upcoming.changed_cas for row in rows)
    if not touched:
        return section
    later = _build(rows, lines, spans, regulation, upcoming.table,
                   stated_override, state_override)
    return _reconcile(section, later, upcoming)


def _family(result: dict) -> str:
    return result.get("family") or str(result.get("hazard_class") or "")


def _reconcile(now: MixtureSection, later: MixtureSection,
               upcoming) -> MixtureSection:
    """One section from the calculation in force and the amended one."""
    amended = {_family(r): r for r in later.results}
    results: list[dict] = []
    notes: list[str] = []
    for result in now.results:
        family = _family(result)
        alt = amended.pop(family, None)
        meets_amended = alt["verdict"] == "consistent" if alt else True
        if result["verdict"] == "inconsistent" and meets_amended:
            # The amended calculation either agrees with Section 2 or does not
            # raise this family at all - which, with nothing stated, is
            # agreement too.
            if alt is not None:
                results.append(alt)
            notes.append(
                f"{family}: consistent with Annex VI as amended by the "
                f"{upcoming.short}, which applies from {upcoming.when} and may "
                "be followed now.")
            continue
        if alt is None:
            results.append(result)
            notes.append(
                f"From {upcoming.when} ({upcoming.short}): {family} - the "
                "calculation no longer raises it.")
            continue
        results.append(result)
        if (alt["verdict"] != result["verdict"]
                or alt.get("calculated_class") != result.get("calculated_class")):
            notes.append(
                f"From {upcoming.when} ({upcoming.short}): {family} - the "
                f"calculation gives {alt.get('calculated_class') or 'no classification'}"
                f", {alt['verdict'].replace('_', ' ')} with Section 2.")
    for family, alt in amended.items():
        notes.append(
            f"From {upcoming.when} ({upcoming.short}): {family} - the "
            f"calculation gives {alt.get('calculated_class') or 'no classification'}"
            f", {alt['verdict'].replace('_', ' ')} with Section 2.")
    counts = dict(now.counts)
    for verdict in ("inconsistent", "cannot_tell", "consistent", "not_calculated"):
        counts[verdict] = sum(1 for r in results if r["verdict"] == verdict)
    return now.model_copy(update={"results": results, "counts": counts,
                                  "upcoming": notes})


def _build(rows, lines, spans, regulation: str, table,
           stated_override: list[str] | None = None,
           state_override: str | None = None) -> MixtureSection:
    """The calculation against one table."""
    # Read first and keep, whatever happens next: a re-run after the reader
    # picks a product must not need the uploaded file back.
    stated = ([parse_class(c) for c in stated_override] if stated_override
              else stated_classes(lines, spans))
    stated_names = [str(c) for c in stated if c]
    # Section 9's answer is kept for the same reason: two of the sensitisation
    # limits turn on it, and a re-run must not need the file back to know it.
    state = state_override or physical_state(lines, spans)

    if not in_scope(regulation):
        return MixtureSection(
            state="out_of_scope", stated=stated_names,
            physical_state=state or "",
            message="Mixture check not available for "
                    f"{display_name(regulation)} yet: no document on file "
                    "sets its mixture rules.")
    if table is None:
        return MixtureSection(state="skipped", stated=stated_names,
            physical_state=state or "",
                              message="No Annex VI table on file.")
    if not rows:
        return MixtureSection(state="nothing", stated=stated_names,
            physical_state=state or "",
                              message=NO_COMPOSITION)

    index = table.by_cas()
    ingredients = []
    assumptions: list[str] = []
    without_concentration = 0
    #: Ingredients whose concentration is known and whose classification is
    #: not - water, say. They are declared, so they count towards the total
    #: and are not undisclosed; no rule can use them, and that is said.
    unknown: list[tuple[str, object]] = []
    #: Every ingredient with a concentration, whatever it is classified as:
    #: acute toxicity is summed over all of them, H302-only ones included.
    every: list = []
    for row in rows:
        ingredient, parsed = _ingredient(
            row.get("cas"), row.get("name"), row.get("concentration"),
            row.get("h_codes") or [], table, index)
        if ingredient is None:
            without_concentration += 1
            continue
        if parsed.assumption:
            assumptions.append(f"{ingredient.label}: {parsed.assumption}")
        every.append(ingredient)
        if not ingredient.classes:
            unknown.append((ingredient.label, ingredient.high))
            continue
        ingredients.append(ingredient)

    from lingua_oracle.mixture import acute
    from lingua_oracle.mixture.classes import ACUTE_CODES

    acute_data = any(c.upper() in ACUTE_CODES for i in every for c in i.h_codes) or any(
        i.limits and i.limits.ates for i in every)
    if not ingredients and not acute_data:
        # Plain words for why: the sheet gives no concentrations at all, or
        # gives them only for ingredients nothing is known about.
        return MixtureSection(
            state="cannot_calculate", stated=stated_names,
            physical_state=state or "",
            message=(NO_CONCENTRATIONS if without_concentration == len(rows)
                     else NO_CLASSIFIED))

    # Every range Section 3 gives, unclassified ingredients included: what is
    # undisclosed is what the upper bounds leave of 100 %, and no more.
    declared = (sum((i.high for i in ingredients), Decimal(0))
                + sum((high for _, high in unknown), Decimal(0)))
    from lingua_oracle.mixture import section_eleven

    eleven = section_eleven.read(lines, [(i.cas, i.name) for i in every if i.cas])
    entries = {}
    for i in every:
        found = index.get((i.cas or "").strip(), []) if i.cas else []
        if len(found) == 1:
            entries[i.cas.strip()] = found[0]
    acute_inputs = {"ingredients": every, "entries": entries,
                    "section_11": eleven.by_cas,
                    "unknown": acute.unknown_share(lines)}
    from lingua_oracle.mixture.stated import justifications

    results, summary = calculate(ingredients, stated, regulation, state,
                                 declared=declared, acute_inputs=acute_inputs,
                                 justification=justifications(lines, spans))
    if eleven.mixture:
        assumptions.append("Section 11 gives for the mixture itself: "
                           + "; ".join(eleven.mixture))
    for line in eleven.ignored:
        assumptions.append(f"Section 11, not used: {line}")
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
    if unknown:
        total = sum((high for _, high in unknown), Decimal(0))
        assumptions.append(
            f"{len(unknown)} ingredient(s), up to {total} % between them, have no "
            "classification on the sheet and none in the list this regulation "
            "uses, so no rule can use them; they are declared, and count "
            "towards the total, not towards the undisclosed part: "
            + ", ".join(label for label, _ in unknown))
    not_covered = summary.get("not_covered") or []
    if not_covered:
        assumptions.append(
            f"{display_name(regulation)} does not have these hazard classes, "
            f"so nothing was calculated for them: {', '.join(not_covered)}")
    return MixtureSection(
        state="calculated", counts=counts,
        declared_total=summary.get("declared_total", "0"),
        undisclosed=summary.get("undisclosed", "0"),
        stated=stated_names,
        physical_state=state or "",
        source_document=summary.get("document", ""),
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
        "family": result.family, "stated_class": result.stated_class,
        "calculated_class": result.calculated_class,
        "implied_from": result.implied_from,
        "justification": result.justification,
    }


def rows_from_app(ingredients) -> list[dict]:
    return [{"cas": i.cas, "name": i.name, "h_codes": i.h_codes,
             "concentration": i.concentration} for i in ingredients]


def rows_from_pdf(ingredients) -> list[dict]:
    return [{"cas": i.cas, "name": getattr(i, "name", None), "h_codes": i.h_codes,
             "concentration": i.concentration} for i in ingredients]


def worst(section: MixtureSection | None) -> str | None:
    if section is None or not section.counts:
        return None
    if section.counts.get("inconsistent"):
        return "inconsistent"
    if section.counts.get("cannot_tell"):
        return "cannot_tell"
    return "consistent" if section.counts.get("consistent") else None
