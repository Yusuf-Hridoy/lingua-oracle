"""A-07: broken characters from a bad encoding or a missing font."""

from __future__ import annotations

import re

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.models import Finding, Severity

CHECK_ID = "A-07"
TITLE = "Broken characters"

# Classic UTF-8-read-as-Latin-1 sequences, e.g. 'A~A|' for 'u-umlaut', and the
# smart-quote family that turns into 'a<EUR>(tm)'.
_MOJIBAKE_RE = re.compile(
    "[\u00c3\u00c2][\u0080-\u00bf]"
    "|\u00e2\u0080[\u0099\u009c\u009d\u0093\u0094]"
)
_REPLACEMENT_RE = re.compile("\ufffd")
# A '?' sitting inside a word, which is how some producers render a missing glyph.
_QUESTION_IN_WORD_RE = re.compile(r"\w\?+\w")
_BOX_RE = re.compile("[\u25a1\u25a0]{2,}")


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    checks = (
        (_REPLACEMENT_RE, "Unicode replacement character (U+FFFD)"),
        (_MOJIBAKE_RE, "mojibake (UTF-8 decoded as Latin-1)"),
        (_QUESTION_IN_WORD_RE, "'?' inside a word, usually a missing glyph"),
        (_BOX_RE, "missing-glyph boxes"),
    )
    for line in ctx.document.lines:
        for pattern, label in checks:
            m = pattern.search(line.text)
            if not m:
                continue
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=Severity.FAIL, page=line.page,
                    found=line.text.strip()[:200],
                    message=f"Broken characters: {label} near {m.group(0)!r}.",
                )
            )
            break
    return findings
