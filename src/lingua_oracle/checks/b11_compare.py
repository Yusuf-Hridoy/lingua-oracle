"""B-11: a translated copy must carry the same set of codes as its original."""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.models import Finding, Severity

CHECK_ID = "B-11"
TITLE = "The translated copy lists the same codes"


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    if ctx.compare_document is None:
        return []
    left = {hit.code for hit in ctx.hits}
    right = {hit.code for hit in ctx.compare_hits}
    other = ctx.compare_language or "the other document"

    findings: list[Finding] = []
    for code in sorted(left - right):
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, code=code,
                message=f"{code} is in this document but missing from {other}.",
            )
        )
    for code in sorted(right - left):
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, code=code,
                message=f"{code} is in {other} but missing from this document.",
            )
        )
    return findings
