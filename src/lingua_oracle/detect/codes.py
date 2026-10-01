"""Finding hazard/precautionary codes and their phrase text in a document."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lingua_oracle.detect.hazard_classes import is_hazard_class
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


#: Table cells that sit next to a code but are not its statement: the hazard
#: category, a date, a bare number, a class name. Real statements never take
#: these shapes, and attaching one would report a false wording failure.
_NOT_A_STATEMENT_RE = re.compile(
    r"^\s*(?:"
    r"category\s+\d|cat\.?\s*\d|type\s+[A-G]\b"
    r"|\d+(?:[.,]\d+)?\s*%?$"
    r"|(?:revision|version|issue|print)\s*date\b"
    r"|\d{4}-\d{2}-\d{2}"
    r"|page\s+\d"
    r")",
    re.IGNORECASE,
)


#: Words too common to tell two statements apart.
_STOPWORDS = frozenset({
    "and", "the", "for", "with", "this", "that", "from", "into", "when",
    "have", "been", "they", "them", "than", "then", "your", "which",
})


def _significant(text: str) -> set[str]:
    """Words long enough to carry meaning, lower-cased."""
    return {
        word for word in re.findall(r"[^\W\d_]{4,}", (text or "").lower())
        if word not in _STOPWORDS
    }


def plausible_statement(text: str, candidates: Sequence[str]) -> bool:
    """True when `text` could be the statement for the code it sits under.

    The classification table puts the hazard class beside the code - "H225 /
    Flam. Liq. 2", "EUH018 / Supplemental" - and a class shares no wording with
    the statement it classifies. The statements table a few lines down has the
    real text, so rejecting the class here costs nothing: the code gets its
    verdict from the occurrence that does carry wording.

    Sharing one significant word is enough. The test is for "could this be the
    statement", not "is it correct" - a sheet with the wrong wording still has
    to be caught, and "Ground/bond container" shares five words with "Ground and
    bond container" while saying something different.

    A hazard class is rejected before any of that. The class shares its
    vocabulary with the statement it classifies - "Skin Irrit. 2" and "Causes
    skin irritation." both say "skin", "Aquatic Chronic 3" and "Harmful to
    aquatic life" both say "aquatic" - so word overlap cannot separate them and
    four such classes passed this guard until it did.

    With nothing to compare against, the text is kept: silence about a code we
    hold no wording for is worse than a reported difference.
    """
    if is_hazard_class(text):
        return False
    if not candidates:
        return True
    words = _significant(text)
    if not words:
        return False
    return any(words & _significant(candidate) for candidate in candidates)


def statement_on_next_line(text: str) -> bool:
    """True when a line following a bare code reads as that code's statement.

    Most real sheets lay Section 2 out as a table, so the code lands on one
    line and its statement on the next. Nothing attached them, so those codes
    reached the checks with no text and could never be verified - which is what
    kept coverage down rather than any gap in the answer keys.
    """
    stripped = (text or "").strip()
    if not stripped or find_codes_in_text(stripped):
        return False
    if starts_new_block(stripped) or _NOT_A_STATEMENT_RE.match(stripped):
        return False
    return bool(re.search(r"[A-Za-z]{3}", stripped))


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


def _repeated_column_values(lines: list[Line]) -> set[str]:
    """Text that follows two or more different bare codes.

    The classification table puts the hazard class beside the code - "EUH018 /
    Supplemental / EUH066 / Supplemental" - and a class name is not a category
    number, so listing the shapes to exclude does not reach it. But a statement
    belongs to one code: anything sitting under several different codes is a
    column value, whatever it says.
    """
    following: dict[str, set[str]] = {}
    for idx, line in enumerate(lines):
        found = find_codes_in_text(line.text)
        if len(found) != 1 or line.text.strip() != found[0][0]:
            continue
        if idx + 1 >= len(lines) or lines[idx + 1].page != line.page:
            continue
        nxt = lines[idx + 1].text.strip()
        if nxt and not find_codes_in_text(nxt):
            following.setdefault(nxt, set()).add(found[0][0])
    return {text for text, codes in following.items() if len(codes) > 1}


def extract_hits(
    lines: list[Line], official: Mapping[str, Sequence[str]] | None = None
) -> list[CodeHit]:
    """Pull every code and the phrase that follows it, up to the next code.

    A phrase may run past the end of its line; continuation lines are consumed
    until the next code, a section heading, or a blank run.
    """
    hits: list[CodeHit] = []
    column_values = _repeated_column_values(lines)
    for idx, line in enumerate(lines):
        found = find_codes_in_text(line.text)
        if not found:
            continue
        for n, (code, _start, end) in enumerate(found):
            if n + 1 < len(found):
                phrase = line.text[end : found[n + 1][1]]
            else:
                phrase = line.text[end:]
                start_at = idx + 1
                if not _clean_phrase(phrase):
                    # The code stands alone on its line, which is how most
                    # sheets lay Section 2 out. Its statement is the next line
                    # - but only if that line reads like one. Where it does
                    # not, this code has no text at all, and the continuation
                    # loop below must not reach past it and pick up whatever
                    # the table holds next.
                    nxt = lines[idx + 1] if idx + 1 < len(lines) else None
                    if (nxt is not None and nxt.page == line.page
                            and nxt.text.strip() not in column_values
                            and statement_on_next_line(nxt.text)
                            and plausible_statement(
                                nxt.text, (official or {}).get(code, ()))):
                        phrase = nxt.text
                        start_at = idx + 2
                    else:
                        start_at = len(lines)
                # Continue onto following lines only while they genuinely read as
                # the rest of this statement. Official texts do not all end in a
                # full stop (OSHA's do not), so "ends with a period" is not a
                # usable stop condition; the same truncation heuristic the line
                # rejoiner uses is applied instead.
                for nxt in lines[start_at : start_at + 3]:
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


def extract_document_hits(
    doc: Document, official: Mapping[str, Sequence[str]] | None = None
) -> list[CodeHit]:
    return extract_hits(doc.lines, official)
