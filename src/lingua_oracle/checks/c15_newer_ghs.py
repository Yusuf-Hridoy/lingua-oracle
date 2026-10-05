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
from lingua_oracle.match.template import MatchKind, match
from lingua_oracle.models import Finding, Severity, StatementVerdict, Tier

CHECK_ID = "C-15"
TITLE = "Codes belong to the revision this regulation has adopted"

_SEVERITY = {"warn": Severity.WARN, "info": Severity.INFO, "fail": Severity.FAIL}


def _wording_note(edition: str, result) -> str:
    """How close the sheet's text is to the edition's, without overstating it.

    "Matches GHS Rev.7 wording exactly" is a claim, and it was being made for a
    sheet that differed in capital letters or a full stop. Those are fine, and
    saying so is fine - saying they are not there is not.
    """
    if result.kind in (MatchKind.EXACT, MatchKind.TEMPLATE):
        return f"Matches {edition} wording exactly"
    return f"Matches {edition} wording except punctuation/capital letters"


def _blanks(ctx: CheckContext, check_id: str, hit, expected: str,
            result) -> tuple[bool, list[Finding]]:
    """Split a match's fill-ins into values and placeholders left unfilled.

    The same rule A-02/A-03 use. A slot still holding "…" is not something the
    author filled in, it is something they have not done yet, and the report has
    a card for exactly that.
    """
    unfilled = False
    findings: list[Finding] = []
    for value in result.fillins:
        blank = "\u2026" in value
        unfilled = unfilled or blank
        findings.append(
            Finding(
                check_id=check_id,
                severity=Severity.WARN if blank else Severity.INFO,
                section=hit.section if hasattr(hit, "section") else None,
                page=hit.page, code=hit.code, expected=expected, found=hit.text,
                tier=Tier.C,
                message=(
                    "Not filled in - the document still shows '\u2026' where a "
                    "value belongs."
                    if blank
                    else f"Filled in: '{value}' - check it is appropriate."
                ),
            )
        )
    return unfilled, findings


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
                           ctx.reference.entries, ctx.regulation.id,
                           ctx.regulation.ghs_edition)
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

        if missing.reason is Reason.DELETED:
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=Severity.FAIL, section=section,
                    page=hit.page, code=hit.code, found=hit.text or hit.code,
                    tier=Tier.C,
                    message=(
                        f"{hit.code} was deleted in {missing.edition}. "
                        f"{ctx.regulation.display_name} no longer has this code."
                    ),
                )
            )
            ctx.record(StatementVerdict(
                code=hit.code, status="wrong", found=hit.text or "",
                source=f"{missing.edition} Annex 3",
                why=f"{hit.code} was deleted in {missing.edition}; "
                    f"{ctx.regulation.display_name} no longer has this code.",
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
        source = (f"{missing.edition}, Annex 3 — GHS wording, outside "
                  f"{where}'s scope" if outside
                  else f"{missing.edition}, Annex 3")
        if result is not None and result.matched and outside:
            # The regulation does not cover this code, and the sheet's wording
            # is GHS's own. Extra information, correctly worded - not something
            # anyone has to act on, so it belongs in the list of statements that
            # match rather than in the issues or the what-to-do list.
            unfilled, blank_findings = _blanks(ctx, CHECK_ID, hit, against, result)
            findings.extend(blank_findings)
            ctx.record(StatementVerdict(
                code=hit.code,
                status="check" if unfilled or result.fillins else "correct",
                blank_unfilled=unfilled,
                found=hit.text,
                expected=against, source=f"{missing.edition}, Annex 3",
                why=("The wording is correct, but a blank was never filled in: "
                     "the document still shows the placeholder."
                     if unfilled else f"{_wording_note(missing.edition, result)}."),
                match_note=(f"{_wording_note(missing.edition, result)}; outside "
                            f"{where}'s scope, allowed as extra information"),
                section=section, page=hit.page,
                fillins=[v for v in result.fillins if "\u2026" not in v],
            ))
            continue

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
            # The right-hand column shows the regulation's own nearest
            # statement where it has one - that is what a reader would use
            # instead. The edition's text is what the sheet already matches, so
            # it goes under the document's own text as a note.
            unfilled, blank_findings = _blanks(ctx, CHECK_ID, hit,
                                              missing.nearest_text or against,
                                              result)
            findings.extend(blank_findings)
            ctx.record(StatementVerdict(
                code=hit.code, status="check", found=hit.text,
                blank_unfilled=unfilled,
                expected=missing.nearest_text or against,
                nearest_code=missing.nearest_code,
                match_note=_wording_note(missing.edition, result),
                source=source,
                why=(
                    f"Correct {missing.edition} wording, but {where} has not "
                    f"adopted {hit.code}. Ask whether that\u2019s accepted; if "
                    f"not, use {missing.nearest_code}."
                    if missing.nearest_code else
                    f"Correct {missing.edition} wording, but {where} has not "
                    f"adopted {hit.code} and has no equivalent statement. "
                    f"Ask whether that\u2019s accepted."
                ),
                section=section, page=hit.page,
                fillins=[v for v in result.fillins if "\u2026" not in v],
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
