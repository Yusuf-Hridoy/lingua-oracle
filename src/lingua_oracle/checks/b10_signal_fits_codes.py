"""B-10: the signal word must fit the hazard codes actually present.

CLP Annex I assigns a signal word per hazard class and category. This tool does
not classify, so it uses what the answer key records: each hazard entry carries
the signal word its source states. If any code present is Danger-only, the
document must say Danger; if every code present is Warning-only, it must not.
"""

from __future__ import annotations

from lingua_oracle.checks.a01_signal_word import _candidates as signal_candidates
from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.match.template import match
from lingua_oracle.models import SIGNAL_DANGER, SIGNAL_WARNING, Finding, Severity

CHECK_ID = "B-10"
TITLE = "Signal word fits the codes"


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    danger_entry = ctx.entry(SIGNAL_DANGER)
    warning_entry = ctx.entry(SIGNAL_WARNING)
    if danger_entry is None:
        return []  # nothing official to compare against

    # Only codes whose source actually states a signal word can be judged. EU CLP
    # Annex III carries no signal word per code (CLP assigns it per hazard class
    # in Annex I), so for EU documents this check abstains rather than guessing.
    known = {
        hit.code: entry.signal_word
        for hit in ctx.hits
        if hit.code.startswith("H")
        and (entry := ctx.entry(hit.code)) is not None
        and entry.signal_word in ("Danger", "Warning")
    }
    if not known:
        return []
    requires_danger = sorted(c for c, w in known.items() if w == "Danger")
    allows_only_warning = all(w == "Warning" for w in known.values())

    stated = signal_candidates(ctx)
    if not stated:
        return []
    says_danger = any(match(value, danger_entry.text).matched for value, _ in stated)

    findings: list[Finding] = []
    if requires_danger and not says_danger:
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, code=requires_danger[0],
                expected=danger_entry.text,
                found=" / ".join(value for value, _ in stated),
                tier=danger_entry.tier,
                message=(
                    "Codes requiring the signal word Danger are present ("
                    + ", ".join(requires_danger[:5])
                    + "), but the document does not state it."
                ),
            )
        )
    elif allows_only_warning and says_danger and warning_entry is not None and ctx.hits:
        findings.append(
            Finding(
                check_id=CHECK_ID, severity=Severity.FAIL, code="SIGNAL",
                expected=warning_entry.text,
                found=" / ".join(value for value, _ in stated),
                tier=warning_entry.tier,
                message=(
                    "Every hazard code present is Warning-level, but the document "
                    "states Danger."
                ),
            )
        )
    return findings
