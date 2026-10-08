"""B-08: Section 16 writes out the statements the rest of the sheet does not.

The rule is the regulation's own, read from its text on safety data sheets
(data/section16/, built by `keys/builders/section16.py`). REACH Annex II,
Section 16(e): "Write out the full text of any statements, which are not
written out in full under sections 2 to 15". So:

* a code written out with its text anywhere in Sections 2 to 15 needs
  nothing in Section 16;
* a code that Sections 2 to 15 give only as a code, and Section 16 does not
  write out, leaves the sheet without its text - a fault;
* a code written out only in Section 16 is said, as a note: it may belong to
  an ingredient whose codes Section 3 omits.

Which statements: H and EUH always; P too where the rule's own sentence
names precautionary statements, as REACH's does ("a list of relevant hazard
statements and/or precautionary statements").

A regulation whose text has no such rule (OSHA Appendix D, the HPR, the GHS
Annex 4) gets no finding, and nor does one whose text is not on file.
"""

from __future__ import annotations

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.detect.codes import split_combined
from lingua_oracle.keys.builders import section16
from lingua_oracle.models import Finding, Severity

CHECK_ID = "B-08"
TITLE = "Section 16 writes out every statement Sections 2 to 15 give only as a code"


def _statement_codes(hits, prefixes):
    """(code, hit) for each statement code the rule covers, combinations
    taken apart."""
    for hit in hits:
        for code in split_combined(hit.code):
            if code.startswith(prefixes):
                yield code, hit


def _covered(rule) -> tuple[str, ...]:
    """The code families the rule's own sentence speaks of."""
    if "precautionary statements" in rule.text.lower():
        return ("H", "EUH", "P")
    return ("H", "EUH")


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    rule = section16.load(ctx.regulation.id)
    if rule is None or rule.status != "rule":
        return []
    if ctx.is_label() or not any(span.name == "16" for span in ctx.spans):
        return []
    # Only Sections 2, 3 and 16 are tracked; the Section 3 span runs on to
    # Section 16, so "2" and "3" together are Sections 2 to 15.
    prefixes = _covered(rule)
    before = [h for h in ctx.hits if ctx.section_for(h) in ("2", "3")]
    written = {code for code, hit in _statement_codes(before, prefixes) if hit.text}
    bare: dict[str, object] = {}
    for code, hit in _statement_codes(before, prefixes):
        if code not in written:
            bare.setdefault(code, hit)
    section16_hits = ctx.hits_in("16")
    spelled_out = {code for code, hit in _statement_codes(section16_hits, prefixes)
                   if hit.text}

    findings: list[Finding] = []
    for code, hit in bare.items():
        if code in spelled_out:
            continue
        entry = ctx.entry(code)
        findings.append(Finding(
            check_id=CHECK_ID, severity=Severity.FAIL, section="16",
            page=hit.page, code=code,
            expected=entry.text if entry else None,
            tier=entry.tier if entry else None,
            message=(f"{code} appears in Sections 2 to 15 only as a code, and "
                     f"Section 16 does not write it out. {rule.citation}: "
                     f"“{rule.text}”.")))
    reported = set(bare)
    for code, hit in _statement_codes(section16_hits, prefixes):
        if hit.text and code not in written and code not in reported:
            reported.add(code)
            findings.append(Finding(
                check_id=CHECK_ID, severity=Severity.INFO, section="16",
                page=hit.page, code=code,
                message=(f"{code} is written out in Section 16 and appears "
                         "nowhere in Sections 2 to 15.")))
    return findings
