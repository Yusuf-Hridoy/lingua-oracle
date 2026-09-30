"""C-15: the sheet uses a code from a later GHS edition than the regulation has.

The regulation's source was parsed in full and does not contain this code, but a
later GHS edition on file does. So the wording is not wrong in itself - it is
simply ahead of the regulation the sheet claims to follow. EU CLP has no P317
family; a sheet citing P317 on a CLP label is using GHS Rev.8 wording that CLP
has not adopted.

Whether that is acceptable is a compliance decision, not a technical one, so the
severity comes from the registry (`newer_ghs_wording`, default warn).

A code no edition on file defines at all is a different matter and fails: it is
either a typo or not a code.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.checks.missing_source import Reason, classify
from lingua_oracle.models import Finding, Severity, Tier

CHECK_ID = "C-15"
TITLE = "Codes belong to the revision this regulation has adopted"

_SEVERITY = {"warn": Severity.WARN, "info": Severity.INFO, "fail": Severity.FAIL}


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for hit in ctx.hits:
        if not hit.code or hit.code in seen or ctx.entry(hit.code) is not None:
            continue
        seen.add(hit.code)
        missing = classify(hit.code, ctx.reference.key_status,
                           ctx.reference.entries, ctx.regulation.id)
        section = ctx.section_for(hit)

        if missing.reason is Reason.UNKNOWN:
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=Severity.FAIL, section=section,
                    page=hit.page, code=hit.code, found=hit.text or hit.code,
                    tier=Tier.C,
                    message=(
                        f"'{hit.code}' is not a code in any GHS edition on file, "
                        "nor in this regulation. Check it for a typo."
                    ),
                )
            )
            continue

        if missing.reason is not Reason.NEWER_GHS:
            continue  # our own gap; A-02/A-03/A-04 report it as not checked

        severity = _SEVERITY[ctx.regulation.newer_ghs_wording]
        message = (
            f"{hit.code} is {missing.edition} wording, which "
            f"{ctx.regulation.display_name} has not adopted."
        )
        if missing.nearest_code:
            message += (
                f" The closest statement {ctx.regulation.display_name} does "
                f"publish is {missing.nearest_code}."
            )
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=severity, section=section,
                page=hit.page, code=hit.code,
                expected=missing.nearest_text or "",
                found=hit.text or hit.code, tier=Tier.C, message=message,
            )
        )
    return findings
