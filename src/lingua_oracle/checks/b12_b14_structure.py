"""B-12 to B-14: the sheet's structure, by the regulation's own text.

The structure is read once by `structure/reader.py` against
data/sds_structure/<reg>.json, and each row that falls short becomes a
finding here, quoting the requirement and where the text states it:

* B-12 - the 16 sections: present, numbered, in order where the text states
  an order, and headed as the text words them;
* B-13 - sub-sections, where the text has them, and empty parts, where the
  text says what an empty part must do;
* B-14 - the objective items: telephone numbers, e-mail address, dates and
  page numbering, each where the text puts it.

A requirement in words that bind ("shall", "must") is a fault; one the text
only recommends ("should") is one to check.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.models import Finding, Severity
from lingua_oracle.structure.reader import ITEMS, SECTIONS, SUBSECTIONS


def _findings(ctx: CheckContext, check: str) -> list[Finding]:
    structure = ctx.structure
    if structure is None or structure.state != "checked" or ctx.is_label():
        return []
    rows = [(section.number, section.page, row) for section in structure.sections
            for row in section.rows]
    rows += [(None, None, row) for row in structure.document_rows]
    out: list[Finding] = []
    for number, page, row in rows:
        if row.check != check or row.status not in ("fix", "check"):
            continue
        where = f" {row.citation}: “{row.quote}”" if row.quote else ""
        out.append(Finding(
            check_id=check,
            severity=Severity.FAIL if row.status == "fix" else Severity.WARN,
            section=number, page=page,
            expected=row.expected or None, found=row.found or None,
            message=f"{row.text}{where}"))
    return out


@register(SECTIONS, "Every section is there, numbered, in order and headed as the text requires")
def sections(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, SECTIONS)


@register(SUBSECTIONS, "Every sub-section the text requires is there, and nothing is left blank")
def subsections(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, SUBSECTIONS)


@register(ITEMS, "The items the text requires are on the sheet, where it puts them")
def items(ctx: CheckContext) -> list[Finding]:
    return _findings(ctx, ITEMS)
