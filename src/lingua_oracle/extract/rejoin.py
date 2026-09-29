"""Rejoin phrases broken across PDF lines.

SDS producers wrap statements freely, so a single H-statement often arrives as
two or three lines. Joining is deliberately conservative: a line is only glued to
the next when the break looks mid-sentence, so that genuinely separate statements
stay separate.
"""

from __future__ import annotations

import re

from lingua_oracle.extract.base import Line
from lingua_oracle.match.normalize import normalize

_CODE_START_RE = re.compile(r"^\s*(?:EUH|AUH|H|P)\s?\d{3}", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*(?:SECTION\s+)?\d{1,2}[.)]\s")
_ENDS_SENTENCE_RE = re.compile(r"[.!?:;]\s*$")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-$")


def _starts_new_block(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return bool(_CODE_START_RE.match(stripped) or _HEADING_RE.match(stripped))


def rejoin_lines(lines: list[Line]) -> list[Line]:
    """Merge continuation lines into the line that starts the phrase."""
    out: list[Line] = []
    for line in lines:
        text = line.text.rstrip()
        if not text.strip():
            continue
        if out and not _starts_new_block(text) and not _ENDS_SENTENCE_RE.search(out[-1].text):
            prev = out[-1]
            if _HYPHEN_BREAK_RE.search(prev.text) and text[:1].islower():
                merged = prev.text[:-1] + text.lstrip()
            else:
                merged = prev.text.rstrip() + " " + text.lstrip()
            out[-1] = Line(text=normalize(merged), page=prev.page, bbox=prev.bbox)
        else:
            out.append(Line(text=normalize(text), page=line.page, bbox=line.bbox))
    return out
