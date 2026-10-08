"""What Section 2 classifies the product as, read against the regulation's
own label-element table (data/label_elements/<reg>.json).

Two ways a sheet writes a classification, both read:

* the class and category code the regulation itself uses - "Flam. Liq. 2",
  "Acute Tox. 4" - where its text has such codes (CLP, GB CLP);
* the class named in words with its category - "Flammable liquids,
  Category 2", "Acute toxicity - Oral - Category 4" - matched to the class
  names in the regulation's own table.

A classification is held as the table entries it can be: "Acute Tox. 4"
without a route is any of oral, dermal or inhalation.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field

from lingua_oracle.registry import data_dir

_ROUTES = ("oral", "dermal", "inhalation")


@functools.lru_cache(maxsize=16)
def table(regulation: str) -> dict | None:
    path = data_dir() / "label_elements" / f"{regulation}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Classification:
    text: str                                  # as printed: "Flam. Liq. 2"
    entries: list[dict] = field(default_factory=list)
    line: int = -1

    @property
    def h_codes(self) -> set[str]:
        return {c for e in self.entries for c in e["h_codes"]}

    @property
    def label(self) -> str:
        return self.text


def _key(code: str) -> str:
    return re.sub(r"[\s.]", "", code).lower()


def _stem(word: str) -> str:
    word = word.lower()
    for suffix in ("es", "s"):
        if word.endswith(suffix) and len(word) > 4:
            word = word[:-len(suffix)]
            break
    return word[:6].replace("z", "s")


def _stems(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "after", "category", "categories", "hazard",
            "hazards", "substance", "substances", "mixture", "mixtures", "which"}
    return {_stem(w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in stop}


_CATEGORY_WORD = re.compile(
    r"\b(?:Category|Cat\.?|Kategorie|Catégorie|Categoría|Type|Typ|Division)\s*"
    r"(?P<cat>\d(?:\.\d)?[A-C]?|[A-G]{1,2})\b", re.IGNORECASE)


def read(lines: list[str], regulation: str) -> list[Classification]:
    """Every classification Section 2's lines state, each with the table
    entries it can stand for."""
    held = table(regulation)
    if held is None:
        return []
    entries = held["entries"]
    by_code: dict[str, list[dict]] = {}
    for entry in entries:
        for code in entry.get("codes", []):
            by_code.setdefault(_key(code), []).append(entry)
    out: list[Classification] = []
    seen: set[tuple] = set()

    def keep(text: str, found: list[dict], index: int) -> None:
        marker = (tuple(sorted(id(e) for e in found)),)
        if found and marker not in seen:
            seen.add(marker)
            out.append(Classification(text, found, index))

    codes = sorted({c for e in entries for c in e.get("codes", [])}, key=len, reverse=True)
    pattern = None
    if codes:
        # "Flam. Liq. 2" written with or without its dots and spaces.
        parts = []
        for code in codes:
            words = re.findall(r"[A-Za-z]+|\d(?:\.\d)?[A-C]?|[A-G]+", code)
            parts.append(r"[\s.]*".join(re.escape(w) for w in words))
        pattern = re.compile(r"(?<![A-Za-z])(?:" + "|".join(parts) + r")(?![0-9A-Za-z])",
                             re.IGNORECASE)
    for index, line in enumerate(lines):
        text = line or ""
        if pattern is not None:
            for found in pattern.finditer(text):
                keep(found.group(0), by_code.get(_key(found.group(0)), []), index)
        for found in _CATEGORY_WORD.finditer(text):
            before = text[:found.start()]
            if not re.search(r"[A-Za-z]{4}", before) and index > 0:
                before = (lines[index - 1] or "") + " " + before
            cat = found.group("cat").upper().replace("CAT", "")
            words = _stems(before[-120:])
            route = next((r for r in _ROUTES if r in before.lower()), "")
            best, score = [], 0.0
            for entry in entries:
                if cat not in [c.upper() for c in entry["category"]]:
                    continue
                theirs = _stems(entry["hazard_class"]) | (
                    _stems(entry["subclass"]) if entry["subclass"] not in _ROUTES else set())
                if not theirs:
                    continue
                share = len(theirs & words) / len(theirs)
                if share < 0.6:
                    continue
                if route and entry["subclass"] in _ROUTES and entry["subclass"] != route:
                    continue
                if share > score:
                    best, score = [entry], share
                elif share == score:
                    best.append(entry)
            keep(f"{before[-60:].strip(' :-–,;')} {found.group(0)}".strip(), best, index)
    return out
