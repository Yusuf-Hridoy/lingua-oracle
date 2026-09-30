"""C-14: a regulation may require more than one language in the same document.

WHMIS requires English and French. The check looks for each required language in
the document body rather than in the codes, because the requirement is about the
whole document.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.language import _detector, tag_to_language
from lingua_oracle.match.normalize import normalize
from lingua_oracle.models import Finding, Severity

CHECK_ID = "C-14"
TITLE = "Every language the regulation requires is present"

# A language counts as present when enough of the body is confidently in it.
_MIN_LINES = 3
_MIN_CHARS = 30
_CONFIDENCE = 0.55


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    required = list(ctx.regulation.required_languages)
    if not required:
        return []

    targets = {tag: lang for tag in required if (lang := tag_to_language(tag)) is not None}
    if not targets:
        return []

    detector = _detector()
    counts = dict.fromkeys(targets, 0)
    for line in ctx.document.lines:
        body = normalize(line.text)
        if len(body) < _MIN_CHARS:
            continue
        values = detector.compute_language_confidence_values(body)
        if not values:
            continue
        top = values[0]
        for tag, language in targets.items():
            if top.language == language and top.value >= _CONFIDENCE:
                counts[tag] += 1

    findings: list[Finding] = []
    for tag in required:
        if counts.get(tag, 0) < _MIN_LINES:
            findings.append(
                Finding(
                    check_id=CHECK_ID, severity=Severity.FAIL, code=None,
                    message=(
                        f"{ctx.regulation.display_name} requires '{tag}', but the "
                        f"document does not appear to contain it "
                        f"({counts.get(tag, 0)} matching lines)."
                    ),
                )
            )
    return findings
