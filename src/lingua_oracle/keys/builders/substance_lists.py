"""The published substance lists, built into the shape Annex VI already has.

Annex VI Table 3 is not the only list of classifications a regulator
publishes. Great Britain keeps its own - the GB mandatory classification and
labelling list - and Australia publishes the Hazardous Chemical Information
System. They say the same kind of thing in the same kind of columns, so they
are read into the same model: one entry per substance, carrying the
identifiers, the classes, the codes, the limits and the notes exactly as the
publisher prints them, with a reference back to the row they came from.

Nothing here normalises a classification. "Eye Damage 1" is how HCIS writes
what Annex VI calls "Eye Dam. 1", and both are kept as written: this is the
reference other things are judged against, and a reference that has been
tidied is a reference that cannot be checked.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.annex_vi import _classify_limit
from lingua_oracle.keys.builders.xlsx import rows
from lingua_oracle.models import AnnexVIEntry, AnnexVITable
from lingua_oracle.registry import data_dir

CAS = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
#: Codes as the lists print them, one per entry however they are separated.
CODE = re.compile(r"\b(?:EU)?H\d{3}[A-Za-z]*\b")


def lists_dir() -> Path:
    return data_dir() / "substance_lists"


def path_for(name: str) -> Path:
    return lists_dir() / f"{name}.json"


@dataclass(frozen=True)
class Column:
    """Where one field of an entry is, in one publisher's spreadsheet."""

    letter: str
    separator: str = ","


def _flat(text: str) -> str:
    """One field on one line: a name wrapped over three lines is one name."""
    return " ".join((text or "").split())


#: Where one limit ends and the next begins, whatever the cell's line breaks
#: do. A limit opens with a class and a semicolon, with an M-factor, or with
#: the route an ATE is for; the wrapping in between is the spreadsheet's.
_LIMIT_START = re.compile(
    r"[A-Z][A-Za-z.\-]*(?:\s+[A-Za-z.()/\-]+)*\s+\d[A-Fa-f]?\s*;"
    r"|M\s*=|(?:oral|dermal|inhalation)\s*:", re.I)


def _limits(text: str) -> list[str]:
    """The Specific Conc. Limits, M-factors and ATEs column, one per entry."""
    joined = _flat(text)
    if not joined:
        return []
    starts = [m.start() for m in _LIMIT_START.finditer(joined)]
    if not starts:
        return [joined]
    bounds = [0, *[s for s in starts if s > 0], len(joined)]
    out = []
    for first, last in zip(bounds, bounds[1:], strict=False):
        piece = joined[first:last].strip(" ;")
        if piece:
            out.append(piece)
    return out


def _split(text: str, separator: str) -> list[str]:
    """One cell's entries, however the publisher separated them.

    A line break is always a separator - the lists put one thing per line -
    and the column's own separator is honoured on top of it.
    """
    if not text:
        return []
    parts: list[str] = []
    for line in text.split("\n"):
        parts += line.split(separator) if separator != " " else line.split()
    return [" ".join(p.split()) for p in parts if p.strip()]


# -- the GB mandatory classification and labelling list ------------------------

GB_SOURCE = "uk-gb-clp/gb_mcl_list.xlsx"
GB_SHEET = "GB MCL List"


def _gb_entries(path: Path, edition: str) -> tuple[list[AnnexVIEntry], list[str]]:
    """One entry per row of the GB MCL list.

    The columns are Annex VI's columns - the list is the GB successor to it -
    so the mapping is direct. Classes are separated by line breaks in the
    published file, which the reader has already flattened to spaces, so they
    are split on the class pattern rather than on a separator that is no
    longer there.
    """
    entries: list[AnnexVIEntry] = []
    issues: list[str] = []
    for row in rows(path, GB_SHEET):
        index_no = row.get("A", "")
        if not re.fullmatch(r"\d{3}-\d{3}-\d{2}-\d", index_no):
            continue
        limits = _limits(row.get("J", ""))
        entry = AnnexVIEntry(
            index_no=index_no,
            name=_flat(row.get("B", "")),
            ec=_split(row.get("C", ""), " "),
            cas=_split(row.get("D", ""), " "),
            hazard_classes=_classes(row.get("E", "")),
            h_codes=CODE.findall(row.get("F", "")),
            pictograms=_split(row.get("G", ""), " "),
            label_h_codes=CODE.findall(row.get("H", "")),
            supplemental_h_codes=CODE.findall(row.get("I", "")),
            euh_codes=[c for c in CODE.findall(row.get("I", ""))
                       if c.startswith("EUH")],
            limits=limits,
            limit_kinds=[_classify_limit(v) for v in limits],
            notes=_split(row.get("K", ""), " "),
            source_ref=f"GB MCL List, Index No {index_no} ({edition})",
        )
        if not entry.hazard_classes and not entry.h_codes:
            issues.append(f"{index_no}: no classification in either column")
            continue
        entries.append(entry)
    return entries, issues


#: A class and its category, as these lists write one. The category may carry
#: a sub-division letter, a star for a minimum classification, or neither.
_CLASS = re.compile(
    r"[A-Z][A-Za-z.\-]*(?:\s+[A-Za-z.()/\-]+)*\s+\d[A-Fa-f]?\*?"
    r"|Press\.\s*Gas[^,;]*")


def _classes(text: str) -> list[str]:
    """The classes one cell lists, however the publisher separated them.

    One per line is how both lists print them; a comma is how an export
    flattens them. Only where a line holds several with neither separator is
    the shape of a class used to tell them apart.
    """
    out: list[str] = []
    for line in _split(text, "\n"):
        if "," in line:
            out += [" ".join(p.split()) for p in line.split(",") if p.strip()]
        elif len(_CLASS.findall(line)) > 1:
            out += [" ".join(m.group(0).split()) for m in _CLASS.finditer(line)]
        elif line:
            out.append(line)
    return out


# -- the Hazardous Chemical Information System --------------------------------

AU_SOURCE = "australia/hcis_hazard_classification_export_2026-10-07.xlsx"


#: Australia prints its supplemental statements as AUH. HCIS, built on EU
#: data, carries them as EUH. Where the Australian key has wording for the AUH
#: code of the same number, that is what an Australian sheet has to print and
#: that is what the list says; where it has not, the EUH code is kept as
#: published and the report says there is no Australian wording for it.
def _australian_codes(codes: list[str], known: set[str]) -> tuple[list[str], list[str]]:
    out: list[str] = []
    without: list[str] = []
    for code in codes:
        if not code.startswith("EUH"):
            out.append(code)
            continue
        australian = "AUH" + code[3:]
        if australian in known:
            out.append(australian)
        else:
            out.append(code)
            without.append(code)
    return out, without


def _au_entries(path: Path, edition: str) -> tuple[list[AnnexVIEntry], list[str]]:
    """One entry per row of an HCIS export.

    HCIS publishes no index numbers and no EC numbers, and its export has no
    column for specific concentration limits, M-factors or ATEs. Those fields
    stay empty rather than being filled from somewhere else: what Australia
    publishes is what Australia publishes.
    """
    from lingua_oracle.keys.store import load_key

    known = {entry.code for entry in load_key("au_whs", "en").entries}
    entries: list[AnnexVIEntry] = []
    issues: list[str] = []
    without_wording: set[str] = set()
    started = False
    for row in rows(path):
        if not started:
            started = row.get("A", "").strip().casefold() == "cas"
            continue
        cas = row.get("A", "")
        name = row.get("B", "")
        if not name:
            continue
        classes = _split(row.get("F", ""), ",") + _split(row.get("H", ""), ",")
        codes = CODE.findall(row.get("G", "")) + CODE.findall(row.get("I", ""))
        supplemental, no_wording = _australian_codes(
            CODE.findall(row.get("J", "")), known)
        without_wording.update(no_wording)
        entry = AnnexVIEntry(
            index_no="",
            name=_flat(name),
            ec=[],
            cas=[cas] if CAS.fullmatch(cas or "") else [],
            hazard_classes=classes,
            h_codes=[c for c in codes if not c.startswith("EUH")],
            pictograms=_split(row.get("E", ""), ",")
            + ([row["D"]] if row.get("D") else []),
            label_h_codes=[],
            supplemental_h_codes=supplemental,
            euh_codes=[c for c in supplemental
                       if c.startswith(("EUH", "AUH"))],
            limits=[],
            limit_kinds=[],
            notes=_split(row.get("K", ""), ","),
            source_ref=f"HCIS, {_flat(name)} ({edition})",
        )
        if not entry.hazard_classes and not entry.h_codes:
            issues.append(f"{name}: no classification in either column")
            continue
        if not entry.cas and cas:
            issues.append(f"{name}: identifier {cas!r} is not a CAS number")
        entries.append(entry)
    for code in sorted(without_wording):
        issues.append(f"{code}: kept as published; no Australian wording on "
                      "file for the AUH statement of the same number")
    return entries, issues


# -- building ------------------------------------------------------------------

@dataclass(frozen=True)
class Catalogue:
    """One published list: where it comes from and how it is read."""

    name: str
    title: str
    source: str
    build: object

    @property
    def edition(self) -> str:
        return sources.BY_PATH[self.source].edition


CATALOGUES: tuple[Catalogue, ...] = (
    Catalogue("gb_mcl", "GB mandatory classification and labelling list",
              GB_SOURCE, _gb_entries),
    Catalogue("au_hcis", "Safe Work Australia HCIS hazard classification data",
              AU_SOURCE, _au_entries),
)

BY_NAME = {c.name: c for c in CATALOGUES}


def build(name: str) -> tuple[AnnexVITable, list[str]]:
    catalogue = BY_NAME[name]
    path = sources.require(catalogue.source)
    entries, issues = catalogue.build(path, catalogue.edition)
    table = AnnexVITable(
        source=f"{catalogue.title} - {sources.BY_PATH[catalogue.source].url}",
        note=(f"{catalogue.title}, {catalogue.edition}, read from "
              f"data/sources/{catalogue.source}"),
        retrieved_at=None,
        entries=entries)
    return table, issues


def write(name: str) -> tuple[Path, list[str]]:
    table, issues = build(name)
    lists_dir().mkdir(parents=True, exist_ok=True)
    target = path_for(name)
    target.write_text(
        json.dumps(table.model_dump(mode="json", exclude_none=False),
                   ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8")
    return target, issues
