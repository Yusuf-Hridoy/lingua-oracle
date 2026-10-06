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

from lingua_oracle.keys.builders.common import now, strip_markers
from lingua_oracle.models import AnnexVIEntry, AnnexVITable
from lingua_oracle.registry import data_dir

#: The header that identifies Table 3 among the act's 544 tables. Matched on the
#: columns rather than on a caption, because the caption is set as prose.
_HEADER = ("index no", "ec no", "cas no")
#: A hazard statement code. Found inside the text rather than matched against
#: the whole of it: the act packs several onto one line and hangs footnote
#: asterisks off them - "H361d *** H304", "H373 **" - and a whole-string match
#: dropped every line that was not a single bare code.
_CODE = re.compile(r"\b(?:EU)?H\d{3}[A-Za-z]?\b")
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

    entries: list[AnnexVIEntry] = []
    issues: list[str] = []
    for position, row in enumerate(table.xpath(".//tr")):
        cells = row.xpath("./td")
        if len(cells) == 1:
            continue  # a consolidation marker row (▼M16) between blocks
        if len(cells) != 11:
            text = " ".join(" ".join(row.itertext()).split())
            if text and not text.lower().startswith(("index no", "hazard class")):
                issues.append(f"row {position}: {len(cells)} cells, expected 11 - "
                              f"{text[:120]}")
            continue
        values = [_paragraphs(cell) for cell in cells]
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
    return entries, issues


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
    table = AnnexVITable(
        source=CELEX,
        note=("CLP Annex VI Part 3 Table 3, the harmonised classifications. "
              "Values are stored exactly as the act prints them, including the "
              "'*' that marks a minimum classification and the [n] suffixes "
              "that tie an identifier to one substance of a multi-substance "
              "entry."),
        retrieved_at=now(),
        entries=sorted(entries, key=lambda e: e.index_no),
    )
    table = preserve_timestamp(table)
    return table, write_table(table), write_parse_issues(issues, CELEX)
