"""Just enough of the xlsx format to read a published list.

Two of the substance lists are spreadsheets. A spreadsheet library would read
them, but the only thing needed here is the text of the cells, in order, and
that is a few lines of zip and XML - which is worth more than a dependency the
rest of the tool would never use, and keeps a fresh clone able to build
everything it ships.

What this does not do is as important as what it does: no formulas, no dates,
no styles. A cell is the text it holds, and a number is the digits as stored,
which is what a CAS number or a concentration limit has to stay.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _column(reference: str) -> str:
    return "".join(c for c in reference if c.isalpha())


def sheets(path: Path) -> dict[str, str]:
    """{sheet name: the path of its XML inside the file}, in workbook order."""
    with zipfile.ZipFile(path) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = {
        rel.get("Id"): rel.get("Target")
        for rel in rels
    }
    out: dict[str, str] = {}
    for sheet in book.iter(f"{NS}sheet"):
        rel = sheet.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        where = target.get(rel, "")
        out[sheet.get("name") or ""] = (
            where if where.startswith("xl/") else f"xl/{where.lstrip('/')}")
    return out


def rows(path: Path, sheet: str | None = None) -> list[dict[str, str]]:
    """Every row of one sheet, as {column letter: text}.

    Empty cells are left out rather than filled in: a column that says nothing
    about a substance is not the same as one that says it has nothing. Within
    a cell, the publisher's line breaks survive; its stray spacing does not.
    """
    found = sheets(path)
    where = found.get(sheet or next(iter(found)), "")
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(t.text or "" for t in entry.iter(f"{NS}t"))
                      for entry in ET.fromstring(
                          archive.read("xl/sharedStrings.xml"))]
        sheet_xml = ET.fromstring(archive.read(where))
    out: list[dict[str, str]] = []
    for row in sheet_xml.iter(f"{NS}row"):
        cells: dict[str, str] = {}
        for cell in row.iter(f"{NS}c"):
            value = cell.find(f"{NS}v")
            if value is None or value.text is None:
                inline = cell.find(f"{NS}is")
                text = ("".join(t.text or "" for t in inline.iter(f"{NS}t"))
                        if inline is not None else "")
            elif cell.get("t") == "s":
                text = shared[int(value.text)]
            else:
                text = value.text
            # A soft hyphen is where the publisher let a word break at the
            # edge of a cell. It is not part of what it breaks, and leaving it
            # in cuts CAS numbers in half - "271<shy> 77-05-5" is 27177-05-5.
            text = re.sub(r"\u00ad\s*", "", text or "")
            # Line breaks inside a cell are kept: the lists print one limit,
            # one class or one note per line, and a cell flattened to a single
            # line is a cell whose entries can no longer be told apart.
            text = "\n".join(
                " ".join(line.split())
                for line in (text or "").replace("\r\n", "\n").split("\n")
                if line.strip())
            if text:
                cells[_column(cell.get("r") or "")] = text
        out.append(cells)
    return out
