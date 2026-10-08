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
# A field label such as "Signalord:" or "Mention d\'avertissement:". The part
# before the colon may not contain sentence punctuation: "exposure. Abbreviation
# legend:" is the tail of a statement followed by a glossary, not a label, and
# treating it as one truncated the statement a word early.
_FIELD_LABEL_RE = re.compile(r"^\s*[^\s:][^:.!?]{0,45}:\s+\S")
_ENDS_SENTENCE_RE = re.compile(r"[.!?:;]\s*$")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-$")

# A line opening a glossary entry or a footnote rather than continuing a
# statement: "ACGIH = American Conference ...", "* indicates a revised section".
_LEGEND_LINE_RE = re.compile(r"^\s*[A-Z][A-Za-z0-9/().-]{1,14}\s*=\s*\S")
_MARKER_LINE_RE = re.compile(r"^\s*[*\u2020\u2021\u2022\u00b0]\s*\S")

# Where a statement ends and something else begins *on the same line*. Only
# applied after a sentence terminator, and only to shapes an official statement
# never contains: a glossary entry ("ACGIH = ..."), a footnote marker, or a
# labelled block ("Abbreviation legend:", "Prepared by:").
#
# Deliberately NOT triggered by an all-caps token followed by a colon: official
# statements are full of those - "IF SWALLOWED:", "IF ON SKIN:" - and cutting
# there would truncate the statement it is meant to protect.
_NEW_ITEM_AFTER_SENTENCE_RE = re.compile(
    r"(?<=[.!?])\s+(?="
    r"[A-Z][A-Za-z0-9/().-]{1,14}\s*=\s"
    r"|[*\u2020\u2021\u2022]\s"
    r"|(?i:abbreviations?|legend|glossary|key|prepared\s+by|revision|"
    r"disclaimer|references?|notes?|date\s+of)\b[^.]{0,40}:"
    r")"
)


#: The words a legend or glossary block opens with. A line that ends a
#: statement and then starts one of these, broken by a hyphen - "... exposure.
#: Abbrevi-" - carries the block's first syllables, and the rest of the word is
#: on a line that is never joined back (overleaf, or capitalised).
_LEGEND_WORDS = (
    "abbreviations", "acronyms", "legend", "glossary", "references", "revision",
    "notes", "explanation", "abkürzungen", "abréviations", "abreviaturas",
    "forkortelser", "afkortingen", "förkortningar", "legende", "légende",
    "leyenda", "legenda",
)
_FRAGMENT_AFTER_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?P<fragment>[^\W\d_]{2,})-\s*$")


def cut_at_new_item(text: str) -> str:
    """Text up to the point where a new item starts after a finished sentence.

    A statement that runs to the end of its line is followed, on real sheets, by
    whatever the section holds next - a glossary, a footnote, a revision note.
    Without this the statement swallows it and fails against wording it never
    claimed to be. That includes the opening syllables of such a block broken
    at the line end ("Abbrevi-"), which no statement ends with.
    """
    match = _NEW_ITEM_AFTER_SENTENCE_RE.search(text or "")
    if match:
        return text[: match.start()].rstrip()
    fragment = _FRAGMENT_AFTER_SENTENCE_RE.search(text or "")
    if fragment and any(word.startswith(fragment.group("fragment").casefold())
                        for word in _LEGEND_WORDS):
        return text[: fragment.start()].rstrip()
    return text


def starts_new_block(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _CODE_START_RE.match(stripped) or _HEADING_RE.match(stripped):
        return True
    if _FIELD_LABEL_RE.match(stripped):
        return True
    if _LEGEND_LINE_RE.match(stripped) or _MARKER_LINE_RE.match(stripped):
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
