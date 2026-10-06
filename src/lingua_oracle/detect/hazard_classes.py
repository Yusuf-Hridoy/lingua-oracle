"""Hazard class and category codes, which are not statements.

A sheet's classification table puts the class beside the code - "H315 / Skin
Irrit. 2" - and the class shares its vocabulary with the statement it
classifies, so comparing words cannot tell them apart: "Skin Irrit. 2" and
"Causes skin irritation." both contain "skin".

The CLP list is read from Annex VI Table 1.1 at build time and committed, so
nothing here is recalled and check time needs no source.
"""

from __future__ import annotations

import functools
import json
import re

from lingua_oracle.registry import data_dir


def _key(text: str) -> str:
    """Comparison key: punctuation dropped, case folded, spaces collapsed.

    The act prints "Skin. Sens. 1" where a sheet writes "Skin Sens. 1"; both
    reduce to "skin sens 1".
    """
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "")).lower().split())


@functools.lru_cache(maxsize=1)
def _clp_classes() -> frozenset[str]:
    path = data_dir() / "hazard_classes" / "eu_clp.json"
    if not path.exists():
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(_key(code) for code in data.get("codes", []) if code)


#: GHS and OSHA spell the class out and end with the category: "Skin
#: corrosion/irritation Category 2", "Acute toxicity, oral Category 4".
_LONG_FORM_RE = re.compile(
    r"^.{0,80}?\b(?:category|cat\.)\s*\d[A-Za-z]?\s*$", re.IGNORECASE
)

#: The short form's own shape, for classes a later ATP adds before we rebuild:
#: two to four abbreviated words then a category token.
_SHORT_FORM_RE = re.compile(
    r"^(?:[A-Z][\w./-]*\.?\s+){1,4}\d[A-Za-z]?$"
)


def is_listed_hazard_class(text: str) -> bool:
    """True only when the text is a class Annex VI actually lists.

    `is_hazard_class` also accepts anything *shaped* like a class, which is what
    it is for - rejecting a line that might be one. Reading a classification off
    a sheet needs the strict test: "SECTION 2" and "Table 3" are both shaped
    like a class and neither is one.
    """
    return _key((text or "").strip()) in _clp_classes()


def is_hazard_class(text: str) -> bool:
    """True when this is a class and category rather than a statement."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _key(stripped) in _clp_classes():
        return True
    return bool(_LONG_FORM_RE.match(stripped) or _SHORT_FORM_RE.match(stripped))
