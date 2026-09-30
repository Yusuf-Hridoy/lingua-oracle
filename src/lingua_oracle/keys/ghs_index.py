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
