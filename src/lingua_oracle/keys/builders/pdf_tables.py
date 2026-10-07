"""Harvesting code/statement pairs from official PDFs.

The UN GHS annexes, GB CLP annexes and the Safe Work Australia guidance all
present statements as a table whose first column is the code and second column
the statement text. Layout, headers and language vary; the *shape* does not. So
rows are matched on the code pattern in column 0 rather than on header text,
which keeps one parser working across English, French and Spanish.

Nothing here infers or repairs text. A row that does not yield a code and a
non-empty statement is recorded in `ParseIssues` and dropped.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

from lingua_oracle.keys.builders.common import (
    cache_dir,
    normalise_code,
    repair_degree_sign,
    strip_amendment_markers,
)
from lingua_oracle.match.normalize import normalize

_SINGLE = r"(?:EUH|AUH|H|P)\s?\d{3}[A-Za-z]?"
# legislation.gov.uk stamps amendment markers onto cells, e.g. "[F50P312".
_AMENDMENT_RE = re.compile(r"^\s*\[?\s*F\d+\s*", re.IGNORECASE)
# Language column labels used by the CLP multilingual annex tables.
_LANG_CELL_RE = re.compile(r"^[A-Z]{2}$")
# The code cell may carry a continuation marker, e.g. "P280 (cont'd)", when a
# statement's table spills onto the next page.
# A combination may end with an optional member in brackets, which is a code
# of its own: "P370 + P380 + P375[+ P378]" is not "P370 + P380 + P375".
CODE_CELL_RE = re.compile(
    rf"^\s*({_SINGLE}(?:\s*\+\s*{_SINGLE})*"
    rf"(?:\s*\[\s*\+\s*{_SINGLE}\s*\])?)"
    rf"\s*(?:\([^()]{{0,20}}\))?\s*$",
    re.IGNORECASE,
)

# Footnote/superscript debris that clings to statement text in these PDFs.
_FOOTNOTE_RE = re.compile(r"\s*\(\s*\d{1,2}\s*\)\s*$")


@dataclass
class ParseIssues:
    """Everything the parser could not use, so gaps are visible not silent."""

    source: str = ""
    pages_scanned: int = 0
    tables_seen: int = 0
    rows_seen: int = 0
    rows_used: int = 0
    empty_statement: list[str] = field(default_factory=list)
    duplicate_conflict: list[str] = field(default_factory=list)
    unparsed_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: code -> 1-based page it was read from, so a reviewer can find the row.
    code_pages: dict[str, int] = field(default_factory=dict)

    def render(self) -> str:
        lines = [f"  parse issues for {self.source}:"]
        lines.append(
            f"    pages={self.pages_scanned} tables={self.tables_seen} "
            f"rows={self.rows_seen} used={self.rows_used}"
        )
        for label, values in (
            ("codes with an empty statement", self.empty_statement),
            ("codes seen twice with different text", self.duplicate_conflict),
            ("codes found in text but not in any table", self.unparsed_codes),
        ):
            if values:
                shown = ", ".join(values[:12]) + ("…" if len(values) > 12 else "")
                lines.append(f"    {label} ({len(values)}): {shown}")
        lines.extend(f"    {n}" for n in self.notes)
        return "\n".join(lines)


def strip_amendment(cell: str) -> str:
    """Drop a leading legislation.gov.uk amendment marker from a cell."""
    return _AMENDMENT_RE.sub("", cell or "").strip()


def harvest_multilingual(
    path: str,
    *,
    first_page: int = 0,
    last_page: int | None = None,
    issues: ParseIssues | None = None,
) -> tuple[dict[str, dict[str, str]], ParseIssues]:
    """Parse CLP-style multilingual annex tables into {lang: {code: text}}.

    These tables open with a header row ``[code, "Language", <hazard class>]`` and
    then carry one row per official language, ``["", "DA", "<text>"]``. A table
    may break across a page, leaving a headerless continuation whose rows belong
    to the code from the previous page, so the current code is carried forward.

    Sometimes the break falls on the header row itself. The GB rendering puts
    the code, the word "Language" and the hazard class at the foot of one page
    as loose text - not as a table row at all - and the language rows on the
    next, so there is no header for this parser to see and the code is simply
    the last one printed on the page before. Four statements were lost that
    way: H200, H250, H290 and H318.
    """
    issues = issues or ParseIssues(source=path)
    out: dict[str, dict[str, str]] = {}
    doc = pymupdf.open(path)
    last = doc.page_count if last_page is None else min(last_page, doc.page_count)
    current: str | None = None
    try:
        for index in range(max(0, first_page), last):
            issues.pages_scanned += 1
            tables = doc[index].find_tables().tables
            if tables and _starts_headerless(tables[0]) and index > 0:
                carried = _last_code_on(doc[index - 1])
                if carried:
                    current = carried
            for table in tables:
                issues.tables_seen += 1
                for row in table.extract():
                    if not row or len(row) < 3:
                        continue
                    issues.rows_seen += 1
                    c0 = strip_amendment(flatten_cell(row[0]))
                    c1 = flatten_cell(row[1]).strip()
                    c2 = flatten_cell(row[2])
                    match = CODE_CELL_RE.match(c0)
                    if match and c1.lower() == "language":
                        current = normalise_code(match.group(1))
                        continue
                    if current and not c0 and _LANG_CELL_RE.match(c1):
                        text = clean_statement(c2)
                        if not text:
                            issues.empty_statement.append(f"{current}/{c1}")
                            continue
                        bucket = out.setdefault(c1.lower(), {})
                        if current not in bucket:
                            bucket[current] = text
                            issues.code_pages.setdefault(current, index + 1)
                            issues.rows_used += 1
                        elif bucket[current] != text:
                            issues.duplicate_conflict.append(f"{current}/{c1}")
    finally:
        doc.close()
    return out, issues


#: A code as the page prints it, with the amendment marker already stripped.
_LOOSE_CODE_RE = re.compile(r"(?:EU|AU)?H\s?\d{3}[A-Za-z]?")


def _starts_headerless(table) -> bool:
    """True when a table opens with a language row rather than a header.

    Such a table is the tail of one whose header is on the page before.
    """
    rows = table.extract()
    if not rows or len(rows[0]) < 3:
        return False
    first = rows[0]
    return (not strip_amendment(flatten_cell(first[0]))
            and bool(_LANG_CELL_RE.match(flatten_cell(first[1]).strip())))


def _last_code_on(page) -> str | None:
    """The last statement code printed on a page, however it is marked up.

    The amendment markers legislation.gov.uk stamps on are removed first:
    "[F50H318" is H318 with a marker glued to it, and a code with a marker
    glued to its front has no word boundary to be found by.
    """
    found = _LOOSE_CODE_RE.findall(strip_amendment(page.get_text()))
    return normalise_code(found[-1]) if found else None


# Annex II defines supplemental statements in prose rather than a table:
#   [F149 1.1.2.]EUH018 - 'In use, may form flammable/explosive vapour-air mixture'
_PROSE_RE = re.compile(
    r"\b((?:EUH|AUH)\s?\d{3}[A-Z]?)\s*[\u2014\u2013-]\s*"
    r"[\u2018'\"]([^\u2019'\"]{4,400})[\u2019'\"]"
)


def harvest_prose(
    path: str,
    *,
    first_page: int = 0,
    last_page: int | None = None,
    issues: ParseIssues | None = None,
) -> tuple[dict[str, str], ParseIssues]:
    """Parse quoted supplemental statements stated as prose rather than tables."""
    issues = issues or ParseIssues(source=path)
    out: dict[str, str] = {}
    doc = pymupdf.open(path)
    last = doc.page_count if last_page is None else min(last_page, doc.page_count)
    try:
        for index in range(max(0, first_page), last):
            text = " ".join(doc[index].get_text().split())
            for match in _PROSE_RE.finditer(text):
                code = normalise_code(match.group(1))
                statement = clean_statement(match.group(2))
                if not statement:
                    issues.empty_statement.append(code)
                    continue
                if code not in out:
                    out[code] = statement
                    issues.code_pages.setdefault(code, index + 1)
                elif out[code] != statement:
                    issues.duplicate_conflict.append(code)
    finally:
        doc.close()
    return out, issues


# Safe Work Australia states the code and its text in one cell:
#   "AUH001 - Explosive when dry"
# A combined code as written in running text, e.g. "P332 + P317".
_COMBINED_IN_TEXT_RE = re.compile(
    rf"{_SINGLE}(?:\s*\+\s*{_SINGLE})+", re.IGNORECASE
)


def combined_codes_on_page(page_text: str) -> dict[str, str]:
    """Map a leading bare code to the combined code it is really part of.

    Table extraction sometimes truncates a code cell at the cell boundary, so a
    row for "P332 + P317" arrives as bare "P332" and collides with the standalone
    P332 defined elsewhere. The page's own running text still spells the combined
    code out, so it is used to repair the key. The repair only applies when every
    occurrence of the bare code on that page is inside a combined token - if the
    page also defines the code standalone, nothing is changed.
    """
    flat = " ".join(page_text.split())
    combined = {normalise_code(m.group(0)) for m in _COMBINED_IN_TEXT_RE.finditer(flat)}
    repair: dict[str, str] = {}
    for full in combined:
        lead = full.split("+")[0]
        # Count on the spaced text: stripping spaces glues the code to the
        # preceding word ("supplementaireP332") and destroys the word boundary,
        # which silently suppressed every repair on such a page.
        occurrences = len(re.findall(rf"\b{re.escape(lead)}\b", flat))
        inside = sum(1 for c in combined if c.split("+")[0] == lead)
        # ambiguous if the lead heads more than one combined code on this page
        if inside != 1:
            continue
        standalone = re.search(rf"\b{re.escape(lead)}\b(?!\s*\+)", flat)
        if standalone is None and occurrences:
            repair[lead] = full
    return repair


_INLINE_RE = re.compile(
    rf"^\s*({_SINGLE}(?:\s*\+\s*{_SINGLE})*)\s*[\u2013\u2014-]\s*(\S.*)$",
    re.IGNORECASE | re.DOTALL,
)


def harvest_inline(
    path: str,
    *,
    first_page: int = 0,
    last_page: int | None = None,
    issues: ParseIssues | None = None,
) -> tuple[dict[str, str], ParseIssues]:
    """Parse tables whose cell holds 'CODE - statement' together."""
    issues = issues or ParseIssues(source=path)
    out: dict[str, str] = {}
    doc = pymupdf.open(path)
    last = doc.page_count if last_page is None else min(last_page, doc.page_count)
    try:
        for index in range(max(0, first_page), last):
            issues.pages_scanned += 1
            for table in doc[index].find_tables().tables:
                issues.tables_seen += 1
                for row in table.extract():
                    for cell in row or []:
                        issues.rows_seen += 1
                        match = _INLINE_RE.match(flatten_cell(cell).strip())
                        if not match:
                            continue
                        code = normalise_code(match.group(1))
                        statement = clean_statement(match.group(2))
                        if not statement:
                            issues.empty_statement.append(code)
                            continue
                        if code not in out:
                            out[code] = statement
                            issues.code_pages.setdefault(code, index + 1)
                            issues.rows_used += 1
                        elif out[code] != statement:
                            issues.duplicate_conflict.append(code)
    finally:
        doc.close()
    return out, issues



_SLASH_WRAP_RE = re.compile(r"/[ \t]*\n[ \t]*")
# A suspended hyphen - German "Spreng- und Wurfstuecke", Danish "Brand- eller
# eksplosionsfare" - is two words and the space after the hyphen is real. What
# follows it is a conjunction, so a wrapped hyphen is only closed up when the
# next line does NOT start with one.
_CONJUNCTIONS = (
    "and", "or",                      # en
    "et", "ou",                       # fr
    "y", "o", "u", "e",               # es, pt, it
    "und", "oder",                    # de
    "en", "of",                       # nl
    "og", "eller", "och",             # da, no, sv
    "ja", "tai", "või",               # fi, et
    "i", "lub", "oraz",               # pl
    "a", "nebo", "alebo", "vagy",     # cs, sk, hu
    "ir", "arba", "un", "vai",        # lt, lv
    "jew",                            # mt
)
_HYPHEN_WRAP_RE = re.compile(
    r"(?<=\w)-[ \t]*\n[ \t]*"
    r"(?!(?:" + "|".join(_CONJUNCTIONS) + r")\b)"
    r"(?=[a-z\u00e0-\u00ff])"
)


def flatten_cell(text: str) -> str:
    """Flatten a table cell onto one line, keeping wrapped alternatives intact.

    A cell that breaks straight after a '/' is a list of alternatives wrapped by
    the layout engine:

        dust/fume/gas/
        mist/vapours/
        spray.

    Turning each break into a space put "gas/ mist/vapours/ spray" in the key,
    which then failed against every document that writes the list normally. The
    break is layout, not a space.

    A source that genuinely spaces its slashes - several EU languages print
    "CENTRE ANTIPOISON / medecin" - puts the space *before* the '/' as well, on
    the same line, so that typography is untouched here.

    A compound broken across lines - "non-" then "sparking" - is rejoined for
    the same reason, keeping the hyphen: the key held "Use non- sparking tools."

    The risk in that second rule is a *suspended* hyphen, where the space is
    real: Danish "Brand- eller eksplosionsfare", German "Spreng- und
    Wurfstuecke". What follows a suspended hyphen is a conjunction, so the join
    is skipped when the next line starts with one. That list is the guard, and
    it is the whole guard: a suspended hyphen followed by something that is not
    a conjunction, and falling exactly on a line end, would still be closed up
    wrongly. No entry in any key is in that position today, and two tests pin
    both directions.
    """
    if not text:
        return ""
    out = _SLASH_WRAP_RE.sub("/", text)
    out = _HYPHEN_WRAP_RE.sub("-", out)
    return out.replace("\n", " ")


def clean_statement(text: str) -> str:
    out = flatten_cell(text)
    out = _FOOTNOTE_RE.sub("", out)
    out = strip_amendment_markers(out)
    return repair_degree_sign(normalize(out))


def find_pages(doc, pattern: str, *, limit: int | None = None) -> list[int]:
    """Page numbers whose text matches `pattern`."""
    rx = re.compile(pattern, re.IGNORECASE)
    out = []
    for i in range(doc.page_count):
        if rx.search(doc[i].get_text()):
            out.append(i)
            if limit and len(out) >= limit:
                break
    return out


def dense_code_pages(path: str, *, min_codes: int = 1) -> list[int]:
    """Pages holding at least `min_codes` distinct codes.

    This locates the statement annexes without relying on a heading in any
    particular language, and without being fooled by the table of contents,
    which mentions the annex but lists no codes. The threshold defaults to 1
    because real annex pages can be sparse - in GHS Rev.11 the page defining
    P280 carries only two codes - and missing one costs a statement, whereas an
    extra page merely costs a little time.
    """
    doc = pymupdf.open(path)
    rx = re.compile(rf"\b{_SINGLE}\b", re.IGNORECASE)
    out: list[int] = []
    try:
        for index in range(doc.page_count):
            codes = {normalise_code(m.group(0)) for m in rx.finditer(doc[index].get_text())}
            if len(codes) >= min_codes:
                out.append(index)
    finally:
        doc.close()
    return out


def annex_page_range(path: str, *, min_codes: int = 5, max_gap: int = 6) -> tuple[int, int]:
    """The contiguous block of pages that holds the statement annexes.

    Dense pages mark where the annexes are, but sparse pages sit *inside* that
    block (the GHS Rev.11 page defining P280 carries two codes) and must be
    harvested too. So the densest run is found first, allowing small gaps, and
    the whole span is returned. Pages elsewhere - a table of contents listing
    the annex, say - fall outside the run and are skipped, which keeps the
    table scan to roughly a fifth of the document.
    """
    dense = dense_code_pages(path, min_codes=min_codes)
    if not dense:
        return (0, 0)
    runs: list[list[int]] = [[dense[0]]]
    for page in dense[1:]:
        if page - runs[-1][-1] <= max_gap:
            runs[-1].append(page)
        else:
            runs.append([page])
    best = max(runs, key=len)
    return (best[0], best[-1] + 1)


def harvest(
    path: str,
    *,
    first_page: int = 0,
    last_page: int | None = None,
    statement_column: int = 1,
    pages: list[int] | None = None,
    issues: ParseIssues | None = None,
) -> tuple[dict[str, str], ParseIssues]:
    """Return ({canonical_code: statement}, issues) from tables on the given pages."""
    issues = issues or ParseIssues(source=path)
    # Table detection costs roughly half a second a page, so a full build of
    # several 600-page annexes is minutes of work. Results are cached against the
    # file's size and mtime, which makes re-runs instant and makes it cheap to
    # rebuild one regulation without re-parsing the rest.
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "path": str(path),
                "stat": [Path(path).stat().st_size, int(Path(path).stat().st_mtime)],
                "range": [first_page, last_page, statement_column],
                "pages": pages,
                # v8: cell flattening keeps slash- and hyphen-wrapped text together
                "v": 9,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:24]
    cache_file = cache_dir() / f"tables-{cache_key}.json"
    if cache_file.exists():
        blob = json.loads(cache_file.read_text(encoding="utf-8"))
        # Deliberately no "loaded from cache" note: whether the cache was warm is
        # an implementation detail, and recording it would make the written parse
        # report differ between two builds of the same unchanged source.
        return blob["found"], ParseIssues(**blob["issues"])

    found: dict[str, str] = {}
    doc = pymupdf.open(path)
    last = doc.page_count if last_page is None else min(last_page, doc.page_count)
    targets = pages if pages is not None else range(max(0, first_page), last)
    try:
        for index in targets:
            issues.pages_scanned += 1
            repair = combined_codes_on_page(doc[index].get_text())
            for table in doc[index].find_tables().tables:
                issues.tables_seen += 1
                for row in table.extract():
                    if not row or len(row) <= statement_column:
                        continue
                    issues.rows_seen += 1
                    cell = strip_amendment(flatten_cell(row[0]))
                    match = CODE_CELL_RE.match(cell)
                    if not match:
                        continue
                    code = normalise_code(match.group(1))
                    if code in repair:
                        issues.notes.append(
                            f"repaired truncated code cell {code} -> {repair[code]} "
                            f"on page {index}"
                        )
                        code = repair[code]
                    statement = clean_statement(row[statement_column])
                    if not statement:
                        issues.empty_statement.append(code)
                        continue
                    previous = found.get(code)
                    if previous is None:
                        found[code] = statement
                        issues.code_pages[code] = index + 1
                        issues.rows_used += 1
                    elif previous != statement:
                        # Keep the first reading; record the disagreement.
                        issues.duplicate_conflict.append(code)
    finally:
        doc.close()
    cache_file.write_text(
        json.dumps({"found": found, "issues": asdict(issues)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return found, issues


def codes_in_text(path: str, first_page: int = 0, last_page: int | None = None) -> set[str]:
    """Every code mentioned anywhere in the page range, for coverage comparison."""
    doc = pymupdf.open(path)
    last = doc.page_count if last_page is None else min(last_page, doc.page_count)
    rx = re.compile(rf"\b{_SINGLE}\b", re.IGNORECASE)
    out: set[str] = set()
    try:
        for index in range(max(0, first_page), last):
            out.update(normalise_code(m.group(0)) for m in rx.finditer(doc[index].get_text()))
    finally:
        doc.close()
    return out
