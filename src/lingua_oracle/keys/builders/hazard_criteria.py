"""Criteria a sheet's own data can be held against, from each regulation's text.

Not an answer key: data/hazard_criteria/<reg>.json.

* Flammable liquids - flash point and initial boiling point per category:
  CLP Annex I Table 2.6.1 (EU, GB), GHS Table 2.6.1 (Rev.11; Rev.7 for
  Australia), HPR section 7.6.1(2), OSHA Appendix B Table B.6.1.
* Hazardous to the aquatic environment - the substance criteria a mixture
  tested as a whole is classified by (CLP 4.1.3.3.1, GHS 4.1.3.3):
  CLP Table 4.1.0 (EU, GB), GHS Table 4.1.1 (Rev.11). Australia excludes
  the aquatic classes (Safe Work Australia's guidance); the HPR and OSHA's
  appendices define no aquatic class - "not adopted".

A criterion that is not read from the text is "not_on_file", and nothing
is judged by it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import (
    BROWSER_UA,
    SourceUnavailable,
    fetch,
    strip_markers,
)
from lingua_oracle.registry import data_dir

REGULATIONS = ("eu_clp", "uk_clp", "us_osha", "ca_whmis", "un_ghs", "au_whs")
APPENDIX_B_URL = "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppB"

_OPS = {"<": "<", ">": ">", "≤": "<=", "≥": ">=", "<=": "<=", ">=": ">="}


@dataclass
class Criterion:
    status: str = "ok"                   # ok / not_on_file / not_adopted
    citation: str = ""
    quote: str = ""
    why: str = ""
    categories: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class HazardCriteria:
    regulation: str
    document: str
    flammable_liquids: Criterion = field(default_factory=Criterion)
    #: aquatic: categories are {"kind": "acute"|"chronic_nonrapid"|"chronic_rapid",
    #: "category", "lower", "upper"} in mg/l
    aquatic: Criterion = field(default_factory=Criterion)
    #: The sentence that lets a mixture tested as a whole be classified by them.
    aquatic_mixture: dict = field(default_factory=dict)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _number(text: str) -> str:
    return str(Decimal(text.replace(",", ".")))


# -- flammable liquids ------------------------------------------------------------

_FLASH = re.compile(
    r"[Ff]lash point\s*(?:is\s*)?(?P<op1>≤|≥|<=|>=|<|>)\s*(?P<v1>\d+(?:[.,]\d+)?)\s*(?:°\s*|o\s*)?C"
    r"(?:\s*\([^)]*\))?(?:\s*and\s*(?P<op2>≤|≥|<=|>=|<|>)\s*(?P<v2>\d+(?:[.,]\d+)?)\s*(?:°\s*|o\s*)?C"
    r"(?!\S*\s*and initial))?")
_BOILING = re.compile(r"initial boiling point\s*(?:is\s*)?(?P<op>≤|≥|<=|>=|<|>)\s*"
                      r"(?P<v>\d+(?:[.,]\d+)?)")


def flammable_rows(table: str) -> list[dict]:
    """ "1 Flash point < 23 °C and initial boiling point ≤ 35 °C 2 ..." -> rows."""
    out = []
    pieces = re.split(r"(?:(?<=\s)|^)(\d)\s+(?=(?:Flammable Liquids — Category \d\s+)?(?:A liquid "
                      r"that has a )?[Ff]lash point)", table)
    for k in range(1, len(pieces) - 1, 2):
        category, words = pieces[k], pieces[k + 1]
        flash = _FLASH.search(words)
        if not flash:
            continue
        row = {"category": category,
               "flash": [[_OPS[flash.group("op1")], _number(flash.group("v1"))]],
               "raw": _flat(words)[:200]}
        if flash.group("op2"):
            row["flash"].append([_OPS[flash.group("op2")], _number(flash.group("v2"))])
        boiling = _BOILING.search(words)
        if boiling:
            row["boiling"] = [_OPS[boiling.group("op")], _number(boiling.group("v"))]
        out.append(row)
    return out


def _flammable(text: str, start: str, citation: str, end: str = r"NOTE|Note|\(\s*\d?\s*\)|"
               r"a a|2\.6\.3|TABLEAU|B\.6\.3") -> Criterion:
    found = [m.start() for m in re.finditer(start, text)]
    if not found:
        return Criterion("not_on_file", citation, why=f"{start!r} not found in the text")
    block = text[found[0]:found[0] + 1600]
    table = re.split(rf"\s(?:{end})", block, maxsplit=1)[0]
    rows = flammable_rows(table)
    if not rows:
        return Criterion("not_on_file", citation, why="criteria rows not read")
    notes = [_flat(n.group(0)) for n in re.finditer(
        r"(?:For the purpose of this Regulation gas oils|Gas oils, diesel and light heating oils)"
        r"[^.]+\.", block)]
    return Criterion("ok", citation, _flat(table)[:900], categories=rows, notes=notes)


# -- aquatic --------------------------------------------------------------------------

def _bands(chunk: str, word: str) -> list[dict]:
    out = []
    for found in re.finditer(rf"Category {word} (\d):(.+?)(?=Category {word} \d:|\([iv]+\)|\(b\)|$)",
                             chunk):
        words = found.group(2)
        upper = re.findall(r"≤\s*(\d+(?:[.,]\d+)?)\s*mg/l", words)
        lower = re.findall(r">\s*(\d+(?:[.,]\d+)?)\s*(?:but|to)", words)
        if upper:
            out.append({"category": found.group(1), "upper": _number(upper[0]),
                        "lower": _number(lower[0]) if lower else None})
    return out


def _aquatic(text: str, start: str, citation: str) -> Criterion:
    found = [m.start() for m in re.finditer(start, text)]
    if not found:
        return Criterion("not_on_file", citation, why=f"{start!r} not found in the text")
    block = text[found[0]:found[0] + 6000]
    acute = block.split("(b)")[0]
    chronic = block[len(acute):]
    nonrapid = chronic.split("(ii)")[0]
    rapid = chronic.split("(ii)", 1)[-1].split("(iii)")[0]
    rows = ([dict(r, kind="acute") for r in _bands(acute, "Acute")]
            + [dict(r, kind="chronic_nonrapid") for r in _bands(nonrapid, "Chronic")]
            + [dict(r, kind="chronic_rapid") for r in _bands(rapid, "Chronic")])
    if not rows:
        return Criterion("not_on_file", citation, why="criteria not read")
    return Criterion("ok", citation, _flat(block[:len(acute) + len(nonrapid) + len(rapid)])[:1800],
                     categories=rows)


def _mixture_rule(text: str, citation: str) -> dict:
    found = re.search(r"When the mixture as a whole has been tested to determine its aquatic "
                      r"toxicity, this information (?:can|shall) be used for classifying the "
                      r"mixture according to the criteria that have been agreed for substances[^.]*\.",
                      text)
    return {"quote": _flat(found.group(0)), "citation": citation} if found else {}


# -- per regulation -------------------------------------------------------------------

def _clp_text(regulation: str) -> tuple[str, str]:
    if regulation == "eu_clp":
        from lxml import html as LH

        from lingua_oracle.keys.builders.eu_clp import BASE_URL, CELEX

        raw = fetch(BASE_URL, headers={"Accept": "application/xhtml+xml",
                                       "Accept-Language": "eng"})
        return (f"Regulation (EC) No 1272/2008, consolidated {CELEX}",
                strip_markers(_flat(" ".join(LH.fromstring(raw).itertext()))))
    import pymupdf

    with pymupdf.open(sources.require("uk-gb-clp/gb_clp_full.pdf")) as pdf:
        text = _flat(" ".join(page.get_text() for page in pdf))
    text = re.sub(r"\[F\d+|\[X\d+|\]|F\d+\s*(?:\.\s*){3}", "", text)
    return "Regulation (EC) No 1272/2008 as retained in GB law", _flat(text)


def _ghs_text(rev11: bool) -> tuple[str, str]:
    from lingua_oracle.keys.builders.acute_toxicity import _pdf_pages

    path = sources.require("un-ghs/GHS_Rev11_en.pdf" if rev11 else "ghs-rev7/GHS_Rev7_en.pdf")
    text = _flat(" ".join(t for _, t in _pdf_pages(path)))
    return ("UN GHS Rev.11 (2025)" if rev11 else "UN GHS Rev.7 (2017)"), text


def build(regulation: str, *, use_cache: bool = True) -> HazardCriteria:
    if regulation in ("eu_clp", "uk_clp"):
        document, text = _clp_text(regulation)
        out = HazardCriteria(regulation, document)
        out.flammable_liquids = _flammable(text, r"(?:Table|TABLE) 2\.6\.1 Criteria for flammable "
                                                 r"liquids", f"{document}, Annex I, Table 2.6.1")
        out.aquatic = _aquatic(text, r"(?:Table|TABLE) 4\.1\.0 Classification categories for substances "
                                     r"hazardous to the aquatic environment",
                               f"{document}, Annex I, Table 4.1.0")
        out.aquatic_mixture = _mixture_rule(text, f"{document}, Annex I, 4.1.3.3.1")
        return out
    if regulation in ("un_ghs", "au_whs"):
        document, text = _ghs_text(regulation == "un_ghs")
        if regulation == "au_whs":
            document = f"{document}, as adopted by the WHS Regulations"
        out = HazardCriteria(regulation, document)
        out.flammable_liquids = _flammable(text, r"Table 2\.6\.1: Criteria for flammable liquids",
                                           f"{document}, Table 2.6.1")
        if regulation == "un_ghs":
            out.aquatic = _aquatic(text, r"Table 4\.1\.1: Categories for substances hazardous to "
                                         r"the aquatic environment", f"{document}, Table 4.1.1")
            out.aquatic_mixture = _mixture_rule(text, f"{document}, 4.1.3.3")
        else:
            from lingua_oracle.keys.builders.label_elements import (
                LabelElements,
                _australian_exclusions,
            )

            held = LabelElements("au_whs", document)
            _australian_exclusions(held)
            aquatic = [x for x in held.not_adopted if "aquatic" in x["what"]]
            out.aquatic = Criterion(
                "not_adopted", aquatic[0]["rule"]["citation"] if aquatic else "",
                aquatic[0]["rule"]["quote"] if aquatic else "",
                why="The WHS Regulations leave the aquatic hazard classes out of "
                    "\"hazardous chemical\".")
        return out
    if regulation == "ca_whmis":
        import pymupdf

        document = "Hazardous Products Regulations (SOR/2015-17)"
        with pymupdf.open(sources.require("ca-whmis/hpr_bilingual.pdf")) as pdf:
            text = _flat(" ".join(page.get_text() for page in pdf))
        out = HazardCriteria(regulation, document)
        out.flammable_liquids = _flammable(
            text, r"TABLE Column 1 Column 2 Item Category Criteria 1 Flammable Liquids — Category 1",
            f"{document}, section 7.6.1(2)")
        out.aquatic = Criterion("not_adopted", document,
                                why="The Hazardous Products Regulations define no hazard class "
                                    "for the aquatic environment (Parts 7 and 8 list the classes).")
        return out
    if regulation == "us_osha":
        import html as _html

        document = "29 CFR 1910.1200 Appendix B"
        raw = fetch(APPENDIX_B_URL, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
        text = _flat(_html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace"))))
        out = HazardCriteria(regulation, document)
        out.flammable_liquids = _flammable(text, r"Table B\.6\.1—Criteria for Flammable Liquids",
                                           f"{document}, Table B.6.1")
        out.aquatic = Criterion("not_adopted", "29 CFR 1910.1200 Appendices A and B",
                                why="OSHA's Appendices A (health) and B (physical) define no "
                                    "hazard class for the aquatic environment.")
        return out
    raise ValueError(f"no hazard criteria source for {regulation}")


def criteria_dir() -> Path:
    return data_dir() / "hazard_criteria"


def write(regulation: str, *, use_cache: bool = True) -> Path:
    criteria = build(regulation, use_cache=use_cache)
    criteria_dir().mkdir(parents=True, exist_ok=True)
    path = criteria_dir() / f"{regulation}.json"
    path.write_text(json.dumps(asdict(criteria), indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


del SourceUnavailable
