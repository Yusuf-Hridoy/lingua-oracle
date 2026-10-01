"""Read-only access to the committed record of the GHS editions on file.

Built by `keys/builders/ghs_index.py`; never built here. Check time reads it to
answer one question: a code we hold no wording for - is it a *newer GHS* code
the regulation has not adopted, or a code that exists nowhere?
"""

from __future__ import annotations

import functools
import json

from lingua_oracle.registry import data_dir


@functools.lru_cache(maxsize=1)
def _index() -> dict:
    path = data_dir() / "ghs_index" / "en.json"
    if not path.exists():
        return {"editions": [], "codes": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def editions() -> list[str]:
    """Edition labels on file, oldest first."""
    return list(_index().get("editions", []))


def editions_defining(code: str) -> list[str]:
    """Editions that give this code a statement, oldest first."""
    found = _index().get("codes", {}).get(code, {})
    return [label for label in editions() if label in found]


def text_in(code: str, edition: str) -> str:
    return _index().get("codes", {}).get(code, {}).get(edition, "")


def known_anywhere(code: str) -> bool:
    return bool(_index().get("codes", {}).get(code))


def deleted_in(code: str) -> list[str]:
    """Editions that print "[Deleted]" for this code, oldest first."""
    found = _index().get("deleted", {}).get(code, [])
    return [label for label in editions() if label in found]


def oldest_edition_defines(code: str) -> bool:
    """True when the oldest edition on file already gives this code a statement.

    Used to separate "this is newer GHS wording" from "this regulation simply
    never adopted an old statement", which are different things to tell a
    reader.
    """
    labels = editions()
    return bool(labels) and labels[0] in _index().get("codes", {}).get(code, {})


@functools.lru_cache(maxsize=1)
def _presence() -> dict:
    path = data_dir() / "ghs_index" / "source_presence.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def source_searched(regulation: str) -> bool:
    """True when we have searched this regulation's own source text."""
    return regulation in _presence()


def wording_in_source(regulation: str, code: str) -> bool:
    """True when the regulation's source carries this code's GHS wording.

    Only meaningful where `source_searched` is true.
    """
    record = _presence().get(regulation)
    return bool(record) and code in record.get("present", [])
