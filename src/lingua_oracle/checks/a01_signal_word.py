"""A-01: the signal word must be the official one for the language."""

from __future__ import annotations

import re

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.match.normalize import normalize
from lingua_oracle.match.template import match
from lingua_oracle.models import SIGNAL_DANGER, SIGNAL_WARNING, Finding, Severity, Tier

CHECK_ID = "A-01"
TITLE = "Signal word exact for the language"

_LABEL = (
    r"signal\s*word|signalord|signalwort|signaalwoord|mention\s+d['’]avertissement"
    r"|palabra\s+de\s+advertencia|注意喚起語"
)
# The value, not the rest of the line: a signal word is a single short word in
# every language on file, so the capture stops at the first separator. Taking
# "(.+)" swallowed a whole sentence and reported it as the stated signal word.
_LABEL_RE = re.compile(rf"(?:{_LABEL})\s*[:\-–]?\s+([^,;.:()\[\]]{{1,40}})", re.IGNORECASE)

# A line declaring that there is NO signal word, or that the product is not
# classified, is the opposite of a signal-word declaration and must not be read
# as one. These are document phrases, not regulatory text.
_NEGATIVE_RE = re.compile(
    r"\bno\s+(?:hazard\s+)?(?:pictogram|signal\s*word|hazard\s+statement|"
    r"precautionary\s+statement)"
    r"|\bnot\s+(?:classified|applicable|required|assigned)"
    r"|\bnone\s+(?:assigned|required)"
    r"|\bnot\s+a\s+hazardous\s+(?:substance|mixture)"
    r"|\bingen\s+signalord|\bikke\s+klassificeret"
    r"|\bkein\s+signalwort|\bnicht\s+eingestuft"
    r"|\bpas\s+de\s+mention\s+d['’]avertissement|\bnon\s+class[ée]"
    r"|\bsin\s+palabra\s+de\s+advertencia|\bno\s+clasificado",
    re.IGNORECASE,
)


def _candidates(ctx: CheckContext) -> list[tuple[str, int]]:
    """(text, page) for anything that looks like a stated signal word."""
    out: list[tuple[str, int]] = []
    for line in ctx.document.lines:
        if _NEGATIVE_RE.search(line.text):
            continue  # states that there is no signal word, not what it is
        m = _LABEL_RE.search(line.text)
        if not m:
            continue
        value = normalize(m.group(1)).strip(" .:;-")
        # A signal word is one word. Anything longer is surrounding prose that
        # happened to follow the label, not a stated value.
        if value and len(value.split()) <= 2:
            out.append((value, line.page))
    return out


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    official = {
        code: entry
        for code in (SIGNAL_DANGER, SIGNAL_WARNING)
        if (entry := ctx.entry(code)) is not None
    }
    findings: list[Finding] = []
    stated = _candidates(ctx)
    if not stated:
        return findings

    if not official:
        for value, page in stated:
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=Severity.WARN, page=page, code="SIGNAL",
                    found=value, tier=Tier.C, unverified=True,
                    message=(
                        f"No official signal word on file for {ctx.regulation.display_name} "
                        f"in '{ctx.language}', so the wording cannot be verified."
                    ),
                )
            )
        return findings

    for value, page in stated:
        best = None
        for code, entry in official.items():
            result = match(value, entry.text)
            if result.matched:
                best = (code, entry, result)
                break
        if best is None:
            expected = " / ".join(sorted(e.text for e in official.values()))
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=Severity.FAIL, page=page, code="SIGNAL",
                    expected=expected, found=value,
                    tier=min(e.tier for e in official.values()),
                    message=(
                        f"Signal word '{value}' is not the official wording for "
                        f"'{ctx.language}'."
                    ),
                )
            )
        else:
            code, entry, result = best
            if not result.is_clean:
                findings.append(
                    Finding(
                        check_id=CHECK_ID, severity=Severity.WARN, page=page, code=code,
                        expected=entry.text, found=value, tier=entry.tier,
                        message=f"Signal word {result.message}.",
                    )
                )
    return findings
