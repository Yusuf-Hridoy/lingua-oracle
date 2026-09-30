"""C-14: a regulation may require more than one language in the same document.

WHMIS requires English and French. The check looks for each required language in
the document body rather than in the codes, because the requirement is about the
whole document.

It asks rather than accuses. A missing language is not wrong wording - the
wording it found may be perfectly correct - and a company that issues the French
sheet as a separate file has complied. The tool can see one document; whether
the other exists is something only the reader knows. So this is a warning that
names the language and asks for confirmation, never a failure.

When two documents are compared and the second supplies the missing language,
the pair satisfies the requirement and nothing is reported.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.language import _detector, language_name, tag_to_language
from lingua_oracle.match.normalize import normalize
from lingua_oracle.models import Finding, Severity

CHECK_ID = "C-14"
TITLE = "Every language the regulation requires is present"

# A language counts as present when enough of the body is confidently in it.
_MIN_LINES = 3
_MIN_CHARS = 30
_CONFIDENCE = 0.55


def _and_list(items: list[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


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

    # A compared document can supply what this one lacks.
    supplied = {ctx.language}
    if ctx.compare_language:
        supplied.add(ctx.compare_language)

    findings: list[Finding] = []
    for tag in required:
        if counts.get(tag, 0) >= _MIN_LINES or tag in supplied:
            continue
        name = language_name(tag)
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.WARN, code=None,
                message=(
                    f"Confirm the {name} version of this SDS exists. "
                    f"{ctx.regulation.display_name} requires "
                    f"{_and_list([language_name(t) for t in required])}, and "
                    f"this document is not in {name}."
                ),
            )
        )
    return findings
