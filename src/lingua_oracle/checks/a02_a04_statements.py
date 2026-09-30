"""A-02, A-03, A-04: statement wording must match the official text.

The three checks share one comparison and differ only in which codes they own:
A-02 hazard (H, including combined H codes), A-03 precautionary (P, including
combined P codes), A-04 supplemental (EUH/AUH).

Codes with no reference text are tier C: no wording verdict is possible, so they
are recorded as unverified and left to the consistency check C-02.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.checks.missing_source import Reason, classify
from lingua_oracle.match.template import MatchKind, match
from lingua_oracle.models import Finding, Severity, StatementVerdict, Tier


def _prefix_of(code: str) -> str:
    if code.startswith(("EUH", "AUH")):
        return "supplemental"
    if code.startswith("H"):
        return "hazard"
    if code.startswith("P"):
        return "precautionary"
    return "other"


def _source_of(ctx: CheckContext, entry) -> str:
    """Where this wording came from, as a reader would cite it."""
    where = entry.source_ref or ctx.regulation.authority or ""
    return f"{ctx.regulation.display_name} — {where}" if where else ctx.regulation.display_name


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
            # Three reasons a code has no reference text, and only one of them
            # is ours. C-15 owns the other two - a code from a later GHS
            # edition, and a code that exists nowhere - so reporting them here
            # as well would say the same thing twice in different words.
            missing = classify(hit.code, ctx.reference.key_status,
                               ctx.reference.entries, ctx.regulation.id)
            if missing.reason is not Reason.NOT_ON_FILE:
                continue
            findings.append(
                Finding(
                    check_id=check_id, severity=Severity.WARN, section=section,
                    page=hit.page, code=hit.code, found=hit.text, tier=Tier.C,
                    unverified=True,
                    message=(
                        f"Not checked: we hold no official "
                        f"{ctx.regulation.display_name} wording for {hit.code} "
                        f"in '{ctx.language}'. Our records are incomplete for "
                        "this regulation; this is not a finding about the sheet."
                    ),
                )
            )
            ctx.record(StatementVerdict(
                code=hit.code, status="not_checked", found=hit.text,
                why=f"We hold no official {ctx.regulation.display_name} wording "
                    f"for {hit.code}, so it could not be compared.",
                section=section, page=hit.page,
            ))
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
        # A filled-in slot is always shown, whatever else the comparison said.
        # The official text only says a value belongs here, never which value is
        # right, so no automatic verdict can cover it and it must not be hidden
        # behind a clean pass.
        unfilled = False
        for value in result.fillins:
            blank = value.strip() in ("…", "...")
            unfilled = unfilled or blank
            findings.append(
                Finding(
                    check_id=check_id, severity=Severity.WARN if blank else Severity.INFO,
                    section=section, page=hit.page, code=hit.code, expected=entry.text,
                    found=hit.text, tier=entry.tier,
                    message=(
                        "Not filled in - the document still shows '…' where a value "
                        "belongs."
                        if blank
                        else f"Filled in: '{value}' - check it is appropriate."
                    ),
                )
            )
        if result.kind in (MatchKind.EXACT, MatchKind.TEMPLATE) and result.matched:
            # The wording is right, but a slot someone filled in - or left
            # empty - still needs a person. Filing those under "correct" would
            # collapse them into a line nobody opens.
            if unfilled:
                why = ("The wording is correct, but a blank was never filled "
                       "in: the document still shows the placeholder.")
            elif result.fillins:
                why = "The wording is correct. Check the text you filled in."
            else:
                why = "Matches the official wording."
            ctx.record(StatementVerdict(
                code=hit.code,
                status="check" if result.fillins else "correct",
                found=hit.text, expected=entry.text, source=_source_of(ctx, entry),
                why=why, section=section, page=hit.page,
                fillins=[v for v in result.fillins if v.strip() not in ("…", "...")],
            ))
            continue
        if result.matched:
            findings.append(
                Finding(
                    check_id=check_id, severity=Severity.WARN, section=section,
                    page=hit.page, code=hit.code, expected=entry.text, found=hit.text,
                    tier=entry.tier, message=f"{hit.code} {result.message}.",
                )
            )
            ctx.record(StatementVerdict(
                code=hit.code, status="check", found=hit.text, expected=entry.text,
                source=_source_of(ctx, entry),
                why=f"The wording {result.message}.",
                section=section, page=hit.page, fillins=list(result.fillins),
            ))
            continue
        findings.append(
            Finding(
                check_id=check_id, severity=Severity.FAIL, section=section,
                page=hit.page, code=hit.code, expected=entry.text, found=hit.text,
                tier=entry.tier,
                message=f"{hit.code} wording does not match the official text.",
            )
        )
        ctx.record(StatementVerdict(
            code=hit.code, status="wrong", found=hit.text, expected=entry.text,
            source=_source_of(ctx, entry),
            why="This does not say what the official text says.",
            section=section, page=hit.page,
        ))
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


@register("A-02", "Hazard statements match the official wording")
def run_a02(ctx: CheckContext) -> list[Finding]:
    return _run_for(ctx, "A-02", "hazard") + _internal_statements(ctx, "A-02")


@register("A-03", "Precautionary statements match the official wording")
def run_a03(ctx: CheckContext) -> list[Finding]:
    return _run_for(ctx, "A-03", "precautionary")


@register("A-04", "EU and Australia-only statements match the official wording")
def run_a04(ctx: CheckContext) -> list[Finding]:
    return _run_for(ctx, "A-04", "supplemental")
