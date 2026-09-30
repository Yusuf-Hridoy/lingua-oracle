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

REV7_FILE = "ghs-rev7/GHS_Rev7_{lang}.pdf"
REV8_FILE = "ghs-rev8/GHS_Rev8_{lang}.pdf"
_EDITION_NAME = {"en": "English", "fr": "French", "es": "Spanish"}


def rev8_name(language: str = "en") -> str:
    return f"UN GHS Rev.8 Annex 3 ({_EDITION_NAME.get(language, language)})"


#: Kept for callers that only ever deal with English.
REV8_NAME = rev8_name("en")
PRESSURE_CLASS_RE = re.compile(r"chemicals?\s+under\s+pressure", re.IGNORECASE)

# French typography puts a space before ':', ';', '!' and '?'. Editions are
# inconsistent about it - GHS Rev.7 French prints "LA PEAU :" where Rev.8 French
# prints "LA PEAU:" - and about which space character it uses.
#
# THIS IS FOR EDITION-PROOF COMPARISON ONLY: deciding whether two *editions* of
# the same official statement say the same thing. It is deliberately NOT used when
# matching a document against the key - that comparison stays exact, and a
# document differing from the key by punctuation is still reported. Do not import
# this into the matcher.
_FRENCH_SPACE_BEFORE_PUNCT_RE = re.compile("[ \u00a0\u202f\u2009]+(?=[:;!?])")


def edition_equal(left: str, right: str) -> bool:
    """Whether two editions state the same statement, ignoring French spacing."""
    def key(text: str) -> str:
        return _FRENCH_SPACE_BEFORE_PUNCT_RE.sub("", normalize(text))

    return bool(left) and bool(right) and key(left) == key(right)


def recover_damaged_cells(
    sources_root: Path, language: str, proof_language: str
) -> dict[str, str]:
    """Rev.7 statements lost to a damaged cell, recovered from Rev.8.

    Some Rev.7 code cells are unreadable - the English edition renders one row's
    code as literally "P302 +", with the rest of the combined code absent from the
    page's text layer. The statement is not missing from the regulation, only from
    this rendering of it.

    Such a code is recovered from Rev.8 **only when another language proves the
    statement did not change between the two editions**: `proof_language` must
    carry the code in both editions with the same wording. Without that proof
    nothing is recovered, which is what keeps statements that genuinely changed -
    and statements Rev.8 introduced, such as chemicals under pressure - out of it.
    """
    paths = {
        ("7", language): sources_root / REV7_FILE.format(lang=language),
        ("8", language): sources_root / REV8_FILE.format(lang=language),
        ("7", proof_language): sources_root / REV7_FILE.format(lang=proof_language),
        ("8", proof_language): sources_root / REV8_FILE.format(lang=proof_language),
    }
    if not all(p.exists() for p in paths.values()):
        return {}
    tables = {k: annex3(v) for k, v in paths.items()}
    rev7, rev8 = tables[("7", language)], tables[("8", language)]
    proof7, proof8 = tables[("7", proof_language)], tables[("8", proof_language)]

    return {
        code: text
        for code, text in rev8.items()
        if code not in rev7
        and edition_equal(proof7.get(code, ""), proof8.get(code, ""))
    }


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


def pressure_overlay(
    sources_root: Path, language: str = "en"
) -> tuple[dict[str, str], dict[str, str]]:
    """Rev.8 statements for chemicals under pressure that Rev.7 does not carry.

    Returns (overlay, unchanged) where `overlay` is what must come from Rev.8 in
    `language`, and `unchanged` is the class's other codes, which are identical in
    Rev.7 and stay there.

    Which codes the class covers is always decided from the **English** Rev.8,
    whose hazard-class column names the class in a form this code can match. The
    statement text then comes from the requested language's own edition, so no
    wording is ever carried across languages - only the set of codes is.
    """
    class_source = sources_root / REV8_FILE.format(lang="en")
    rev7_path = sources_root / REV7_FILE.format(lang=language)
    rev8_path = sources_root / REV8_FILE.format(lang=language)
    if not class_source.exists() or not rev8_path.exists() or not rev7_path.exists():
        return {}, {}

    codes = codes_for_class(class_source, PRESSURE_CLASS_RE)
    rev7, rev8 = annex3(rev7_path), annex3(rev8_path)
    overlay, unchanged = {}, {}
    for code in codes:
        text8 = rev8.get(code)
        if text8 is None:
            continue
        text7 = rev7.get(code)
        if text7 is None:
            overlay[code] = text8
        elif normalize(text7) == normalize(text8):
            unchanged[code] = text7
    return overlay, unchanged
