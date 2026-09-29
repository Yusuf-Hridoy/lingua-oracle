"""C-02: the same code must read the same way everywhere in one document.

This is the only wording check available for tier C codes, where there is no
reference text to compare against. It also runs for tier A and B codes, because a
document that contradicts itself is worth flagging regardless.
"""

from __future__ import annotations

import collections

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.language import _detector, tag_to_language
from lingua_oracle.match.normalize import normalize
from lingua_oracle.models import Finding, Severity, Tier

CHECK_ID = "C-02"
TITLE = "Same code gives the same text everywhere in the document"


def _language_bucket(ctx: CheckContext, text: str, required: list[str]) -> str:
    """Which required language a phrase is in, for mandated-bilingual documents.

    A document that must carry English and French will legitimately state the
    same code twice, once per language. Comparing those two against each other
    would flag every correct bilingual sheet, so phrases are bucketed by
    language first and only compared within a bucket.
    """
    targets = {tag: lang for tag in required if (lang := tag_to_language(tag)) is not None}
    if len(targets) < 2:
        return ""
    values = _detector().compute_language_confidence_values(text)
    if not values:
        return ""
    top = values[0].language
    for tag, language in targets.items():
        if top == language:
            return tag
    return ""


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    required = list(ctx.regulation.required_languages)
    multilingual = len(required) > 1
    by_code: dict[tuple[str, str], list] = collections.defaultdict(list)
    for hit in ctx.hits:
        if hit.text:
            bucket = _language_bucket(ctx, hit.text, required) if multilingual else ""
            by_code[(hit.code, bucket)].append(hit)

    findings: list[Finding] = []
    for (code, _bucket), hits in sorted(by_code.items()):
        variants: dict[str, list] = collections.defaultdict(list)
        for hit in hits:
            variants[normalize(hit.text).casefold().rstrip(".")].append(hit)
        if len(variants) < 2:
            continue
        ordered = sorted(variants.items(), key=lambda kv: -len(kv[1]))
        majority_hits = ordered[0][1]
        tier = ctx.tier_for(code)
        for _key, odd_hits in ordered[1:]:
            for hit in odd_hits:
                findings.append(
                    Finding(
                        check_id=CHECK_ID, severity=Severity.WARN,
                        section=ctx.section_for(hit), page=hit.page, code=code,
                        expected=majority_hits[0].text, found=hit.text, tier=tier,
                        unverified=tier == Tier.C,
                        message=(
                            f"{code} is written differently in different places in "
                            "this document."
                        ),
                    )
                )
    return findings
