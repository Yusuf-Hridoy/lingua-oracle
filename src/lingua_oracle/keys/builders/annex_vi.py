"""Annex VI Table 3: the harmonised classifications, as committed data.

CLP Annex VI Part 3 Table 3 is the list of substances the Union has classified
itself. Where a substance appears there, its classification is not the
supplier's to choose: the entry is the law, and a safety data sheet has to carry
at least what it says.

The table comes from the same consolidated act the answer keys are built from,
through the same CELLAR fetch, so it carries the same provenance. Every value is
stored exactly as the act prints it - including the "*" that marks a minimum
classification, the "[1]"/"[2]" suffixes that tie several CAS numbers to the
several substances an entry covers, and the notes letters. Nothing is repaired:
a row that cannot be read goes to the parse report and is left out, because an
invented harmonised classification is worse than a missing one.

One table, 4 400-odd entries, rebuilt deterministically.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lingua_oracle.keys.builders import annulled
from lingua_oracle.keys.builders.common import now, strip_markers
from lingua_oracle.models import AnnexVIAmendment, AnnexVIEntry, AnnexVITable
from lingua_oracle.registry import data_dir

#: The header that identifies Table 3 among the act's 544 tables. Matched on the
#: columns rather than on a caption, because the caption is set as prose.
_HEADER = ("index no", "ec no", "cas no")
#: A hazard statement code. Found inside the text rather than matched against
#: the whole of it: the act packs several onto one line and hangs footnote
#: asterisks off them - "H361d *** H304", "H373 **" - and a whole-string match
#: dropped every line that was not a single bare code. Up to two letters: the
#: reproductive toxicity codes name both effects at once - H360FD, H360Df,
#: H360Fd, H361fd - and with one letter allowed the word boundary failed and
#: the whole code was lost, from 114 entries.
_CODE = re.compile(r"\b(?:EU)?H\d{3}[A-Za-z]{0,2}\b")
#: "233-139-2 [1]" - the bracketed index ties the identifier to one of the
#: substances a multi-substance entry covers.
_WHICH = re.compile(r"\s*\[(\d+)\]\s*$")
_ABSENT = {"", "-", "—", "–", "n.a.", "not applicable"}


def find_table(doc):
    """The Table 3 element, or None."""
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        if len(rows) < 100:
            continue
        head = " | ".join(
            " ".join(" ".join(cell.itertext()).split()).lower()
            for cell in rows[0].xpath("./td|./th")
        )
        if all(word in head for word in _HEADER):
            return table
    return None


def _paragraphs(cell) -> list[str]:
    """The cell's values, one per printed line, markers stripped."""
    from lingua_oracle.keys.builders.eu_clp import _cell_paragraphs

    out = []
    for text in _cell_paragraphs(cell):
        value = strip_markers(text).strip()
        if value:
            out.append(value)
    return out


def _codes(values: list[str]) -> list[str]:
    """Every hazard statement code printed in a column, in order."""
    out: list[str] = []
    for value in values:
        out += _CODE.findall(value)
    return out


def _identifiers(values: list[str]) -> list[str]:
    """CAS or EC numbers, keeping the [n] that says which substance they are for."""
    return [v for v in values if v.strip().lower() not in _ABSENT
            and v.strip().strip("[]0123456789 ") not in ("-", "")]


def cas_digits_valid(cas: str) -> bool:
    """The CAS registry check digit: sum of digits weighted right to left, mod 10."""
    bare = _WHICH.sub("", cas).strip()
    if not re.fullmatch(r"\d{2,7}-\d{2}-\d", bare):
        return False
    body, check = bare.replace("-", "")[:-1], int(bare[-1])
    total = sum(int(d) * i for i, d in enumerate(reversed(body), start=1))
    return total % 10 == check


#: Annex VI writes a statement with the route or effect it applies to appended:
#: H350i (by inhalation), H360F (fertility), H360FD (both), H361d. The wording
#: belongs to the base code; the suffix narrows which hazard it was assigned for.
_SUB_CODED = re.compile(r"^(H3[456]\d)[A-Za-z]{1,2}$")


def base_code(code: str) -> str:
    """H350i -> H350. Any other code is its own base."""
    match = _SUB_CODED.match(code)
    return match.group(1) if match else code


def _classify_limit(text: str) -> str:
    """Which of the three the Specific Conc. Limits column is printing."""
    lowered = text.lower()
    if lowered.startswith("m=") or lowered.startswith("m =") or "m-factor" in lowered:
        return "m_factor"
    if "ate" in lowered.split("=")[0].lower() or lowered.startswith(
            ("oral", "dermal", "inhalation")):
        return "ate"
    return "scl"


def parse_table3(doc, *, celex: str) -> tuple[list[AnnexVIEntry], list[str]]:
    """Every entry in Annex VI Table 3, and the rows that could not be read."""
    table = find_table(doc)
    if table is None:
        return [], ["Annex VI Table 3 was not found in the consolidation."]
    issues: list[str] = []
    return _entries(table.xpath(".//tr"), celex, issues), issues


#: An Annex VI index number, "607-776-00-5".
_INDEX = re.compile(r"^\d{3}-\d{3}-\d{2}-[\dX]$")
#: The quotation marks an amending act wraps each new row in: "‘" opens the
#: first cell, "’" closes the last one that holds anything.
_OPENING, _CLOSING = "\u2018", "\u2019"


def _unquote(values: list[list[str]]) -> list[list[str]]:
    """A row as an amending act prints it, without the quotation around it."""
    values = [list(v) for v in values]
    if values and values[0]:
        values[0][0] = values[0][0].lstrip(_OPENING).strip()
    for column in reversed(values):
        if column:
            column[-1] = column[-1].rstrip(_CLOSING).strip()
            break
    return values


def _entries(rows, celex: str, issues: list[str], *,
             quoted: bool = False) -> list[AnnexVIEntry]:
    """The entries in Table 3's eleven-column rows.

    `quoted` is for an amending act, whose rows are quotations: the quotation
    marks are taken off, and a row whose first cell is not an index number - a
    repeated header - is skipped rather than reported.
    """
    entries: list[AnnexVIEntry] = []
    for position, row in enumerate(rows):
        cells = row.xpath("./td")
        if len(cells) == 1:
            continue  # a consolidation marker row (▼M16) between blocks
        if len(cells) != 11:
            text = " ".join(" ".join(row.itertext()).split())
            if (text and not quoted
                    and not text.lower().startswith(("index no", "hazard class"))):
                issues.append(f"row {position}: {len(cells)} cells, expected 11 - "
                              f"{text[:120]}")
            continue
        values = [_paragraphs(cell) for cell in cells]
        if quoted:
            values = _unquote(values)
            if not _INDEX.match(" ".join(values[0]).strip()):
                continue
        index_no = " ".join(values[0]).strip()
        if not index_no:
            issues.append(f"row {position}: no index number")
            continue

        limits = [v for v in values[9] if v.strip()]
        entry = AnnexVIEntry(
            index_no=index_no,
            name=" ".join(values[1]).strip(),
            ec=_identifiers(values[2]),
            cas=_identifiers(values[3]),
            hazard_classes=[v for v in values[4] if v.strip()],
            h_codes=_codes(values[5]),
            pictograms=[v for v in values[6] if v.strip()],
            label_h_codes=_codes(values[7]),
            supplemental_h_codes=_codes(values[8]),
            euh_codes=[c for c in _codes(values[8]) if c.startswith("EUH")],
            limits=limits,
            limit_kinds=[_classify_limit(v) for v in limits],
            notes=[v for v in values[10] if v.strip()],
            source_ref=f"Annex VI, Table 3, Index No {index_no} ({celex})",
        )
        if not entry.hazard_classes and not entry.h_codes:
            issues.append(f"{index_no}: no classification in either column")
            continue
        entries.append(entry)
    return entries


# -- an amending act that does not apply yet ----------------------------------

#: The amending acts held as upcoming, by CELEX number, with the name a reader
#: knows them by. Each is read from the act as published in the Official
#: Journal; no consolidation carries an ATP before it applies.
UPCOMING = {"32025R1222": "Delegated Regulation (EU) 2025/1222 (23rd ATP)"}
_APPLIES = re.compile(r"(?:It|This Regulation) shall apply from "
                      r"(\d{1,2}) (\w+) (\d{4})")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")


def applies_from(doc):
    """The date the act says it applies from, and the sentence that says so."""
    from datetime import date

    text = " ".join(" ".join(doc.itertext()).split())
    match = _APPLIES.search(text)
    if match is None:
        return None, ""
    day, month, year = match.groups()
    if month.lower() not in _MONTHS:
        return None, ""
    return (date(int(year), _MONTHS.index(month.lower()) + 1, int(day)),
            match.group(0) + ".")


def parse_amendment(doc, *, celex: str):
    """The entries an ATP inserts and the entries it replaces, with issues.

    The act's Annex quotes its new rows inside two numbered points: "(1) the
    following entries are inserted ..." and "(2) the entries corresponding to
    index numbers ... are replaced by the following". Each point holds one
    table that opens with Table 3's own header; which point a table belongs to
    is read from the point's own words, and the index numbers point (2) names
    are checked against the rows it gives.
    """
    inserted: list[AnnexVIEntry] = []
    replaced: list[AnnexVIEntry] = []
    issues: list[str] = []
    named: list[str] = []
    for table in doc.xpath("//table"):
        rows = table.xpath("./tr|./tbody/tr|./thead/tr")
        if not rows:
            continue
        head = " ".join(" ".join(rows[0].itertext()).split()).lower()
        if not head.startswith("index no"):
            continue
        point = table.xpath("ancestor::table[1]")
        intro = (" ".join(" ".join(point[0].itertext()).split()).lower()[:400]
                 if point else "")
        found = _entries(rows, celex, issues, quoted=True)
        if "are inserted" in intro:
            inserted += found
        elif "are replaced" in intro:
            replaced += found
            named += re.findall(r"\d{3}-\d{3}-\d{2}-[\dX]", intro)
        else:
            issues.append(f"a table of {len(found)} entries under neither "
                          "point: " + intro[:120])
    given = {e.index_no for e in replaced}
    for index_no in sorted(set(named) - given):
        issues.append(f"{index_no}: named as replaced, but no row given for it")
    for index_no in sorted(given - set(named)):
        issues.append(f"{index_no}: a replacement row the act does not name")
    return inserted, replaced, issues


def upcoming_path() -> Path:
    return data_dir() / "annex_vi" / "upcoming.json"


def load_upcoming() -> AnnexVIAmendment | None:
    """The committed upcoming amendment, or None. Check time reads only this."""
    path = upcoming_path()
    if not path.exists():
        return None
    return AnnexVIAmendment.model_validate_json(path.read_text(encoding="utf-8"))


def build_upcoming(*, use_cache: bool = True) -> tuple[AnnexVIAmendment, Path, list[str]]:
    """data/annex_vi/upcoming.json, read from the amending act itself."""
    from lingua_oracle.keys.builders.eu_clp import _doc

    (celex, title), = UPCOMING.items()
    url = f"http://publications.europa.eu/resource/celex/{celex}"
    doc = _doc("eng", use_cache=use_cache, url=url)
    when, sentence = applies_from(doc)
    if when is None:
        raise ValueError(f"{celex}: no date of application found in the act")
    inserted, replaced, issues = parse_amendment(doc, celex=celex)
    amendment = AnnexVIAmendment(
        act=celex, title=title, applies_from=when, applies_from_text=sentence,
        source_url=url, retrieved_at=now(), inserted=inserted, replaced=replaced)
    existing = load_upcoming()
    if existing is not None and existing.model_dump(exclude={"retrieved_at"}) \
            == amendment.model_dump(exclude={"retrieved_at"}):
        amendment = amendment.model_copy(
            update={"retrieved_at": existing.retrieved_at})
    target = upcoming_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(amendment.model_dump(mode="json"), ensure_ascii=False,
                   indent=1) + "\n", encoding="utf-8")
    return amendment, target, issues


def table_path() -> Path:
    return data_dir() / "annex_vi" / "table3.json"


def preserve_timestamp(table: AnnexVITable) -> AnnexVITable:
    """Keep the stored retrieval time when nothing in the table changed.

    A build stamps the current time, so an unchanged rebuild would rewrite the
    file and show a three-megabyte diff that means nothing. The timestamp moves
    only when an entry does.
    """
    existing = load_table()
    if existing is None:
        return table
    if [e.model_dump() for e in existing.entries] != [
            e.model_dump() for e in table.entries]:
        return table
    if existing.source != table.source or existing.note != table.note:
        return table
    return table.model_copy(update={"retrieved_at": existing.retrieved_at})


def load_table() -> AnnexVITable | None:
    """The committed table, or None. Check time reads this and never the act."""
    path = table_path()
    if not path.exists():
        return None
    return AnnexVITable.model_validate_json(path.read_text(encoding="utf-8"))


def write_table(table: AnnexVITable) -> Path:
    target = table_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(table.model_dump(mode="json", exclude_none=False),
                   ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return target


def write_parse_issues(issues: list[str], celex: str) -> Path:
    """Rows the parser could not read, written out rather than swallowed."""
    target = Path("reports") / "parse_issues_annex_vi.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Annex VI Table 3 - rows that could not be read",
        "",
        f"Source: `{celex}`",
        "",
        "A row here is left out of `data/annex_vi/table3.json`. Nothing is",
        "guessed: an entry invented to fill a gap would be presented to a reader",
        "as harmonised law, which it would not be.",
        "",
        f"Rows not read: {len(issues)}",
        "",
    ]
    lines += [f"* {issue}" for issue in issues] or ["* (none)"]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def build(*, use_cache: bool = True) -> tuple[AnnexVITable, Path, Path]:
    """Build data/annex_vi/table3.json from the consolidated act."""
    from lingua_oracle.keys.builders.eu_clp import CELEX, _doc

    doc = _doc("eng", use_cache=use_cache)
    entries, issues = parse_table3(doc, celex=CELEX)
    note = ("CLP Annex VI Part 3 Table 3, the harmonised classifications. "
            "Values are stored exactly as the act prints them, including the "
            "'*' that marks a minimum classification and the [n] suffixes "
            "that tie an identifier to one substance of a multi-substance "
            "entry.")
    if annulled.applies_to(CELEX):
        # A row the courts have annulled is not a harmonised classification,
        # whatever the consolidation still prints.
        dropped = sorted(e.index_no for e in entries
                         if e.index_no in annulled.ANNEX_VI_ENTRIES)
        entries = [e for e in entries if e.index_no not in annulled.ANNEX_VI_ENTRIES]
        for index_no in dropped:
            issues.append(f"{index_no}: left out, {annulled.why()}")
        if dropped:
            note += f" Left out as annulled: {', '.join(dropped)} ({annulled.NOTICE})."
    table = AnnexVITable(
        source=CELEX,
        note=note,
        retrieved_at=now(),
        entries=sorted(entries, key=lambda e: e.index_no),
    )
    table = preserve_timestamp(table)
    return table, write_table(table), write_parse_issues(issues, CELEX)
