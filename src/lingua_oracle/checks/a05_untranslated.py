"""A-05: English phrases left behind in a document that is not in English."""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.language import looks_untranslated
from lingua_oracle.models import Finding, Severity

CHECK_ID = "A-05"
TITLE = "English left behind in a non-English document"


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    if ctx.language.lower().split("-")[0] == "en":
        return []
    findings: list[Finding] = []
    for hit in ctx.hits:
        if not hit.text or not looks_untranslated(hit.text, ctx.language):
            continue
        entry = ctx.entry(hit.code)
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL,
                section=ctx.section_for(hit), page=hit.page, code=hit.code,
                expected=entry.text if entry else None, found=hit.text,
                tier=entry.tier if entry else None,
                message=(
                    f"{hit.code} reads as English in a \'{ctx.language}\' document; "
                    "it looks untranslated."
                ),
            )
        )
    return findings
