"""B-09: Section 2 and the label must agree, when both are present."""

from __future__ import annotations

from lingua_oracle.checks.a01_signal_word import _candidates as signal_candidates
from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.sections import LABEL
from lingua_oracle.models import Finding, Severity

CHECK_ID = "B-09"
TITLE = "Section 2 and label show the same signal word and statements"


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    names = {span.name for span in ctx.spans}
    if LABEL not in names or "2" not in names:
        return []  # only meaningful when both are present

    section2 = {h.code for h in ctx.hits_in("2")}
    label = {h.code for h in ctx.hits_in(LABEL)}
    # A block that names a label but lists no codes is boilerplate, not label
    # artwork. Comparing against it would report every Section 2 code as missing.
    if not label or not section2:
        return []
    findings: list[Finding] = []

    for code in sorted(section2 - label):
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, section="2", code=code,
                message=f"{code} appears in Section 2 but not on the label.",
            )
        )
    for code in sorted(label - section2):
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, section=LABEL, code=code,
                message=f"{code} appears on the label but not in Section 2.",
            )
        )

    words = {value.casefold() for value, _page in signal_candidates(ctx)}
    if len(words) > 1:
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, code="SIGNAL",
                found=" / ".join(sorted(words)),
                message="The document states more than one signal word.",
            )
        )
    return findings
