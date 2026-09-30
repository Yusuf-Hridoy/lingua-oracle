"""Reading a specific GHS edition, and overlaying Rev.8 where a regulation says so.

Both Canada's HPR and OSHA adopt GHS Rev.7 in general but point one hazard class -
chemicals under pressure - at Annex 3 of the **Eighth** revised edition. This
module keeps that overlay narrow and evidence-based:

* which codes the class covers is read from the hazard-class column of Rev.8
  itself, never recalled;
* only codes Rev.7 does not contain are taken from Rev.8. The precautionary codes
  the class uses (P376, P378, P370+P378, P410+P403) are word-for-word identical in
  the two editions and serve other classes too, so they stay on Rev.7 and nothing
  is silently reworded beneath them.

The result is an overlay of exactly the statements the regulation asked for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from lingua_oracle.keys.builders.common import normalise_code
from lingua_oracle.keys.builders.pdf_tables import annex_page_range, harvest
from lingua_oracle.match.normalize import normalize

REV7_FILE = "ghs-rev7/GHS_Rev7_en.pdf"
REV8_FILE = "ghs-rev8/GHS_Rev8_en.pdf"
REV8_NAME = "UN GHS Rev.8 Annex 3 (English)"
PRESSURE_CLASS_RE = re.compile(r"chemicals?\s+under\s+pressure", re.IGNORECASE)


def annex3(path: str | Path) -> dict[str, str]:
    """Code -> statement for one GHS edition's Annex 3."""
    first, last = annex_page_range(str(path))
    found, _issues = harvest(str(path), first_page=first, last_page=last)
    return {c: t for c, t in found.items() if c[:1] in "HP"}


def codes_for_class(path: str | Path, pattern: re.Pattern[str]) -> set[str]:
    """Codes whose hazard-class column matches `pattern`, read from the document."""
    doc = pymupdf.open(path)
    out: set[str] = set()
    try:
        for index in range(doc.page_count):
            if not pattern.search(doc[index].get_text()):
                continue
            for table in doc[index].find_tables().tables:
                for row in table.extract():
                    if len(row) < 3:
                        continue
                    code = " ".join((row[0] or "").split())
                    hazard_class = " ".join((row[2] or "").split())
                    if re.fullmatch(r"[HP]\d{3}(?:\s*\+\s*[HP]\d{3})*", code) and pattern.search(
                        hazard_class
                    ):
                        out.add(normalise_code(code))
    finally:
        doc.close()
    return out


def pressure_overlay(sources_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Rev.8 statements for chemicals under pressure that Rev.7 does not carry.

    Returns (overlay, unchanged) where `overlay` is what must come from Rev.8 and
    `unchanged` is the class's other codes, which are identical in Rev.7 and stay
    there. A code whose text differs between the editions is *not* overlaid
    silently - it would be reported by the caller - but in practice none does.
    """
    rev7_path, rev8_path = sources_root / REV7_FILE, sources_root / REV8_FILE
    if not rev8_path.exists() or not rev7_path.exists():
        return {}, {}
    rev7, rev8 = annex3(rev7_path), annex3(rev8_path)
    overlay, unchanged = {}, {}
    for code in codes_for_class(rev8_path, PRESSURE_CLASS_RE):
        text8 = rev8.get(code)
        if text8 is None:
            continue
        text7 = rev7.get(code)
        if text7 is None:
            overlay[code] = text8
        elif normalize(text7) == normalize(text8):
            unchanged[code] = text7
    return overlay, unchanged
