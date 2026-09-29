"""A-06: placeholders that were never filled in."""

from __future__ import annotations

import re

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.models import Finding, Severity

CHECK_ID = "A-06"
TITLE = "Leftover placeholders"

# Format placeholders, template tags, and the fill-in instructions from the
# official texts that an author was supposed to replace.
_PATTERNS: list[tuple[str, str]] = [
    (r"\{\s*\d+\s*\}", "format placeholder"),
    (r"\{\{[^{}]{0,60}\}\}", "template tag"),
    (r"%s\b|%d\b", "printf placeholder"),
    (r"<\s*(?:state|specify|insert|indicate|or state)[^<>]{0,120}>", "unfilled instruction"),
    (r"\[\s*(?:state|specify|insert|indicate|xxx+|tbd|to be)[^\[\]]{0,80}\]",
     "unfilled bracket"),
    (r"\bXXXX+\b", "placeholder text"),
    (r"\bTBD\b|\bTO BE (?:COMPLETED|ADVISED|DETERMINED)\b", "unfinished marker"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in _PATTERNS]


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for line in ctx.document.lines:
        for pattern, label in _COMPILED:
            for m in pattern.finditer(line.text):
                token = m.group(0).strip()
                if (token, line.page) in seen:
                    continue
                seen.add((token, line.page))
                findings.append(
                    Finding(
                        check_id=CHECK_ID, severity=Severity.FAIL, page=line.page,
                        found=line.text.strip()[:200],
                        message=f"Leftover {label}: {token!r}.",
                    )
                )
    return findings
