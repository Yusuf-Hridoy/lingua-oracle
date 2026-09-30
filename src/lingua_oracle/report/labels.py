"""The words the report shows a reader, in one place.

Everything here is a presentation decision, not a data model. The codes stay
what they are - Severity.FAIL is still FAIL in the JSON - but a compliance
reviewer should never have to learn that "tier C" means "we had nothing to
check this against".

The proposals behind these choices are in docs/ui-plain-language.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from lingua_oracle.models import Report, Severity, Tier


@dataclass(frozen=True)
class Label:
    """A word, an icon and a colour class. Never the colour on its own."""

    word: str
    icon: str
    css: str
    help: str = ""


#: Severity as a reader meets it. The icon carries the same meaning as the
#: colour, so the page still reads correctly in greyscale or with colour vision
#: deficiency.
SEVERITY: dict[Severity, Label] = {
    Severity.FAIL: Label("Wrong wording", "✕", "fail",
                         "This does not match the official text."),
    Severity.WARN: Label("Check this", "!", "warn",
                         "A difference that may or may not matter."),
    Severity.INFO: Label("Needs a person", "i", "info",
                         "Correct so far as the tool can tell; a human has to judge it."),
}

#: A code we had no official text for. Not a verdict on the document.
NOT_CHECKED = Label("Not checked", "?", "unver",
                    "Our records hold no official wording for this code, so we "
                    "could not compare it. This is our gap, not the sheet's.")

#: Where the wording we compared against came from.
SOURCE: dict[Tier, Label] = {
    Tier.A: Label("Official", "A", "A",
                  "The regulation's own published wording for this language."),
    Tier.B: Label("Borrowed", "B", "B",
                  "EU CLP's published translation, used because this "
                  "regulation's English wording is identical."),
    Tier.C: Label("None on file", "C", "C",
                  "No official wording available, so no wording verdict."),
}

#: How the regulation was decided.
SET_BY = {"flag": "You chose it", "auto": "Read from the document"}

#: Column and tile headings.
COLUMNS = {
    "severity": "Result",
    "section": "Section",
    "page": "Page",
    "code": "Code",
    "tier": "Source of official text",
    "expected": "Official wording",
    "found": "Your document",
}

#: C-15 shows the regulation's nearest published statement in the "Official
#: wording" column. It is a pointer, not the wording the sheet should have had,
#: so the column gets its own heading there.
NEWER_GHS_EXPECTED_COLUMN = "Closest official statement"

TILES = {
    "fail": "Wrong wording",
    "warn": "Check this",
    "info": "Needs a person",
    "unverified": "Not checked",
    "coverage": "Codes we could check",
    "codes": "Codes in document",
}

META = {
    "file": "File",
    "regulation": "Regulation",
    "language": "Language",
    "set_by": "Regulation set by",
    "created": "Checked on",
    "id": "Reference",
}

#: Codes that are ours, not the regulation's, and must be named as such.
INTERNAL_CODE_LABELS = {"SIGNAL": "Signal word"}

SECTION_NAMES = {
    "2": "Hazards identification",
    "3": "Composition / information on ingredients",
    "16": "Other information",
}


def code_label(code: str | None) -> str:
    if not code:
        return ""
    return INTERNAL_CODE_LABELS.get(code, code)


def section_label(section: str | None) -> str:
    if not section:
        return ""
    name = SECTION_NAMES.get(section)
    return f"{section} — {name}" if name else section


# --------------------------------------------------------------------------
# The verdict banner
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    headline: str
    tone: str          # ok | warn | bad
    icon: str
    detail: str
    caveats: list[str]


def _caveats(report: Report) -> list[str]:
    """What this report does NOT cover.

    A green headline that stands alone would overclaim. These lines run under
    every verdict, including the clean one, so "all checked wording matches"
    is always read next to what "checked" excluded.
    """
    out: list[str] = []

    unverified = [f.code for f in report.findings if f.unverified and f.code]
    if unverified:
        shown = ", ".join(sorted(set(unverified))[:8])
        more = len(set(unverified)) - 8
        out.append(
            f"{len(set(unverified))} code(s) could not be checked - we hold no "
            f"official wording for them in this regulation and language: "
            f"{shown}{f' and {more} more' if more > 0 else ''}."
        )

    borrowed = sorted({f.code for f in report.findings
                       if f.tier == Tier.B and f.code})
    if borrowed:
        out.append(
            f"{len(borrowed)} statement(s) were compared against EU CLP's "
            "published translation, borrowed because this regulation's English "
            "wording is identical."
        )

    if report.coverage.codes_found and report.coverage.percent < 100:
        out.append(
            f"We could check {report.coverage.percent}% of the "
            f"{report.coverage.codes_found} codes found in this document."
        )

    out.append(
        "This checks the wording of statements against the official text. It "
        "does not check whether the classification itself is correct, nor "
        "anything outside the statements."
    )
    return out


def verdict_of(report: Report) -> Verdict:
    s = report.summary
    if s.fail:
        return Verdict(
            headline="Wording problems found — fix before release",
            tone="bad", icon="✕",
            detail=f"{s.fail} statement(s) do not match the official text.",
            caveats=_caveats(report),
        )
    if s.warn or s.info:
        bits = []
        if s.warn:
            bits.append(f"{s.warn} to check")
        if s.info:
            bits.append(f"{s.info} needing a person")
        return Verdict(
            headline="Looks correct — some items need a person to check",
            tone="warn", icon="!",
            detail="Nothing contradicts the official text. " + ", ".join(bits) + ".",
            caveats=_caveats(report),
        )
    return Verdict(
        headline="All checked wording matches the official text",
        tone="ok", icon="✓",
        detail="Every statement we could check is word for word the official text.",
        caveats=_caveats(report),
    )
