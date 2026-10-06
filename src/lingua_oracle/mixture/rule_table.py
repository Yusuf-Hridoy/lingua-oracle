"""The rules one regulation is calculated with, as read from its own text.

`data/mixture_rules/<regulation>.json` is built by
`keys/builders/mixture_rules.py` straight out of the published documents, and
every number in it carries the document, section and page it was read from.
This module is the reading end: it loads one of those files and answers two
questions the calculation asks - what limit does this regulation set for this
rule, and does this regulation have this hazard class at all.

Three answers are possible and they are not the same thing:

* a value - the regulation sets this limit, and here is where it says so;
* nothing on file - the document does not give this rule, so it is reported as
  not calculated rather than calculated with somebody else's number;
* not covered - the regulation has no such hazard class, which is not a gap in
  what we know but a fact about the regulation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path

from lingua_oracle.registry import data_dir


@dataclass(frozen=True)
class Value:
    """One limit, and the words it was read from."""

    amount: Decimal
    document: str
    section: str
    page: int | None
    raw: str = ""
    qualifier: str = ""

    @property
    def citation(self) -> str:
        where = f", page {self.page}" if self.page else ""
        return f"{self.document}, {self.section}{where}"

    def __str__(self) -> str:
        return f"{self.amount} %" + (f" ({self.qualifier})" if self.qualifier else "")


@dataclass(frozen=True)
class RuleTable:
    regulation: str
    document: str
    covers: frozenset[str]
    values: dict[str, dict[str, tuple[Value, ...]]]
    notes: tuple[str, ...] = ()

    def variants(self, rule: str, key: str) -> tuple[Value, ...]:
        """Every limit the document gives for one rule.

        More than one is not a mistake in the source: the published tables give
        a second limit where the answer turns on something a composition does
        not say - the physical state of an ingredient, or which of two options
        an authority took. They are all kept, and the calculation says so when
        they disagree.
        """
        return self.values.get(rule, {}).get(key, ())

    def one(self, rule: str, key: str) -> Value | None:
        """The single limit for a rule, or nothing when the document has none."""
        found = self.variants(rule, key)
        return found[0] if found else None

    def has(self, rule: str, *keys: str) -> bool:
        return all(self.variants(rule, key) for key in keys)

    def covers_class(self, name: str) -> bool:
        return name in self.covers


def path_for(regulation: str) -> Path:
    return data_dir() / "mixture_rules" / f"{regulation}.json"


@cache
def load(regulation: str) -> RuleTable | None:
    """One regulation's rules, or nothing where no document sets them."""
    path = path_for(regulation)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    values: dict[str, dict[str, tuple[Value, ...]]] = {}
    for rule, keys in raw.get("rules", {}).items():
        values[rule] = {
            key: tuple(
                Value(amount=Decimal(v["amount"]),
                      document=v["source"]["document"],
                      section=v["source"]["section"],
                      page=v["source"].get("page"),
                      raw=v.get("raw", ""), qualifier=v.get("qualifier", ""))
                for v in entries)
            for key, entries in keys.items()}
    return RuleTable(
        regulation=raw["regulation"], document=raw["document"],
        covers=frozenset(raw.get("covers", ())), values=values,
        notes=tuple(raw.get("notes", ())))


def regulations_with_rules() -> list[str]:
    directory = data_dir() / "mixture_rules"
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))
