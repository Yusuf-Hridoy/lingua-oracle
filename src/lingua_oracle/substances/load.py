"""Loading the list one regulation is checked against.

Annex VI lives where it always has; the other lists live beside it under
data/substance_lists/. Which one a regulation uses is `substances.lists`'
business, and this is the part that reads it off disk.
"""

from __future__ import annotations

import json
from functools import cache

from lingua_oracle.models import AnnexVITable
from lingua_oracle.registry import data_dir
from lingua_oracle.substances.lists import ListUse, for_regulation


@cache
def load_list(name: str) -> AnnexVITable | None:
    """One published list by name, or nothing where it is not on file."""
    if name == "annex_vi":
        from lingua_oracle.keys.builders.annex_vi import load_table

        return load_table()
    path = data_dir() / "substance_lists" / f"{name}.json"
    if not path.exists():
        return None
    return AnnexVITable.model_validate(
        json.loads(path.read_text(encoding="utf-8")))


def for_check(regulation: str | None) -> tuple[ListUse | None, AnnexVITable | None]:
    """The list to judge an ingredient by, and the list itself.

    Where a regulation has no list on file at all, both are nothing and the
    ingredient check says so rather than reaching for another regulation's.
    """
    use = for_regulation(regulation or "")
    if use is None:
        return None, None
    return use, load_list(use.name)
