"""C-16 to C-20: section against section, by the regulation's own text.

Read once by `consistency/runner.py`; each row that falls short becomes a
finding here, quoting the requirement and where its text states it.

* C-16 - label elements (signal word, hazard statements, pictograms)
  against the classification;
* C-17 - Section 9's flash point and boiling point against a flammable
  liquid classification;
* C-18 - Section 11's data on the mixture as a whole against its acute
  toxicity classification;
* C-19 - Section 12's data on the mixture as a whole against its aquatic
  classification;
* C-20 - product name and revision date, the sheet against itself.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.models import Finding, Severity

_SEVERITY = {"fix": Severity.FAIL, "check": Severity.WARN, "info": Severity.INFO}


def _findings(ctx: CheckContext, check: str) -> list[Finding]:
    out = []
    for row in ctx.consistency or []:
        if row.check != check or row.status not in _SEVERITY:
            continue
        where = f" {row.citation}: “{row.quote}”" if row.quote else (
            f" ({row.citation})" if row.citation else "")
        out.append(Finding(check_id=check, severity=_SEVERITY[row.status], section=row.section,
                           expected=row.expected or None, found=row.found or None,
                           message=f"{row.text}{where}"))
    return out


@register("C-16", "Label elements fit the classification")
def label_elements(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-16")


@register("C-17", "Section 9's flash point fits the flammable-liquid classification")
def flammability(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-17")


@register("C-18", "Section 11's data on the mixture fits its acute toxicity classification")
def acute_data(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-18")


@register("C-19", "Section 12's data on the mixture fits its aquatic classification")
def aquatic_data(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-19")


@register("C-20", "Product name and revision date are the same throughout")
def document_consistency(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-20")


@register("C-21", "Section 14 agrees with the dangerous goods list")
def transport(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-21")


@register("C-22", "Candidate List substances are named where REACH Annex II requires")
def candidate_list(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-22")


@register("C-23", "Section 14's transport class fits the product's state and flash point")
def transport_class(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-23")


@register("C-24", "Section 14 gives the fields its regulation requires with a UN number")
def transport_fields(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-24")


@register("C-25", "Section 9 states the physical state")
def physical_state(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, "C-25")
