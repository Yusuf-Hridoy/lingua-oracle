"""One regulation's acute toxicity rules, as `keys/builders/acute_toxicity.py`
read them out of its text: bands, conversion values, relevance, the unknown
share, and the highest ATE an ingredient may have and still count."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import cache

from lingua_oracle.registry import data_dir


@dataclass(frozen=True)
class Band:
    category: str
    low: Decimal       # exclusive
    high: Decimal      # inclusive


@dataclass(frozen=True)
class AcuteRules:
    regulation: str
    document: str
    bands: dict[str, tuple[Band, ...]]
    conversion: dict[str, dict[str, Decimal]]
    relevance: Decimal
    unknown_threshold: Decimal
    ingredient_limit: dict[str, Decimal]
    citations: dict[str, str]
    notes: tuple[str, ...] = ()

    def category(self, form: str, ate: Decimal) -> str | None:
        """The category an ATE falls in for this route, or None beyond the last."""
        for band in self.bands.get(form, ()):
            if band.low < ate <= band.high:
                return band.category
        return None

    @property
    def categories(self) -> set[str]:
        """Every acute toxicity category the regulation has, on any route."""
        return {b.category for bands in self.bands.values() for b in bands}

    def without_category_5(self) -> str | None:
        """Where the regulation's own text shows it has no Category 5, or None
        where it has one. A regulation that excludes it in terms (Australia)
        is cited for the exclusion; the others for their table, which stops
        at Category 4."""
        if "5" in self.categories:
            return None
        for note in self.notes:
            if note.startswith("Category 5 excluded"):
                cited = re.search(r"\(([^()]*)\)\s*$", note)
                if cited:
                    return cited.group(1)
        return self.citations["bands"]

    def band_text(self, form: str, category: str) -> str:
        band = next(b for b in self.bands[form] if b.category == category)
        low = "" if band.low == 0 else f"{_n(band.low)} < "
        return f"{low}ATE ≤ {_n(band.high)}"


def _n(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _cite(entry: dict | None) -> str:
    if not entry:
        return ""
    where = f", page {entry['page']}" if entry.get("page") else ""
    return f"{entry['document']}, {entry['section']}{where}"


@cache
def load(regulation: str) -> AcuteRules | None:
    path = data_dir() / "acute_toxicity" / f"{regulation}.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AcuteRules(
        regulation=regulation, document=raw["document"],
        bands={form: tuple(Band(b["category"], Decimal(b["low"]), Decimal(b["high"]))
                           for b in bands) for form, bands in raw["bands"].items()},
        conversion={form: {c: Decimal(v) for c, v in values.items()}
                    for form, values in raw["conversion"].items()},
        relevance=Decimal(raw["relevance"]["value"]),
        unknown_threshold=Decimal(raw["unknown_threshold"]["value"]),
        ingredient_limit={form: Decimal(v) for form, v in raw["ingredient_limit"].items()},
        citations={"bands": _cite(raw.get("bands_from")),
                   "conversion": _cite(raw.get("conversion_from")),
                   "relevance": _cite(raw.get("relevance")),
                   "unknown": _cite(raw.get("unknown_threshold")),
                   "formula": _cite(raw.get("formula")),
                   "limit": _cite(raw.get("ingredient_limit_from"))},
        notes=tuple(raw.get("notes") or ()))
