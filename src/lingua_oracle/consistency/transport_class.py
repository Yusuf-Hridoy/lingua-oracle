"""C-23: Section 14's transport class against what the sheet says of the
product itself - Section 9's physical state and flash point, Section 2's
classification - by the UN Model Regulations' own definitions (part 2,
quoted in data/lists/un_dangerous_goods.json):

* 2.2.1.1 - a gas is a substance which at 50 °C has a vapour pressure
  greater than 300 kPa, or is completely gaseous at 20 °C;
* 2.3.1.2 - flammable liquids are liquids which give off a flammable vapour
  at not more than 60 °C closed-cup (65.6 °C open-cup): the limits are read
  from the quoted text, not written here.

A liquid (Section 9, or a flammable liquid classification in Section 2)
whose flash point is within the Class 3 limit, shipped under a Class 2
entry, is a fault. The flash point is Section 9's; where Section 9 gives
none, the stated Flam. Liq. category's own criterion stands for it
(data/hazard_criteria, the regulation's table: category 2 is "flash point
< 23 °C"), and the row says so; so is a gas shipped under Class 3. Where the sheet does
not say enough to decide - no state, no flash point - nothing is reported.
An aerosol is a receptacle of gas that may hold a liquid, so a sheet that
says aerosol is left alone.
"""

from __future__ import annotations

import re

from lingua_oracle.consistency import physical, transport
from lingua_oracle.keys.builders import lists
from lingua_oracle.models import ConsistencyRow

CHECK = "C-23"
_AEROSOL = re.compile(r"aerosol", re.IGNORECASE)
_OPEN_CUP = re.compile(r"open[- ]?cup|\bo\.\s?c\.|cleveland", re.IGNORECASE)


def _classes(section_14: list[str], regulation: str) -> list[tuple[str, str]]:
    """(UN number, class) for each block: the class the sheet prints, or
    the list's for its number where the sheet prints none."""
    read = transport.read(section_14)
    un, dot = lists.load("un_dangerous_goods"), lists.load("us_dot_hmt")
    out: list[tuple[str, str]] = []
    for mode, block in read:
        hazard_class = block["class"]
        if not hazard_class and block["number"]:
            use_dot = regulation == "us_osha" and mode in ("", "DOT", "US DOT", "49 CFR")
            held = (dot if use_dot else un) or {}
            found = {m.group(0) for e in held.get("entries", []) if e["id"] == block["number"]
                     and (m := re.match(r"\d(?:\.\d)?", e["class"] or ""))}
            hazard_class = found.pop() if len(found) == 1 else ""
        if hazard_class and (block["number"] or "", hazard_class) not in out:
            out.append((block["number"] or "", hazard_class))
    return out


def _flash(section_9: list[str]) -> tuple[str, object, bool] | None:
    """(printed, highest °C, open-cup) - None where no number is given."""
    read = physical.read_value(section_9, physical._FLASH_LABEL)
    if read is None or read[1] is None or read[1][1] is None:
        return None
    k = next(i for i, line in enumerate(section_9) if physical._FLASH_LABEL.search(line or ""))
    near = " ".join(section_9[k:k + 2])
    return read[0], read[1][1], bool(_OPEN_CUP.search(near))


def run(section_14: list[str], section_9: list[str], section_2: list[str], regulation: str,
        state: str | None, flammable: list[str]) -> list[ConsistencyRow]:
    held = lists.load("un_dangerous_goods") or {}
    rules = held.get("class_rules") or {}
    gas, liquid = rules.get("2.2.1.1", {}), rules.get("2.3.1.2", {})
    limits = rules.get("flash_point_limit") or {}
    if not section_14 or not gas.get("quote") or not liquid.get("quote") or not limits:
        return []
    if _AEROSOL.search(" ".join(section_14 + section_9 + section_2)):
        return []
    rule = {"quote": f"{gas['quote']} / {liquid['quote']}",
            "citation": f"{gas['citation']} and {liquid['citation'].rsplit(', ', 1)[-1]}"}
    flash = _flash(section_9)
    limit = limits["open_cup" if flash and flash[2] else "closed_cup"]
    within = flash is not None and float(flash[1]) <= limit
    point = (f"its flash point {flash[0]} is within Class 3's limit ({limit:g} °C "
             f"{'open' if flash[2] else 'closed'}-cup)") if within else ""
    if flash is None and flammable:
        # Section 9 gives no flash point: the stated category's criterion does.
        held_criteria = (physical.criteria(regulation) or {}).get("flammable_liquids", {})
        category = next((c for c in held_criteria.get("categories", [])
                         if c["category"] == flammable[0]), None)
        upper = [float(v) for op, v in (category or {}).get("flash", []) if op in ("<", "<=")]
        if upper and min(upper) <= limit:
            within = True
            point = (f"Section 9 gives no flash point, but Flam. Liq. {flammable[0]} is "
                     f"“{category['raw']}” ({held_criteria.get('citation', '')}) - within Class "
                     f"3's limit ({limit:g} °C closed-cup)")
    as_liquid = state == "liquid" or bool(flammable)
    said = ("Section 9 says liquid" if state == "liquid" else
            f"Section 2 classifies it Flam. Liq. {flammable[0]}" if flammable else "")
    rows: list[ConsistencyRow] = []
    for number, hazard_class in _classes(section_14, regulation):
        key = f"{number + ' ' if number else ''}class {hazard_class}"
        family = hazard_class.split(".")[0]
        if family == "2" and as_liquid and within:
            rows.append(ConsistencyRow(
                section="14", check=CHECK, key=key, status="fix",
                text=f"Section 14 gives Class {hazard_class}, gases; {said}, and {point}.",
                quote=rule["quote"], citation=rule["citation"], found=hazard_class,
                expected="3"))
        elif family == "3" and state == "gas":
            rows.append(ConsistencyRow(
                section="14", check=CHECK, key=key, status="fix",
                text=f"Section 14 gives Class {hazard_class}, flammable liquids; Section 9 says "
                     "the product is a gas.", quote=rule["quote"], citation=rule["citation"],
                found=hazard_class))
        elif family == "3" and as_liquid and within:
            rows.append(ConsistencyRow(
                section="14", check=CHECK, key=key, status="ok",
                text=f"Class {hazard_class} fits: {said}, and {point}.",
                citation=liquid["citation"]))
        elif family == "2" and state == "gas":
            rows.append(ConsistencyRow(
                section="14", check=CHECK, key=key, status="ok",
                text=f"Class {hazard_class} fits: Section 9 says the product is a gas.",
                citation=gas["citation"]))
    return rows
