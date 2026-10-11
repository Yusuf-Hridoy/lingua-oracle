"""What Section 9 says that a special rule turns on: the pH, and the
viscosity - kinematic, at which temperature - as printed.

Read as the sheet gives them and no further: a dynamic viscosity is not
turned into a kinematic one, nor a value at 20 °C into one at 40 °C; the
rule that needs the other is then "can't confirm", with the reason.
"""

from __future__ import annotations

import re

_PH = re.compile(r"(?<![A-Za-z])pH\b(?!\s*(?:as a solution|of a|\(of))", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\d.])(-?\d+(?:[.,]\d+)?)")
_VISCOSITY = re.compile(r"(kinematic\s+|dynamic\s+)?viscosity", re.IGNORECASE)
_KINEMATIC_UNIT = re.compile(r"mm\s?(?:2|²)\s?/\s?s|cSt|centistokes", re.IGNORECASE)
_DYNAMIC_UNIT = re.compile(r"mPa\s?[·.\s]?s|cP\b|centipoise|Pa\s?[·.\s]?s", re.IGNORECASE)
_TEMPERATURE = re.compile(r"(?:at|@|\()\s*(-?\d+(?:[.,]\d+)?)\s*°?\s*C\b", re.IGNORECASE)
_NONE = re.compile(r"not (?:available|applicable|determined|specified|relevant)|no data|n/?a\b",
                   re.IGNORECASE)


def _value_text(lines: list[str], k: int, label_end: int) -> str:
    rest = (lines[k] or "")[label_end:].strip(" :：-–")
    if not rest and k + 1 < len(lines):
        rest = (lines[k + 1] or "").strip(" :：-–")
    return rest


def read_ph(lines: list[str]) -> dict:
    """{"value": 12.5, "text": "12.5 (1 % solution)"} - value None where
    Section 9 gives no number for it."""
    for k, line in enumerate(lines):
        found = _PH.search(line or "")
        if not found or found.start() > 4:
            continue
        text = _value_text(lines, k, found.end())
        if _NONE.match(text):
            return {"value": None, "text": text}
        number = _NUMBER.search(text[:40])
        value = float(number.group(1).replace(",", ".")) if number else None
        if value is not None and not 0 <= value <= 14:
            value = None
        return {"value": value, "text": " ".join(text.split())[:80]}
    return {}


def read_viscosity(lines: list[str]) -> dict:
    """{"value", "kind" (kinematic / dynamic / ""), "temperature", "text"}."""
    for k, line in enumerate(lines):
        found = _VISCOSITY.search(line or "")
        if not found:
            continue
        text = _value_text(lines, k, found.end())
        label = (found.group(1) or "").strip().lower()
        whole = f"{line} {text}"
        if _NONE.match(text):
            return {"value": None, "kind": label, "temperature": None, "text": text}
        number = _NUMBER.search(text)
        kind = ("kinematic" if _KINEMATIC_UNIT.search(text) else
                "dynamic" if _DYNAMIC_UNIT.search(text) else label)
        temperature = _TEMPERATURE.search(whole)
        return {"value": float(number.group(1).replace(",", ".")) if number else None,
                "kind": kind,
                "temperature": float(temperature.group(1).replace(",", ".")) if temperature
                else None,
                "text": " ".join(text.split())[:80]}
    return {}
