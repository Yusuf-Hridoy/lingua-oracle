"""C-20: the sheet against itself - not a requirement any regulation's text
states, and so never more than one to check.

* the product name Section 1 gives, against a "Product name: ..." printed in
  the running header of the pages;
* every revision date the sheet prints - on the first page, in its running
  header, in Section 16 - against each other.
"""

from __future__ import annotations

import re
from collections import Counter

from lingua_oracle.models import ConsistencyRow

CHECK = "C-20"
_NOT_REGULATORY = {"quote": "", "citation": "Internal consistency - not a requirement in the "
                                            "regulation's text"}
_PRODUCT_LABEL = re.compile(r"(?:product\s*name|trade\s*name|produktname|handelsname|"
                            r"nom du produit|nombre del producto)\s*[:：]\s*(?P<value>.+)$",
                            re.IGNORECASE)
_REVISION = re.compile(r"revision\s*date|date\s*of\s*revision|revised(?:\s*on)?|revision\s*:|"
                       r"überarbeitet\s*am|revisionsdato|date de (?:la )?révision|"
                       r"fecha de revisión|data di revisione|herzieningsdatum", re.IGNORECASE)
_MONTHS = {m: n for n, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                       "sep", "oct", "nov", "dec"), start=1)}


def _date_key(text: str) -> tuple | None:
    """The numbers a date is made of, whatever order it prints them in."""
    from lingua_oracle.structure.reader import _DATE

    found = _DATE.search(text)
    if not found:
        return None
    raw = found.group(0)
    numbers = [int(n) for n in re.findall(r"\d+", raw)]
    month = re.search(r"[A-Za-zäéû]{3,}", raw)
    if month and month.group(0)[:3].lower() in _MONTHS:
        numbers.append(_MONTHS[month.group(0)[:3].lower()])
    numbers = [n + 2000 if n < 100 and len(numbers) == 3 and n == numbers[-1] else n
               for n in numbers]
    return tuple(sorted(numbers))


def _headers(document) -> list[str]:
    """Lines printed at the top of two or more pages: the running header."""
    tops: Counter[str] = Counter()
    for page in document.pages:
        seen = set()
        for line in (page.raw_lines or page.lines):
            if line.bbox[1] > 110 or line.bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            key = re.sub(r"\d+", "#", " ".join((line.text or "").split()))
            if key and key not in seen:
                seen.add(key)
                tops[key] += 1
    repeated = {k for k, n in tops.items() if n >= 2}
    out = []
    for page in document.pages:
        for line in (page.raw_lines or page.lines):
            key = re.sub(r"\d+", "#", " ".join((line.text or "").split()))
            if key in repeated and line.bbox[1] <= 110:
                out.append(" ".join((line.text or "").split()))
    return out


def run(document, section_16: list[str], product: str | None) -> list[ConsistencyRow]:
    from lingua_oracle.ingredients.matching import normalised

    rows: list[ConsistencyRow] = []
    headers = _headers(document) if len(document.pages) > 1 else []
    if product:
        named = [m.group("value").strip() for h in headers
                 if (m := _PRODUCT_LABEL.search(h))]
        different = sorted({n for n in named if normalised(n) != normalised(product)})
        if different:
            rows.append(ConsistencyRow(
                section="1", check=CHECK, key="Product name", status="check",
                text=f"Section 1 names the product “{product}”; the page header names it "
                     f"“{different[0]}”.", citation=_NOT_REGULATORY["citation"],
                found=different[0], expected=product))
        elif named:
            rows.append(ConsistencyRow(
                section="1", check=CHECK, key="Product name", status="ok",
                text="The page header names the product as Section 1 does.",
                citation=_NOT_REGULATORY["citation"]))
    places: list[tuple[str, str, tuple]] = []
    first = document.pages[0] if document.pages else None
    if first is not None:
        for line in (first.raw_lines or first.lines):
            text = " ".join((line.text or "").split())
            if _REVISION.search(text) and (key := _date_key(text[_REVISION.search(text).start():])):
                places.append(("page 1", text, key))
    for text in headers:
        if _REVISION.search(text) and (key := _date_key(text[_REVISION.search(text).start():])):
            places.append(("the page header", text, key))
    for k, text in enumerate(section_16):
        if _REVISION.search(text or ""):
            window = (text or "")[_REVISION.search(text).start():] + " " + (
                section_16[k + 1] if k + 1 < len(section_16) else "")
            if key := _date_key(window):
                places.append(("Section 16", text, key))
    keys = {p[2] for p in places}
    if len(keys) > 1:
        shown = "; ".join(sorted({f"{where}: “{text[:60]}”" for where, text, _ in places}))
        rows.append(ConsistencyRow(
            section="1", check=CHECK, key="Revision date", status="check",
            text=f"The revision date differs where it appears - {shown}.",
            citation=_NOT_REGULATORY["citation"]))
    elif len(places) > 1:
        rows.append(ConsistencyRow(
            section="1", check=CHECK, key="Revision date", status="ok",
            text=f"The same revision date wherever it appears ({len(places)} places).",
            citation=_NOT_REGULATORY["citation"]))
    return rows
