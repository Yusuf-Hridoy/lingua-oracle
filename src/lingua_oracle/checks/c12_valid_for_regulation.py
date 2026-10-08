"""C-12: every phrase used must be valid for the chosen regulation.

EUH codes belong to EU/UK CLP, AUH codes to Australia. Seeing either on an OSHA
document means the wrong source was used.

H303, H313 and H333 are acute toxicity Category 5, which only some
regulations have. Where the regulation's own acute toxicity table stops at
Category 4 (data/acute_toxicity/), the code is outside its classification:
said as a note, with the place the regulation shows it - not a fault, since
the GHS allows it, and not a classification the mixture is judged on.
"""

from __future__ import annotations

import re

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.codes import split_combined
from lingua_oracle.mixture import acute_table
from lingua_oracle.mixture.classes import ACUTE_CODES
from lingua_oracle.models import Finding, Severity

CHECK_ID = "C-12"
TITLE = "Every statement belongs to this regulation"

_PREFIX_RE = re.compile(r"^(EUH|AUH|H|P)")


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    allowed = set(ctx.regulation.allowed_prefixes)
    findings: list[Finding] = []
    reported: set[str] = set()
    for hit in ctx.hits:
        m = _PREFIX_RE.match(hit.code)
        if not m:
            continue
        prefix = m.group(1)
        if prefix in allowed or hit.code in reported:
            continue
        reported.add(hit.code)
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL,
                section=ctx.section_for(hit), page=hit.page, code=hit.code,
                found=hit.text or hit.code,
                message=(
                    f"{hit.code} uses the '{prefix}' family, which is not valid for "
                    f"{ctx.regulation.display_name} "
                    f"(allowed: {', '.join(sorted(allowed))})."
                ),
            )
        )
    return findings + _category_5(ctx)


def _category_5(ctx: CheckContext) -> list[Finding]:
    rules = acute_table.load(ctx.regulation.id)
    where = rules.without_category_5() if rules else None
    if where is None:
        return []
    findings: list[Finding] = []
    reported: set[str] = set()
    for hit in ctx.hits:
        for code in split_combined(hit.code):
            if code in reported or ACUTE_CODES.get(code, ("", ()))[1] != ("5",):
                continue
            reported.add(code)
            findings.append(Finding(
                check_id=CHECK_ID, severity=Severity.INFO,
                section=ctx.section_for(hit), page=hit.page, code=code,
                message=(f"Category 5 is not part of {ctx.regulation.display_name}; "
                         f"this code is outside its classification ({where}).")))
    return findings
