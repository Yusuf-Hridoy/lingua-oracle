"""C-12: every phrase used must be valid for the chosen regulation.

EUH codes belong to EU/UK CLP, AUH codes to Australia. Seeing either on an OSHA
document means the wrong source was used.
"""

from __future__ import annotations

import re

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.models import Finding, Severity

CHECK_ID = "C-12"
TITLE = "Phrases valid for the chosen regulation"

_PREFIX_RE = re.compile(r"^(EUH|AUH|H|P)")


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    allowed = set(ctx.regulation.allowed_prefixes)
    findings: list[Finding] = []
    reported: set[str] = set()
    for hit in ctx.hits:
        m = _PREFIX_RE.match(hit.code)
        if not m:
            continue
        prefix = m.group(1)
        if prefix in allowed or hit.code in reported:
            continue
        reported.add(hit.code)
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL,
                section=ctx.section_for(hit), page=hit.page, code=hit.code,
                found=hit.text or hit.code,
                message=(
                    f"{hit.code} uses the '{prefix}' family, which is not valid for "
                    f"{ctx.regulation.display_name} "
                    f"(allowed: {', '.join(sorted(allowed))})."
                ),
            )
        )
    return findings
