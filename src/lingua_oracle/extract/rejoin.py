"""Rejoin phrases broken across PDF lines.

SDS producers wrap statements freely, so a single H-statement often arrives as
two or three lines. Joining is deliberately conservative: gluing a heading onto
the text beneath it destroys both section detection and the statement, which is
far worse than leaving a wrapped phrase split. A line is therefore only merged
into the previous one when the previous line looks genuinely truncated *and* this
line looks like its continuation.
"""

from __future__ import annotations

import re

from lingua_oracle.extract.base import Line
from lingua_oracle.match.normalize import normalize

_CODE_START_RE = re.compile(r"^\s*(?:EUH|AUH|H|P)\s?\d{3}", re.IGNORECASE)
_HEADING_RE = re.compile(
    r"^\s*(?:SECTION|SEKTION|AFSNIT|PUNKT|ABSCHNITT|RUBRIQUE|SECCI[\u00d3O]N)?\s*"
    r"\d{1,2}\s*[.):\uff1a]\s*\S",
    re.IGNORECASE,
)
# A field label such as "Signalord:" or "Mention d\'avertissement:".
_FIELD_LABEL_RE = re.compile(r"^\s*[^\s:][^:]{0,45}:\s+\S")
_ENDS_SENTENCE_RE = re.compile(r"[.!?:;]\s*$")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-$")


def starts_new_block(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _CODE_START_RE.match(stripped) or _HEADING_RE.match(stripped):
        return True
    if _FIELD_LABEL_RE.match(stripped):
        return True
    # A short all-caps line is a heading, e.g. "ETIKET / LABEL".
    letters = [c for c in stripped if c.isalpha()]
    return bool(letters) and len(stripped) <= 40 and all(c.isupper() for c in letters)


def is_continuation(prev: str, text: str) -> bool:
    """True when `text` reads as the rest of the sentence started on `prev`."""
    if _ENDS_SENTENCE_RE.search(prev):
        return False
    if _HYPHEN_BREAK_RE.search(prev):
        return True
    first = text.lstrip()[:1]
    # A wrapped line normally resumes in lower case; a new field or sentence
    # starts with a capital and is left alone.
    return bool(first) and not first.isupper()


def rejoin_lines(lines: list[Line]) -> list[Line]:
    """Merge continuation lines into the line that starts the phrase."""
    out: list[Line] = []
    for line in lines:
        text = line.text.rstrip()
        if not text.strip():
            continue
        if (
            out
            and line.page == out[-1].page
            and not starts_new_block(text)
            and is_continuation(out[-1].text, text)
        ):
            prev = out[-1]
            if _HYPHEN_BREAK_RE.search(prev.text):
                merged = prev.text[:-1] + text.lstrip()
            else:
                merged = prev.text.rstrip() + " " + text.lstrip()
            out[-1] = Line(text=normalize(merged), page=prev.page, bbox=prev.bbox)
        else:
            out.append(Line(text=normalize(text), page=line.page, bbox=line.bbox))
    return out
