"""What is in the product, as (CAS, name, concentration as printed).

From the app's record where the product is one it holds; otherwise from
Section 3 - its table where one is read, and its lines, so an ingredient
printed without hazard codes is not lost.
"""

from __future__ import annotations

import re

from lingua_oracle.keys.builders.lists import cas_valid

_CAS = re.compile(r"(?<![\d-])\d{2,7}-\d{2}-\d(?![\d-])")
_SHARE = re.compile(r"(?:[<>]=?|≤|≥)?\s*\d+(?:[.,]\d+)?\s*%?\s*(?:[-–—]|to)\s*(?:[<>]=?|≤|≥)?\s*"
                    r"\d+(?:[.,]\d+)?\s*%?|(?:[<>]=?|≤|≥)?\s*\d+(?:[.,]\d+)?\s*%")


def from_sheet(path: str, section_three: list[str]) -> list[dict]:
    from lingua_oracle.ingredients.from_pdf import ingredients_in_section_three

    out: dict[str, dict] = {}
    try:
        table = ingredients_in_section_three(path)
    except Exception:  # noqa: BLE001 - a sheet whose Section 3 cannot be read
        table = []
    for item in table:
        if not (item.cas or "").strip():
            continue
        out.setdefault(item.cas.strip(), {"cas": item.cas.strip(), "name": item.name or "",
                                  "concentration": item.concentration or ""})
    for k, line in enumerate(section_three):
        for cas in _CAS.findall(line or ""):
            if not cas_valid(cas):
                continue
            after = (line or "")[(line or "").index(cas) + len(cas):]
            found = _SHARE.search(after)
            share = found.group(0).strip() if found else ""
            if not share and k + 1 < len(section_three):
                # A table cell below: the concentration alone on the next line,
                # "%" in the column's heading ("CONCENTRATION (%)" / "77").
                below = (section_three[k + 1] or "").strip()
                if _SHARE.fullmatch(below) or re.fullmatch(r"\d+(?:[.,]\d+)?", below):
                    share = below
            row = out.setdefault(cas, {"cas": cas, "name": (line or "").split(cas)[0].strip(" |,;:"),
                                       "concentration": ""})
            if not row["concentration"] and share:
                row["concentration"] = share
    return list(out.values())


def from_app(ingredients) -> tuple[list[dict], dict[str, list[str]]]:
    rows, codes = [], {}
    for item in ingredients:
        if not item.cas:
            continue
        rows.append({"cas": item.cas, "name": item.name or "",
                     "concentration": item.concentration or ""})
        codes[item.cas] = list(item.h_codes)
    return rows, codes
