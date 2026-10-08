"""What Section 11 prints about acute toxicity, ingredient by ingredient.

A sheet often gives each ingredient's LD50 or LC50 under its own name or CAS
number, and sometimes an ATE for the mixture as a whole. An ingredient's value
is the second place its ATE is taken from (`mixture/acute.py`), after its list
entry; the mixture's own value is evidence for Section 2, shown beside the
verdict, never used to overrule the calculation.

A value is attributed only to an ingredient named or numbered on its line or
in the lines just above it within Section 11. A value written as "> 2000" is a
limit test and gives no ATE (CLP 3.1.3.6.1(c)): it is recorded and not used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from lingua_oracle.mixture.acute import Section11Ate

_START = re.compile(
    r"^\s*(?:section\s*)?11[.):]?\s*(toxicological|toxikologische|informations "
    r"toxicologiques|información toxicológica|informazioni tossicologiche|"
    r"toksikologiske|toxicologische)", re.I)
_END = re.compile(
    r"^\s*(?:section\s*)?12[.):]?\s*(ecological|umweltbezogene|informations "
    r"écologiques|información ecológica|informazioni ecologiche|miljø|"
    r"ecologische)", re.I)
_CAS = re.compile(r"(?<![\d-])(\d{2,7}-\d{2}-\d)(?![\d-])")
_VALUE = re.compile(
    r"\b(?P<kind>LD\s*50|LC\s*50|ATE)\b(?P<between>[^0-9<>≥≤]{0,80}?)"
    r"(?P<op>[<>≥≤]=?)?\s*(?P<value>\d{1,3}(?:[ ,.]\d{3})+(?![\d])|\d+(?:[.,]\d+)?)"
    r"\s*(?P<unit>mg/kg|mg/l|mg/L|ppmV|ppm)", re.I)
#: The words that put a value on the mixture rather than on one ingredient.
_MIXTURE = re.compile(r"\b(mixture|product|ATE\s*mix|preparation)\b", re.I)
#: How far above a value its ingredient's name may sit.
_REACH = 4


@dataclass
class SectionEleven:
    by_cas: dict[str, list[Section11Ate]] = field(default_factory=dict)
    #: Lines giving an ATE or LD50/LC50 for the mixture itself, as printed.
    mixture: list[str] = field(default_factory=list)
    #: Values not used, with why: limit tests, values for no named ingredient.
    ignored: list[str] = field(default_factory=list)


def _lines(lines) -> list[str]:
    out, inside = [], False
    for line in lines:
        text = line.text or ""
        if _START.match(text):
            inside = True
            continue
        if inside and _END.match(text):
            break
        if inside:
            out.append(text)
    return out


def _number(text: str) -> Decimal | None:
    cleaned = text.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", cleaned):     # 4,700 = four thousand
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned.replace(",", "."))
    except InvalidOperation:
        return None


def _route(text: str) -> str | None:
    lowered = text.lower()
    if "oral" in lowered:
        return "oral"
    if "dermal" in lowered or "skin" in lowered or "cutane" in lowered:
        return "dermal"
    if "inhal" in lowered:
        return "inhalation"
    return None


def _form(text: str, unit: str) -> str | None:
    lowered = text.lower()
    if "dust" in lowered or "mist" in lowered or "aerosol" in lowered:
        return "dusts_mists"
    if "vapour" in lowered or "vapor" in lowered:
        return "vapours"
    if "gas" in lowered or unit.lower().startswith("ppm"):
        return "gases"
    return None


def read(lines, ingredients: list[tuple[str, str | None]]) -> SectionEleven:
    """Section 11's acute values, by the CAS number of the ingredient they are for.

    `ingredients` are (CAS, name) pairs from Section 3.
    """
    found = SectionEleven()
    text = _lines(lines)
    names = [(cas, (name or "").lower()) for cas, name in ingredients if cas]
    recent: list[tuple[int, str]] = []        # (line number, CAS) mentions
    for number, line in enumerate(text):
        lowered = line.lower()
        named_here = None
        for cas, name in names:
            if cas in line or (len(name) >= 4 and name in lowered):
                recent.append((number, cas))
                named_here = cas
        for match in _VALUE.finditer(line):
            value = _number(match.group("value"))
            if value is None:
                continue
            context = line[:match.start()] + match.group("between")
            route = _route(context) or _route(line)
            if match.group("kind").upper().startswith("LC"):
                route = route or "inhalation"
            if route is None:
                continue
            raw = " ".join(line.split())[:160]
            if (match.group("op") or "").startswith((">", "≥")):
                found.ignored.append(f"{raw} - a limit test, which gives no ATE")
                continue
            # A line about the mixture is the mixture's, whatever ingredient
            # was named above it; otherwise the nearest ingredient named.
            if named_here is None and _MIXTURE.search(line):
                found.mixture.append(raw)
                continue
            owner = named_here or next((cas for n, cas in reversed(recent)
                                        if number - n <= _REACH), None)
            if owner is None:
                found.ignored.append(f"{raw} - names no ingredient")
                continue
            found.by_cas.setdefault(owner, []).append(Section11Ate(
                route=route, form=_form(line, match.group("unit")) if route == "inhalation"
                else None, value=value, raw=raw))
    return found
