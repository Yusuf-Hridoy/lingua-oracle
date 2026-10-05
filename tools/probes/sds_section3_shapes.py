#!/usr/bin/env python3
"""Phase 0 / 0b discovery probe: what Sections 2 and 3 of an SDS PDF hold.

NOT part of the checker. Nothing in `src/` imports this and no test runs it. It
exists so the findings in `docs/classification/phase0_extraction.md` can be
reproduced, and so the next phase starts from measurement rather than memory.

Read-only: it opens PDFs and prints shapes. It writes nothing and never names a
product - identifiers and classifications are the subject, not the substance.

Usage:
    uv run python tools/probes/sds_section3_shapes.py data/validation/app
    uv run python tools/probes/sds_section3_shapes.py --json <dir> [<dir> ...]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber

from lingua_oracle.detect.codes import CODE_RE

ROOT = Path("data/validation")
CLASSES = json.loads(Path("data/hazard_classes/eu_clp.json").read_text())["codes"]
# "Skin Corr. 1B", "Aquatic Chronic 3", "Acute Tox. 4" - the class list with a
# category after it. Built from the committed Annex VI list, never typed out.
_CLASS_STEMS = sorted({re.sub(r"\s*\d.*$", "", c) for c in CLASSES}, key=len, reverse=True)
CLASS_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _CLASS_STEMS) + r")\s*"
    r"(\d[A-Fa-f]?(?:\s*[/,]\s*\d[A-Fa-f]?)*)?", re.IGNORECASE)

CAS_RE = re.compile(r"\b(\d{2,7}-\d{2}-\d)\b")
EC_RE = re.compile(r"\b(\d{3}-\d{3}-\d)\b")
INDEX_RE = re.compile(r"\b(\d{3}-\d{3}-\d{2}-\d)\b")
REACH_RE = re.compile(r"\b(\d{2}-\d{10}-\d{2}(?:-\d{4}|-XXXX)?)\b")
PCT = r"(?:%|\bw/w\b|\bwt%|\bvol%|\bppm\b|\bg/l\b|\bmg/kg\b)"
# A CAS number and a concentration range are the same shape - "67-64-1" against
# "5-10". Identifiers are masked out before concentrations are looked for, or
# every CAS number in the sheet is read as a range.
IDENTIFIER_RE = re.compile(
    r"\b\d{2}-\d{10}-\d{2}(?:-\w{4})?\b"      # REACH registration
    r"|\b\d{3}-\d{3}-\d{2}-\d\b"              # Index number
    r"|\b\d{2,7}-\d{2}-\d\b"                   # CAS
    r"|\b\d{3}-\d{3}-\d\b")                    # EC
CONC_RE = re.compile(
    r"(?:[<>≤≥]\s*\d+(?:[.,]\d+)?\s*(?:" + PCT + r")?"
    r"|\d+(?:[.,]\d+)?\s*[-–—]\s*\d+(?:[.,]\d+)?\s*(?:" + PCT + r")?"
    r"|\d+(?:[.,]\d+)?\s*(?:" + PCT + r"))", re.IGNORECASE)
SCL_RE = re.compile(r"\bSCL\b|specific concentration limit", re.IGNORECASE)
MFACTOR_RE = re.compile(r"\bM[- ]?factor\b|\bM\s*=\s*\d+", re.IGNORECASE)
ATE_RE = re.compile(r"\bATE\b|acute toxicity estimate", re.IGNORECASE)
NOTE_RE = re.compile(r"\[\s*\d+\s*\]|\(\s*\*+\s*\)|\*{1,3}(?!\w)|¹|²")

HEAD2 = re.compile(r"(?:^|\b)(?:section\s*)?2[.:)\s]{0,3}\s*(hazard[s]?\s+identification"
                   r"|identification\s+des\s+dangers|mogliche\s+gefahren|mögliche\s+gefahren"
                   r"|identificación\s+de\s+los\s+peligros|fareidentifikation)",
                   re.IGNORECASE)
HEAD3 = re.compile(r"(?:^|\b)(?:section\s*)?3[.:)\s]{0,3}\s*(composition"
                   r"|zusammensetzung|composición|sammensætning)", re.IGNORECASE)
HEAD4 = re.compile(r"(?:^|\b)(?:section\s*)?4[.:)\s]{0,3}\s*(first[- ]aid|erste[- ]hilfe"
                   r"|premiers\s+secours|primeros\s+auxilios|førstehjælp)",
                   re.IGNORECASE)
SINGLE_RE = re.compile(r"\bsubstance\b|\bmono[- ]?constituent\b|\bone\s+substance\b",
                       re.IGNORECASE)
MIXTURE_RE = re.compile(r"\bmixture[s]?\b|\bpreparation\b", re.IGNORECASE)
# The GHS long form of the same thing: "Flammable liquids, Category 2" where CLP
# writes "Flam. Liq. 2". Both appear, sometimes in the same document.
LONGFORM_RE = re.compile(
    r"\b([A-Z][A-Za-z/ -]{3,48}?)\s*[,;:]?\s*"
    r"\b(?:Category|Cat\.?|Kategorie|Catégorie|Categoría)\s*"
    r"([0-9][A-Fa-f]?(?:\s*[-/]\s*[0-9][A-Fa-f]?)?)", re.IGNORECASE)
# Text drawn twice by the producer: "SSEECCTTIIOONN 11". The letters are all
# there and no heading or code can be matched.
DOUBLED_RE = re.compile(r"(?:([A-Za-z])\1){4,}")

HEADER_WORDS = {
    "cas": re.compile(r"\bCAS\b", re.I),
    "ec": re.compile(r"\bEC\b|\bEINECS\b|\bELINCS\b", re.I),
    "index": re.compile(r"\bindex\b", re.I),
    "reach": re.compile(r"\bREACH\b|registration", re.I),
    "name": re.compile(r"\bname\b|\bidentity\b|\bingredient\b|\bcomponent\b|"
                       r"bezeichnung|stoffname|nom|nombre", re.I),
    "concentration": re.compile(r"concentrat|\bconc\.?\b|\b%\b|gehalt|menge|teneur", re.I),
    "classification": re.compile(r"classif|einstufung|clasificaci", re.I),
    "note": re.compile(r"\bnote[s]?\b|anmerkung", re.I),
}


def sections(words_by_page):
    """(page, y) of the Section 2, 3 and 4 headings, if found."""
    found = {}
    for page_no, lines in words_by_page:
        for y, text in lines:
            for name, pattern in (("2", HEAD2), ("3", HEAD3), ("4", HEAD4)):
                if name not in found and pattern.search(text):
                    found[name] = (page_no, y)
    return found


def lines_between(words_by_page, start, end):
    out = []
    if not start:
        return out
    for page_no, lines in words_by_page:
        for y, text in lines:
            after = (page_no, y) >= start
            before = (page_no, y) < end if end else True
            if after and before:
                out.append((page_no, y, text))
    return out


def page_lines(page):
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    rows: dict[int, list] = {}
    for w in words:
        rows.setdefault(round(w["top"] / 3), []).append(w)
    out = []
    for key in sorted(rows):
        ws = sorted(rows[key], key=lambda w: w["x0"])
        out.append((ws[0]["top"], " ".join(w["text"] for w in ws)))
    return out


def masked(text: str) -> str:
    return IDENTIFIER_RE.sub(" ", text)


def long_forms(text):
    return sorted({f"{' '.join(m.group(1).split())}, Category {m.group(2)}"
                   for m in LONGFORM_RE.finditer(text)})


def classes_in(text):
    out = []
    for m in CLASS_RE.finditer(text):
        stem, cat = m.group(1), (m.group(2) or "").strip()
        out.append(f"{stem} {cat}".strip())
    return out


SUB_RE = re.compile(r"\b3\.1\b.{0,20}\bsubstance", re.I)
MIX_RE = re.compile(r"\b3\.2\b.{0,20}\bmixture", re.I)
REFER_RE = re.compile(r"refer to component|see component sds", re.I)
CAT_ONLY_RE = re.compile(r"\b(?:EUH\d{3}[A-Z]?|H\d{3}[A-Za-z]?)\s+(?:Category\s*\d[A-Fa-f]?|Supplemental)\b")
CONC_CELL_RE = re.compile(
    r"^(?:\s*(?:[<>≤≥]=?|ca\.?|approx\.?)\s*)?\d+(?:[.,]\d+)?\s*"
    r"(?:(?:[-–—]|to|bis)\s*(?:[<>≤≥]=?\s*)?\d+(?:[.,]\d+)?)?\s*"
    r"(?:%|w/w|wt%|ppm)?\s*$", re.I)

def grade(path: Path) -> dict:
    with pdfplumber.open(str(path)) as pdf:
        pages = [(i + 1, page_lines(p)) for i, p in enumerate(pdf.pages)]
        # Tables carry their own bounding box, so a table can be placed against
        # the section headings rather than merely "on the same page". Section 2
        # and Section 3 often share a page, and picking by page alone brings
        # back Section 2's statement table.
        tables = []
        for i, pg in enumerate(pdf.pages):
            for t in (pg.find_tables() or []):
                tables.append((i + 1, t.bbox[1], t.extract()))
        marks = sections(pages)
        s2 = lines_between(pages, marks.get("2"), marks.get("3"))
        s3 = lines_between(pages, marks.get("3"), marks.get("4"))
        s2_text = " ".join(t for _, _, t in s2)
        s3_text = " ".join(t for _, _, t in s3)
        whole = " ".join(t for _, ls in pages for _, t in ls)

        best = None
        start, end = marks.get("3"), marks.get("4")
        for page_no, top, table in tables:
            if len(table) < 2 or start is None:
                continue
            if (page_no, top) < start or (end and (page_no, top) >= end):
                continue
            head = " | ".join(" ".join((c or "").split()) for c in table[0]).lower()
            if not re.search(r"cas|component|chemical name|ingredient", head):
                continue
            if re.search(r"iarc|ntp|acgih|tsca|osha|mexico", head):
                continue  # a regulatory-listing table, not the composition
            body = [r for r in table[1:]
                    if any((c or "").strip() for c in r)]
            if best is None or len(body) > len(best[1]):
                best = ([" ".join((c or "").split()) for c in table[0]], body)

        ingredient_cas = sorted(set(CAS_RE.findall(s3_text)))
        rows = []
        if best:
            headers, body = best
            for row in body:
                cells = [" ".join((c or "").split()) for c in row]
                joined = " ".join(cells)
                if not CAS_RE.search(joined):
                    continue
                rows.append({
                    "cas": CAS_RE.findall(joined)[:1],
                    "ec": EC_RE.findall(joined)[:1],
                    "conc": [c for c in cells if CONC_CELL_RE.match(c) and c],
                    "classes": classes_in(joined),
                    "h": sorted({m.group(0).upper().replace(" ", "")
                                 for m in CODE_RE.finditer(joined)}),
                })

        # Both "3.1 Substances" and "3.2 Mixtures" can appear as headings, with
        # the one that does not apply marked "n.a.". The heading alone proves
        # nothing; what carries the ingredients decides.
        sub = SUB_RE.search(s3_text) or SUB_RE.search(whole)
        mix = MIX_RE.search(s3_text) or MIX_RE.search(whole)
        if sub and mix:
            kind = "mixture" if len(rows) > 1 or len(ingredient_cas) > 1 else "substance"
        else:
            kind = ("single substance" if sub else "mixture" if mix else "unstated")
        has_class_col = bool(best and re.search(
            r"classif|einstufung", " ".join(best[0]), re.I))
        if REFER_RE.search(s3_text):
            cleanliness = "not found (refers to component sheets)"
        elif DOUBLED_RE.search(whole):
            cleanliness = "not found (doubled characters)"
        elif best and rows:
            cleanliness = "clean table"
        elif CAS_RE.search(s3_text):
            cleanliness = "messy layout"
        else:
            cleanliness = "not found"

        return {
            "file": path.name,
            "folder": path.parent.name,
            "pages": len(pdf.pages),
            "kind": kind,
            "cleanliness": cleanliness,
            "s2_found": bool(marks.get("2")),
            "s2_long_form": long_forms(s2_text)[:6],
            "s2_code_plus_category": sorted({m.group(0) for m in CAT_ONLY_RE.finditer(s2_text)})[:8],
            "s2_short_codes": sorted(set(classes_in(s2_text)))[:8],
            "s2_h": sorted({m.group(0).upper().replace(" ", "")
                            for m in CODE_RE.finditer(s2_text)})[:14],
            "s3_found": bool(marks.get("3")),
            "s3_headers": best[0] if best else [],
            "s3_rows": rows,
            "s3_cas_in_text": sorted(set(CAS_RE.findall(s3_text))),
            "s3_has_classification_column": has_class_col,
            "s3_classes_in_text": sorted(set(classes_in(s3_text)))[:8],
            "s3_scl": bool(SCL_RE.search(s3_text)),
            "s3_m": bool(MFACTOR_RE.search(s3_text)),
            "s3_ate": bool(ATE_RE.search(s3_text)),
        }



def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", help="directories of PDFs to read")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    out = []
    for root in args.roots:
        for path in sorted(Path(root).glob("*.pdf")):
            try:
                out.append(grade(path))
            except Exception as exc:  # noqa: BLE001 - a broken PDF is a finding
                out.append({"file": path.name, "folder": path.parent.name,
                            "error": repr(exc)})
    for r in out:
        if "error" in r:
            print(f"{r['file'][:34]:34} ERROR {r['error'][:60]}")
            continue
        print(f"{r['file'][:34]:34} {r['kind'][:16]:16} {r['cleanliness'][:34]:34} "
              f"ingredients={len(r['s3_rows'])} classification={r['s3_has_classification_column']}")
    if args.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

