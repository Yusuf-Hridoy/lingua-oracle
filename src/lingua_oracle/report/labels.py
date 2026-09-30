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


#: The checks that compare a statement against official wording. Only these may
#: report "Wrong wording" - a missing language or a code from a later revision
#: is not a wording defect, and saying so sent readers hunting for a typo that
#: was never there.
WORDING_CHECKS = frozenset({"A-01", "A-02", "A-03", "A-04"})

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

#: A failure from a check that is not about wording. Same severity, different
#: words: something has to change, but not the wording of a statement.
NEEDS_FIXING = Label("Fix this", "✕", "fail",
                     "Something on the sheet has to change before release.")


def result_of(check_id: str, severity: Severity, unverified: bool) -> Label:
    """The words shown in the Result column."""
    if unverified:
        return NOT_CHECKED
    if severity is Severity.FAIL and check_id not in WORDING_CHECKS:
        return NEEDS_FIXING
    return SEVERITY[severity]

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
# What to do about it
# --------------------------------------------------------------------------

#: One imperative per finding. The finding says what is wrong; this says what
#: the reader does next, which is the thing they actually came for.
_ACTIONS: dict[str, str] = {
    "A-01": "Use the official signal word for this language.",
    "A-02": "Correct this statement to the official wording.",
    "A-03": "Correct this statement to the official wording.",
    "A-04": "Correct this statement to the official wording.",
    "A-05": "Translate this statement into the document's language.",
    "A-06": "Replace the placeholder with the real information.",
    "A-07": "Fix the damaged characters.",
    "B-08": "Write this statement out in full in Section 16.",
    "B-09": "Make Section 2 and the label agree.",
    "B-10": "Check the signal word against the hazard codes on this sheet.",
    "B-11": "Add the missing statement to the other-language version.",
    "C-02": "Write this statement the same way everywhere in the document.",
    "C-12": "Remove this statement, or use the code this regulation defines.",
    "C-13": "Check which revision this wording comes from.",
    "C-14": "Confirm that version of the SDS exists.",
}


#: The statement card's own result words.
STATUS: dict[str, Label] = {
    "wrong": Label("Wrong wording", "❌", "fail",
                   "This does not say what the official text says."),
    "check": Label("Check this", "⚠", "warn",
                   "A difference that may or may not matter."),
    "correct": Label("Correct", "✅", "ok", "Matches the official wording."),
    "not_checked": Label("Not checked", "?", "unver",
                         "We hold no official wording for this code."),
}

#: What to do about one statement, in the imperative.
STATUS_ACTION = {
    "wrong": "Replace it with the correct text.",
    "check": "Read both and decide whether the difference matters.",
    "not_checked": "No action; our tool has no official text for this.",
}


def action_for(finding, regulation_display: str = "") -> str:
    """The plain-words next step for one finding."""
    message = finding.message or ""
    if finding.unverified:
        return "No action; our tool has no official text for this."
    if "not filled in" in message.lower():
        return "Fill in the blank before this sheet is issued."
    if message.lower().startswith("filled in:"):
        return "Check the filled-in text is right for this product."
    if "differs only in capitalisation" in message:
        return "Match the capitalisation of the official text, or confirm it does not matter."
    if finding.check_id == "C-15":
        if "not a code" in message:
            return "Check this code for a typo."
        where = regulation_display or "this regulation"
        if "no equivalent statement" in message:
            return (f"Ask whether {where} allows this wording; there is no "
                    f"equivalent statement to use instead.")
        marker = "publishes is "
        if marker in message:
            nearest = message.rsplit(marker, 1)[-1].rstrip(".").strip()
            return f"Ask whether {where} allows this wording; if not, use {nearest}."
        return f"Ask whether {where} allows this wording."
    if finding.check_id == "C-14":
        # "Confirm the French version of this SDS exists."
        return message.split(".")[0].strip() + "."
    return _ACTIONS.get(finding.check_id, "Review this finding.")


# --------------------------------------------------------------------------
# The verdict banner
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    #: The one line a reader acts on, in capitals at the top of the report.
    release: str
    headline: str
    tone: str          # ok | warn | bad
    icon: str
    detail: str
    #: Grouped "what to do" lines, most urgent first, at most five.
    actions: list[tuple[str, int]]
    caveats: list[str]


READY = "READY TO RELEASE"
REVIEW = "REVIEW BEFORE RELEASE"
FIX = "FIX BEFORE RELEASE"

_MAX_ACTIONS = 5


def _rank(finding) -> int:
    if finding.unverified:
        return 3
    if finding.severity is Severity.FAIL:
        return 0
    if finding.severity is Severity.WARN:
        return 1
    return 2


def actions_for(report: Report, regulation_display: str = "") -> list[tuple[str, int]]:
    """Every finding's next step, identical ones grouped and counted."""
    counted: dict[str, int] = {}
    order: dict[str, int] = {}
    for finding in report.findings:
        if finding.unverified:
            continue  # nothing to do about our own gap
        text = action_for(finding, regulation_display)
        counted[text] = counted.get(text, 0) + 1
        order[text] = min(order.get(text, 99), _rank(finding))
    ranked = sorted(counted.items(), key=lambda kv: (order[kv[0]], -kv[1], kv[0]))
    return ranked[:_MAX_ACTIONS]


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


def verdict_of(report: Report, regulation_display: str = "") -> Verdict:
    """One line to act on, then what to do, then what was not covered."""
    summary = report.summary
    actions = actions_for(report, regulation_display)
    wording_fails = sum(
        1 for f in report.findings
        if f.severity is Severity.FAIL and not f.unverified
        and f.check_id in WORDING_CHECKS
    )
    other_fails = summary.fail - wording_fails

    if summary.fail:
        parts = []
        if wording_fails:
            parts.append(f"{wording_fails} statement(s) do not match the official text")
        if other_fails:
            parts.append(f"{other_fails} other problem(s) to fix")
        return Verdict(
            release=FIX,
            headline="Wording problems found — fix before release"
            if wording_fails else "Problems found — fix before release",
            tone="bad", icon="✕", detail="; ".join(parts) + ".",
            actions=actions, caveats=_caveats(report),
        )
    if summary.warn or summary.info:
        bits = []
        if summary.warn:
            bits.append(f"{summary.warn} to check")
        if summary.info:
            bits.append(f"{summary.info} needing a person")
        return Verdict(
            release=REVIEW,
            headline="Looks correct — some items need a person to check",
            tone="warn", icon="!",
            detail="Nothing contradicts the official text. " + ", ".join(bits) + ".",
            actions=actions, caveats=_caveats(report),
        )
    return Verdict(
        release=READY,
        headline="All checked wording matches the official text",
        tone="ok", icon="✓",
        detail="Every statement we could check is word for word the official text.",
        actions=actions, caveats=_caveats(report),
    )
