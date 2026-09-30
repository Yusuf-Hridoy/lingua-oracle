"""A-02, A-03, A-04: statement wording must match the official text.

The three checks share one comparison and differ only in which codes they own:
A-02 hazard (H, including combined H codes), A-03 precautionary (P, including
combined P codes), A-04 supplemental (EUH/AUH).

Codes with no reference text are tier C: no wording verdict is possible, so they
are recorded as unverified and left to the consistency check C-02.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.match.template import MatchKind, match
from lingua_oracle.models import Finding, Severity, Tier


def _prefix_of(code: str) -> str:
    if code.startswith(("EUH", "AUH")):
        return "supplemental"
    if code.startswith("H"):
        return "hazard"
    if code.startswith("P"):
        return "precautionary"
    return "other"


def _run_for(ctx: CheckContext, check_id: str, family: str) -> list[Finding]:
    findings: list[Finding] = []
    for hit in ctx.hits:
        if _prefix_of(hit.code) != family:
            continue
        if not hit.text:
            continue  # a bare code reference, e.g. in Section 3; B-08 covers that
        entry = ctx.entry(hit.code)
        section = ctx.section_for(hit)
        if entry is None:
            findings.append(
                Finding(
                    check_id=check_id, severity=Severity.WARN, section=section,
                    page=hit.page, code=hit.code, found=hit.text, tier=Tier.C,
                    unverified=True,
                    message=(
                        f"No reference text for {hit.code} in "
                        f"{ctx.regulation.display_name} '{ctx.language}' "
                        "(tier C): wording not verified."
                    ),
                )
            )
            continue

        loose_end = ctx.regulation.statements_lack_terminal_punctuation
        result = match(hit.text, entry.text, optional_terminator=loose_end)
        if not result.matched:
            # A regulation may require several languages in one document, and a
            # phrase only has to be correct in the language it is written in.
            for other_language, other in ctx.alternate_entries(hit.code):
                other_result = match(hit.text, other.text, optional_terminator=loose_end)
                if other_result.matched:
                    result, entry = other_result, other
                    findings.append(
                        Finding(
                            check_id=check_id, severity=Severity.INFO, section=section,
                            page=hit.page, code=hit.code, expected=other.text,
                            found=hit.text, tier=other.tier,
                            message=f"{hit.code} is in '{other_language}', which "
                                    f"{ctx.regulation.display_name} also requires.",
                        )
                    )
                    break
        if result.kind in (MatchKind.EXACT, MatchKind.TEMPLATE) and result.matched:
            for value in result.fillins:
                findings.append(
                    Finding(
                        check_id=check_id, severity=Severity.INFO, section=section,
                        page=hit.page, code=hit.code, expected=entry.text,
                        found=hit.text, tier=entry.tier,
                        message=f"Fill-in value '{value}' needs human review.",
                    )
                )
            continue
        if result.matched:
            findings.append(
                Finding(
                    check_id=check_id, severity=Severity.WARN, section=section,
                    page=hit.page, code=hit.code, expected=entry.text, found=hit.text,
                    tier=entry.tier, message=f"{hit.code} {result.message}.",
                )
            )
            continue
        findings.append(
            Finding(
                check_id=check_id, severity=Severity.FAIL, section=section,
                page=hit.page, code=hit.code, expected=entry.text, found=hit.text,
                tier=entry.tier,
                message=f"{hit.code} wording does not match the official text.",
            )
        )
    return findings


def _internal_statements(ctx: CheckContext, check_id: str) -> list[Finding]:
    """Recognise hazards the regulation defines without giving them a code.

    OSHA's combustible dust and simple asphyxiant statements have no H code, so
    no code hit points at them. They are found by matching the document's own
    lines against the stored wording instead.
    """
    if not ctx.internal_entries():
        return []
    findings: list[Finding] = []
    seen: set[str] = set()
    for line in ctx.document.lines:
        text = line.text.strip()
        if len(text) < 20:
            continue
        found = ctx.match_internal(text)
        if found is None:
            continue
        entry, result = found
        if entry.code in seen:
            continue
        seen.add(entry.code)
        findings.append(
            Finding(
                check_id=check_id, severity=Severity.INFO, page=line.page,
                code=entry.code, expected=entry.text, found=text, tier=entry.tier,
                message=(
                    f"Matched {ctx.regulation.display_name}'s '{entry.code}' by wording. "
                    "That is an internal identifier of this tool, not a regulatory "
                    "code: this hazard class has no GHS code."
                )
                + ("" if result.is_clean else f" Note: {result.message}."),
            )
        )
    return findings


@register("A-02", "H-statement text matches key (incl. combined H codes)")
def run_a02(ctx: CheckContext) -> list[Finding]:
    return _run_for(ctx, "A-02", "hazard") + _internal_statements(ctx, "A-02")


@register("A-03", "P-statement text matches key (incl. combined P codes)")
def run_a03(ctx: CheckContext) -> list[Finding]:
    return _run_for(ctx, "A-03", "precautionary")


@register("A-04", "Supplemental statements (EUH/AUH) match key")
def run_a04(ctx: CheckContext) -> list[Finding]:
    return _run_for(ctx, "A-04", "supplemental")
