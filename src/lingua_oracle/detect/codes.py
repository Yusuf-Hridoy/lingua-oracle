"""Finding hazard/precautionary codes and their phrase text in a document."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lingua_oracle.extract.base import Document, Line
from lingua_oracle.extract.rejoin import (
    cut_at_new_item,
    is_continuation,
    starts_new_block,
)
from lingua_oracle.match.normalize import normalize

# A single code: prefix + 3 digits, optional trailing letter (H350i, EUH201A),
# tolerating a space between prefix and digits ("EUH 066").
_SINGLE = r"(?:EUH|AUH|H|P)\s?\d{3}[A-Za-z]?"
# A combined code joins singles with '+', e.g. P303 + P361 + P353.
CODE_RE = re.compile(rf"\b{_SINGLE}(?:\s*\+\s*{_SINGLE})*", re.IGNORECASE)

# Text that ends a phrase even without a following code.
_SECTION_BREAK_RE = re.compile(
    r"^\s*(?:SECTION|SEKTION|AFSNIT|PUNKT|ABSCHNITT|RUBRIQUE|SECCI[ÓO]N)?\s*"
    r"\d{1,2}\s*[.):：]\s*\S",
    re.IGNORECASE,
)


def canonical_code(raw: str) -> str:
    """'euh 066' -> 'EUH066'; 'P303 + P361 + P353' -> 'P303+P361+P353'."""
    out = raw.upper()
    out = re.sub(r"\s*\+\s*", "+", out)
    out = re.sub(r"\b(EUH|AUH|H|P)\s+(\d)", r"\1\2", out)
    return out.strip()


def split_combined(code: str) -> list[str]:
    return [c for c in canonical_code(code).split("+") if c]


@dataclass
class CodeHit:
    code: str
    text: str
    page: int
    line_index: int
    section: str | None = None
    raw_code: str = ""


def find_codes_in_text(text: str) -> list[tuple[str, int, int]]:
    """(canonical_code, start, end) for every code occurrence in `text`."""
    return [(canonical_code(m.group(0)), m.start(), m.end()) for m in CODE_RE.finditer(text)]


def _clean_phrase(text: str) -> str:
    """Trim separators, and stop where the statement stops.

    A statement running to the end of its line is followed on real sheets by
    whatever comes next in the section - a glossary, a footnote, a revision
    note. `cut_at_new_item` ends the phrase there.
    """
    out = cut_at_new_item(text).strip()
    out = re.sub(r"^[\s:\-\u2013\u2014.,;)\]]+", "", out)
    out = re.sub(r"[\s;,]+$", "", out)
    return normalize(out)


def extract_hits(lines: list[Line]) -> list[CodeHit]:
    """Pull every code and the phrase that follows it, up to the next code.

    A phrase may run past the end of its line; continuation lines are consumed
    until the next code, a section heading, or a blank run.
    """
    hits: list[CodeHit] = []
    for idx, line in enumerate(lines):
        found = find_codes_in_text(line.text)
        if not found:
            continue
        for n, (code, _start, end) in enumerate(found):
            if n + 1 < len(found):
                phrase = line.text[end : found[n + 1][1]]
            else:
                phrase = line.text[end:]
                # Continue onto following lines only while they genuinely read as
                # the rest of this statement. Official texts do not all end in a
                # full stop (OSHA's do not), so "ends with a period" is not a
                # usable stop condition; the same truncation heuristic the line
                # rejoiner uses is applied instead.
                for nxt in lines[idx + 1 : idx + 4]:
                    if nxt.page != line.page or not nxt.text.strip():
                        break
                    if find_codes_in_text(nxt.text) or _SECTION_BREAK_RE.match(nxt.text):
                        break
                    if starts_new_block(nxt.text):
                        break
                    if not is_continuation(_clean_phrase(phrase), nxt.text):
                        break
                    phrase += " " + nxt.text
            hits.append(
                CodeHit(
                    code=code,
                    text=_clean_phrase(phrase),
                    page=line.page,
                    line_index=idx,
                    raw_code=code,
                )
            )
    return hits


def extract_document_hits(doc: Document) -> list[CodeHit]:
    return extract_hits(doc.lines)
