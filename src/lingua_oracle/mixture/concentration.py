"""Reading a concentration as a range.

Sheets write them every way Phase 0 found: a bare number with the unit in the
column header, a single bound, a plain range, a two-sided bound, and a mixed
one. All of them become a pair - a single value is a range whose ends are
equal - because the calculation has to be run at both ends either way.

A bound with no other side is closed at the obvious place: "< 15" is 0 to 15,
">= 90" is 90 to 100. That is an assumption, and it is recorded on the range so
the report can say it was made.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_NUMBER = r"\d+(?:[.,]\d+)?"
_RANGE = re.compile(
    rf"(?P<low_op>[<>]=?|≤|≥)?\s*(?P<low>{_NUMBER})\s*(?:%|\s)?\s*"
    rf"(?:[-–—]|to|bis)\s*(?P<high_op>[<>]=?|≤|≥)?\s*(?P<high>{_NUMBER})")
_ONE_SIDED = re.compile(rf"(?P<op>[<>]=?|≤|≥)\s*(?P<value>{_NUMBER})")
_BARE = re.compile(rf"^\s*(?:ca\.?|approx\.?)?\s*(?P<value>{_NUMBER})\s*%?\s*$")


@dataclass(frozen=True)
class Range:
    low: Decimal
    high: Decimal
    raw: str
    assumption: str = ""

    @property
    def is_single(self) -> bool:
        return self.low == self.high


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def parse(text: str | None) -> Range | None:
    """A concentration as a range, or None where there is no number in it."""
    if not text:
        return None
    cleaned = " ".join(str(text).split())

    found = _RANGE.search(cleaned)
    if found:
        low, high = _decimal(found.group("low")), _decimal(found.group("high"))
        if low is not None and high is not None:
            if low > high:
                low, high = high, low
            return Range(low=low, high=high, raw=cleaned)

    found = _ONE_SIDED.search(cleaned)
    if found:
        value = _decimal(found.group("value"))
        if value is not None:
            if found.group("op") in ("<", "<=", "≤"):
                return Range(Decimal(0), value, cleaned,
                             "an upper bound with no lower one is read as 0 to "
                             f"{value} %")
            return Range(value, Decimal(100), cleaned,
                         "a lower bound with no upper one is read as "
                         f"{value} to 100 %")

    found = _BARE.match(cleaned)
    if found:
        value = _decimal(found.group("value"))
        if value is not None:
            return Range(value, value, cleaned)
    return None
