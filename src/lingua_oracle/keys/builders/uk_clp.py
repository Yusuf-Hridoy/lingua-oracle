"""Answer-key builder for UK GB CLP, from a local copy of the retained regulation.

legislation.gov.uk serves every view behind an AWS WAF challenge, so this builder
reads a PDF supplied by hand under data/sources/uk-gb-clp/.

GB CLP is retained EU law, and the retained text keeps the EU's annex layout
intact, including its 24 language columns:

* **Annex III** (hazard and supplemental statements) uses the CLP multilingual
  table - a header row ``[code, "Language", <class>]`` then one row per language.
  GB CLP is an English-language regime, so the EN row is what is stored.
* **Annex IV** (precautionary statements) uses a plain English table whose first
  column is the code.

Cells carry legislation.gov.uk amendment markers such as ``[F50P312``; those are
stripped before the code is read.
"""

from __future__ import annotations

import re
from pathlib import Path

from lingua_oracle.keys.builders.common import normalise_code, now
from lingua_oracle.keys.builders.pdf_tables import (
    ParseIssues,
    clean_statement,
    dense_code_pages,
    harvest,
    harvest_multilingual,
    harvest_prose,
)
from lingua_oracle.keys.builders.signal_words import entries_for, from_english
from lingua_oracle.keys.builders.sources import source_note
from lingua_oracle.match.normalize import normalize, strip_punctuation
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Status, Tier
from lingua_oracle.registry import data_dir

REGULATION = "uk_clp"
REVISION = "retained-1272-2008"
SOURCE_URL = "https://www.legislation.gov.uk/eur/2008/1272/contents"
DEFAULT_FILE = "uk-gb-clp/gb_clp_full.pdf"


def _kind(code: str) -> Kind:
    if code.startswith("EUH"):
        return Kind.SUPPLEMENTAL
    if code.startswith("H"):
        return Kind.HAZARD
    return Kind.PRECAUTIONARY


_PART_ONE_CODE_RE = re.compile(
    r"^\s*(?:\[\s*[FX]\d+\s*)?((?:EUH|AUH|P|H)\s?\d{3}[A-Za-z]?)\s*$"
)


def doc_page_count(path: str) -> int:
    import pymupdf

    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def part_one_statements(path: str, first_page: int, last_page: int) -> dict[str, str]:
    """{code: text} from the Part 1 tables, which name the code in each row.

    GB CLP states each statement twice, as EU CLP does, and Part 1 carries
    amendments Part 2 did not receive. Two shapes are rejected here because
    they are not statements: a Part 2 table's header row, whose second cell is
    the word "Language", and a cell the table extractor truncated.
    """
    import pymupdf

    out: dict[str, str] = {}
    doc = pymupdf.open(path)
    try:
        last = min(last_page, doc.page_count)
        for index in range(max(0, first_page), last):
            for table in doc[index].find_tables().tables:
                for row in table.extract():
                    if not row or len(row) < 2 or not row[0] or not row[1]:
                        continue
                    match = _PART_ONE_CODE_RE.match(" ".join(row[0].split()))
                    if not match or row[1].strip().lower() == "language":
                        continue
                    text = clean_statement(row[1])
                    if text:
                        out.setdefault(normalise_code(match.group(1)), text)
    finally:
        doc.close()
    return out


def supersedes(held: str, part_one: str) -> bool:
    """True when the Part 1 rendering is a later text rather than a worse one.

    A rendering that is merely a shortened form of what we hold is a truncated
    cell - GB CLP's P220 comes out as "Keep away from clothing and other" - and
    taking it would lose half the statement.
    """
    if not part_one or not held:
        return False
    if _same_statement(held, part_one):
        return False
    short, long = sorted((held.strip(), part_one.strip()), key=len)
    return not long.startswith(short) or len(part_one) > len(held)


def _same_statement(a: str, b: str) -> bool:
    key = lambda t: strip_punctuation(normalize(t)).casefold()  # noqa: E731
    return key(a) == key(b)


def build(
    languages: list[str] | None = None,
    *,
    from_file: str | None = None,
    sources_root: Path | None = None,
) -> tuple[list[AnswerKey], list[ParseIssues]]:
    root = sources_root or (data_dir() / "sources")
    path = Path(from_file) if from_file else root / DEFAULT_FILE
    ts = now()

    if not path.exists():
        issues = ParseIssues(source=f"{REGULATION}/en")
        issues.notes.append(source_note(DEFAULT_FILE, path))
        return (
            [
                AnswerKey(
                    regulation=REGULATION, language="en", revision=REVISION,
                    status=Status.PENDING_SOURCE, source_url=SOURCE_URL,
                    retrieved_at=ts, entries=[],
                )
            ],
            [issues],
        )

    pages = dense_code_pages(str(path), min_codes=2)
    lo, hi = (min(pages), max(pages) + 1) if pages else (0, 0)

    # Annex III: multilingual tables -> keep English.
    multi, issues = harvest_multilingual(str(path), first_page=lo, last_page=hi)
    found = dict(multi.get("en", {}))
    annex3_count = len(found)

    # Annex IV: plain English code/statement tables.
    plain, issues2 = harvest(str(path), first_page=lo, last_page=hi)
    added = 0
    for code, text in plain.items():
        if code not in found:
            found[code] = text
            added += 1

    # GB CLP states each statement twice as EU CLP does, and the Part 1 tables
    # carry amendments Part 2 did not receive: Regulation 2019/521 substituted
    # P103 and P280, and only Part 1 shows it.
    part_one = part_one_statements(str(path), 0, doc_page_count(str(path)))
    replaced = sorted(
        code for code, text in part_one.items()
        if code in found and supersedes(found[code], text)
    )
    for code in replaced:
        found[code] = part_one[code]
    if replaced:
        issues.notes.append(
            f"Part 1 text used where it supersedes Part 2 ({len(replaced)}): "
            + ", ".join(replaced)
        )

    # Annex II states the supplemental (EUH) statements as quoted prose rather
    # than in a table, so the table parsers alone miss most of them.
    prose, issues3 = harvest_prose(str(path), first_page=lo, last_page=hi)
    prose_added = 0
    for code, text in prose.items():
        if code not in found:
            found[code] = text
            prose_added += 1

    issues.source = f"{REGULATION}/en ({path.name})"
    issues.tables_seen += issues2.tables_seen
    issues.rows_seen += issues2.rows_seen
    issues.rows_used += issues2.rows_used
    issues.duplicate_conflict.extend(issues2.duplicate_conflict)
    issues.empty_statement.extend(issues2.empty_statement)
    issues.notes.append(f"annex pages {lo}-{hi}")
    issues.notes.append(
        f"Annex III multilingual EN rows: {annex3_count}; "
        f"Annex IV English rows added: {added}; "
        f"Annex II prose (EUH) added: {prose_added}"
    )
    issues.duplicate_conflict.extend(issues3.duplicate_conflict)
    issues.notes.append(
        "GB CLP is retained EU law, so EU CLP codes introduced after retention "
        "(EUH380/381/430/431/440/441/450/451) are legitimately absent, not missing."
    )
    other = sorted(set(multi) - {"en"})
    if other:
        issues.notes.append(
            f"retained text also carries {len(other)} other language column(s) "
            f"({', '.join(other[:8])}…); not stored, GB CLP is English"
        )

    # page each code was read from, across all three parsers, for the spot check
    code_pages = {**issues.code_pages, **issues2.code_pages, **issues3.code_pages}
    entries = [
        AnswerKeyEntry(
            regulation=REGULATION, revision=REVISION, language="en", code=code,
            kind=_kind(code), text=text, tier=Tier.A, source_url=SOURCE_URL,
            source_ref=f"GB CLP (retained Reg. 1272/2008) Annex II/III/IV, row for "
                       f"{code} ({path.name}"
                       + (f", p{code_pages[code]}" if code in code_pages else "")
                       + ")",
            retrieved_at=ts, status=Status.OK,
        )
        for code, text in sorted(found.items())
    ]
    words = from_english(str(path))
    entries.extend(
        entries_for(
            words, regulation=REGULATION, revision=REVISION, language="en",
            source_url=SOURCE_URL,
            source_ref=f"GB CLP Annex I label element tables ({path.name})",
            retrieved_at=ts,
        )
    )
    issues.notes.append(f"signal words found: {sorted(words.values()) or 'none'}")
    entries.sort(key=lambda e: (e.kind, e.code))
    return (
        [
            AnswerKey(
                regulation=REGULATION, language="en", revision=REVISION,
                status=Status.OK if entries else Status.PENDING_SOURCE,
                source_url=SOURCE_URL, retrieved_at=ts, entries=entries,
            )
        ],
        [issues],
    )
