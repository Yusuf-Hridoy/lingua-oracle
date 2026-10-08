"""B-08: every H code Section 2 uses - and Section 3, where it prints codes -
has its full text in Section 16.

Section 16 writes out the hazard statements the sheet relies on. Section 2 is
where the sheet states them; Section 3 is where an ingredient's codes are
printed. A Section 3 code not written out in Section 16 is missing from the
sheet altogether - Section 3 prints it bare - and is a fault. A Section 2 code
missing from Section 16 is written out once already, in Section 2, so it is
one to check rather than a fault. A code written out in Section 16 and used in
neither is said, as information - it may belong to an ingredient whose codes
Section 3 omits.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.codes import split_combined
from lingua_oracle.models import Finding, Severity

CHECK_ID = "B-08"
TITLE = "Every hazard code in Sections 2 and 3 is written out in Section 16"


def _h_codes(hits) -> dict[str, object]:
    out: dict[str, object] = {}
    for hit in hits:
        if not hit.code.startswith("H"):
            continue
        for code in split_combined(hit.code):
            out.setdefault(code, hit)
    return out


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    if ctx.is_label() or not any(span.name == "16" for span in ctx.spans):
        return []
    used = {"2": _h_codes(ctx.hits_in("2")), "3": _h_codes(ctx.hits_in("3"))}
    if not used["2"] and not used["3"]:
        return []
    section16 = ctx.hits_in("16")
    spelled_out = {h.code for h in section16 if h.text} | {
        part for h in section16 if h.text for part in split_combined(h.code)}

    findings: list[Finding] = []
    reported: set[str] = set()
    for section in ("3", "2"):
        for code, hit in used[section].items():
            if code in spelled_out or code in reported:
                continue
            reported.add(code)
            entry = ctx.entry(code)
            findings.append(Finding(
                check_id=CHECK_ID,
                severity=Severity.FAIL if section == "3" else Severity.WARN,
                section="16", page=hit.page, code=code,
                expected=entry.text if entry else None,
                tier=entry.tier if entry else None,
                message=(f"{code} is used in Section {section} but its full text "
                         "is missing from Section 16.")))
    elsewhere = set(used["2"]) | set(used["3"])
    for hit in section16:
        for code in split_combined(hit.code):
            if (code.startswith("H") and hit.text and code not in elsewhere
                    and code not in reported):
                reported.add(code)
                findings.append(Finding(
                    check_id=CHECK_ID, severity=Severity.INFO, section="16",
                    page=hit.page, code=code,
                    message=(f"{code} is written out in Section 16 and used in "
                             "neither Section 2 nor Section 3.")))
    return findings
