"""Reading a supplier sheet's Section 3: which substances, and their codes.

For a sheet that is not one of ours there is no app record to consult, so the
ingredients have to come from the document.

Read from the table, not from the lines. Section 3 is a table on most sheets,
and a line-based reading of one is unsafe here: the section detector's idea of
where Section 3 begins is approximate, and on several sheets it swallows the
end of Section 2 - whose list of hazard statements is one code per line. Read
line by line, that list becomes the ingredients' classification, and the report
accuses a supplier of codes their sheet never attached to that substance. The
table has the columns the sheet drew, so a code in the classification column
belongs to the row it is in.

What this takes from a row is only what the comparison needs: a CAS number and
the hazard codes printed against it. Concentrations, classes and the other
identifiers are Phase 2's problem. Where no table can be read, nothing is
returned and the report says nothing was checked - which is true, and better
than a guess dressed as a finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from lingua_oracle.detect.codes import CODE_RE

#: A CAS registry number, with word boundaries that keep it from matching inside
#: a REACH registration number or an Index number.
CAS_RE = re.compile(r"(?<![\d-])(\d{2,7}-\d{2}-\d)(?![\d-])")
_REACH_RE = re.compile(r"\b\d{2}-\d{10}-\d{2}(?:-\w{4})?\b")
_INDEX_RE = re.compile(r"\b\d{3}-\d{3}-\d{2}-\d\b")
#: An EC number. Masked before a concentration is looked for, for the same
#: reason the CAS numbers are: "200-827-9" contains the range "200-827".
_EC_RE = re.compile(r"(?<![\d-])\d{3}-\d{3}-\d(?![\d-])")

#: Section headings, in the languages the application issues sheets in. Matched
#: loosely because the numbering varies - "SECTION 3:", "3.", "3 -".
_HEAD3 = re.compile(
    r"(?:section\s*)?3[.:)\s-]{0,3}\s*(composition|zusammensetzung|composición"
    r"|composición|sammensætning|composition/informations|samenstelling"
    r"|composizione|composição|skład|koostis|sudėtis|sastav)", re.IGNORECASE)
_HEAD4 = re.compile(
    r"(?:section\s*)?4[.:)\s-]{0,3}\s*(first[- ]aid|erste[- ]hilfe|premiers"
    r"|primeros|førstehjælp|eerstehulp|misure di primo|primeiros|pierwsza)",
    re.IGNORECASE)
#: A composition table names its substances somehow. Tables elsewhere in a sheet
#: share these columns - regulatory listings, exposure limits - so the ones that
#: are plainly something else are refused.
_COMPOSITION = re.compile(r"cas|component|chemical name|ingredient|substance",
                          re.IGNORECASE)
_NOT_COMPOSITION = re.compile(r"iarc|ntp|acgih|tsca|sara|proposition|osha pel"
                              r"|exposure limit|dnel|pnec", re.IGNORECASE)


@dataclass
class PdfIngredient:
    """One substance read off the sheet."""

    cas: str
    h_codes: list[str] = field(default_factory=list)
    raw: str = ""
    page: int | None = None
    #: The concentration cell, as printed. Parsed by mixture.concentration.
    concentration: str | None = None

    @property
    def name(self) -> str | None:
        """The row's text before its CAS number - the chemical name column."""
        if not self.cas or self.cas not in self.raw:
            return None
        return self.raw.split(self.cas)[0].strip(" |,;:") or None


def _codes_in(text: str) -> list[str]:
    """Hazard and supplemental statement codes, in the order printed."""
    out: list[str] = []
    for match in CODE_RE.finditer(text or ""):
        code = match.group(0).upper().replace(" ", "")
        if code.startswith(("H", "EUH")) and code not in out:
            out.append(code)
    return out


#: A concentration as Section 3 prints it, in any of the shapes Phase 0 found.
#: Searched for after the identifiers have been masked out, because a CAS number
#: and a range are the same shape.
_CONCENTRATION_RE = re.compile(
    r"(?:[<>]=?|≤|≥)?\s*\d+(?:[.,]\d+)?\s*(?:%|\s)?\s*(?:[-–—]|to)\s*"
    r"(?:[<>]=?|≤|≥)?\s*\d+(?:[.,]\d+)?\s*%?"
    r"|(?:[<>]=?|≤|≥)\s*\d+(?:[.,]\d+)?\s*%?"
    r"|\d+(?:[.,]\d+)?\s*%")


def _concentration_in(text: str) -> str | None:
    found = _CONCENTRATION_RE.search(text or "")
    return found.group(0).strip() if found else None


def _cell_lines(cell: str | None) -> list[str]:
    """A table cell's own lines.

    pdfplumber keeps the line breaks inside a cell, and it has to: a three-row
    composition table can come back as one row whose cells each hold three
    newline-separated values. Collapsing the whitespace loses the rows silently.
    """
    return [part.strip() for part in (cell or "").split("\n")]


def _rows_of(table: list[list[str | None]]) -> list[str]:
    """One text per ingredient row, unpacking cells that hold several rows."""
    out: list[str] = []
    for row in table[1:]:
        cells = [_cell_lines(cell) for cell in row]
        depth = max((len(c) for c in cells), default=0)
        deep = sum(1 for c in cells if len(c) == depth)
        # Several ingredients packed into one row looks exactly like one
        # ingredient whose longest cell wrapped - both are a cell with several
        # lines. What separates them is how many columns carry those lines: a
        # packed row has the same count in at least two of them, a wrapped one
        # has it in the single cell that was too long.
        if depth > 1 and deep > 1 and all(
                len(c) in (1, depth) for c in cells if any(c)):
            for index in range(depth):
                out.append(" ".join(
                    c[index] if len(c) == depth else (c[0] if c else "")
                    for c in cells))
            continue
        out.append(" ".join(" ".join(" ".join(c).split()) for c in cells))
    return out


def _section_three_band(page) -> tuple[float, float] | None:
    """(top, bottom) of Section 3 on this page, or None if it is not here."""
    words = page.extract_words(use_text_flow=False) or []
    rows: dict[int, list] = {}
    for word in words:
        rows.setdefault(round(word["top"] / 3), []).append(word)
    start = end = None
    for key in sorted(rows):
        line = " ".join(w["text"] for w in sorted(rows[key], key=lambda w: w["x0"]))
        top = min(w["top"] for w in rows[key])
        if start is None and _HEAD3.search(line):
            start = top
        elif start is not None and _HEAD4.search(line):
            end = top
            break
    if start is None:
        return None
    return start, (end if end is not None else page.height)


def ingredients_in_section_three(path: str | Path) -> list[PdfIngredient]:
    """Every substance Section 3 prints with hazard codes beside it.

    One upload asks for this three times - the ingredient check, substance or
    mixture, the mixture calculation - and table detection costs about half a
    second a page, so the reading is kept per file as it stands on disk.
    """
    target = Path(path)
    try:
        stat = target.stat()
    except OSError:
        return []
    return list(_read(str(target), stat.st_size, stat.st_mtime_ns))


@lru_cache(maxsize=16)
def _read(path: str, _size: int, _mtime: int) -> tuple[PdfIngredient, ...]:
    return tuple(_read_section_three(path))


def _read_section_three(path: str | Path) -> list[PdfIngredient]:
    try:
        import pdfplumber
    except ImportError:          # pragma: no cover - pdfplumber is a dependency
        return []

    out: list[PdfIngredient] = []
    seen: set[str] = set()
    try:
        with pdfplumber.open(str(path)) as pdf:
            carry: tuple[float, float] | None = None
            for number, page in enumerate(pdf.pages, start=1):
                band = _section_three_band(page)
                if band is None and carry is None:
                    continue
                if band is None:
                    # Section 3 began on an earlier page and has not ended.
                    band = (0.0, page.height)
                top, bottom = band
                carry = band if bottom >= page.height else None
                for found in page.find_tables() or []:
                    if not (top <= found.bbox[1] <= bottom):
                        continue
                    table = found.extract()
                    if len(table) < 2:
                        continue
                    header = " | ".join(
                        " ".join((cell or "").split()) for cell in table[0])
                    if not _COMPOSITION.search(header):
                        continue
                    if _NOT_COMPOSITION.search(header):
                        continue
                    for text in _rows_of(table):
                        masked = _INDEX_RE.sub(" ", _REACH_RE.sub(" ", text))
                        numbers = CAS_RE.findall(masked)
                        if numbers and numbers[0] in seen:
                            continue
                        if not numbers:
                            # A row with a concentration and no CAS number is
                            # a trade secret, or a name the author chose not
                            # to pair with one. The ingredient check can do
                            # nothing with it, but the mixture has to know
                            # that this much of the mixture is undisclosed
                            # rather than absent.
                            share = _concentration_in(_EC_RE.sub(" ", masked))
                            if share:
                                out.append(PdfIngredient(
                                    cas="", h_codes=[],
                                    raw=" ".join(text.split())[:300],
                                    page=number, concentration=share))
                            continue
                        seen.add(numbers[0])
                        out.append(PdfIngredient(
                            cas=numbers[0], h_codes=_codes_in(masked),
                            raw=" ".join(text.split())[:300], page=number,
                            # The CAS numbers go too before a concentration is
                            # looked for: "67-64-1" is the same shape as the
                            # range "67-64", which is the first trap Phase 0
                            # found and the easiest one to walk back into.
                            concentration=_concentration_in(
                                _EC_RE.sub(" ", CAS_RE.sub(" ", masked)))))
    except (OSError, ValueError) as exc:
        # A PDF that cannot be opened or parsed checks nothing; it is not an
        # error in this tool. Deliberately narrow: a TypeError here would be a
        # bug in the reader, and swallowing it once cost an afternoon.
        del exc
        return out
    return out


def has_anything_to_check(ingredients: list[PdfIngredient]) -> bool:
    """True when at least one substance was printed with codes beside it.

    A Section 3 listing CAS numbers and no codes cannot be compared: there is
    nothing on the sheet to hold against the harmonised entry.
    """
    return any(i.h_codes for i in ingredients)
