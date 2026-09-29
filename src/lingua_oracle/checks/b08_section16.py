"""B-08: every H-code used in Section 3 must have its full text in Section 16."""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.codes import split_combined
from lingua_oracle.models import Finding, Severity

CHECK_ID = "B-08"
TITLE = "Every H-code in Section 3 has full text in Section 16"


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    if ctx.is_label():
        return []
    section3 = ctx.hits_in("3")
    section16 = ctx.hits_in("16")
    if not section3 or not any(span.name == "16" for span in ctx.spans):
        return []

    spelled_out = {
        h.code for h in section16 if h.text
    } | {
        part for h in section16 if h.text for part in split_combined(h.code)
    }

    findings: list[Finding] = []
    reported: set[str] = set()
    for hit in section3:
        if not hit.code.startswith("H"):
            continue
        for code in split_combined(hit.code):
            if code in spelled_out or code in reported:
                continue
            reported.add(code)
            entry = ctx.entry(code)
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=Severity.FAIL, section="3",
                    page=hit.page, code=code,
                    expected=entry.text if entry else None,
                    tier=entry.tier if entry else None,
                    message=(
                        f"{code} is used in Section 3 but its full text is missing "
                        "from Section 16."
                    ),
                )
            )
    return findings
