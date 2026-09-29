"""C-02: the same code must read the same way everywhere in one document.

This is the only wording check available for tier C codes, where there is no
reference text to compare against. It also runs for tier A and B codes, because a
document that contradicts itself is worth flagging regardless.
"""

from __future__ import annotations

import collections

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.match.normalize import normalize
from lingua_oracle.models import Finding, Severity, Tier

CHECK_ID = "C-02"
TITLE = "Same code gives the same text everywhere in the document"


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    by_code: dict[str, list] = collections.defaultdict(list)
    for hit in ctx.hits:
        if hit.text:
            by_code[hit.code].append(hit)

    findings: list[Finding] = []
    for code, hits in sorted(by_code.items()):
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
