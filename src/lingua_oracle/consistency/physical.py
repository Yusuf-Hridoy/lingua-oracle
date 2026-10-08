"""C-17: Section 9's flash point and boiling point against Section 2.

The categories are the regulation's own (data/hazard_criteria/<reg>.json,
flammable liquids). Section 9's value is read with its unit - °C or °F,
converted - and any range or limit it is given as ("56 - 58 °C", "> 93 °C").
A value that falls in one category, at every point it can take, gives that
category; one that spans a limit is one to check, as is a value not found
where Section 2 states a flammable liquid.
"""

from __future__ import annotations

import functools
import json
import re
from decimal import Decimal

from lingua_oracle.models import ConsistencyRow
from lingua_oracle.registry import data_dir

CHECK = "C-17"
_FLASH_LABEL = re.compile(r"flash\s*point|flammpunkt|point d['’]éclair|punto de inflamación|"
                          r"flammepunkt|vlampunt|flampunkt|leimahduspiste|punto di infiammabilità",
                          re.IGNORECASE)
_BOIL_LABEL = re.compile(r"(?:initial\s+)?boiling\s+(?:point|range)|siedebeginn|siedepunkt|"
                         r"point (?:initial )?d['’]ébullition|kogepunkt|kookpunt|kokpunkt",
                         re.IGNORECASE)
_VALUE = re.compile(
    r"(?P<cmp>[<>≤≥]=?|approx\.?|ca\.?|~)?\s*(?P<a>-?\d+(?:[.,]\d+)?)\s*(?:°\s*)?(?P<ua>[CF])?\b"
    r"(?:\s*(?:-|–|to|bis|à)\s*(?P<b>-?\d+(?:[.,]\d+)?))?\s*(?:°\s*)?(?P<unit>[CF])\b")
_NONE = re.compile(r"not applicable|not available|no data|n\.?a\.?\b|not determined|"
                   r"nicht anwendbar|keine daten|non applicable|ikke relevant", re.IGNORECASE)


@functools.lru_cache(maxsize=16)
def criteria(regulation: str) -> dict | None:
    path = data_dir() / "hazard_criteria" / f"{regulation}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _celsius(value: Decimal, unit: str) -> Decimal:
    return (value - 32) * 5 / 9 if unit.upper() == "F" else value


def read_value(lines: list[str], label: re.Pattern) -> tuple[str, tuple | None] | None:
    """(printed, (low °C, high °C, low open, high open)) for the first line
    the label is on; the value on that line or the next. None where the label
    is not found; (printed, None) where it is but gives no number."""
    for k, line in enumerate(lines):
        found = label.search(line or "")
        if not found:
            continue
        rest = (line[found.end():] + " " + (lines[k + 1] if k + 1 < len(lines) else "")).strip()
        value = _VALUE.search(rest[:120])
        if value is None or (_NONE.search(rest[:40]) and (value.start() > 30)):
            return " ".join(rest.split())[:80], None
        unit = value.group("unit")
        a = _celsius(Decimal(value.group("a").replace(",", ".")), value.group("ua") or unit)
        b = value.group("b")
        printed = " ".join(value.group(0).split())
        cmp = (value.group("cmp") or "").strip()
        if b is not None:
            hi = _celsius(Decimal(b.replace(",", ".")), unit)
            return printed, (min(a, hi), max(a, hi), False, False)
        if cmp.startswith((">", "≥")):
            return printed, (a, None, cmp == ">", False)
        if cmp.startswith(("<", "≤")):
            return printed, (None, a, False, cmp == "<")
        return printed, (a, a, False, False)
    return None


def _holds(op: str, limit: Decimal, low, high, low_open, high_open) -> bool | None:
    """Whether every value in [low, high] meets "op limit"; None where some
    do and some do not."""
    def test(x):
        return {"<": x < limit, "<=": x <= limit, ">": x > limit, ">=": x >= limit}[op]
    ends = []
    if low is not None:
        ends.append(test(low) if not (low_open and op in (">=",) and low == limit) else True)
    else:
        ends.append(op in ("<", "<="))
    if high is not None:
        ends.append(test(high) if not (high_open and op in ("<=",) and high == limit) else True)
    else:
        ends.append(op in (">", ">="))
    if all(ends):
        return True
    if not any(ends):
        return False
    return None


def category_of(rows: list[dict], flash: tuple, boiling: tuple | None) -> tuple[str | None, str]:
    """(category or None, why) - None with why "ambiguous" where the values
    span a limit, "none" where they meet no category."""
    candidates = []
    for row in rows:
        verdicts = [_holds(op, Decimal(v), *flash) for op, v in row["flash"]]
        if row.get("boiling"):
            if boiling is None:
                verdicts.append(None)
            else:
                verdicts.append(_holds(row["boiling"][0], Decimal(row["boiling"][1]), *boiling))
        if all(v is True for v in verdicts):
            return row["category"], "met"
        if not any(v is False for v in verdicts):
            candidates.append(row["category"])
    if candidates:
        return None, "ambiguous:" + ",".join(candidates)
    return None, "none"


def run(section_9: list[str], stated: list, codes: set[str], regulation: str,
        state: str | None) -> list[ConsistencyRow]:
    held = criteria(regulation)
    flam = (held or {}).get("flammable_liquids", {})
    stated_cats = sorted({c for s in stated for e in s.entries
                          if e["hazard_class"].startswith("flammable liquid")
                          for c in e["category"][:1]}) or sorted(
        {{"H224": "1", "H225": "2", "H226": "3", "H227": "4"}[c] for c in codes
         if c in ("H224", "H225", "H226", "H227")})
    rule = {"quote": flam.get("quote", ""), "citation": flam.get("citation", "")}

    def row(status, text, found="", expected=""):
        return ConsistencyRow(section="9", check=CHECK, key="Flash point", status=status,
                              text=text, quote=rule["quote"], citation=rule["citation"],
                              found=found, expected=expected)

    if flam.get("status") != "ok":
        return [row("na", "Not checked (criterion not on file).")] if stated_cats else []
    if state in ("solid", "gas"):
        return []
    flash = read_value(section_9, _FLASH_LABEL)
    boiling = read_value(section_9, _BOIL_LABEL)
    said = f"Flam. Liq. {stated_cats[0]}" if stated_cats else "no flammable-liquid category"
    if flash is None or flash[1] is None:
        if not stated_cats:
            return []
        printed = f" (“{flash[0]}”)" if flash else ""
        return [row("check", f"Section 2 states {said}, but Section 9 gives no flash point{printed} "
                    "to hold it against.", found=flash[0] if flash else "")]
    category, why = category_of(flam["categories"], flash[1], boiling[1] if boiling else None)
    shown = f"flash point {flash[0]}" + (f", initial boiling point {boiling[0]}"
                                         if boiling and boiling[1] else "")
    if category is None and why.startswith("ambiguous"):
        options = why.split(":", 1)[1]
        return [row("check", f"Section 9 gives {shown}: that could be category "
                    f"{options.replace(',', ' or ')} - a value is missing or spans a limit.",
                    found=shown)]
    if category is None:
        if stated_cats:
            return [row("fix", f"Section 9 gives {shown}, which meets no flammable-liquid "
                        f"category; Section 2 states {said}.", found=said, expected="not classified")]
        return [row("ok", f"Section 9 gives {shown}: not a flammable liquid, and Section 2 states "
                    "none.")]
    if not stated_cats:
        return [row("fix", f"Section 9 gives {shown}: Flammable liquid, Category {category}; "
                    "Section 2 states none.", expected=f"Category {category}")]
    if category not in stated_cats:
        return [row("fix", f"Section 9 gives {shown}: Category {category}; Section 2 states "
                    f"{said}.", found=said, expected=f"Category {category}")]
    return [row("ok", f"Section 9 gives {shown}: Category {category}, as Section 2 states.")]
