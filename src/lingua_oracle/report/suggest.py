"""The text a reader is told to use: the shortest one the official wording
allows, with what may be added said beside it.

The official texts carry the author's choices (see match/template.py, which
reads them the same way): a slot the text itself makes conditional ("(state
all organs affected, if known)", "<state route of exposure if it is
conclusively proven ...>") may be left out, and an optional group ("Wash
hands [and …] thoroughly") may be dropped. A suggested correction leaves
both out and says they may be added; a slot the text requires is shown as
"…" with what goes in it named - never the bracketed instruction itself.
"""

from __future__ import annotations

import re

from lingua_oracle.match.template import _CONDITIONAL_SLOT_RE, _OPTIONAL_MARK, _SLOT_RE

_OPTIONAL_GROUP = re.compile(r"\s*\[([^\[\]]*)\]")


def tidy(text: str) -> str:
    """Official text as shown: no stray space inside a bracket ("( state" ->
    "(state"), no invisible markers."""
    text = (text or "").replace(_OPTIONAL_MARK, "")
    text = re.sub(r"([(\[<])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]>])", r"\1", text)
    return " ".join(text.split())


def _what(slot: str) -> str:
    """What a slot asks for, in a few words: "all organs affected"."""
    inner = slot.strip("<>()" + _OPTIONAL_MARK + " ").replace(_OPTIONAL_MARK, "")
    inner = re.sub(r"^(?:or\s+)?(?:state|specify|indicate|insert|list)\s+", "", inner,
                   flags=re.IGNORECASE)
    inner = re.split(r",?\s+if\b", inner, maxsplit=1, flags=re.IGNORECASE)[0]
    return inner.strip(" ,")


def shortest(official: str) -> tuple[str, str]:
    """(the shortest valid text, a note on what may be added or filled in)."""
    text = (official or "").replace(_OPTIONAL_MARK + "", _OPTIONAL_MARK)
    added: list[str] = []
    fill: list[str] = []

    def group(found: re.Match) -> str:
        added.append(f"“{found.group(1).strip()}”")
        return ""

    text = _OPTIONAL_GROUP.sub(group, text)

    def slot(found: re.Match) -> str:
        value = found.group(0)
        if value == "…":
            return value
        if _CONDITIONAL_SLOT_RE.search(value) or _OPTIONAL_MARK in value:
            added.append(_what(value))
            return ""
        fill.append(_what(value))
        return "…"

    text = _SLOT_RE.sub(slot, text)
    text = re.sub(r"\s+([.,;:])", r"\1", " ".join(text.split()))
    text = tidy(text)
    notes = []
    if added:
        notes.append(f"{' / '.join(dict.fromkeys(added))} may be added")
    if fill:
        notes.append(f"fill in “…”: {', '.join(dict.fromkeys(fill))}")
    return text, "; ".join(notes)
