"""The words the report shows a reader, in one place.

Everything here is a presentation decision, not a data model. The codes stay
what they are - Severity.FAIL is still FAIL in the JSON - but a compliance
reviewer should never have to learn that "tier C" means "we had nothing to
check this against".

The proposals behind these choices are in docs/ui-plain-language.md.
"""

from __future__ import annotations

import re
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

#: How the regulation was decided, phrased to sit in a meta line:
#: "Regulation read from the document".
SET_BY = {"flag": "chosen by you", "auto": "read from the document"}

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


#: The five words a reader meets on an issue card. "Fix this" and "Wrong
#: wording" are both failures, kept apart because they need different work: one
#: is a statement that disagrees with the official text, the other is something
#: unfinished or missing that no official wording can settle.
STATUS: dict[str, Label] = {
    "wrong": Label("Wrong wording", "✕", "fix",
                   "This does not say what the official text says."),
    "fix": Label("Fix this", "!", "fix",
                 "Something here is unfinished or missing."),
    "check": Label("Check this", "!", "check",
                   "A difference that may or may not matter."),
    "correct": Label("Correct", "✓", "ok", "Matches the official wording."),
    "not_checked": Label("Not checked", "?", "unver",
                         "We hold no official wording for this code."),
}

#: Which filter pill an issue belongs to.
MUST_FIX = ("wrong", "fix")

#: Two statements whose blank needs more said about it than its shape reveals.
#: Everything else is worked out from the statement itself.
_BLANK_BY_CODE = {
    "P501": "Name the disposal route, e.g. \u2018to an approved waste disposal "
            "plant\u2019 or \u2018in accordance with local regulations\u2019.",
    "P280": "Keep only the protection that applies to this product, and replace "
            "or remove the trailing \u2018\u2026\u2019.",
}


def blank_instruction(code: str, official: str) -> str:
    """What goes in the blank, in plain words.

    Read from the statement's own shape wherever that is enough - a trailing
    slash list, a bracketed option, a slot mid-sentence - so a code we have
    never seen still gets useful guidance. Only P501 and P280 need wording of
    their own, because what belongs in their blank is not something the
    punctuation can say.
    """
    if code in _BLANK_BY_CODE:
        return _BLANK_BY_CODE[code]
    text = (official or "").strip()
    if re.search(r"/\s*\u2026", text):
        return ("Keep only the options that apply to this product, and replace "
                "or remove the trailing \u2018\u2026\u2019.")
    if re.search(r"\[[^\]]*\u2026[^\]]*\]", text):
        return ("Complete the bracketed part if it applies to this product, or "
                "remove it.")
    if re.search(r"\(\s*\u2026\s*\)", text):
        return "Name what the brackets refer to, or remove them."
    return ("Replace \u2018\u2026\u2019 with the specific information for this "
            "product.")


#: What to do about one statement, in the imperative.
STATUS_ACTION = {
    "wrong": "Replace it with the correct text.",
    "fix": "Complete this before the sheet is issued.",
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
    if "differs only in" in message and (
            "capitalisation" in message or "punctuation" in message):
        # Deliberately one sentence for both, so a sheet with a mixture of the
        # two gets one line in "What to do" rather than two near-identical ones.
        return ("Align punctuation and capital letters with the official text, "
                "or confirm they do not matter.")
    if finding.check_id == "C-15":
        if "was deleted in" in message:
            return "Remove this code; it no longer exists in this revision."
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


READY = "Ready to release"
REVIEW = "Review before release"
FIX = "Fix before release"


def _caveats(report: Report, page=None) -> list[str]:
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

    out.append(_coverage(report, page))
    held = getattr(report, "hcodes", None)
    if held is not None:
        out += [f"H-code verdict: {line}" for line in held.assumptions]
        out += [f"Likely cause (not part of any verdict): {line}" for line in held.notes]
        if held.state == "judged":
            out.append("H-code verdict inputs: PubChem (ECHA C&L notifications) — reference, "
                       "not legally binding; Annex VI and the GB MCL are binding; HCIS is a "
                       "reference. The mixture is calculated by Lingua's own rules.")
    return out


def _ranges(numbers: list[int]) -> str:
    """[1, 2, 4, 5, 6, 7, 8, 15] -> "1, 2, 4–8 and 15": a run of three or more
    as a range."""
    runs: list[list[int]] = []
    for number in sorted(numbers):
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    parts: list[str] = []
    for run in runs:
        parts += [f"{run[0]}–{run[-1]}"] if len(run) > 2 else [str(n) for n in run]
    return ", ".join(parts[:-1]) + f" and {parts[-1]}" if len(parts) > 1 else parts[0]


def _coverage(report: Report, page) -> str:
    """What this report checked and did not, from what actually ran."""
    checked = ["the wording of each statement against the official text"]
    if report.structure is not None and report.structure.state == "checked":
        checked.append("the structure of every section (number, order, heading, "
                       "required items)")
    unchecked: list[str] = []
    if page is not None:
        numbered = [s for s in page.sections if s.number.isdigit()]
        deep = [int(s.number) for s in numbered if s.deep]
        if deep:
            word = "Section" if len(deep) == 1 else "Sections"
            checked.append(f"{word} {_ranges(deep)} in depth, section against section "
                           "and against the official lists")
        shallow = [n for n in range(1, 17) if n not in deep]
        if shallow:
            word = "Section" if len(shallow) == 1 else "Sections"
            unchecked.append(f"the content of {word} {_ranges(shallow)} beyond "
                             + ("its" if len(shallow) == 1 else "their") + " structure")
    if any(r.check == "C-16" and r.key == "Pictograms" and r.status == "na"
           for r in report.consistency):
        unchecked.append("pictograms printed only as images")
    text = "Checked: " + "; ".join(checked) + "."
    if unchecked:
        text += " Not checked: " + "; ".join(unchecked) + "."
    return text


def plural(count: int, singular: str, many: str | None = None) -> str:
    """"1 statement", "2 statements" - written out, never "statement(s)".

    A reader counting problems should not have to parse a bracket.
    """
    word = singular if count == 1 else (many or singular + "s")
    return f"{count} {word}"


