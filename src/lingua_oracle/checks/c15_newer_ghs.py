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
from lingua_oracle.match.template import match
from lingua_oracle.models import Finding, Severity, StatementVerdict, Tier

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
        if not hit.text:
            continue  # a bare code reference carries no wording to judge
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
            ctx.record(StatementVerdict(
                code=hit.code, status="wrong", found=hit.text or hit.code,
                why="This is not a code in any GHS edition on file, nor in "
                    "this regulation.",
                section=section, page=hit.page,
            ))
            continue

        if missing.reason not in (Reason.NEWER_GHS, Reason.OUTSIDE_SCOPE):
            continue  # our own gap; A-02/A-03/A-04 report it as not checked
        outside = missing.reason is Reason.OUTSIDE_SCOPE

        # The regulation has no text for this code, but the GHS edition that
        # introduced it does - so the wording CAN be checked, against that
        # edition. Saying only "not adopted" left a correct statement and a
        # garbled one looking identical, and left the code uncounted.
        severity = _SEVERITY[ctx.regulation.newer_ghs_wording]
        against = missing.edition_text
        result = match(hit.text or "", against,
                       optional_terminator=ctx.regulation
                       .statements_lack_terminal_punctuation) if hit.text and against else None

        where = ctx.regulation.display_name
        source = (f"{missing.edition} Annex 3 — GHS wording, outside "
                  f"{where}'s scope" if outside
                  else f"{missing.edition} Annex 3")
        if result is not None and result.matched:
            message = (
                f"{hit.code} is correct {missing.edition} wording. "
                f"{where} does not cover this code."
                if outside else
                f"{hit.code} is correct {missing.edition} wording, but {where} "
                "has not adopted it."
            )
            if missing.nearest_code:
                message += f" The closest statement {where} publishes is {missing.nearest_code}."
            else:
                message += f" There is no equivalent statement in {where}."
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=severity, section=section,
                    page=hit.page, code=hit.code,
                    expected=missing.nearest_text or against,
                    found=hit.text, tier=Tier.C, message=message,
                )
            )
            ctx.record(StatementVerdict(
                code=hit.code, status="check", found=hit.text,
                expected=against, source=source,
                why=(f"This is correct {missing.edition} wording. {where} "
                     f"does not cover this code, so it was checked against GHS."
                     if outside else
                     f"This is correct {missing.edition} wording, but {where} "
                     f"has not adopted this code."),
                section=section, page=hit.page, fillins=list(result.fillins),
            ))
            continue

        # It does not even match the edition it came from.
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, section=section,
                page=hit.page, code=hit.code, expected=against,
                found=hit.text, tier=Tier.C,
                message=(
                    f"{hit.code} does not match {missing.edition}'s wording. "
                    f"{where} does not cover this code, so GHS is the only "
                    "text available to check it against."
                    if outside else
                    f"{hit.code} does not match {missing.edition}'s wording "
                    f"either, and {where} has not adopted the code at all."
                ),
            )
        )
        ctx.record(StatementVerdict(
            code=hit.code, status="wrong", found=hit.text or "",
            expected=against, source=source,
            why=(f"{where} does not cover this code, and the text does not "
                 f"match {missing.edition} either."
                 if outside else
                 f"{where} has not adopted this code, and the text does not "
                 f"match {missing.edition} either."),
            section=section, page=hit.page,
        ))
    return findings
