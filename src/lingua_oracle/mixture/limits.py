"""Annex VI's Specific Conc. Limits, M-factors and ATEs, read as numbers.

Table 3 prints them as text in one column:

    Eye Dam. 1; H318: C >= 36 %
    Eye Irrit. 2; H319: 22 % <= C < 36 %
    M = 10

The calculation needs the numbers; a reader needs the sentence. Both are kept -
every parsed value carries the line it came from, so a trace can quote the act
rather than paraphrase it.

Nothing is inferred. A line that does not parse is returned as unparsed and
named in the trace, because a specific limit silently dropped would put the
ingredient back under the generic limit and change the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from lingua_oracle.mixture.classes import HazardClass, parse_class

#: "C >= 36 %", "22 % <= C < 36 %", "0,2 %". The act uses a comma for the
#: decimal point and spaces inside large numbers.
_NUMBER = r"\d+(?:[.,]\d+)?"
_LOWER_FIRST = re.compile(
    rf"(?P<low>{_NUMBER})\s*%?\s*(?P<lower_op><=|≤|<)\s*C\s*"
    rf"(?P<upper_op><=|≤|<)\s*(?P<high>{_NUMBER})\s*%")
_ONE_SIDED = re.compile(
    rf"C\s*(?P<op>>=|≥|>|<=|≤|<)\s*(?P<value>{_NUMBER})\s*%")
_BARE = re.compile(rf"^\s*(?P<value>{_NUMBER})\s*%\s*$")
_M_FACTOR = re.compile(r"M\s*=\s*(?P<value>[\d\s]+)", re.IGNORECASE)
#: An ATE's number may carry a space inside it - "1 000 mg/kg bw" - the way the
#: act groups thousands.
_ATE = re.compile(
    r"(?P<route>oral|dermal|inhalation)\s*:\s*ATE\s*=\s*"
    r"(?P<value>\d[\d\s]*(?:[.,]\d+)?)\s*"
    r"(?P<unit>mg/kg(?:\s*bw)?|mg/l|mg/L|ppmV|ppm)", re.IGNORECASE)


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


@dataclass(frozen=True)
class SpecificLimit:
    """A specific concentration limit for one class on one substance."""

    hazard_class: HazardClass
    low: Decimal | None            # at or above this, the class applies
    high: Decimal | None           # below this, where the act gives a band
    source: str                    # the line, as the act prints it

    def applies_at(self, concentration: Decimal) -> bool:
        """CLP limits are inclusive at the bottom and exclusive at the top."""
        if self.low is not None and concentration < self.low:
            return False
        return not (self.high is not None and concentration >= self.high)


@dataclass(frozen=True)
class MFactor:
    value: Decimal
    source: str


@dataclass(frozen=True)
class Ate:
    route: str
    value: Decimal
    unit: str
    source: str


@dataclass
class ParsedLimits:
    """Everything Annex VI's limit column says about one substance."""

    specific: list[SpecificLimit]
    m_factors: list[MFactor]
    ates: list[Ate]
    unparsed: list[str]

    def limit_for(self, hazard_class: HazardClass) -> SpecificLimit | None:
        """The specific limit for a class, matching the sub-category first."""
        wanted = str(hazard_class)
        for limit in self.specific:
            if str(limit.hazard_class) == wanted:
                return limit
        for limit in self.specific:
            if limit.hazard_class.generic == hazard_class.generic:
                return limit
        return None


#: A limit the act broke across lines ends mid-sentence - after the colon that
#: introduces it, after the semicolon between class and code, or after the
#: comparison operator itself ("Skin Sens. 1; H317: C >=" / "0,1 %").
_CONTINUES = (":", ";", ">=", "≥", ">", "<=", "≤", "<", "=")
#: A line that is only a footnote marker says nothing about a limit.
_MARKER_ONLY = re.compile(r"^[\s*†‡()\[\]]+$")


def _join_wrapped(lines: list[str]) -> list[str]:
    """Rejoin a limit the act broke across lines, and drop footnote markers."""
    out: list[str] = []
    for line in lines:
        text = " ".join((line or "").split())
        if not text or _MARKER_ONLY.match(text):
            continue
        if out and out[-1].rstrip().endswith(_CONTINUES):
            out[-1] = f"{out[-1]} {text}"
            continue
        # A fragment that opens with a comparison is the tail of the line above.
        if out and re.match(r"^(?:[<>≤≥]=?|C\s*[<>≤≥])", text):
            out[-1] = f"{out[-1]} {text}"
            continue
        out.append(text)
    return out


def parse(lines: list[str]) -> ParsedLimits:
    """Read Annex VI's limit column into numbers, keeping every source line."""
    specific: list[SpecificLimit] = []
    m_factors: list[MFactor] = []
    ates: list[Ate] = []
    unparsed: list[str] = []

    for line in _join_wrapped(lines):
        found = _ATE.search(line)
        if found:
            value = _decimal(found.group("value"))
            if value is not None:
                ates.append(Ate(route=found.group("route").lower(), value=value,
                                unit=found.group("unit"), source=line))
                continue

        found = _M_FACTOR.search(line)
        if found and "ATE" not in line.upper():
            value = _decimal(found.group("value"))
            if value is not None:
                m_factors.append(MFactor(value=value, source=line))
                continue

        hazard_class = None
        head, _, tail = line.partition(":")
        if tail:
            hazard_class = parse_class(head.split(";")[0])
        text = tail or line

        band = _LOWER_FIRST.search(text)
        if band and hazard_class:
            specific.append(SpecificLimit(
                hazard_class=hazard_class, low=_decimal(band.group("low")),
                high=_decimal(band.group("high")), source=line))
            continue
        single = _ONE_SIDED.search(text)
        if single and hazard_class:
            value = _decimal(single.group("value"))
            operator = single.group("op")
            if operator in (">=", "≥", ">"):
                specific.append(SpecificLimit(hazard_class, value, None, line))
            else:
                specific.append(SpecificLimit(hazard_class, None, value, line))
            continue
        bare = _BARE.search(text)
        if bare and hazard_class:
            specific.append(SpecificLimit(
                hazard_class, _decimal(bare.group("value")), None, line))
            continue
        unparsed.append(line)

    return ParsedLimits(specific=specific, m_factors=m_factors, ates=ates,
                        unparsed=unparsed)
