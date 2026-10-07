"""Substance or mixture: what Section 3 says the product is.

It decides which check applies. A substance's classification is the list's
entry for its own CAS number, so Section 2 is compared with that entry and
there is no mixture to calculate; a mixture's classification follows from its
ingredients. Read in order of how plainly the sheet says it:

1. the subsection heading the SDS format gives each case - "3.1 Substances",
   "3.2 Mixtures";
2. a sentence that says so - "This product is a substance";
3. a composition of one CAS number at (about) 100 %.

Where none of them settles it the answer is "unknown", which the pipeline
treats as a mixture - the check that does not assume - and the report says it
could not tell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

SUBSTANCE, MIXTURE, UNKNOWN = "substance", "mixture", "unknown"

_HEADING_SUBSTANCE = re.compile(
    r"^\s*3\.1\.?\s*(substances?|stoffe?|substance|sustancias?|sostanze?|stof)\b",
    re.IGNORECASE)
_HEADING_MIXTURE = re.compile(
    r"^\s*3\.2\.?\s*(mixtures?|gemische?|mélanges?|mezclas?|miscele|"
    r"blandinger|mengsels?)\b", re.IGNORECASE)
_SAYS_SUBSTANCE = re.compile(
    r"\b(is a (?:pure |single |mono-constituent )?substance|single substance|"
    r"mono-constituent substance|chemical characteri[sz]ation\s*:\s*substance)\b",
    re.IGNORECASE)
_SAYS_MIXTURE = re.compile(
    r"\b(is a mixture|chemical characteri[sz]ation\s*:\s*mixture)\b",
    re.IGNORECASE)
#: How close to 100 % one ingredient has to be to make the product a substance.
#: A substance's purity is printed as "100 %", "≥ 99 %" or "95 - 100 %"; an
#: ingredient at "60 %" is a mixture with the rest undeclared.
_PURE = Decimal(95)


@dataclass(frozen=True)
class Composition:
    kind: str
    #: Why, in words a reader can check against the sheet.
    evidence: str


def _section_three(lines, spans) -> list[str]:
    return [line.text or "" for span in spans if span.name == "3"
            for line in lines[span.start:span.end]]


def detect(lines, spans, rows) -> Composition:
    """What the product is, from Section 3's text and its composition rows.

    `rows` are the ingredients the Section 3 reader found (`from_pdf`): a CAS
    number, codes and a concentration each.
    """
    from lingua_oracle.mixture.concentration import parse

    text = _section_three(lines, spans)
    for line in text:
        if _HEADING_SUBSTANCE.search(line):
            return Composition(SUBSTANCE, f"Section 3 heading: “{line.strip()[:60]}”")
        if _HEADING_MIXTURE.search(line):
            return Composition(MIXTURE, f"Section 3 heading: “{line.strip()[:60]}”")
    for line in text:
        said = _SAYS_SUBSTANCE.search(line)
        if said:
            return Composition(SUBSTANCE, f"Section 3 says “{said.group(0)}”")
        said = _SAYS_MIXTURE.search(line)
        if said:
            return Composition(MIXTURE, f"Section 3 says “{said.group(0)}”")
    if len(rows) == 1 and rows[0].cas:
        share = parse(rows[0].concentration)
        if share is not None and share.high == 100 and share.low >= _PURE:
            return Composition(
                SUBSTANCE, f"Section 3 lists one CAS number, {rows[0].cas}, at "
                           f"{rows[0].concentration}")
    if len(rows) > 1:
        return Composition(MIXTURE, f"Section 3 lists {len(rows)} ingredients")
    return Composition(UNKNOWN, "Section 3 does not say whether this is a "
                                "substance or a mixture")
