"""C-18 and C-19: the mixture's own test data, against Section 2.

C-18 - an LD50, LC50 or ATE Section 11 gives for the mixture as a whole
(not an ingredient) is put in the regulation's acute toxicity band for its
route (data/acute_toxicity/<reg>.json) and held against Section 2.

C-19 - an LC50, EC50 or ErC50 (short-term) or NOEC/ECx (long-term) Section
12 gives for the mixture as a whole is put in the regulation's aquatic
criteria (data/hazard_criteria/<reg>.json), which its text applies to a
mixture tested as a whole, and held against Section 2. The long-term
categories depend on rapid degradability: Section 12's own "readily
biodegradable" decides, and where it says nothing and the answer would
differ, the row is one to check.

Where Section 2 is stricter than the data it is one to check - it may rest
on other information - and where it is weaker, a fault, as the mixture
verdicts have it.

A value is the mixture's only where its line, or the one above, says so
(mixture, product, preparation) and names no CAS number. Ingredient values
are never mixture values.
"""

from __future__ import annotations

import re
from decimal import Decimal

from lingua_oracle.models import ConsistencyRow

_MIXTURE = re.compile(r"\b(mixture|product|preparation|gemisch|mélange|mezcla|blanding)\b",
                      re.IGNORECASE)
_CAS = re.compile(r"(?<![\d-])\d{2,7}-\d{2}-\d(?![\d-])")
_ACUTE_CODES = {"H300": ("oral", ("1", "2")), "H301": ("oral", ("3",)), "H302": ("oral", ("4",)),
                "H310": ("dermal", ("1", "2")), "H311": ("dermal", ("3",)),
                "H312": ("dermal", ("4",)), "H330": ("inhalation", ("1", "2")),
                "H331": ("inhalation", ("3",)), "H332": ("inhalation", ("4",))}


def _mixture_lines(lines: list[str]) -> list[tuple[int, str]]:
    out = []
    for k, line in enumerate(lines):
        here = line or ""
        above = lines[k - 1] if k else ""
        if _CAS.search(here):
            continue
        if _MIXTURE.search(here) or (_MIXTURE.search(above or "") and not _CAS.search(above or "")):
            out.append((k, here))
    return out


# -- C-18 --------------------------------------------------------------------------

def mixture_acute(section_11: list[str], regulation: str, state: str | None) -> dict[str, dict]:
    """Per route, what Section 11's value for the mixture as a whole gives:
    {"oral": {"category": "4" | "none" | None (cannot tell), "printed",
    "band", "citation"}}. The first value per route is taken."""
    from lingua_oracle.mixture import acute_table
    from lingua_oracle.mixture.section_eleven import _VALUE, _form, _route

    rules = acute_table.load(regulation)
    out: dict[str, dict] = {}
    if rules is None:
        return out
    for _k, line in _mixture_lines(section_11):
        for found in _VALUE.finditer(line):
            value = Decimal(found.group("value").replace(" ", "").replace(",", "."))
            route = _route(line[:found.start()] + found.group("between")) or _route(line)
            if found.group("kind").upper().startswith("LC"):
                route = route or "inhalation"
            if route is None or route in out:
                continue
            unit = found.group("unit")
            if route == "inhalation":
                form = _form(line, unit)
                forms = [form] if form else ({"liquid": ["vapours"], "solid": ["dusts_mists"],
                                              "gas": ["gases"]}.get(state or "",
                                                                    ["vapours", "dusts_mists"]))
            else:
                forms = [route]
            op = (found.group("op") or "").strip()
            cats = set()
            for form in forms:
                if op.startswith((">", "≥")):
                    last = max(b.high for b in rules.bands[form])
                    cats.add("none" if value >= last else None)
                else:
                    cats.add(rules.category(form, value) or "none")
            category = cats.pop() if len(cats) == 1 else None
            out[route] = {
                "category": category, "printed": " ".join(found.group(0).split()),
                "band": rules.band_text(forms[0], category) if category not in (None, "none")
                else "", "citation": rules.citations.get("bands", "")}
    return out


def acute(section_11: list[str], stated, codes: set[str], regulation: str,
          state: str | None) -> list[ConsistencyRow]:
    said: dict[str, set[str]] = {}
    for c in stated:
        for e in c.entries:
            if e["hazard_class"].startswith("acute tox") and e["subclass"] in _routes():
                said.setdefault(e["subclass"], set()).update(e["category"][:1])
    for code in codes:
        if code in _ACUTE_CODES:
            route, cats = _ACUTE_CODES[code]
            said.setdefault(route, set()).update(cats)
    rows: list[ConsistencyRow] = []
    for route, got in mixture_acute(section_11, regulation, state).items():
        printed, category = got["printed"], got["category"]
        rule = {"quote": f"{printed} - {route}", "citation": got["citation"]}
        key = f"Acute toxicity, {route}"
        stated_here = said.get(route, set())
        if category is None:
            rows.append(_row("11", "C-18", key, "check", f"Section 11 gives the mixture's "
                             f"{printed}: its category cannot be read from that alone.", rule,
                             found=printed))
            continue
        words = "not classified" if category == "none" else f"Category {category}"
        band = f" ({got['band']}, {got['citation']})" if got["band"] else ""
        if (category == "none" and not stated_here) or category in stated_here:
            rows.append(_row("11", "C-18", key, "ok", f"Section 11 gives the mixture's "
                             f"{printed}: {words}{band}, as Section 2 states.", rule))
        else:
            rows.append(_row("11", "C-18", key, _mismatch_status(category, stated_here),
                             f"Section 11 gives the mixture's {printed}: {words}{band}; "
                             f"Section 2 states {_said(stated_here, 'Acute Tox.')}.", rule,
                             found=printed, expected=words))
    return rows


def _stricter_in_section_2(category: str, stated: set[str]) -> bool:
    """Section 2 states a stricter category than the data gives: a lower
    number, or any category where the data gives none."""
    if not stated:
        return False
    strictest = min(stated, key=lambda c: (int(re.sub(r"\D", "", c) or 9), c))
    if category == "none":
        return True
    return int(re.sub(r"\D", "", strictest) or 9) < int(re.sub(r"\D", "", category) or 9)


def _mismatch_status(category: str, stated: set[str]) -> str:
    """As the mixture verdicts have it: Section 2 stricter than the data may
    rest on other information - one to check; weaker is a fault."""
    return "check" if _stricter_in_section_2(category, stated) else "fix"


def _routes():
    return ("oral", "dermal", "inhalation")


def _said(cats: set[str], name: str) -> str:
    return " / ".join(f"{name} {c}" for c in sorted(cats)) if cats else "none"


def _row(section, check, key, status, text, rule, *, found="", expected="") -> ConsistencyRow:
    return ConsistencyRow(section=section, check=check, key=key, status=status, text=text,
                          quote=rule.get("quote", ""), citation=rule.get("citation", ""),
                          found=found, expected=expected)


# -- C-19 --------------------------------------------------------------------------

_AQUATIC = re.compile(
    r"\b(?P<kind>LC\s*50|ErC\s*50|EbC\s*50|EC\s*50|NOEC|EC\s*10|ECx|E[rb]?C\s*10)\b"
    r"(?P<between>(?:[^0-9<>≥≤]|\d+\s*(?:h|hr|hrs|hours?|d|days?)\b){0,80}?)"
    r"(?P<op>[<>≤≥]=?)?\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>mg/l|mg/L|µg/l|μg/l|µg/L|μg/L)")
_AQUATIC_CODES = {"H400": ("acute", "1"), "H401": ("acute", "2"), "H402": ("acute", "3"),
                  "H410": ("chronic", "1"), "H411": ("chronic", "2"), "H412": ("chronic", "3"),
                  "H413": ("chronic", "4")}


def _band(rows: list[dict], value: Decimal) -> str:
    for row in sorted(rows, key=lambda r: Decimal(r["upper"])):
        lower = Decimal(row["lower"]) if row.get("lower") else None
        if value <= Decimal(row["upper"]) and (lower is None or value > lower):
            return row["category"]
    return "none"


def aquatic(section_12: list[str], stated, codes: set[str], held: dict | None) -> list[ConsistencyRow]:
    criteria = (held or {}).get("aquatic", {})
    if criteria.get("status") == "not_adopted":
        return []
    values: dict[str, list[tuple[Decimal, str, str]]] = {"acute": [], "chronic": []}
    for _k, line in _mixture_lines(section_12):
        for found in _AQUATIC.finditer(line):
            value = Decimal(found.group("value").replace(",", "."))
            if found.group("unit").lower().startswith(("µ", "μ")):
                value = value / 1000
            kind = "acute" if "50" in found.group("kind") else "chronic"
            values[kind].append((value, (found.group("op") or "").strip(),
                                 " ".join(found.group(0).split())))
    if not values["acute"] and not values["chronic"]:
        return []
    if criteria.get("status") != "ok":
        return [_row("12", "C-19", "Aquatic", "na", "Not checked (criterion not on file).", {})]
    rule = {"quote": ((held or {}).get("aquatic_mixture") or {}).get("quote", ""),
            "citation": criteria.get("citation", "")}
    text = " ".join(section_12).lower()
    rapid = ("not readily biodegradable" not in text and "readily biodegradable" in text)
    nonrapid = "not readily biodegradable" in text
    said: dict[str, set[str]] = {"acute": set(), "chronic": set()}
    for c in stated:
        for e in c.entries:
            sub = e["subclass"]
            if "acute" in sub or "short" in sub:
                said["acute"].update(e["category"][:1])
            elif "chronic" in sub or "long" in sub:
                said["chronic"].update(e["category"][:1])
    for code in codes:
        if code in _AQUATIC_CODES:
            kind, cat = _AQUATIC_CODES[code]
            said[kind].add(cat)
    rows: list[ConsistencyRow] = []
    for kind in ("acute", "chronic"):
        if not values[kind]:
            continue
        plain = [v for v in values[kind] if not v[1].startswith((">", "≥"))]
        if not plain:
            continue
        value, _op, printed = min(plain, key=lambda v: v[0])
        if kind == "acute":
            category = _band([r for r in criteria["categories"] if r["kind"] == "acute"], value)
        else:
            options = {name: _band([r for r in criteria["categories"] if r["kind"] == name], value)
                       for name in ("chronic_rapid", "chronic_nonrapid")}
            if rapid:
                category = options["chronic_rapid"]
            elif nonrapid:
                category = options["chronic_nonrapid"]
            elif len(set(options.values())) == 1:
                category = options["chronic_rapid"]
            else:
                rows.append(_row("12", "C-19", "Aquatic, long-term", "check", f"Section 12 gives "
                                 f"the mixture's {printed}: Chronic {options['chronic_rapid']} if "
                                 f"rapidly degradable, Chronic {options['chronic_nonrapid']} if not "
                                 "- Section 12 does not say which.", rule, found=printed))
                continue
        name = "Acute" if kind == "acute" else "Chronic"
        words = "not classified" if category == "none" else f"Aquatic {name} {category}"
        key = "Aquatic, short-term" if kind == "acute" else "Aquatic, long-term"
        if (category == "none" and not said[kind]) or category in said[kind]:
            rows.append(_row("12", "C-19", key, "ok", f"Section 12 gives the mixture's {printed}: "
                             f"{words}, as Section 2 states.", rule))
        else:
            rows.append(_row("12", "C-19", key, _mismatch_status(category, said[kind]),
                             f"Section 12 gives the mixture's {printed}: {words}; Section 2 "
                             f"states {_said(said[kind], f'Aquatic {name}')}.",
                             rule, found=printed, expected=words))
    return rows
